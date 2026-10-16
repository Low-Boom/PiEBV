#include "protocol.h"

#include <cctype>
#include <cerrno>
#include <climits>
#include <cstdlib>
#include <cstring>
#include <strings.h>  // strcasecmp
#include "hardware/timer.h"

namespace {

// ---------------------------------------------------------------- bounded replies
// SerialUSB::write() keeps retrying for as long as the host accepts a byte at
// least once a second, so one long reply to a slowly-draining (or paused) host
// can block for many seconds -- during which no DISARM can be read, and the 3 s
// watchdog could fire. ReplyOut buffers each reply line and hands Serial a whole
// line only when the TX FIFO has room for all of it, waiting at most
// kReplyBudgetUs per command; a line that does not make it is dropped whole (and
// counted), so a truncated reply can never glue itself onto the next one. Once a
// wait has run out, the stall is sticky: until the host drains the FIFO again,
// later replies write only what fits and never wait, so a backlog of queued
// commands cannot add up to a long DISARM delay.
constexpr uint64_t kReplyBudgetUs = 250000;
constexpr int kDrainedRoom = 64;  // free TX FIFO bytes that count as "the host is reading again"

class ReplyOut : public Print {
public:
    // Called before every reply: flushes any leftover partial line, then grants a
    // fresh time budget unless the host is still not draining after an earlier
    // give-up.
    void startCommand() {
        flushLine();
        if (stalled_ && Serial && Serial.availableForWrite() >= kDrainedRoom) {
            stalled_ = false;
        }
        deadlineUs_ = stalled_ ? 0 : time_us_64() + kReplyBudgetUs;
    }
    size_t write(uint8_t c) override {
        // Every line ends in "\r\n", as println() writes it: a bare '\n' (inside a
        // multi-line F() text) gets its '\r' here.
        if (c == '\n' && prev_ != '\r') {
            put('\r');
        }
        put(c);
        return 1;
    }
    size_t write(const uint8_t *buf, size_t n) override {
        for (size_t i = 0; i < n; ++i) {
            write(buf[i]);
        }
        return n;
    }
    uint32_t dropped() const { return dropped_; }

private:
    void put(uint8_t c) {
        prev_ = c;
        line_[lineLen_++] = c;
        if (c == '\n' || lineLen_ == sizeof(line_)) {
            flushLine();
        }
    }

    void flushLine() {
        if (lineLen_ == 0) {
            return;
        }
        bool sent = false;
        while (Serial) {  // no host listening: drop at once, never wait
            if (Serial.availableForWrite() >= (int)lineLen_) {
                sent = Serial.write(line_, lineLen_) == lineLen_;
                break;
            }
            if (time_us_64() >= deadlineUs_) {
                stalled_ = true;
                break;
            }
        }
        if (!sent) {
            dropped_ += (uint32_t)lineLen_;
        }
        lineLen_ = 0;
    }

    uint8_t line_[256];  // = the USB CDC TX FIFO size, so any line fits once it has drained
    size_t lineLen_ = 0;
    uint8_t prev_ = 0;  // last byte put, also across a flush
    uint64_t deadlineUs_ = 0;
    bool stalled_ = false;
    uint32_t dropped_ = 0;
};

ReplyOut g_out;

// ---------------------------------------------------------------- fields
// How a field's realized value is shown.
enum class Unit : uint8_t { Ns, Hz, Mode, PixMode };

struct FieldCommand {
    const char *name;
    uint32_t PulseParams::*field;
    Unit unit;
    uint32_t RealizedTiming::*realized;  // cycle count (the period, for Hz)
};

const FieldCommand kFields[] = {
    {"FREQ", &PulseParams::freqHz, Unit::Hz, &RealizedTiming::periodCycles},
    {"WIDTH", &PulseParams::widthNs, Unit::Ns, &RealizedTiming::widthCycles},
    {"DELAY", &PulseParams::delayNs, Unit::Ns, &RealizedTiming::delayCycles},
    {"MARKERWIDTH", &PulseParams::markerWidthNs, Unit::Ns, &RealizedTiming::markerWidthCycles},
    {"COMBINE", &PulseParams::combine, Unit::Mode, &RealizedTiming::combine},
    {"PIXGATE", &PulseParams::pixGate, Unit::PixMode, &RealizedTiming::pixGate},
    {"PIXLEAD", &PulseParams::pixLeadNs, Unit::Ns, &RealizedTiming::pixLeadCycles},
    {"PIXLAG", &PulseParams::pixLagNs, Unit::Ns, &RealizedTiming::pixLagCycles},
};

// Prints "NAME=value" plus the realized value -- " (actual X ns, N cyc)" or
// " (actual X Hz, period N cyc)" -- then a newline.
void printField(const FieldCommand &f, uint32_t value, const RealizedTiming &r) {
    g_out.print(f.name);
    g_out.print('=');
    g_out.print(value);
    if (f.unit == Unit::Mode) {
        g_out.print(value ? F(" (CH1 + CH2 on LASER 1 and LASER 2)") : F(" (CH1 on LASER 1, CH2 on LASER 2)"));
    } else if (f.unit == Unit::PixMode) {
        g_out.print(value == 0   ? F(" (off: pixel reset from J12 only)")
                    : value == 1 ? F(" (pixels reset between pulse pairs while ARMED)")
                                 : F(" (pixels reset between pulse pairs, also while DISARMED)"));
    } else if (r.clkHz != 0) {
        const uint32_t n = r.*(f.realized);
        char num[32];
        g_out.print(F(" (actual "));
        switch (f.unit) {
            case Unit::Ns:
                pulseFormatNs(n, r.clkHz, num, sizeof(num));
                g_out.print(num);
                g_out.print(F(" ns, "));
                g_out.print(n);
                g_out.print(F(" cyc)"));
                break;
            case Unit::Hz:
                pulseFormatHz(n, r.clkHz, num, sizeof(num));
                g_out.print(num);
                g_out.print(F(" Hz, period "));
                g_out.print(n);
                g_out.print(F(" cyc)"));
                break;
            case Unit::Mode:
            case Unit::PixMode:
                break;
        }
    }
    g_out.println();
}

// The pixel-reset window the gate realizes each period (STATUS only).
void printPixReset(const RealizedTiming &r) {
    g_out.print(F("PIXRESET="));
    if (!r.pixGate || r.clkHz == 0) {
        g_out.println(F("off"));
        return;
    }
    char num[32];
    pulseFormatNs(r.pixResetCycles, r.clkHz, num, sizeof(num));
    g_out.print(num);
    g_out.print(F(" ns per period, from CH1 + "));
    pulseFormatNs(r.pixResetStartCycles, r.clkHz, num, sizeof(num));
    g_out.print(num);
    g_out.print(F(" ns; pixels free "));
    pulseFormatNs(r.periodCycles - r.pixResetCycles, r.clkHz, num, sizeof(num));
    g_out.print(num);
    g_out.println(F(" ns around each pulse pair"));
}

void printArmed(bool armed) {
    g_out.print(F("ARMED="));
    g_out.println(armed ? 1 : 0);
}

void reportErr(const char *name, const char *reason) {
    g_out.print(F("ERR "));
    g_out.print(name);
    g_out.print(' ');
    g_out.println(reason);
}

// For a command that takes no argument: reports an error and returns true if one was
// given, so that e.g. "ARM? 1" cannot pass for a setting.
bool rejectArgument(const char *name, const char *valueStr) {
    if (!valueStr) {
        return false;
    }
    reportErr(name, "takes no argument");
    return true;
}

// Every number that depends on the clock or on a timing constant is computed, not
// written into the text. clkHz 0 (unknown) leaves out the lines that need it.
void printHelp(uint32_t clkHz) {
    g_out.print(F(
        "FREQ <Hz>          pulse-pair repetition frequency\n"
        "WIDTH <ns>         CH1/CH2 pulse width\n"
        "DELAY <ns>         CH2 rising edge after CH1 rising edge\n"
        "MARKERWIDTH <ns>   marker pulse width\n"
        "COMBINE <0|1>      1 = both pulses on BOTH laser outputs (two sources, one\n"
        "                   double pulse); 0 = CH1 on LASER 1, CH2 on LASER 2\n"
        "PIXGATE <0|1|2>    camera pixel reset between pulse pairs, ANDed with the J12\n"
        "                   input: 0 = off (J12 only), 1 = while ARMED, 2 = always\n"
        "PIXLEAD <ns>       pixels released this long before each CH1 (>= "));
    g_out.print(kPixGateMinLeadCycles);
    g_out.println(F(" cycles)\n"
        "PIXLAG <ns>        pixels reset again this long after the last laser pulse\n"
        "ARM                enable the laser outputs (the board boots DISARMED)\n"
        "DISARM             disable the laser outputs: always accepted, immediate, and\n"
        "                   recognised anywhere in the input, even mid-line\n"
        "ARM?               query the arm state\n"
        "STATUS             all settings with realized values, arm state, reset cause\n"
        "ID?                firmware identity and version\n"
        "HELP               this text"));
    g_out.print(F("SYNC (the camera sync clock) is fixed at "));
    g_out.print(kSyncHz);
    g_out.println(F(" Hz: not a setting, and not in STATUS.\n"
                    "A bare name (e.g. DELAY) queries it; NAME VALUE sets it. ARM, ARM?,\n"
                    "STATUS, ID? and HELP take no argument."));
    char buf[32];
    if (clkHz != 0) {
        constexpr uint32_t kExampleNs = 1003;
        const uint64_t exampleCycles = pulseNsToCycles(kExampleNs, clkHz);
        pulseFormatNs(exampleCycles, clkHz, buf, sizeof(buf));
        g_out.print(F("Replies show the realized value, e.g. OK DELAY="));
        g_out.print(kExampleNs);
        g_out.print(F(" (actual "));
        g_out.print(buf);
        g_out.print(F(" ns, "));
        g_out.print((uint32_t)exampleCycles);
        g_out.println(F(" cyc)."));
        pulseFormatNs(1, clkHz, buf, sizeof(buf));
        g_out.print(F("Times realize to whole PIO cycles of "));
        g_out.print(buf);
        pulseFormatNs(kPulseMinWidthCycles, clkHz, buf, sizeof(buf));
        g_out.print(F(" ns; WIDTH and MARKERWIDTH must realize to >= "));
        g_out.print(kPulseMinWidthCycles);
        g_out.print(F(" cycles ("));
        g_out.print(buf);
        g_out.println(F(" ns)."));
    }
    g_out.print(F("No laser-driver limits are imposed (pulse width, duty): check your driver's\n"
                  "ratings. Pulse pairs stay separated: DELAY <= 1/FREQ - 2 x WIDTH.\n"
                  "With COMBINE 1 each output carries both pulses, so DELAY must also exceed\n"
                  "WIDTH (by >= 1 cycle). Change COMBINE only while DISARMED.\n"
                  "With PIXGATE on, PIXLEAD + DELAY + WIDTH + PIXLAG must leave >= "));
    g_out.print(kPulseMinWidthCycles);
    g_out.println(F(" cycles\n"
                    "of pixel reset per period. The first pulse pair after a start has no reset\n"
                    "before it; every later pair does."));
    g_out.println(F(
        "MARKER and SYNC run while DISARMED; CH1/CH2 are held LOW. ARM, and pulse\n"
        "changes while armed, restart CH1/CH2/MARKER together after a hold-off of up\n"
        "to one pulse period (<= 1 s), so the laser pulse spacing never drops below\n"
        "the set period. The reply comes at once; the pulses follow the hold-off."));
}

}  // namespace

const char *Protocol::begin(PulseParams *params, const ProtocolHooks &hooks) {
    params_ = params;
    hooks_ = hooks;
    len_ = 0;
    discarding_ = false;
    recentEnd_ = 0;
    recentLen_ = 0;
    if (!hooks_.apply) {
        return "no hardware";
    }
    return hooks_.apply(*params_, &realized_);
}

void Protocol::disarmNow() {
    hooks_.setArmed(false);
    g_out.startCommand();
    g_out.print(F("OK "));
    printArmed(false);
}

void Protocol::feed(char c) {
    if (c == '\0') {
        return;  // a NUL would silently truncate the command (e.g. "ARM<NUL>X" -> "ARM")
    }
    if (c == '\r' || c == '\n') {
        // CR, LF and CRLF all end a line (the LF of a CRLF then ends an empty
        // line, which is ignored).
        buf_[len_] = '\0';
        if (len_ > 0 && !discarding_) {
            dispatch(buf_);
        }
        len_ = 0;
        discarding_ = false;
        recentLen_ = 0;
        return;
    }
    if (c == '\b' || c == 0x7F) {  // Backspace / DEL: erase the previous character
        if (len_ > 0) {
            --len_;
        }
        if (recentLen_ > 0) {
            --recentLen_;
            recentEnd_ = (recentEnd_ == 0 ? kLineMax : recentEnd_) - 1;
        }
        return;
    }

    // Streaming DISARM match, independent of the line buffer and of discard mode:
    // the last six characters of the edited history. When the ring is full, the new
    // character replaces the oldest.
    recent_[recentEnd_] = (char)toupper((unsigned char)c);
    recentEnd_ = (recentEnd_ + 1 == kLineMax) ? 0 : recentEnd_ + 1;
    if (recentLen_ < kLineMax) {
        ++recentLen_;
    }
    static constexpr char kDisarm[] = "DISARM";
    constexpr size_t kDisarmLen = sizeof(kDisarm) - 1;
    bool disarm = recentLen_ >= kDisarmLen;
    for (size_t i = 0; disarm && i < kDisarmLen; ++i) {
        disarm = recent_[(recentEnd_ + kLineMax - kDisarmLen + i) % kLineMax] == kDisarm[i];
    }
    if (disarm) {
        disarmNow();
        len_ = 0;
        discarding_ = true;  // nothing else on this line runs
        recentLen_ = 0;
        return;
    }

    if (discarding_) {
        return;
    }
    if (len_ + 1 >= sizeof(buf_)) {
        // Drop the whole line, including whatever arrives before its end, so no
        // tail of it is ever run as a command of its own.
        len_ = 0;
        discarding_ = true;
        g_out.startCommand();
        g_out.println(F("ERR line too long"));
        return;
    }
    buf_[len_++] = c;
}

void Protocol::dispatch(char *line) {
    g_out.startCommand();
    char *cmd = strtok(line, " \t");
    if (!cmd) {
        return;
    }
    // Fallback only: feed()'s streaming match already disarms (and discards the
    // line) as soon as D-I-S-A-R-M arrives, so this should never be reached.
    if (strncasecmp(cmd, "DISARM", 6) == 0) {
        disarmNow();
        return;
    }

    char *valueStr = strtok(nullptr, " \t");
    const bool extraArgs = valueStr && strtok(nullptr, " \t") != nullptr;

    if (strcasecmp(cmd, "ARM?") == 0) {
        if (!rejectArgument("ARM?", valueStr)) {
            printArmed(hooks_.isArmed());
        }
        return;
    }

    if (strcasecmp(cmd, "ARM") == 0) {
        // Arming is strict: only a bare "ARM" arms.
        if (rejectArgument("ARM", valueStr)) {
            return;
        }
        if (const char *why = hooks_.setArmed(true)) {
            reportErr("ARM", why);
            return;
        }
        g_out.print(F("OK "));
        g_out.print(F("ARMED=1"));
        if (const uint32_t us = hooks_.startPendingUs ? hooks_.startPendingUs() : 0) {
            g_out.print(F(" (laser pulses start after a "));
            g_out.print(us);
            g_out.print(F(" us hold-off)"));
        }
        g_out.println();
        return;
    }

    for (const auto &f : kFields) {
        if (strcasecmp(cmd, f.name) != 0) {
            continue;
        }
        if (!valueStr) {
            printField(f, params_->*(f.field), realized_);
            return;
        }
        if (extraArgs) {
            reportErr(f.name, "takes one value");
            return;
        }
        char *end = nullptr;
        errno = 0;
        const unsigned long v = strtoul(valueStr, &end, 10);
        bool bad = !isdigit((unsigned char)valueStr[0]) || end == valueStr || *end != '\0' || errno == ERANGE;
#if ULONG_MAX > 0xFFFFFFFFUL
        bad = bad || v > 0xFFFFFFFFUL;  // only reachable where unsigned long is 64-bit
#endif
        if (bad) {
            reportErr(f.name, "invalid value");
            return;
        }
        PulseParams candidate = *params_;
        candidate.*(f.field) = (uint32_t)v;
        RealizedTiming realized;
        if (const char *why = hooks_.apply(candidate, &realized)) {
            g_out.print(F("ERR "));
            g_out.print(f.name);
            g_out.print(F(" rejected: "));
            g_out.println(why);
            return;
        }
        *params_ = candidate;
        realized_ = realized;
        g_out.print(F("OK "));
        printField(f, (uint32_t)v, realized_);
        return;
    }

    if (strcasecmp(cmd, "STATUS") == 0) {
        if (rejectArgument("STATUS", valueStr)) {
            return;
        }
        for (const auto &f : kFields) {
            printField(f, params_->*(f.field), realized_);
        }
        printPixReset(realized_);
        printArmed(hooks_.isArmed());
        if (hooks_.printSystemStatus) {
            hooks_.printSystemStatus(g_out);
        }
        g_out.print(F("TX_DROPPED="));
        g_out.println(g_out.dropped());
        return;
    }

    if (strcasecmp(cmd, "ID?") == 0 || strcasecmp(cmd, "ID") == 0) {
        if (!rejectArgument("ID?", valueStr) && hooks_.printIdentity) {
            hooks_.printIdentity(g_out);
        }
        return;
    }

    if (strcasecmp(cmd, "HELP") == 0) {
        if (!rejectArgument("HELP", valueStr)) {
            printHelp(hooks_.clkHz ? hooks_.clkHz() : realized_.clkHz);
        }
        return;
    }

    if (strcasecmp(cmd, "MARKERDIV") == 0) {  // removed setting: say why, for old host scripts
        reportErr("MARKERDIV", "removed: the marker fires with every pulse pair");
        return;
    }

    reportErr(cmd, "unknown command");
}
