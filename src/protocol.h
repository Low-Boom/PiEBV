#pragma once
// Line-based ASCII serial protocol for the PiEBV delay generator.
//
// The same protocol runs on every host link: the Pico's USB serial port and, on a
// Pico 2 W with Wi-Fi switched on, one TCP connection (net_link.h). Each link is a
// ProtocolLink with its own line buffer and its own reply path; the settings and the arm
// state are shared. A reply goes only to the link that sent the command.
//
// One command per line, terminated by '\n', '\r' or "\r\n". Backspace (0x08)
// and DEL (0x7F) erase the previous character, so raw terminals work. A bare
// command name queries the current value; a command followed by one value sets
// it. ARM, ARM?, STATUS, ID?/ID and HELP take no argument. WIFI has sub-commands (the
// Wi-Fi set-up; it changes settings only from the USB link). See HELP output in
// protocol.cpp for the full command list. Every reply line ends in "\r\n".
//
// Time/frequency values are what the user asked for; every reply also shows
// the REALIZED value the PIO actually produces, e.g. at 150 MHz
//   DELAY 1003  ->  OK DELAY=1003 (actual 1000.000 ns, 150 cyc)
// so nobody has to correct for the 6.667 ns quantization by hand.
//
// Laser arming. The outputs boot DISARMED. ARM (exactly that, no argument)
// enables them. DISARM can never be refused: the six characters D-I-S-A-R-M
// (any case) anywhere in the input disarm at once, without waiting for the end
// of the line and whatever surrounds them; the rest of that line is discarded.
//
// Replies are written a whole line at a time with a per-command time budget, and
// once a host stops reading, later replies stop waiting at all until it drains
// again. A host that stops reading therefore delays a DISARM queued on its own link
// by at most about kReplyBudgetUs (250 ms). A DISARM on the other link can wait for
// one such stalled command as well, because the main loop gives the other link its
// turn after every stalled command (main.cpp, serviceLink): about 0.5 s when both
// hosts have stopped reading. Lines that could not be sent are dropped whole and their
// bytes counted (STATUS TX_DROPPED, counted per link and per network host).

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
// waiting at most kReplyBudgetUs per command; a line that does not make it is dropped
// whole (and counted), so a truncated reply can never glue itself onto the next one.
// Once a wait has run out, the stall is sticky: until the host drains the sink again,
// later replies write only what fits and never wait, so a backlog of queued commands
// cannot add up to a long DISARM delay.
class ReplyOut : public Print {
public:
    explicit ReplyOut(ReplySink &sink) : sink_(sink) {}
    // Called before every reply: flushes any leftover partial line, then grants a
    // fresh time budget unless the host is still not draining after an earlier
    // give-up.
    void startCommand();
    size_t write(uint8_t c) override;
    size_t write(const uint8_t *buf, size_t n) override;
    uint32_t dropped() const { return dropped_; }
    // True if a reply of the current command waited out its time budget.
    bool stalled() const { return stalled_; }
    // A new host on this link: nothing of the old host's replies is left to send, and
    // its dropped-byte count does not carry over.
    void reset();

private:
    void put(uint8_t c);
    void flushLine();

    ReplySink &sink_;
    uint8_t line_[256];  // = the USB CDC TX FIFO size, so any line fits once it has drained
    size_t lineLen_ = 0;
    uint8_t prev_ = 0;  // last byte put, also across a flush
    uint64_t deadlineUs_ = 0;
    bool stalled_ = false;
    uint32_t dropped_ = 0;
};

// Line buffer size: a line holds up to kProtocolLineMax - 1 characters (+ NUL).
constexpr size_t kProtocolLineMax = 96;

// One host link: its input line and its reply path.
class ProtocolLink {
public:
    // usb: this is the Pico's USB port. Only that link may change the Wi-Fi set-up.
    ProtocolLink(ReplySink &sink, bool usb) : out_(sink), usb_(usb) {}
    // A new host on this link (a new TCP client): forgets a partial line.
    void reset();
    // The host of this link is not reading replies (ReplyOut::stalled()).
    bool stalled() const { return out_.stalled(); }

private:
    friend class Protocol;
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
};

struct ProtocolHooks {
    // Applies a candidate parameter set to the hardware. Returns nullptr on
    // success and fills *realized; otherwise returns a short reason, and the
    // previous configuration must be left running untouched. (Sole exception: the
    // hardware fails to load counts that passed every check; then the outputs stop,
    // the lasers are disarmed, and STATUS reports it as HW=ERR.)
    const char *(*apply)(const PulseParams &params, RealizedTiming *realized);
    // ARM (true) or DISARM (false). Returns nullptr on success, or a reason.
    // DISARM must always succeed.
    const char *(*setArmed)(bool arm);
    bool (*isArmed)();
    // Microseconds until a pending laser (re)start fires (restart hold-off), or 0.
    uint32_t (*startPendingUs)();
    // Prints the extra STATUS lines (hardware state, reset cause, watchdog), one
    // "KEY=value" each.
    void (*printSystemStatus)(Print &out);
    // One-line firmware identity for ID?.
    void (*printIdentity)(Print &out);
    // The PIO clock in Hz (clk_sys), for HELP's cycle length.
    uint32_t (*clkHz)();
    // --- Wi-Fi set-up (WIFI command). wifiSet == nullptr: no radio in this build. ---
    // The configuration in use.
    void (*wifiGet)(WifiConfig *cfg);
    // Makes cfg the configuration in use (radio on, off, or a new join) and stores it
    // in flash. Returns nullptr, or why it was refused (then the configuration is as
    // before). On success *notSaved is nullptr, or why cfg holds for this power cycle only.
    const char *(*wifiSet)(const WifiConfig &cfg, const char **notSaved);
    // Prints the Wi-Fi and network STATUS lines, one "KEY=value" each.
    void (*printNetStatus)(Print &out);
};

class Protocol {
public:
    // Applies *params once (the compiled-in defaults). Returns nullptr on
    // success, or the reason they were rejected.
    const char *begin(PulseParams *params, const ProtocolHooks &hooks);

    // Feed the characters of one link one at a time (e.g. from Serial.read()); a
    // command is dispatched as soon as a complete line has been accumulated.
    void feed(ProtocolLink &link, char c);

private:
    void dispatch(ProtocolLink &link, char *line);
    void disarmNow(ProtocolLink &link);
    void wifiCommand(ProtocolLink &link, char *args);

    PulseParams *params_ = nullptr;
    ProtocolHooks hooks_{};
    RealizedTiming realized_{};
    // WIFI SSID / WIFI PASS collect here until the next WIFI ON, OFF or CLEAR. Each of
    // those three ends with wifi_ equal to the configuration in use, accepted or
    // refused, so nothing typed earlier can take effect later by surprise.
    WifiConfig wifi_{};
};
