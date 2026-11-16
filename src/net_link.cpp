#include "net_link.h"

#if defined(ARDUINO_RASPBERRY_PI_PICO_2W)

#include <EEPROM.h>
#include <SimpleMDNS.h>
#include <lwIP_CYW43.h>
#include <pico/cyw43_arch.h>
#include "clock_mode.h"
#include "tcp_link.h"
#include "hardware/clocks.h"
#include "hardware/timer.h"
#include "lwip/netif.h"

namespace {

constexpr uint32_t kPollMs = 200;           // join-state poll
constexpr uint32_t kRejoinDelayMs = 5000;   // shortest time between two join requests
constexpr uint32_t kJoinTimeoutMs = 20000;  // a join with no result is started again
constexpr uint32_t kProbeMs = 2000;         // signal-level read while joined: also the radio's liveness check
// The driver reports "no answer" also for a chip that is alive but holds back its bus
// credits for about a second (a bad link), so one failed test is not a fault: the
// second one in a row is.
constexpr int kProbeFailLimit = 2;
// A frame send that took this long waited inside the driver. Frames are then held back
// until the chip has answered a test command.
constexpr uint64_t kSlowFrameUs = 300000;
constexpr uint32_t kIoctlGetRssi = 0xFE;    // CYW43_IOCTL_GET_RSSI, as in the core's CYW43lwIP::RSSI()
constexpr size_t kEepromSize = 256;         // >= kWifiRecordSize, a multiple of the flash page
// cyw43_wifi_pm() value the core uses for "no power saving" (WiFiClass::noLowPowerMode):
// the radio stays awake, so a command does not wait for the next beacon.
constexpr uint32_t kNoPowerSave = 0xA11140;

static_assert(kEepromSize >= kWifiRecordSize && kEepromSize % 256 == 0, "EEPROM size");

WifiConfig g_cfg;
bool g_saved = true;  // g_cfg is what the next power-up will load from flash

enum class Phase : uint8_t {
    Off,      // radio chip off, no network interface
    Joining,  // join requested, or waiting to request it again
    Linked,   // joined; CONNECTED once DHCP gave an address
    Fault,    // as Off, after the radio chip stopped answering; until WIFI ON or a power cycle
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
// True: no frame is handed to the radio's driver (the chip is off, or it is in doubt).
// With a chip that does not answer, the driver waits about a second inside every frame
// send, also in lwIP's background work. lwIP sends a dropped TCP segment again.
volatile bool g_radioOff = true;
volatile bool g_radioSuspect = false;  // a frame send was slow: test the chip at once
int g_probeFails = 0;                  // failed test commands in a row

// One cheap driver command. False = the driver gave up: it could not wake the bus,
// could not send (no bus credits), or got no answer, each after its own time-out of
// about 1 s (cyw43_ll.c). `*rssi` (may be nullptr) gets the signal level.
bool radioAnswers(int32_t *rssi) {
    int32_t v = 0;
    if (cyw43_ioctl(&cyw43_state, kIoctlGetRssi, sizeof(v), (uint8_t *)&v, CYW43_ITF_STA) != 0) {
        return false;
    }
    if (rssi) {
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

// The core's CYW43 device, with three changes:
//   * begin() does not wait for the join. (The core's CYW43::begin() polls the join
//     with delay() for up to its time-out, and without a limit when the time-out ends
//     in the middle of a join.)
//   * end() sends no "leave" command: radioStop() powers the chip off instead, which
//     needs no answer from the chip.
//   * sendFrame() drops the frame while g_radioOff is set.
class RadioDev : public CYW43 {
public:
    using CYW43::CYW43;

    // Called by LwipIntfDev::begin() after netif_add(). False if the radio chip did
    // not start.
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
        // Powers the chip and loads its firmware (the long call): the chip is always
        // off before this, see radioStop().
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

    void end() { _netif = nullptr; }

    // Called from the main loop and from lwIP's background work.
    uint16_t sendFrame(struct pbuf *p) {
        if (g_radioOff) {
            return 0;
        }
        const uint64_t t0 = time_us_64();
        const uint16_t sent = CYW43::sendFrame(p);
        if (time_us_64() - t0 >= kSlowFrameUs) {
            g_radioOff = true;  // until probe() has heard from the chip
            g_radioSuspect = true;
        }
        return sent;
    }
};

LwipIntfDev<RadioDev> g_radio;
bool g_mdnsStarted = false;

// ---------------------------------------------------------------- radio
// Takes the link down and powers the radio chip off. `polite` true (a command of the
// user, chip in order): the host gets a reset and the network a DHCP release before
// the chip goes off. `polite` false (the chip does not answer): nothing more is handed
// to the driver. Neither way needs an answer from the chip, and the next start powers
// it up and loads its firmware again.
// Chip supply off (WL_REG_ON low) and the driver back in its start state, with its bus
// (a PIO state machine and two DMA channels) released. cyw43_deinit() does this for a
// chip that started. It returns at once for a chip whose start failed part of the way,
// which the driver leaves powered and with the bus claimed; so the two steps are also
// made directly. Both do nothing when there is nothing to do, and neither needs an
// answer from the chip.
void radioPowerOff() {
    cyw43_deinit(&cyw43_state);
    cyw43_arch_lwip_begin();  // the driver's lock
    cyw43_ll_deinit(&cyw43_state.cyw43_ll);
    cyw43_init(&cyw43_state);
    cyw43_arch_lwip_end();
}

void radioStop(bool polite) {
    const bool running = g_phase == Phase::Joining || g_phase == Phase::Linked;
    if (!polite) {
        g_radioOff = true;
    }
    tcplink::stop(!polite);  // a failed radio: input that has arrived is still run
    if (running) {
        g_radio.end();  // DHCP stop, interface removed (mDNS follows through its callback)
    }
    g_radioOff = true;
    radioPowerOff();
    g_radioSuspect = false;
    g_probeFails = 0;
    g_phase = Phase::Off;
    g_note = nullptr;
    g_rssiKnown = false;
}

void radioFault() {
    radioStop(false);
    g_phase = Phase::Fault;
    g_note = "the radio chip stopped answering: send WIFI ON to start it again";
}

// Powers the radio up, brings the interface up and requests the join. nullptr, or why
// the radio is off.
const char *radioStart() {
    radioStop(true);
    g_radioOff = false;
    g_radio.setHostname(kNetHostname);
    if (!g_radio.begin()) {
        radioStop(false);
        g_note = "the radio chip did not start";
        return g_note;
    }
    g_phase = Phase::Joining;  // from here on radioStop() takes the interface down
    cyw43_wifi_pm(&cyw43_state, kNoPowerSave);
    if (!tcplink::start(kNetPort)) {
        radioStop(true);
        g_note = "the TCP server did not start";
        return g_note;
    }
    if (!g_mdnsStarted) {  // once: it follows the interface from here on
        g_mdnsStarted = MDNS.begin(kNetHostname);
        MDNS.addService(kNetHostname, "tcp", kNetPort);
    }
    g_lastJoinMs = millis();
    g_lastPollMs = g_lastJoinMs;
    g_lastProbeMs = g_lastJoinMs;
    return nullptr;
}

bool linkUp() {
    return netif_is_link_up(g_radio.getNetIf());
}

// Tests the chip with one driver command. True if it answered. On the second failure
// in a row the radio is powered off (radioFault()).
// Frames are held back from before the test until the chip has answered: when the
// driver call ends, lwIP's background work runs with everything that became due in the
// meantime, and each frame to a chip that does not answer would wait in the driver
// again. So a failed test costs the command loop the driver's time-outs for one
// command (1 to 2 s), and nothing after that.
bool probe(int32_t *rssi) {
    g_radioOff = true;
    g_radioSuspect = false;
    if (radioAnswers(rssi)) {
        g_probeFails = 0;
        g_radioOff = false;
        return true;
    }
    if (++g_probeFails >= kProbeFailLimit) {
        radioFault();
    }
    return false;
}

// A join request is more than ten driver commands, whose results the driver does not
// report. So it goes only to a chip that has just answered one.
void rejoin(uint32_t nowMs) {
    g_lastJoinMs = nowMs;
    if (probe(nullptr)) {
        requestJoin();
    }
}

void pollJoin(uint32_t nowMs) {
    const bool up = linkUp();
    if (g_phase == Phase::Linked) {
        if (!up) {
            g_phase = Phase::Joining;
            g_note = "link lost";
            g_rssiKnown = false;
        } else if (g_radioSuspect || nowMs - g_lastProbeMs >= kProbeMs) {
            // The signal level for STATUS, read here so that STATUS makes no radio
            // call; a chip that has stopped answering is found here too.
            g_lastProbeMs = nowMs;
            int32_t rssi = 0;
            if (probe(&rssi) && rssi != 0) {
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

// Writes cfg to flash if the flash holds something else. nullptr, or why it is not there.
const char *store(const WifiConfig &cfg) {
    uint8_t rec[kWifiRecordSize];
    wifiRecordEncode(cfg, rec);
    EEPROM.begin(kEepromSize);  // (re)reads the sector
    // Nothing to write if the flash already gives this set-up at power-up: the same
    // record, or no valid record and the empty set-up (as begin() reads it).
    WifiConfig inFlash;
    if (!wifiRecordDecode(EEPROM.getConstDataPtr(), &inFlash)) {
        inFlash = WifiConfig{};
    }
    if (wifiConfigSame(inFlash, cfg)) {
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
    if (!wifiRecordDecode(EEPROM.getConstDataPtr(), &g_cfg)) {
        g_cfg = WifiConfig{};  // no record: the set-up of every power-up until one is stored
    }
    g_saved = true;
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
        radioStop(true);
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
    const uint32_t now = millis();
    if ((g_phase == Phase::Joining || g_phase == Phase::Linked) &&
        (now - g_lastPollMs >= kPollMs || g_radioSuspect)) {
        g_lastPollMs = now;
        pollJoin(now);
    }
    tcplink::service();  // also with the radio off: the last input of a host is still read
}

int read() {
    return tcplink::read();
}

void flush() {
    tcplink::flush();
}

ProtocolLink &link() {
    return tcplink::link();
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
    ip_addr_t host;
    if (tcplink::hostAddress(&host)) {
        out.println(IPAddress(host));
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
