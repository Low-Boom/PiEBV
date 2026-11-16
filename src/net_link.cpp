#include "net_link.h"

#if defined(ARDUINO_RASPBERRY_PI_PICO_2W)

#include <EEPROM.h>
#include <SimpleMDNS.h>
#include <WiFi.h>  // WiFiServer, WiFiClient (the WiFi object itself is not used)
#include <lwIP_CYW43.h>
#include <lwip/tcp.h>
#include <lwip_wrap.h>  // LWIPMutex
#include <include/ClientContext.h>  // the core's TCP connection object (for its lwIP pcb)
#include <pico/cyw43_arch.h>
#include "clock_mode.h"
#include "hardware/clocks.h"
#include "hardware/timer.h"
#include "lwip/netif.h"

namespace {

constexpr uint32_t kPollMs = 200;           // join-state poll
constexpr uint32_t kRejoinDelayMs = 5000;   // shortest time between two join requests
constexpr uint32_t kJoinTimeoutMs = 20000;  // a join with no result is started again
constexpr uint32_t kProbeMs = 2000;         // signal-level read while joined: also the radio's liveness check
// A radio chip that does not answer makes each driver command (ioctl) wait for its
// time-out, 1 s in this port (CYW43_IOCTL_TIMEOUT_US, cyw43_configport.h), and one join
// request is more than ten such commands. So the link never sends a join to a chip it
// has not just heard from: it sends one cheap command first, and a command that takes
// this long is a fault. A dead chip therefore costs the command loop one time-out
// (about 1 s), once, and the link then makes no radio call until the next power cycle.
constexpr uint64_t kSlowCallUs = 500000;
constexpr uint32_t kIoctlGetRssi = 0xFE;    // CYW43_IOCTL_GET_RSSI, as in the core's CYW43lwIP::RSSI()
constexpr size_t kEepromSize = 256;         // >= kWifiRecordSize, a multiple of the flash page
// Free send-buffer space that counts as "the host reads again" after a reply was
// dropped: room for the longest reply (HELP, about 3.3 kB) in one piece, so a host
// that drains slowly cannot make every command wait out its reply budget.
constexpr int kDrainedRoom = 4096;
static_assert(kDrainedRoom < TCP_SND_BUF, "the send buffer must be able to reach the drained level");
// TCP keep-alive: a host that went away without closing (crash, cable, sleep) frees
// the link after about 5 + 3 x 2 = 11 s.
constexpr uint16_t kKeepAliveIdleS = 5, kKeepAliveIntervalS = 2;
constexpr uint8_t kKeepAliveCount = 3;
// cyw43_wifi_pm() value the core uses for "no power saving" (WiFiClass::noLowPowerMode):
// the radio stays awake, so a command does not wait for the next beacon.
constexpr uint32_t kNoPowerSave = 0xA11140;

static_assert(kEepromSize >= kWifiRecordSize && kEepromSize % 256 == 0, "EEPROM size");

WifiConfig g_cfg;
bool g_saved = false;  // g_cfg is what the flash holds

enum class Phase : uint8_t {
    Off,      // no network interface
    Joining,  // join requested, or waiting to request it again
    Linked,   // joined; CONNECTED once DHCP gave an address
    Fault,    // the radio does not answer; stays until WIFI ON
};
Phase g_phase = Phase::Off;
const char *g_note = nullptr;  // why the link is not up (STATUS), or nullptr
uint32_t g_lastPollMs = 0;
uint32_t g_lastJoinMs = 0;
uint32_t g_lastProbeMs = 0;
bool g_rssiKnown = false;
int32_t g_rssi = 0;
bool g_macKnown = false;
uint8_t g_mac[6] = {};

// One cheap driver command, timed. False = the radio chip did not answer in time (it
// then took the driver's full time-out). `*rssi` (may be nullptr) gets the signal level
// if the chip gave one; a chip that is not joined answers quickly with an error.
bool radioAnswers(int32_t *rssi) {
    int32_t v = 0;
    const uint64_t t0 = time_us_64();
    const int ret = cyw43_ioctl(&cyw43_state, kIoctlGetRssi, sizeof(v), (uint8_t *)&v, CYW43_ITF_STA);
    if (time_us_64() - t0 >= kSlowCallUs) {
        return false;
    }
    if (rssi && ret == 0) {
        *rssi = v;
    }
    return true;
}

int requestJoin() {
    const size_t passLen = strlen(g_cfg.pass);
    return cyw43_wifi_join(&cyw43_state, strlen(g_cfg.ssid), (const uint8_t *)g_cfg.ssid, passLen,
                           (const uint8_t *)g_cfg.pass, passLen ? CYW43_AUTH_WPA2_AES_PSK : CYW43_AUTH_OPEN, nullptr,
                           CYW43_CHANNEL_NONE);
}

// The core's CYW43 device with a begin() that does not wait for the join. (The core's
// CYW43::begin() polls the join with delay() for up to its time-out, and without a
// limit when the time-out ends in the middle of a join.)
class RadioDev : public CYW43 {
public:
    using CYW43::CYW43;

    // Called by LwipIntfDev::begin() after netif_add(). False only if the radio chip
    // did not start.
    bool begin(const uint8_t *address, netif *netif) {
        (void)address;
        _self = &cyw43_state;
        _netif = netif;
        _itf = CYW43_ITF_STA;
        // The interface comes up "link up" (LwipIntfDev::netif_init). Here the link is
        // up only when the join has completed: the driver then calls
        // cyw43_cb_tcpip_set_link_up(), which the core routes to netif_set_link_up().
        // dhcp_start() waits for that, and service() reads the join result from it.
        netif->flags &= (uint8_t)~NETIF_FLAG_LINK_UP;
        // First call after power-up: powers the chip and loads its firmware (the long
        // call). Later calls return at once.
        cyw43_arch_enable_sta_mode();
        if (!(cyw43_state.itf_state & (1u << CYW43_ITF_STA))) {
            return false;
        }
        // The chip was already up (a second WIFI ON): make sure it still answers
        // before the many commands below.
        if (!radioAnswers(nullptr)) {
            return false;
        }
        cyw43_wifi_get_mac(&cyw43_state, CYW43_ITF_STA, netif->hwaddr);
        memcpy(g_mac, netif->hwaddr, sizeof(g_mac));
        g_macKnown = true;
        // mDNS multicast, as in the core's CYW43::begin().
        uint8_t mdnsV4[] = {0x01, 0x00, 0x5E, 0x00, 0x00, 0xFB};
        cyw43_wifi_update_multicast_filter(&cyw43_state, mdnsV4, true);
#if LWIP_IPV6
        uint8_t mdnsV6[] = {0x33, 0x33, 0x00, 0x00, 0x00, 0xFB};
        cyw43_wifi_update_multicast_filter(&cyw43_state, mdnsV6, true);
#endif
        requestJoin();  // a failed request is repeated by service()
        return true;
    }
};

LwipIntfDev<RadioDev> g_radio;
WiFiServer g_server(kNetPort);

// The core's TCP client, plus direct access to its lwIP connection. The link reads
// through WiFiClient but writes with tcp_write() itself: WiFiClient::write() waits
// inside the core when lwIP cannot queue the bytes (for as long as its time-out, which
// the core reads as SECONDS for values below 100), and that wait would hold the command
// loop: no DISARM is read, and the watchdog is not fed.
class LinkClient : public WiFiClient {
public:
    LinkClient() = default;
    LinkClient(const WiFiClient &c) : WiFiClient(c) {}
    // Call with the lwIP lock held: the background lwIP work can free the connection.
    tcp_pcb *pcb() { return _client ? _client->getPCB() : nullptr; }
};
LinkClient g_client;
bool g_haveClient = false;
bool g_mdnsStarted = false;
size_t g_unsent = 0;  // bytes queued in lwIP since the last tcp_output()
// lwIP refused a write although the send buffer had room: it has no memory for another
// segment. Room is then reported as 0 until the host has acknowledged everything, so
// that ReplyOut waits for this once (its reply budget) and not again for every command.
bool g_noMemory = false;

// Replies can go out while the connection is open in our direction: established, or
// the host has closed its sending side only (CLOSE_WAIT), e.g. `echo STATUS | nc -N`.
bool canSend(const tcp_pcb *pcb) {
    return pcb && (pcb->state == ESTABLISHED || pcb->state == CLOSE_WAIT);
}

class TcpSink final : public ReplySink {
public:
    bool connected() override {
        if (!g_haveClient) {
            return false;
        }
        LWIPMutex lock;
        return canSend(g_client.pcb());
    }
    int room() override {
        LWIPMutex lock;
        tcp_pcb *pcb = g_client.pcb();
        if (!canSend(pcb)) {
            return 0;
        }
        if (g_noMemory) {
            if (pcb->unacked != nullptr || pcb->unsent != nullptr) {
                return 0;
            }
            g_noMemory = false;
        }
        return (int)tcp_sndbuf(pcb);
    }
    // All or nothing, and never waits: 0 when lwIP cannot take the whole line now (no
    // room, or no memory for a segment). The bytes are only queued here; flush() sends
    // them, so the lines of one reply share segments. (One segment per line would use a
    // full-size lwIP buffer for each line until the host acknowledges it.)
    size_t write(const uint8_t *buf, size_t n) override {
        LWIPMutex lock;
        tcp_pcb *pcb = g_client.pcb();
        if (!canSend(pcb) || tcp_sndbuf(pcb) < n) {
            return 0;
        }
        if (tcp_write(pcb, buf, (u16_t)n, TCP_WRITE_FLAG_COPY) != ERR_OK) {
            g_noMemory = true;
            tcp_output(pcb);  // what is queued must go out for its memory to come back
            g_unsent = 0;
            return 0;
        }
        g_unsent += n;
        if (g_unsent >= TCP_MSS) {  // a full segment is ready: send it, so that its space comes back
            g_unsent = 0;
            tcp_output(pcb);
        }
        return n;
    }
    int drainedRoom() override { return kDrainedRoom; }
};
TcpSink g_sink;
ProtocolLink g_link(g_sink, false);

void flushClient() {
    if (g_unsent == 0) {
        return;
    }
    g_unsent = 0;
    LWIPMutex lock;
    if (tcp_pcb *pcb = g_client.pcb()) {
        tcp_output(pcb);
    }
}

// Closes a connection. Unread input is thrown away first: closing with unread data
// makes lwIP send a reset, and the host could then lose the last reply (or the "busy"
// text) that was sent before the close.
void closeClient(WiFiClient &c) {
    uint8_t scrap[64];
    for (int i = 0; i < 64 && c.read(scrap, sizeof(scrap)) > 0; ++i) {
    }
    c.stop(1);  // 1 ms: do not wait for the peer's acknowledgements
}

void dropClient() {
    if (g_haveClient) {
        flushClient();
        closeClient(g_client);
        g_client = LinkClient();
        g_haveClient = false;
    }
    g_unsent = 0;
    g_noMemory = false;
    g_link.reset();
}

void radioStop() {
    dropClient();
    if (g_phase != Phase::Off) {
        // Connections that lwIP accepted but the link did not take yet would stay
        // queued in the server and come back, with their input, after a restart.
        for (int i = 0; i < 16 && g_server.hasClient(); ++i) {
            WiFiClient c = g_server.accept();
            closeClient(c);
        }
        g_server.close();
        g_radio.end();
    }
    g_phase = Phase::Off;
    g_note = nullptr;
    g_rssiKnown = false;
}

constexpr char kNoAnswer[] = "the radio chip does not answer: power-cycle the board";

void radioFault() {
    dropClient();
    g_phase = Phase::Fault;
    g_note = kNoAnswer;
    g_rssiKnown = false;
}

// Brings the interface up and requests the join. nullptr, or why the radio is off.
const char *radioStart() {
    if (g_phase == Phase::Fault) {
        return kNoAnswer;  // more radio calls would only wait for their time-outs
    }
    radioStop();
    g_radio.setHostname(kNetHostname);
    if (!g_radio.begin()) {
        g_note = "the radio chip did not start";
        return g_note;
    }
    cyw43_wifi_pm(&cyw43_state, kNoPowerSave);
    g_server.begin();
    g_server.setNoDelay(true);
    if (!g_mdnsStarted) {  // once: it follows the interface from here on
        g_mdnsStarted = MDNS.begin(kNetHostname);
        MDNS.addService(kNetHostname, "tcp", kNetPort);
    }
    g_phase = Phase::Joining;
    g_lastJoinMs = millis();
    g_lastPollMs = g_lastJoinMs;
    g_lastProbeMs = g_lastJoinMs;
    return nullptr;
}

bool linkUp() {
    return netif_is_link_up(g_radio.getNetIf());
}

void rejoin(uint32_t nowMs) {
    g_lastJoinMs = nowMs;
    if (!radioAnswers(nullptr)) {
        radioFault();
        return;
    }
    const uint64_t t0 = time_us_64();
    requestJoin();
    if (time_us_64() - t0 >= kSlowCallUs) {
        radioFault();
    }
}

void pollJoin(uint32_t nowMs) {
    const bool up = linkUp();
    if (g_phase == Phase::Linked) {
        if (!up) {
            g_phase = Phase::Joining;
            g_note = "link lost";
            g_rssiKnown = false;
        } else if (nowMs - g_lastProbeMs >= kProbeMs) {
            // The signal level for STATUS, read here so that STATUS makes no radio
            // call; a chip that has stopped answering is found here too.
            g_lastProbeMs = nowMs;
            int32_t rssi = 0;
            if (!radioAnswers(&rssi)) {
                radioFault();
            } else if (rssi != 0) {
                g_rssi = rssi;
                g_rssiKnown = true;
            }
        }
        return;
    }
    if (up) {
        g_phase = Phase::Linked;
        g_note = nullptr;
        g_lastProbeMs = nowMs - kProbeMs;  // read the signal level at the next poll
        return;
    }
    const int st = cyw43_wifi_link_status(&cyw43_state, CYW43_ITF_STA);
    const char *err = st == CYW43_LINK_NONET     ? "network not found"
                      : st == CYW43_LINK_BADAUTH ? "the network refused the passphrase"
                      : st == CYW43_LINK_FAIL    ? "join failed"
                                                 : nullptr;
    if (err) {
        g_note = err;
    }
    const uint32_t sinceJoin = nowMs - g_lastJoinMs;
    // CYW43_LINK_JOIN here = a join is in progress: give it kJoinTimeoutMs.
    if (sinceJoin >= kJoinTimeoutMs || (st != CYW43_LINK_JOIN && sinceJoin >= kRejoinDelayMs)) {
        rejoin(nowMs);
    }
}

void serviceClient() {
    // Gone = the core sees no open connection and no unread input. (A host that closed
    // only its sending side is dropped here too, after its last input was read and
    // answered; the close then sends the queued replies before the FIN.)
    bool gone = false;
    if (g_haveClient) {
        LWIPMutex lock;
        gone = !g_client.connected();
    }
    if (gone) {
        dropClient();
    }
    if (!g_server.hasClient()) {
        return;
    }
    WiFiClient c = g_server.accept();
    if (g_haveClient) {  // one host at a time; the first one keeps the link
        static const char kBusy[] = "ERR busy: another host is connected\r\n";
        {
            LWIPMutex lock;
            tcp_pcb *pcb = LinkClient(c).pcb();
            if (canSend(pcb) && tcp_write(pcb, kBusy, sizeof(kBusy) - 1, TCP_WRITE_FLAG_COPY) == ERR_OK) {
                tcp_output(pcb);
            }
        }
        closeClient(c);
        return;
    }
    g_client = LinkClient(c);
    g_client.setNoDelay(true);
    g_client.keepAlive(kKeepAliveIdleS, kKeepAliveIntervalS, kKeepAliveCount);
    g_haveClient = true;
    g_unsent = 0;
    g_noMemory = false;
    g_link.reset();
}

// Writes cfg to flash if the flash holds something else. nullptr, or why it is not there.
const char *store(const WifiConfig &cfg) {
    uint8_t rec[kWifiRecordSize];
    wifiRecordEncode(cfg, rec);
    EEPROM.begin(kEepromSize);  // (re)reads the sector
    if (memcmp(EEPROM.getConstDataPtr(), rec, sizeof(rec)) == 0) {
        return nullptr;
    }
    if (clock_get_hz(clk_sys) != kStandardClockHz) {
        return "not stored: flash is written only at the 150 MHz clock; remove the clock jumper to store it";
    }
    memcpy(EEPROM.getDataPtr(), rec, sizeof(rec));  // marks the buffer as changed
    if (!EEPROM.commit()) {
        return "not stored: the flash write failed";
    }
    EEPROM.begin(kEepromSize);  // read back
    return memcmp(EEPROM.getConstDataPtr(), rec, sizeof(rec)) == 0 ? nullptr : "not stored: the flash write failed";
}

void printMac(Print &out) {
    for (size_t i = 0; i < sizeof(g_mac); ++i) {
        if (i) {
            out.print(':');
        }
        if (g_mac[i] < 0x10) {
            out.print('0');
        }
        out.print(g_mac[i], HEX);
    }
}

}  // namespace

namespace net {

void begin() {
    EEPROM.begin(kEepromSize);
    g_saved = wifiRecordDecode(EEPROM.getConstDataPtr(), &g_cfg);
    if (!g_saved) {
        g_cfg = WifiConfig{};
    }
}

void start(bool allowed) {
    if (!g_cfg.enabled) {
        return;
    }
    if (!allowed) {
        g_note = "held off after a watchdog reset: send WIFI ON, or power-cycle";
        return;
    }
    radioStart();  // a failure shows in STATUS
}

const WifiConfig &config() {
    return g_cfg;
}

const char *set(const WifiConfig &cfg, const char **notSaved) {
    const WifiConfig old = g_cfg;
    const bool running = g_phase == Phase::Joining || g_phase == Phase::Linked;
    g_cfg = cfg;  // radioStart() joins with g_cfg
    if (!cfg.enabled) {
        if (g_phase == Phase::Fault) {
            // Leaving the network is one more command to a chip that does not answer:
            // skip it. The interface stays as it is, unused, until the power cycle.
            g_note = kNoAnswer;
        } else {
            radioStop();
        }
    } else if (!running || strcmp(cfg.ssid, old.ssid) != 0 || strcmp(cfg.pass, old.pass) != 0) {
        if (const char *why = radioStart()) {
            g_cfg = old;
            return why;
        }
    }
    *notSaved = store(cfg);
    g_saved = *notSaved == nullptr;
    return nullptr;
}

void service() {
    if (g_phase != Phase::Joining && g_phase != Phase::Linked) {
        return;
    }
    const uint32_t now = millis();
    if (now - g_lastPollMs >= kPollMs) {
        g_lastPollMs = now;
        pollJoin(now);
        if (g_phase == Phase::Fault) {
            return;
        }
    }
    serviceClient();
}

int read() {
    if (!g_haveClient) {
        return -1;
    }
    // The core's read path is not protected against its own receive callback, which
    // runs in the background: take the lwIP lock around it.
    LWIPMutex lock;
    return g_client.read();
}

void flush() {
    flushClient();
}

ProtocolLink &link() {
    return g_link;
}

void printStatus(Print &out) {
    const bool linked = g_phase == Phase::Linked;
    const bool hasIp = linked && g_radio.connected();  // connected() = has an IPv4 address
    out.print(F("WIFI="));
    out.print(g_phase == Phase::Off       ? F("OFF")
              : g_phase == Phase::Fault   ? F("FAULT")
              : g_phase == Phase::Joining ? F("JOINING")
              : hasIp                     ? F("CONNECTED")
                                          : F("DHCP"));
    if (g_note) {
        out.print(F(" ("));
        out.print(g_note);
        out.print(')');
    }
    out.println();
    out.print(F("WIFI_SSID="));
    out.println(g_cfg.ssid);
    out.print(F("WIFI_PASS="));
    out.println(g_cfg.pass[0] ? F("SET") : F("NONE"));
    out.print(F("WIFI_AT_POWER_UP="));
    out.println(g_cfg.enabled ? 1 : 0);
    out.print(F("WIFI_SAVED="));
    out.println(g_saved ? 1 : 0);
    out.print(F("WIFI_MAC="));
    if (g_macKnown) {
        printMac(out);
        out.println();
    } else {
        out.println(F("UNKNOWN (read when the radio starts)"));
    }
    out.print(F("WIFI_IP="));
    if (hasIp) {
        out.println(g_radio.localIP());
    } else {
        out.println(F("NONE"));
    }
    out.print(F("WIFI_RSSI_DBM="));  // read every kProbeMs in pollJoin(): no radio call here
    if (linked && g_rssiKnown) {
        out.println(g_rssi);
    } else {
        out.println(F("NONE"));
    }
    out.print(F("NET_PORT="));
    out.println(kNetPort);
    out.print(F("NET_CLIENT="));
    if (g_haveClient) {
        IPAddress host;
        {
            LWIPMutex lock;  // not held while printing: a reply write can wait for the host
            host = g_client.remoteIP();
        }
        out.println(host);
    } else {
        out.println(F("NONE"));
    }
}

}  // namespace net

#else  // no radio: a plain Pico 2

namespace {
class NoSink final : public ReplySink {
public:
    bool connected() override { return false; }
    int room() override { return 0; }
    size_t write(const uint8_t *, size_t) override { return 0; }
};
NoSink g_sink;
ProtocolLink g_link(g_sink, false);
const WifiConfig g_cfg{};
}  // namespace

namespace net {

void begin() {}
void start(bool) {}
const WifiConfig &config() {
    return g_cfg;
}
const char *set(const WifiConfig &, const char **) {
    return "this firmware image is for a Pico 2, which has no radio";
}
void service() {}
int read() {
    return -1;
}
void flush() {}
ProtocolLink &link() {
    return g_link;
}
void printStatus(Print &out) {
    out.println(F("WIFI=UNAVAILABLE (firmware image for a Pico 2, which has no radio)"));
}

}  // namespace net

#endif
