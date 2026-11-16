#include "net_link.h"

#if defined(ARDUINO_RASPBERRY_PI_PICO_2W)

#include <EEPROM.h>
#include <SimpleMDNS.h>
#include <WiFi.h>  // WiFiServer, WiFiClient (the WiFi object itself is not used)
#include <lwIP_CYW43.h>
#include <pico/cyw43_arch.h>
#include "clock_mode.h"
#include "hardware/clocks.h"
#include "hardware/timer.h"
#include "lwip/netif.h"

namespace {

constexpr uint32_t kPollMs = 200;           // join-state poll
constexpr uint32_t kRejoinDelayMs = 5000;   // shortest time between two join requests
constexpr uint32_t kJoinTimeoutMs = 20000;  // a join with no result is started again
constexpr uint64_t kSlowCallUs = 1000000;   // a radio call this slow is a fault
constexpr int kMaxFaults = 3;               // faults in a row that stop the link
constexpr size_t kEepromSize = 256;         // >= kWifiRecordSize, a multiple of the flash page
// Reply writes go through ReplyOut, which writes only what the send buffer takes. This
// bounds the wait if lwIP still cannot queue the bytes (no segment memory).
constexpr unsigned long kClientWriteTimeoutMs = 20;
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
int g_faults = 0;
bool g_macKnown = false;
uint8_t g_mac[6] = {};

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
WiFiClient g_client;
bool g_haveClient = false;
bool g_mdnsStarted = false;

class TcpSink final : public ReplySink {
public:
    bool connected() override { return g_haveClient && g_client.connected(); }
    int room() override { return g_client.availableForWrite(); }
    size_t write(const uint8_t *buf, size_t n) override { return g_client.write(buf, n); }
};
TcpSink g_sink;
ProtocolLink g_link(g_sink, false);

void dropClient() {
    if (g_haveClient) {
        g_client.stop(1);  // 1 ms: do not wait for the peer's acknowledgements
        g_client = WiFiClient();
        g_haveClient = false;
    }
    g_link.reset();
}

void radioStop() {
    dropClient();
    if (g_phase != Phase::Off) {
        g_server.close();
        g_radio.end();
    }
    g_phase = Phase::Off;
    g_note = nullptr;
    g_faults = 0;
}

// Brings the interface up and requests the join. nullptr, or why the radio is off.
const char *radioStart() {
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
    return nullptr;
}

bool linkUp() {
    return netif_is_link_up(g_radio.getNetIf());
}

void rejoin(uint32_t nowMs) {
    const uint64_t t0 = time_us_64();
    const int ret = requestJoin();
    g_lastJoinMs = nowMs;
    if (ret == 0 && time_us_64() - t0 < kSlowCallUs) {
        g_faults = 0;
        return;
    }
    if (++g_faults >= kMaxFaults) {
        dropClient();
        g_phase = Phase::Fault;
        g_note = "the radio chip does not answer: send WIFI ON to start it again";
    }
}

void pollJoin(uint32_t nowMs) {
    const bool up = linkUp();
    if (g_phase == Phase::Linked) {
        if (!up) {
            g_phase = Phase::Joining;
            g_note = "link lost";
        }
        return;
    }
    if (up) {
        g_phase = Phase::Linked;
        g_note = nullptr;
        g_faults = 0;
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
    if (g_haveClient && !g_client.connected()) {
        dropClient();
    }
    WiFiClient c = g_server.accept();
    if (!c) {
        return;
    }
    c.setTimeout(kClientWriteTimeoutMs);
    if (g_haveClient) {  // one host at a time; the first one keeps the link
        static const char kBusy[] = "ERR busy: another host is connected\r\n";
        if (c.availableForWrite() >= (int)(sizeof(kBusy) - 1)) {
            c.write((const uint8_t *)kBusy, sizeof(kBusy) - 1);
        }
        c.stop(1);
        return;
    }
    g_client = c;
    g_client.setNoDelay(true);
    g_client.keepAlive(kKeepAliveIdleS, kKeepAliveIntervalS, kKeepAliveCount);
    g_haveClient = true;
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
        radioStop();
    } else if (!running || strcmp(cfg.ssid, old.ssid) != 0 || strcmp(cfg.pass, old.pass) != 0) {
        if (const char *why = radioStart()) {
            g_cfg = old;
            g_phase = Phase::Off;
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
    return g_haveClient ? g_client.read() : -1;
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
    out.print(F("WIFI_RSSI_DBM="));
    int32_t rssi = 0;
    // 0xFE = CYW43_IOCTL_GET_RSSI, as in the core's CYW43lwIP::RSSI().
    if (linked && cyw43_ioctl(&cyw43_state, 0xFE, sizeof(rssi), (uint8_t *)&rssi, CYW43_ITF_STA) == 0) {
        out.println(rssi);
    } else {
        out.println(F("NONE"));
    }
    out.print(F("NET_PORT="));
    out.println(kNetPort);
    out.print(F("NET_CLIENT="));
    if (g_haveClient) {
        out.println(g_client.remoteIP());
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
ProtocolLink &link() {
    return g_link;
}
void printStatus(Print &out) {
    out.println(F("WIFI=UNAVAILABLE (firmware image for a Pico 2, which has no radio)"));
}

}  // namespace net

#endif
