#include "protocol.h"

#include <cctype>
#include <cerrno>
#include <climits>
#include <cstdlib>
#include <cstring>
#include <strings.h>  // strcasecmp
#include "hardware/timer.h"

namespace {

constexpr uint64_t kReplyBudgetUs = 250000;
constexpr uint64_t kBudgetRefillDiv = 8;  // 1 us of budget comes back per 8 us that pass

// The reply path of the command being handled. Set on entry to Protocol::feed(), so
// the print helpers below need no extra argument. The firmware is single-threaded.
ReplyOut *g_out = nullptr;

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
    g_out->print(f.name);
    g_out->print('=');
    g_out->print(value);
    if (f.unit == Unit::Mode) {
        g_out->print(value ? F(" (CH1 + CH2 on LASER 1 and LASER 2)") : F(" (CH1 on LASER 1, CH2 on LASER 2)"));
    } else if (f.unit == Unit::PixMode) {
        g_out->print(value == 0   ? F(" (off: no pixel reset)")
                    : value == 1 ? F(" (pixels reset between pulse pairs while ARMED)")
                                 : F(" (pixels reset between pulse pairs, also while DISARMED)"));
    } else if (r.clkHz != 0) {
        const uint32_t n = r.*(f.realized);
        char num[32];
        g_out->print(F(" (actual "));
        switch (f.unit) {
            case Unit::Ns:
                pulseFormatNs(n, r.clkHz, num, sizeof(num));
                g_out->print(num);
                g_out->print(F(" ns, "));
                g_out->print(n);
                g_out->print(F(" cyc)"));
                break;
            case Unit::Hz:
                pulseFormatHz(n, r.clkHz, num, sizeof(num));
                g_out->print(num);
                g_out->print(F(" Hz, period "));
                g_out->print(n);
                g_out->print(F(" cyc)"));
                break;
            case Unit::Mode:
            case Unit::PixMode:
                break;
        }
    }
    g_out->println();
}

// The pixel-reset window the gate realizes each period (STATUS only).
void printPixReset(const RealizedTiming &r) {
    g_out->print(F("PIXRESET="));
    if (!r.pixGate || r.clkHz == 0) {
        g_out->println(F("off"));
        return;
    }
    char num[32];
    pulseFormatNs(r.pixResetCycles, r.clkHz, num, sizeof(num));
    g_out->print(num);
    g_out->print(F(" ns per period, from CH1 + "));
    pulseFormatNs(r.pixResetStartCycles, r.clkHz, num, sizeof(num));
    g_out->print(num);
    g_out->print(F(" ns; pixels free "));
    pulseFormatNs(r.periodCycles - r.pixResetCycles, r.clkHz, num, sizeof(num));
    g_out->print(num);
    g_out->println(F(" ns around each pulse pair"));
}

void printArmed(bool armed) {
    g_out->print(F("ARMED="));
    g_out->println(armed ? 1 : 0);
}

void reportErr(const char *name, const char *reason) {
    g_out->print(F("ERR "));
    g_out->print(name);
    g_out->print(' ');
    g_out->println(reason);
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
    g_out->print(F(
        "FREQ <Hz>          pulse-pair repetition frequency\n"
        "WIDTH <ns>         CH1/CH2 pulse width\n"
        "DELAY <ns>         CH2 rising edge after CH1 rising edge\n"
        "MARKERWIDTH <ns>   marker pulse width (camera trigger and J12), <= 1/FREQ / 2\n"
        "COMBINE <0|1>      1 = both pulses on BOTH laser outputs (two sources, one\n"
        "                   double pulse); 0 = CH1 on LASER 1, CH2 on LASER 2\n"
        "PIXGATE <0|1|2>    camera pixel reset between pulse pairs (the only source of\n"
        "                   pixel reset): 0 = off, 1 = while ARMED, 2 = always\n"
        "PIXLEAD <ns>       pixels released this long before each CH1 (>= "));
    g_out->print(kPixGateMinLeadCycles);
    g_out->println(F(" cycles)\n"
        "PIXLAG <ns>        pixels reset again this long after the last laser pulse\n"
        "ARM                enable the laser outputs (the board boots DISARMED)\n"
        "DISARM             disable the laser outputs: always accepted, immediate, and\n"
        "                   recognised anywhere in the input, even mid-line\n"
        "ARM?               query the arm state\n"
        "STATUS             all settings with realized values, arm state, reset cause\n"
        "ID?                firmware identity and version\n"
        "WIFI               Wi-Fi state. Set-up, from the USB port only, while DISARMED:\n"
        "                   WIFI SSID <name>, WIFI PASS [passphrase], then WIFI ON (joins\n"
        "                   now and at every power-up); WIFI OFF; WIFI CLEAR\n"
        "HELP               this text"));
    g_out->print(F("SYNC (the camera sync clock) is fixed at "));
    g_out->print(kSyncHz);
    g_out->println(F(" Hz: not a setting, and not in STATUS.\n"
                    "A bare name (e.g. DELAY) queries it; NAME VALUE sets it. ARM, ARM?,\n"
                    "STATUS, ID? and HELP take no argument."));
    g_out->print(F("With Wi-Fi on, the same commands also run on TCP port "));
    g_out->print(kNetPort);
    g_out->println(F(", one host at a time,\n"
                    "ARM included. The link has no password and no encryption. A lost link\n"
                    "does not disarm."));
    char buf[32];
    if (clkHz != 0) {
        constexpr uint32_t kExampleNs = 1003;
        const uint64_t exampleCycles = pulseNsToCycles(kExampleNs, clkHz);
        pulseFormatNs(exampleCycles, clkHz, buf, sizeof(buf));
        g_out->print(F("Replies show the realized value, e.g. OK DELAY="));
        g_out->print(kExampleNs);
        g_out->print(F(" (actual "));
        g_out->print(buf);
        g_out->print(F(" ns, "));
        g_out->print((uint32_t)exampleCycles);
        g_out->println(F(" cyc)."));
        pulseFormatNs(1, clkHz, buf, sizeof(buf));
        g_out->print(F("Times realize to whole PIO cycles of "));
        g_out->print(buf);
        pulseFormatNs(kPulseMinWidthCycles, clkHz, buf, sizeof(buf));
        g_out->print(F(" ns; WIDTH and MARKERWIDTH must realize to >= "));
        g_out->print(kPulseMinWidthCycles);
        g_out->print(F(" cycles ("));
        g_out->print(buf);
        g_out->println(F(" ns)."));
    }
    g_out->print(F("No laser-driver limits are imposed (pulse width, duty): check your driver's\n"
                  "ratings. Pulse pairs stay separated: DELAY <= 1/FREQ - 2 x WIDTH.\n"
                  "The marker is at most 50 % duty (2 x MARKERWIDTH <= 1/FREQ), which\n"
                  "protects the J12 output (External Sync Out) against a shorted cable.\n"
                  "With COMBINE 1 each output carries both pulses, so DELAY must also exceed\n"
                  "WIDTH (by >= 1 cycle). Change COMBINE only while DISARMED.\n"
                  "With PIXGATE on, PIXLEAD + DELAY + WIDTH + PIXLAG must leave >= "));
    g_out->print(kPulseMinWidthCycles);
    g_out->println(F(" cycles\n"
                    "of pixel reset per period. The first pulse pair after a start has no reset\n"
                    "before it; every later pair does."));
    g_out->println(F(
        "MARKER and SYNC run while DISARMED; CH1/CH2 are held LOW. ARM, and pulse\n"
        "changes while armed, restart CH1/CH2/MARKER together after a hold-off of up\n"
        "to one pulse period (<= 1 s), so the laser pulse spacing never drops below\n"
        "the set period. The reply comes at once; the pulses follow the hold-off."));
}

}  // namespace

// ---------------------------------------------------------------- bounded replies
void ReplyOut::startCommand() {
    flushLine();
    const uint64_t now = time_us_64();
    const uint64_t back = (now - refillUs_) / kBudgetRefillDiv;
    refillUs_ += back * kBudgetRefillDiv;
    budgetUs_ = (budgetUs_ > kReplyBudgetUs || back >= kReplyBudgetUs - budgetUs_) ? kReplyBudgetUs : budgetUs_ + back;
    if (stalled_ && sink_.connected() && sink_.room() >= sink_.drainedRoom()) {
        stalled_ = false;
    }
    deadlineUs_ = stalled_ ? 0 : now + budgetUs_;
}

size_t ReplyOut::write(uint8_t c) {
    // Every line ends in "\r\n", as println() writes it: a bare '\n' (inside a
    // multi-line F() text) gets its '\r' here.
    if (c == '\n' && prev_ != '\r') {
        put('\r');
    }
    put(c);
    return 1;
}

size_t ReplyOut::write(const uint8_t *buf, size_t n) {
    for (size_t i = 0; i < n; ++i) {
        write(buf[i]);
    }
    return n;
}

void ReplyOut::reset() {
    dropped_ = 0;
    lineLen_ = 0;
    prev_ = 0;
    stalled_ = false;
    deadlineUs_ = 0;
}

void ReplyOut::put(uint8_t c) {
    prev_ = c;
    line_[lineLen_++] = c;
    if (c == '\n' || lineLen_ == sizeof(line_)) {
        flushLine();
    }
}

void ReplyOut::flushLine() {
    if (lineLen_ == 0) {
        return;
    }
    bool sent = false;
    uint64_t waitFromUs = 0;  // 0 = this line has not waited
    while (sink_.connected()) {  // no host listening: drop at once, never wait
        if (sink_.room() >= (int)lineLen_) {
            const size_t n = sink_.write(line_, lineLen_);
            if (n != 0) {
                sent = n == lineLen_;
                break;
            }
            // 0: the sink took nothing after all; wait like for room.
        }
        const uint64_t now = time_us_64();
        if (now >= deadlineUs_) {
            stalled_ = true;
            break;
        }
        if (waitFromUs == 0) {
            waitFromUs = now;
        }
    }
    if (waitFromUs != 0) {  // the wait comes out of the link's budget
        const uint64_t waited = time_us_64() - waitFromUs;
        budgetUs_ = (stalled_ || waited >= budgetUs_) ? 0 : budgetUs_ - waited;
    }
    if (!sent) {
        dropped_ += (uint32_t)lineLen_;
    }
    lineLen_ = 0;
}

void ProtocolLink::reset() {
    out_.reset();
    len_ = 0;
    discarding_ = false;
    recentEnd_ = 0;
    recentLen_ = 0;
}

const char *Protocol::begin(PulseParams *params, const ProtocolHooks &hooks) {
    params_ = params;
    hooks_ = hooks;
    wifi_ = WifiConfig{};
    if (hooks_.wifiGet) {
        hooks_.wifiGet(&wifi_);
    }
    if (!hooks_.apply) {
        return "no hardware";
    }
    return hooks_.apply(*params_, &realized_);
}

void Protocol::disarmNow(ProtocolLink &link) {
    hooks_.setArmed(false);
    g_out = &link.out_;
    g_out->startCommand();
    g_out->print(F("OK "));
    printArmed(false);
}

void Protocol::feed(ProtocolLink &link, char c) {
    g_out = &link.out_;
    if (c == '\0') {
        return;  // a NUL would silently truncate the command (e.g. "ARM<NUL>X" -> "ARM")
    }
    if (c == '\r' || c == '\n') {
        // CR, LF and CRLF all end a line (the LF of a CRLF then ends an empty
        // line, which is ignored).
        link.buf_[link.len_] = '\0';
        if (link.len_ > 0 && !link.discarding_) {
            dispatch(link, link.buf_);
        }
        link.len_ = 0;
        link.discarding_ = false;
        link.recentLen_ = 0;
        return;
    }
    if (c == '\b' || c == 0x7F) {  // Backspace / DEL: erase the previous character
        if (link.len_ > 0) {
            --link.len_;
        }
        if (link.recentLen_ > 0) {
            --link.recentLen_;
            link.recentEnd_ = (link.recentEnd_ == 0 ? kProtocolLineMax : link.recentEnd_) - 1;
        }
        return;
    }

    // Streaming DISARM match, independent of the line buffer and of discard mode:
    // the last six characters of the edited history. When the ring is full, the new
    // character replaces the oldest.
    link.recent_[link.recentEnd_] = (char)toupper((unsigned char)c);
    link.recentEnd_ = (link.recentEnd_ + 1 == kProtocolLineMax) ? 0 : link.recentEnd_ + 1;
    if (link.recentLen_ < kProtocolLineMax) {
        ++link.recentLen_;
    }
    static constexpr char kDisarm[] = "DISARM";
    constexpr size_t kDisarmLen = sizeof(kDisarm) - 1;
    bool disarm = link.recentLen_ >= kDisarmLen;
    for (size_t i = 0; disarm && i < kDisarmLen; ++i) {
        disarm = link.recent_[(link.recentEnd_ + kProtocolLineMax - kDisarmLen + i) % kProtocolLineMax] == kDisarm[i];
    }
    if (disarm) {
        disarmNow(link);
        link.len_ = 0;
        link.discarding_ = true;  // nothing else on this line runs
        link.recentLen_ = 0;
        return;
    }

    if (link.discarding_) {
        return;
    }
    if (link.len_ + 1 >= sizeof(link.buf_)) {
        // Drop the whole line, including whatever arrives before its end, so no
        // tail of it is ever run as a command of its own.
        link.len_ = 0;
        link.discarding_ = true;
        g_out->startCommand();
        g_out->println(F("ERR line too long"));
        return;
    }
    link.buf_[link.len_++] = c;
}

// STATUS line WIFI_PENDING: 1 = a name or passphrase was given with WIFI SSID / WIFI
// PASS and is not in use (the next WIFI ON takes it; WIFI OFF and CLEAR discard it).
// Nothing is printed on a firmware without Wi-Fi.
void Protocol::printWifiPending() {
    if (!hooks_.wifiSet || !hooks_.wifiGet) {
        return;
    }
    WifiConfig inUse{};
    hooks_.wifiGet(&inUse);
    g_out->print(F("WIFI_PENDING="));
    g_out->println(strcmp(wifi_.ssid, inUse.ssid) != 0 || strcmp(wifi_.pass, inUse.pass) != 0 ? 1 : 0);
}

// WIFI: the Wi-Fi set-up. `args` is the rest of the line after "WIFI" (nullptr if
// none), not split into words: a network name or a passphrase can hold spaces.
//   WIFI                    the Wi-Fi and network STATUS lines
//   WIFI SSID <name>        network name; clears a   } kept in RAM until the
//                           collected passphrase     } next WIFI ON, OFF or
//   WIFI PASS [passphrase]  no passphrase = open     } CLEAR
//   WIFI ON                 join the network now and at every power-up
//   WIFI OFF                radio link off, now and at power-up; keeps the name and
//                           passphrase in use
//   WIFI CLEAR              as OFF, and erases the name and the passphrase
// A name or passphrase given with SSID / PASS holds only until the next ON, OFF or
// CLEAR, accepted or refused for any reason. WIFI PASS alone, then WIFI ON, changes the
// passphrase of the network in use.
// Everything but the bare query is refused from the network link: a host on the
// network must not be able to move the board to another network or lock the USB
// user out. The passphrase is never printed.
void Protocol::wifiCommand(ProtocolLink &link, char *args) {
    // Sub-command = first word; value = the rest, without the white space around it.
    char *sub = args;
    while (sub && (*sub == ' ' || *sub == '\t')) {
        ++sub;
    }
    if (!sub || !*sub) {
        if (hooks_.printNetStatus) {
            hooks_.printNetStatus(*g_out);
            printWifiPending();
        } else {
            g_out->println(F("WIFI=UNAVAILABLE (this firmware has no Wi-Fi)"));
        }
        return;
    }
    char *value = sub;
    while (*value && *value != ' ' && *value != '\t') {
        ++value;
    }
    if (*value) {
        *value++ = '\0';
        while (*value == ' ' || *value == '\t') {
            ++value;
        }
    }
    for (size_t n = strlen(value); n > 0 && (value[n - 1] == ' ' || value[n - 1] == '\t'); --n) {
        value[n - 1] = '\0';
    }

    const bool isSsid = strcasecmp(sub, "SSID") == 0, isPass = strcasecmp(sub, "PASS") == 0;
    const bool isOn = strcasecmp(sub, "ON") == 0, isOff = strcasecmp(sub, "OFF") == 0;
    const bool isClear = strcasecmp(sub, "CLEAR") == 0;
    if (!isSsid && !isPass && !isOn && !isOff && !isClear) {
        reportErr("WIFI", "unknown sub-command (SSID, PASS, ON, OFF, CLEAR; see HELP)");
        return;
    }
    if (!hooks_.wifiSet || !hooks_.wifiGet) {
        reportErr("WIFI", "not available: this firmware has no Wi-Fi");
        return;
    }
    if (!link.usb_) {
        reportErr("WIFI", "refused: the Wi-Fi set-up changes only from the Pico USB port");
        return;
    }

    if (isSsid) {
        if (const char *why = wifiCheckSsid(value)) {
            reportErr("WIFI SSID", why);
            return;
        }
        // A new name starts without a passphrase: the passphrase of one network must
        // never be tried on another one. WIFI PASS comes after WIFI SSID.
        strcpy(wifi_.ssid, value);
        wifi_.pass[0] = '\0';
        g_out->print(F("OK WIFI SSID="));
        g_out->print(wifi_.ssid);
        g_out->println(F(" (not in use yet: send WIFI PASS if it has a passphrase, then WIFI ON)"));
        return;
    }
    if (isPass) {
        if (const char *why = wifiCheckPass(value)) {
            reportErr("WIFI PASS", why);
            return;
        }
        strcpy(wifi_.pass, value);
        g_out->print(F("OK WIFI PASS="));
        g_out->print(wifi_.pass[0] ? F("SET") : F("NONE (open network)"));
        g_out->println(F(" (not in use yet: send WIFI ON)"));
        return;
    }
    // ON, OFF or CLEAR. What was collected with SSID / PASS ends here, on every path
    // below (see wifi_): ON takes it, OFF keeps the name and passphrase in use, CLEAR
    // erases them, and every refusal drops it.
    const WifiConfig collected = wifi_;
    WifiConfig inUse{};
    hooks_.wifiGet(&inUse);
    wifi_ = inUse;
    // Told to the user when a refusal dropped something that was collected.
    const bool dropped = strcmp(collected.ssid, inUse.ssid) != 0 || strcmp(collected.pass, inUse.pass) != 0;
    const __FlashStringHelper *again = dropped ? F(" (what was sent with WIFI SSID / WIFI PASS is discarded)") : F("");
    if (*value) {
        g_out->print(F("ERR WIFI "));
        g_out->print(sub);
        g_out->print(F(" takes no value"));
        g_out->println(again);
        return;
    }
    WifiConfig cfg = isOn ? collected : isOff ? inUse : WifiConfig{};
    cfg.enabled = isOn;
    if (isOn && !cfg.ssid[0]) {
        g_out->print(F("ERR WIFI ON no network name: send WIFI SSID <name> first"));
        g_out->println(again);
        return;
    }
    const char *notSaved = nullptr;
    if (const char *why = hooks_.wifiSet(cfg, &notSaved)) {
        hooks_.wifiGet(&wifi_);  // as the hook left it
        g_out->print(F("ERR WIFI "));
        g_out->print(sub);
        g_out->print(F(" refused: "));
        g_out->print(why);
        g_out->println(again);
        return;
    }
    wifi_ = cfg;
    g_out->print(F("OK WIFI="));
    g_out->print(cfg.enabled ? F("ON SSID=") : F("OFF SSID="));
    g_out->print(cfg.ssid);
    g_out->print(cfg.pass[0] ? F(" PASS=SET") : F(" PASS=NONE"));  // never the passphrase itself
    if (notSaved) {
        g_out->print(F(" SAVED=0 ("));
        g_out->print(notSaved);
        g_out->println(')');
    } else {
        g_out->println(F(" SAVED=1"));
    }
}

void Protocol::dispatch(ProtocolLink &link, char *line) {
    g_out->startCommand();
    char *cmd = strtok(line, " \t");
    if (!cmd) {
        return;
    }
    // Fallback only: feed()'s streaming match already disarms (and discards the
    // line) as soon as D-I-S-A-R-M arrives, so this should never be reached.
    if (strncasecmp(cmd, "DISARM", 6) == 0) {
        disarmNow(link);
        return;
    }

    if (strcasecmp(cmd, "WIFI") == 0 || strcasecmp(cmd, "WIFI?") == 0) {
        wifiCommand(link, strtok(nullptr, ""));  // "" = no delimiters: the whole rest of the line
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
        g_out->print(F("OK "));
        g_out->print(F("ARMED=1"));
        if (const uint32_t us = hooks_.startPendingUs ? hooks_.startPendingUs() : 0) {
            g_out->print(F(" (laser pulses start after a "));
            g_out->print(us);
            g_out->print(F(" us hold-off)"));
        }
        g_out->println();
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
            g_out->print(F("ERR "));
            g_out->print(f.name);
            g_out->print(F(" rejected: "));
            g_out->println(why);
            return;
        }
        *params_ = candidate;
        realized_ = realized;
        g_out->print(F("OK "));
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
            hooks_.printSystemStatus(*g_out);
            printWifiPending();
        }
        g_out->print(F("TX_DROPPED="));
        g_out->println(g_out->dropped());
        return;
    }

    if (strcasecmp(cmd, "ID?") == 0 || strcasecmp(cmd, "ID") == 0) {
        if (!rejectArgument("ID?", valueStr) && hooks_.printIdentity) {
            hooks_.printIdentity(*g_out);
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
