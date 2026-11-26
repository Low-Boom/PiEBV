#pragma once
// SCPI command protocol of the PiEBV delay generator (IEEE 488.2 syntax, SCPI-style
// command tree). The command list is in docs/COMMANDS.md and in the reply to
// SYSTem:HELP:HEADers?; the parser and the tree are in protocol.cpp.
//
// The same protocol runs on every host link: the Pico's USB serial port and, on a
// Pico 2 W with Wi-Fi switched on, one TCP connection (net_link.h). Each link is a
// ProtocolLink with its own line buffer, reply path, error queue, status registers and
// echo switch; the settings and the arm state are shared. A reply goes only to the
// link that sent the command.
//
// Program messages end with '\n', '\r' or "\r\n", up to kProtocolLineMax - 1
// characters. Backspace (0x08) and DEL (0x7F) erase the previous character, so raw
// terminals work. Message units are separated by ';', with the SCPI rules for the
// current path. Headers have a long and a short form, in any case. Times are in
// seconds and frequencies in hertz; suffixes (NS, US, MS, S, HZ, KHZ, MHZ) are
// accepted. A query returns the REALIZED value (whole PIO cycles), in NR3 form.
// Responses to the queries of one message are joined by ';' and end in "\r\n".
//
// A setting gives no reply, and an error goes to the link's error queue
// (SYSTem:ERRor?), as SCPI requires. SYSTem:ECHO ON (not SCPI, per link, off at start)
// makes each setting reply "OK <header> <realized value>" and each error reply
// "ERR <code>,\"<text>\"", for use in a terminal.
//
// Laser arming. The outputs boot DISARMED. OUTPut ON enables them. Not SCPI, for
// safety: the six characters D-I-S-A-R-M (any case) anywhere in the input disarm at
// once, without waiting for the end of the line and whatever surrounds them; the rest
// of that line is discarded. OUTPut OFF and ABORt disarm too.
//
// Replies are written a whole line at a time, and wait for a host that is slow to take
// them only out of a time budget of the link: kReplyBudgetUs (250 ms), which comes back
// at one eighth of the time that passes. When it is used up, replies are dropped
// without a wait until the host has drained the link again.
//   * While more input of the link waits behind the command that is answered, every
//     wait is charged to the budget: a DISARM could be in that input. So commands
//     queued before a DISARM delay it by about 0.3 s in all, however many they are
//     (plus the processor time to run them).
//   * While nothing waits behind the command (a host that sends a command and reads
//     the reply before it sends the next one), a wait is charged only as far as the
//     host takes the line slower than 20 kB/s. Such a host keeps its budget and loses
//     no line, also when it polls in a tight loop. A DISARM that arrives during such a
//     command waits for the rest of it: 250 ms at most.
// Together: about 0.55 s for a DISARM on its own link. The main loop ends a link's
// turn after kLinkTurnUs (main.cpp, serviceLink), so the other link costs one slow
// command for each turn until its own budget is used up; with both hosts slow that
// is about as much again (1.2 s). From tests on a computer with long command queues;
// not measured on a board. Lines that could not be sent are dropped whole and their
// bytes counted (DIAGnostic:TXDRopped?, counted per link and per network host).

#include <Arduino.h>
#include <cstddef>
#include <cstdint>
#include "pulse_timing.h"
#include "wifi_config.h"

// Where the replies of one host link go: the USB serial port, or the TCP client.
class ReplySink {
public:
    virtual bool connected() = 0;  // a host is listening
    virtual int room() = 0;        // bytes that write() takes now without waiting
    // Returns n. 0 = nothing was taken and the caller may try again; any other value =
    // part of the bytes went out (the line then counts as dropped).
    virtual size_t write(const uint8_t *buf, size_t n) = 0;
    // room() that counts as "the host reads again" after a reply was dropped.
    virtual int drainedRoom() { return 64; }

protected:
    ~ReplySink() = default;
};

// ---------------------------------------------------------------- bounded replies
// A sink's write can block for a long time when the host does not read (SerialUSB keeps
// retrying for as long as the host accepts a byte at least once a second) -- during
// which no DISARM can be read, and the 3 s watchdog could fire. ReplyOut buffers each
// reply line and hands the sink a whole line only when it has room for all of it,
// waiting for room only while the link's time budget lasts; a line that does not make
// it is dropped whole (and counted), so a truncated reply can never glue itself onto
// the next one. The budget is one amount for the link, not one per command: it is used
// up by waiting for a slow host and comes back slowly, so a backlog of queued commands
// cannot add up to a long DISARM delay, also when the host takes each reply just in
// time. Once the
// budget has run out, the stall is sticky: until the host drains the sink again, later
// replies write only what fits and never wait.
class ReplyOut : public Print {
public:
    explicit ReplyOut(ReplySink &sink) : sink_(sink) {}
    // Called before every reply: flushes any leftover partial line, then lets the
    // reply wait for as long as the link's time budget lasts, unless the host is
    // still not draining after an earlier give-up.
    void startCommand();
    size_t write(uint8_t c) override;
    size_t write(const uint8_t *buf, size_t n) override;
    uint32_t dropped() const { return dropped_; }
    // True if a reply waited out the time budget and the host has not drained since.
    bool stalled() const { return stalled_; }
    // More input of this link waits behind the command that is being answered (it
    // could be a DISARM): waits are then charged to the budget in full.
    void setInputPending(bool pending) { inputPending_ = pending; }
    // A new host on this link: nothing of the old host's replies is left to send, and
    // its dropped-byte count does not carry over. The time budget does: a host cannot
    // get a new one by connecting again.
    void reset();

private:
    void put(uint8_t c);
    void flushLine();

    ReplySink &sink_;
    uint8_t line_[256];  // = the USB CDC TX FIFO size, so any line fits once it has drained
    size_t lineLen_ = 0;
    uint8_t prev_ = 0;  // last byte put, also across a flush
    uint64_t deadlineUs_ = 0;
    uint64_t budgetUs_ = ~0ull;   // waiting time left; capped to kReplyBudgetUs at the first command
    uint64_t refillUs_ = 0;       // time up to which the budget's refill is counted
    bool stalled_ = false;
    bool inputPending_ = false;
    uint32_t dropped_ = 0;
};

// Line buffer size: a line holds up to kProtocolLineMax - 1 characters (+ NUL).
constexpr size_t kProtocolLineMax = 256;
// Error queue entries per link (SCPI: at least 2); the last one is replaced by -350
// "Queue overflow" when the queue is full.
constexpr size_t kErrorQueueLen = 8;
constexpr size_t kErrorTextMax = 256;  // with the NUL (SCPI allows 255 characters)

// One host link: its input line and its reply path.
class ProtocolLink {
public:
    // usb: this is the Pico's USB port. Only that link may change the Wi-Fi set-up.
    ProtocolLink(ReplySink &sink, bool usb) : out_(sink), usb_(usb) {}
    // A new host on this link (a new TCP client): forgets a partial line.
    void reset();
    // The host of this link is not reading replies (ReplyOut::stalled()).
    bool stalled() const { return out_.stalled(); }
    // Dropped reply bytes (DIAGnostic:TXDRopped?).
    uint32_t dropped() const { return out_.dropped(); }
    // Call before feed(): true if more input of this link has already arrived behind
    // the character that is fed (ReplyOut::setInputPending()).
    void setInputPending(bool pending) { out_.setInputPending(pending); }

    // One entry of the error queue (SYSTem:ERRor?).
    struct Error {
        int16_t code;
        char text[kErrorTextMax];
    };

private:
    friend class Protocol;
    friend struct ScpiAccess;  // protocol.cpp: error queue and status registers
    ReplyOut out_;
    bool usb_;
    char buf_[kProtocolLineMax];
    size_t len_ = 0;
    bool discarding_ = false;  // rest of the current line is dropped, never dispatched
    // Edit-aware history of the current line for the streaming DISARM match (kept
    // separately from buf_ because it must keep working in discard mode): a ring of
    // the last kProtocolLineMax characters, so backspacing over an old character still
    // restores it, with no copying per character.
    char recent_[kProtocolLineMax] = {};
    size_t recentEnd_ = 0;  // ring index of the next character
    size_t recentLen_ = 0;  // characters held, <= kProtocolLineMax
    // --- SCPI state of the link (a new host on the link starts with it cleared)
    Error errors_[kErrorQueueLen];
    size_t errHead_ = 0, errCount_ = 0;
    uint8_t esr_ = 0x80, ese_ = 0, sre_ = 0;  // IEEE 488.2 standard event status (power-on bit set), its enable, service request enable
    bool echo_ = false;                    // SYSTem:ECHO
};

// Read-outs for the SYSTem and DIAGnostic queries.
struct SystemInfo {
    char hw[112];              // "" = in order, else why the pulse outputs do not run
    uint32_t startPendingUs;   // until a pending laser start (restart hold-off), 0 = none
    uint32_t clkHz;
    char clkMode[96];          // STANDARD | OVERCLOCK (jumper fitted) | STANDARD (jumper fitted, overclock off: ...)
    uint32_t vregMv;
    const char *resetCause;    // POWER_ON, WATCHDOG, ...
    uint32_t wdReason, chipReset;  // raw reset registers
    uint32_t wdtResets, wdtMs;
};

struct Identity {
    const char *model;     // e.g. "Pico 2 W"
    const char *serial;    // unique board ID, or "0"
    const char *firmware;  // git describe of the build
};

// The network link's state (SYSTem:COMMunicate:WLAN queries).
struct NetInfo {
    const char *state = "UNAVAILABLE";  // OFF, JOINING, DHCP, CONNECTED, FAULT, UNAVAILABLE
    const char *note = "";              // why the link is not up, or ""
    char ssid[kWifiSsidMax + 1] = "";
    bool passSet = false, atPowerUp = false, saved = true;
    bool macKnown = false;
    uint8_t mac[6] = {};
    char ip[16] = "";        // "" = no address
    bool rssiKnown = false;
    int32_t rssi = 0;
    uint16_t port = 0;
    char client[16] = "";    // address of the TCP host, or ""
};

struct ProtocolHooks {
    // Applies a candidate parameter set to the hardware. Returns nullptr on
    // success and fills *realized; otherwise returns a short reason, and the
    // previous configuration must be left running untouched. (Sole exception: the
    // hardware fails to load counts that passed every check; then the outputs stop,
    // the lasers are disarmed, and DIAGnostic:HARDware? reports it.)
    const char *(*apply)(const PulseParams &params, RealizedTiming *realized);
    // Arm (true) or disarm (false). Returns nullptr on success, or a reason.
    // Disarming must always succeed.
    const char *(*setArmed)(bool arm);
    bool (*isArmed)();
    // Microseconds until a pending laser (re)start fires (restart hold-off), or 0.
    uint32_t (*startPendingUs)();
    void (*systemInfo)(SystemInfo *out);
    void (*identity)(Identity *out);
    // --- Wi-Fi set-up. wifiSet == nullptr: no radio in this build. ---
    // The configuration in use.
    void (*wifiGet)(WifiConfig *cfg);
    // Makes cfg the configuration in use (radio on, off, or a new join) and stores it
    // in flash. Returns nullptr, or why it was refused (then the configuration is as
    // before). On success *notSaved is nullptr, or why cfg holds for this power cycle only.
    const char *(*wifiSet)(const WifiConfig &cfg, const char **notSaved);
    void (*netInfo)(NetInfo *out);
};


struct ScpiCtx;  // one message unit being executed (protocol.cpp)

class Protocol {
public:
    // Applies *params once (the compiled-in defaults). Returns nullptr on
    // success, or the reason they were rejected.
    const char *begin(PulseParams *params, const ProtocolHooks &hooks);

    // Feed the characters of one link one at a time (e.g. from Serial.read()); a
    // program message is run as soon as a complete line has been accumulated.
    void feed(ProtocolLink &link, char c);

    // Queues an error on a link (for example a boot-time hardware problem on the USB
    // link). `code` is an SCPI error number.
    void reportError(ProtocolLink &link, int code, const char *detail);

    // The handlers of the command table in protocol.cpp.
    void cmdField(ScpiCtx &c);
    void cmdPeriod(ScpiCtx &c);
    void cmdDouble(ScpiCtx &c);
    void cmdSync(ScpiCtx &c);
    void cmdOutput(ScpiCtx &c);
    void cmdAbort(ScpiCtx &c);
    void cmdPending(ScpiCtx &c);
    void cmdPixWindow(ScpiCtx &c);
    void cmdIdn(ScpiCtx &c);
    void cmdRst(ScpiCtx &c);
    void cmdCls(ScpiCtx &c);
    void cmdEse(ScpiCtx &c);
    void cmdEsr(ScpiCtx &c);
    void cmdSre(ScpiCtx &c);
    void cmdStb(ScpiCtx &c);
    void cmdOpc(ScpiCtx &c);
    void cmdWai(ScpiCtx &c);
    void cmdTst(ScpiCtx &c);
    void cmdSysErr(ScpiCtx &c);
    void cmdSysErrCount(ScpiCtx &c);
    void cmdSysVersion(ScpiCtx &c);
    void cmdSysEcho(ScpiCtx &c);
    void cmdSysHelp(ScpiCtx &c);
    void cmdWlan(ScpiCtx &c);
    void cmdDiag(ScpiCtx &c);

private:
    void dispatch(ProtocolLink &link, char *line);
    void disarmNow(ProtocolLink &link);
    void wifiChange(ScpiCtx &c, int action);

    PulseParams *params_ = nullptr;
    ProtocolHooks hooks_{};
    RealizedTiming realized_{};
    // WLAN:SSID / WLAN:PASSword collect here until the next WLAN:STATe ON or OFF or
    // WLAN:CLEar. Each of those ends with wifi_ equal to the configuration in use,
    // accepted or refused, so nothing typed earlier can take effect later by surprise.
    WifiConfig wifi_{};
};

// An Arduino Print into a fixed buffer, always NUL-terminated (for SystemInfo texts).
class BufPrint : public Print {
public:
    BufPrint(char *buf, size_t len) : buf_(buf), len_(len) {
        if (len_) {
            buf_[0] = '\0';
        }
    }
    size_t write(uint8_t c) override {
        if (n_ + 1 >= len_) {
            return 0;
        }
        buf_[n_++] = (char)c;
        buf_[n_] = '\0';
        return 1;
    }
    using Print::write;

private:
    char *buf_;
    size_t len_;
    size_t n_ = 0;
};
