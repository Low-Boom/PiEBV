#include "protocol.h"

#include <cctype>
#include <cerrno>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <strings.h>  // strcasecmp, strncasecmp
#include "hardware/timer.h"

// SCPI parser and command tree of the PiEBV firmware. The syntax follows IEEE 488.2
// (program messages, message units, headers, parameters, responses); the tree and the
// error queue follow SCPI-1999. The command list for users is docs/COMMANDS.md.

namespace {

constexpr uint64_t kReplyBudgetUs = 250000;
constexpr uint64_t kBudgetRefillDiv = 8;  // 1 us of budget comes back per 8 us that pass
// A host that takes its replies at 20 kB/s or faster is not slow: while no further
// input waits on the link, the wait for a line that went out is charged to the budget
// only beyond that line's time at this rate. (A USB host drains the 256-byte FIFO far
// faster; a script that polls in a tight loop makes the board wait most of the time,
// and must not lose lines for that.) With input waiting, every wait is charged.
constexpr uint64_t kFairUsPerByte = 50;

// The reply path of the link being served. Set on entry to Protocol::feed(), so the
// print helpers below need no extra argument. The firmware is single-threaded.
ReplyOut *g_out = nullptr;

// ---------------------------------------------------------------- numbers out
// num/den in SCPI NR3 form with 10 significant digits, e.g. "6.666666667E-09".
// Exact integer arithmetic (no floating point), rounded half up.
void printSci(Print &out, uint64_t num, uint64_t den) {
    if (den == 0) {
        out.print(F("9.91E+37"));  // SCPI "not a number"
        return;
    }
    if (num == 0) {
        out.print(F("0.000000000E+00"));
        return;
    }
    // Scale so that 1 <= num/den < 10, counting the decimal exponent. num and den stay
    // below 2^63: num <= 2^32 * 2^16 here, and each step multiplies only the smaller one.
    int exp10 = 0;
    while (num / den >= 10) {
        if (den <= (UINT64_MAX / 10)) {
            den *= 10;
        } else {
            num /= 10;
        }
        ++exp10;
    }
    while (num < den) {
        num *= 10;
        --exp10;
    }
    char digits[11];
    uint64_t rem = num;
    for (int i = 0; i < 10; ++i) {
        digits[i] = (char)('0' + rem / den);
        rem = (rem % den) * 10;
    }
    if (rem / den >= 5) {  // round half up, carrying through the digits
        int i = 9;
        while (i >= 0 && digits[i] == '9') {
            digits[i--] = '0';
        }
        if (i >= 0) {
            ++digits[i];
        } else {
            digits[0] = '1';
            ++exp10;
        }
    }
    out.print(digits[0]);
    out.print('.');
    for (int i = 1; i < 10; ++i) {
        out.print(digits[i]);
    }
    out.print('E');
    out.print(exp10 < 0 ? '-' : '+');
    const int e = exp10 < 0 ? -exp10 : exp10;
    if (e < 10) {
        out.print('0');
    }
    out.print(e);
}

// A SCPI string response: in double quotes, an inner double quote doubled.
void printQuoted(Print &out, const char *s) {
    out.print('"');
    for (; *s; ++s) {
        if (*s == '"') {
            out.print('"');
        }
        out.print(*s);
    }
    out.print('"');
}

// ---------------------------------------------------------------- errors
const char *errorText(int code) {
    switch (code) {
        case 0: return "No error";
        case -100: return "Command error";
        case -101: return "Invalid character";
        case -102: return "Syntax error";
        case -103: return "Invalid separator";
        case -104: return "Data type error";
        case -108: return "Parameter not allowed";
        case -109: return "Missing parameter";
        case -113: return "Undefined header";
        case -120: return "Numeric data error";
        case -121: return "Invalid character in number";
        case -131: return "Invalid suffix";
        case -138: return "Suffix not allowed";
        case -141: return "Invalid character data";
        case -151: return "Invalid string data";
        case -200: return "Execution error";
        case -203: return "Command protected";
        case -221: return "Settings conflict";
        case -222: return "Data out of range";
        case -224: return "Illegal parameter value";
        case -240: return "Hardware error";
        case -241: return "Hardware missing";
        case -350: return "Queue overflow";
        case -363: return "Input buffer overrun";
        case 101: return "Set-up not stored";
        default: return code < 0 ? "Error" : "Device-specific error";
    }
}

// IEEE 488.2 standard event status register bits.
constexpr uint8_t kEsrOpc = 0x01, kEsrQye = 0x04, kEsrDde = 0x08, kEsrExe = 0x10, kEsrCme = 0x20, kEsrPon = 0x80;

uint8_t esrBitFor(int code) {
    if (code <= -100 && code > -200) return kEsrCme;
    if (code <= -200 && code > -300) return kEsrExe;
    if (code <= -400 && code > -500) return kEsrQye;
    return kEsrDde;  // -3xx and the positive (device-specific) codes
}

}  // namespace

// ---------------------------------------------------------------- one message unit
struct ScpiParam {
    const char *p;  // trimmed text of the parameter (not NUL-terminated)
    size_t n;
};

struct ScpiCmd;

struct ScpiCtx {
    Protocol *proto;
    ProtocolLink *link;
    const ScpiCmd *cmd;
    bool query;
    ScpiParam params[4];
    size_t nparams;
    bool *respStarted;  // a response of this message has been started (';' before the next one)
    bool failed;        // the unit pushed an error
};


// Access to a link's SCPI state (error queue, status registers, echo).
struct ScpiAccess {
    // "<standard text>;<detail>" into out (kErrorTextMax bytes).
    static void compose(int code, const char *detail, size_t detailLen, char *out) {
        size_t n = 0;
        for (const char *t = errorText(code); *t && n + 1 < kErrorTextMax; ++t) {
            out[n++] = *t;
        }
        if (detail && detailLen && n + 2 < kErrorTextMax) {
            out[n++] = ';';
            for (size_t i = 0; i < detailLen && detail[i] && n + 1 < kErrorTextMax; ++i) {
                // A double quote would end the response string: use a single one.
                out[n++] = detail[i] == '"' ? '\'' : detail[i];
            }
        }
        out[n] = '\0';
    }
    static void push(ProtocolLink &l, int code, const char *text) {
        l.esr_ |= esrBitFor(code);
        ProtocolLink::Error *e;
        if (l.errCount_ < kErrorQueueLen) {
            e = &l.errors_[(l.errHead_ + l.errCount_) % kErrorQueueLen];
            ++l.errCount_;
        } else {  // full: the newest entry becomes "Queue overflow" (SCPI)
            e = &l.errors_[(l.errHead_ + kErrorQueueLen - 1) % kErrorQueueLen];
            code = -350;
            text = errorText(-350);
            l.esr_ |= esrBitFor(-350);
        }
        e->code = (int16_t)code;
        snprintf(e->text, sizeof(e->text), "%s", text);
    }
    static bool pop(ProtocolLink &l, int *code, const char **text) {
        if (l.errCount_ == 0) {
            return false;
        }
        const ProtocolLink::Error &e = l.errors_[l.errHead_];
        *code = e.code;
        *text = e.text;
        l.errHead_ = (l.errHead_ + 1) % kErrorQueueLen;
        --l.errCount_;
        return true;
    }
    static size_t count(ProtocolLink &l) { return l.errCount_; }
    static void clear(ProtocolLink &l) {
        l.errCount_ = 0;
        l.esr_ = 0;
    }
    static uint8_t &esr(ProtocolLink &l) { return l.esr_; }
    static uint8_t &ese(ProtocolLink &l) { return l.ese_; }
    static uint8_t &sre(ProtocolLink &l) { return l.sre_; }
    static bool &echo(ProtocolLink &l) { return l.echo_; }
    static bool usb(ProtocolLink &l) { return l.usb_; }
    static ReplyOut &out(ProtocolLink &l) { return l.out_; }
};

namespace {

// Ends a response line that is being built, before a line of its own (echo, error).
void endResponseLine(ScpiCtx *c) {
    if (c && *c->respStarted) {
        g_out->println();
        *c->respStarted = false;
    }
}

void error(ScpiCtx &c, int code, const char *detail = nullptr, size_t detailLen = SIZE_MAX) {
    c.failed = true;
    ProtocolLink &l = *c.link;
    char text[kErrorTextMax];
    ScpiAccess::compose(code, detail, detail ? detailLen : 0, text);
    ScpiAccess::push(l, code, text);
    if (ScpiAccess::echo(l)) {  // the error itself, also when the queue is full
        endResponseLine(&c);
        g_out->print(F("ERR "));
        g_out->print(code);
        g_out->print(',');
        printQuoted(*g_out, text);
        g_out->println();
    }
}

// Starts the response of one query: ';' between the responses of one message.
void beginResponse(ScpiCtx &c) {
    if (*c.respStarted) {
        g_out->print(';');
    }
    *c.respStarted = true;
}

// Starts an echo line ("OK ...") if echo is on; false = no echo, print nothing.
bool beginEcho(ScpiCtx &c) {
    if (!ScpiAccess::echo(*c.link)) {
        return false;
    }
    endResponseLine(&c);
    g_out->print(F("OK "));
    return true;
}

// ---------------------------------------------------------------- parameters
bool paramIs(const ScpiParam &p, const char *shortForm, const char *longForm) {
    return (p.n == strlen(shortForm) && strncasecmp(p.p, shortForm, p.n) == 0) ||
           (longForm && p.n == strlen(longForm) && strncasecmp(p.p, longForm, p.n) == 0);
}

// Checks the number of parameters; pushes -109 / -108 and returns false if wrong.
bool wantParams(ScpiCtx &c, size_t n) {
    if (c.nparams < n) {
        error(c, -109);
        return false;
    }
    if (c.nparams > n) {
        error(c, -108);
        return false;
    }
    return true;
}

enum class Unit : uint8_t { None, Second, Hertz };

// SCPI <DECIMAL NUMERIC PROGRAM DATA> with an optional suffix of `unit`. On success
// *value is in the base unit (seconds, hertz). Pushes the error and returns false.
bool parseNumber(ScpiCtx &c, const ScpiParam &p, Unit unit, double *value) {
    size_t i = 0;
    char num[48];
    size_t n = 0;
    auto take = [&](char ch) {
        if (n + 1 < sizeof(num)) num[n++] = ch;
    };
    if (i < p.n && (p.p[i] == '+' || p.p[i] == '-')) take(p.p[i++]);
    size_t digits = 0;
    while (i < p.n && isdigit((unsigned char)p.p[i])) take(p.p[i++]), ++digits;
    if (i < p.n && p.p[i] == '.') {
        take(p.p[i++]);
        while (i < p.n && isdigit((unsigned char)p.p[i])) take(p.p[i++]), ++digits;
    }
    if (digits == 0) {
        error(c, -104, "a number is needed here");
        return false;
    }
    // Exponent: E, optional spaces, sign, digits. An E with no digits after it is
    // the start of a suffix ("1 EX" does not exist here, so it is an error then).
    if (i < p.n && (p.p[i] == 'E' || p.p[i] == 'e')) {
        size_t j = i + 1;
        while (j < p.n && p.p[j] == ' ') ++j;
        size_t k = j;
        if (k < p.n && (p.p[k] == '+' || p.p[k] == '-')) ++k;
        if (k < p.n && isdigit((unsigned char)p.p[k])) {
            take('E');
            for (size_t m = j; m < k; ++m) take(p.p[m]);
            while (k < p.n && isdigit((unsigned char)p.p[k])) take(p.p[k++]);
            i = k;
        }
    }
    num[n] = '\0';
    while (i < p.n && (p.p[i] == ' ' || p.p[i] == '\t')) ++i;
    double mult = 1.0;
    if (i < p.n) {
        const char *suf = p.p + i;
        const size_t sn = p.n - i;
        struct Suffix {
            const char *name;
            Unit unit;
            double mult;
        };
        static const Suffix kSuffixes[] = {
            {"S", Unit::Second, 1.0},      {"MS", Unit::Second, 1e-3},  {"US", Unit::Second, 1e-6},
            {"NS", Unit::Second, 1e-9},    {"PS", Unit::Second, 1e-12}, {"HZ", Unit::Hertz, 1.0},
            {"KHZ", Unit::Hertz, 1e3},     {"MHZ", Unit::Hertz, 1e6},   {"MAHZ", Unit::Hertz, 1e6},
            {"GHZ", Unit::Hertz, 1e9},
        };
        if (unit == Unit::None) {
            error(c, -138);
            return false;
        }
        bool found = false;
        for (const Suffix &s : kSuffixes) {
            if (s.unit == unit && sn == strlen(s.name) && strncasecmp(suf, s.name, sn) == 0) {
                mult = s.mult;
                found = true;
                break;
            }
        }
        if (!found) {
            for (size_t m = 0; m < sn; ++m) {
                if (!isalpha((unsigned char)suf[m])) {
                    error(c, -121);
                    return false;
                }
            }
            error(c, -131, unit == Unit::Second ? "use S, MS, US, NS or PS" : "use HZ, KHZ, MHZ or GHZ");
            return false;
        }
    }
    char *end = nullptr;
    errno = 0;
    const double v = strtod(num, &end);
    if (end == num || *end != '\0' || errno == ERANGE || !std::isfinite(v)) {
        error(c, -222, "number too large");
        return false;
    }
    *value = v * mult;
    return true;
}

// A time or frequency for a PulseParams field: whole ns or Hz, 0 .. 2^32 - 1.
// DEFault gives `def`. Pushes the error and returns false.
bool parseField(ScpiCtx &c, const ScpiParam &p, Unit unit, uint32_t def, uint32_t *out) {
    if (paramIs(p, "DEF", "DEFAULT")) {
        *out = def;
        return true;
    }
    if (paramIs(p, "MIN", "MINIMUM") || paramIs(p, "MAX", "MAXIMUM")) {
        error(c, -224, "MINimum and MAXimum are not supported: give a value");
        return false;
    }
    if (p.n && isalpha((unsigned char)p.p[0])) {
        error(c, -104, "a number is needed here");
        return false;
    }
    double v;
    if (!parseNumber(c, p, unit, &v)) {
        return false;
    }
    const double scaled = unit == Unit::Second ? v * 1e9 : v;  // ns or Hz
    if (scaled < -0.5) {
        error(c, -222, "the value cannot be negative");
        return false;
    }
    if (scaled >= 4294967295.5) {
        error(c, -222, unit == Unit::Second ? "longer than 4.29 s" : "above 4.29 GHz");
        return false;
    }
    *out = (uint32_t)llround(scaled);
    return true;
}

// <Boolean PROGRAM DATA>: ON, OFF, or a number (rounded; not 0 = ON).
bool parseBool(ScpiCtx &c, const ScpiParam &p, bool *out) {
    if (paramIs(p, "ON", nullptr)) {
        *out = true;
        return true;
    }
    if (paramIs(p, "OFF", nullptr)) {
        *out = false;
        return true;
    }
    if (p.n && isalpha((unsigned char)p.p[0])) {
        error(c, -224, "use ON, OFF, 1 or 0");
        return false;
    }
    double v;
    if (!parseNumber(c, p, Unit::None, &v)) {
        return false;
    }
    *out = llround(v) != 0;
    return true;
}

// A whole number 0 .. 255 (*ESE, *SRE).
bool parseByte(ScpiCtx &c, const ScpiParam &p, uint8_t *out) {
    double v;
    if (!parseNumber(c, p, Unit::None, &v)) {
        return false;
    }
    const long long r = llround(v);
    if (r < 0 || r > 255) {
        error(c, -222, "0 to 255");
        return false;
    }
    *out = (uint8_t)r;
    return true;
}

// <STRING PROGRAM DATA>: '...' or "...", the quote doubled inside. Into out (NUL-
// terminated, at most max bytes of text). Pushes the error and returns false.
bool parseString(ScpiCtx &c, const ScpiParam &p, char *out, size_t max, const char *tooLong) {
    if (p.n < 2 || (p.p[0] != '"' && p.p[0] != '\'') || p.p[p.n - 1] != p.p[0]) {
        error(c, -104, "a quoted string is needed here");
        return false;
    }
    const char q = p.p[0];
    size_t n = 0;
    for (size_t i = 1; i + 1 < p.n; ++i) {
        if (p.p[i] == q) {
            if (i + 2 < p.n && p.p[i + 1] == q) {
                ++i;  // a doubled quote is one quote
            } else {
                error(c, -151, "a quote inside the string must be doubled");
                return false;
            }
        }
        if (n >= max) {
            error(c, -222, tooLong);
            return false;
        }
        out[n++] = p.p[i];
    }
    out[n] = '\0';
    return true;
}

}  // namespace

// ---------------------------------------------------------------- command tree
namespace {

enum class FieldKind : uint8_t { Time, Freq, Bool, PixGate };

struct FieldDesc {
    const char *header;  // short form, for the echo
    uint32_t PulseParams::*field;
    FieldKind kind;
    uint32_t RealizedTiming::*realized;  // cycle count (the period, for FREQ)
};

const FieldDesc kFieldDescs[] = {
    {":FREQ", &PulseParams::freqHz, FieldKind::Freq, &RealizedTiming::periodCycles},
    {":PULS:WIDT", &PulseParams::widthNs, FieldKind::Time, &RealizedTiming::widthCycles},
    {":PULS:DOUB:DEL", &PulseParams::delayNs, FieldKind::Time, &RealizedTiming::delayCycles},
    {":MARK:WIDT", &PulseParams::markerWidthNs, FieldKind::Time, &RealizedTiming::markerWidthCycles},
    {":OUTP:COMB", &PulseParams::combine, FieldKind::Bool, &RealizedTiming::combine},
    {":PIX:GATE", &PulseParams::pixGate, FieldKind::PixGate, &RealizedTiming::pixGate},
    {":PIX:LEAD", &PulseParams::pixLeadNs, FieldKind::Time, &RealizedTiming::pixLeadCycles},
    {":PIX:LAG", &PulseParams::pixLagNs, FieldKind::Time, &RealizedTiming::pixLagCycles},
};

const char *const kPixGateNames[] = {"OFF", "ARM", "ALW"};  // short forms of OFF, ARMed, ALWays

}  // namespace

constexpr uint8_t kQ = 1, kS = 2;  // the command has a query form / a setting form

struct ScpiCmd {
    const char *pattern;  // SCPI notation: [optional nodes], long forms with the short form in capitals
    void (Protocol::*fn)(ScpiCtx &);
    uint8_t flags;
    uint8_t arg;
};

namespace {

const ScpiCmd kCommands[] = {
    // IEEE 488.2 common commands
    {"*IDN", &Protocol::cmdIdn, kQ, 0},
    {"*RST", &Protocol::cmdRst, kS, 0},
    {"*CLS", &Protocol::cmdCls, kS, 0},
    {"*ESE", &Protocol::cmdEse, kQ | kS, 0},
    {"*ESR", &Protocol::cmdEsr, kQ, 0},
    {"*SRE", &Protocol::cmdSre, kQ | kS, 0},
    {"*STB", &Protocol::cmdStb, kQ, 0},
    {"*OPC", &Protocol::cmdOpc, kQ | kS, 0},
    {"*WAI", &Protocol::cmdWai, kS, 0},
    {"*TST", &Protocol::cmdTst, kQ, 0},
    // pulse timing
    {"[:SOURce]:FREQuency[:CW]", &Protocol::cmdField, kQ | kS, 0},
    {"[:SOURce]:PULSe:PERiod", &Protocol::cmdPeriod, kQ, 0},
    {"[:SOURce]:PULSe:WIDTh", &Protocol::cmdField, kQ | kS, 1},
    {"[:SOURce]:PULSe:DOUBle[:STATe]", &Protocol::cmdDouble, kQ, 0},
    {"[:SOURce]:PULSe:DOUBle:DELay", &Protocol::cmdField, kQ | kS, 2},
    {"[:SOURce]:MARKer:WIDTh", &Protocol::cmdField, kQ | kS, 3},
    {"[:SOURce]:SYNC:FREQuency", &Protocol::cmdSync, kQ, 0},
    // laser outputs
    {":OUTPut[:STATe]", &Protocol::cmdOutput, kQ | kS, 0},
    {":OUTPut:COMBine", &Protocol::cmdField, kQ | kS, 4},
    {":OUTPut:PENDing", &Protocol::cmdPending, kQ, 0},
    {":ABORt", &Protocol::cmdAbort, kS, 0},
    // camera pixel-reset gate
    {":PIXel:GATE", &Protocol::cmdField, kQ | kS, 5},
    {":PIXel:LEAD", &Protocol::cmdField, kQ | kS, 6},
    {":PIXel:LAG", &Protocol::cmdField, kQ | kS, 7},
    {":PIXel:WINDow", &Protocol::cmdPixWindow, kQ, 0},
    // system
    {":SYSTem:ERRor[:NEXT]", &Protocol::cmdSysErr, kQ, 0},
    {":SYSTem:ERRor:COUNt", &Protocol::cmdSysErrCount, kQ, 0},
    {":SYSTem:VERSion", &Protocol::cmdSysVersion, kQ, 0},
    {":SYSTem:ECHO", &Protocol::cmdSysEcho, kQ | kS, 0},
    {":SYSTem:HELP:HEADers", &Protocol::cmdSysHelp, kQ, 0},
    // network link (Wi-Fi)
    {":SYSTem:COMMunicate:WLAN[:STATe]", &Protocol::cmdWlan, kQ | kS, 0},
    {":SYSTem:COMMunicate:WLAN:SSID", &Protocol::cmdWlan, kQ | kS, 1},
    {":SYSTem:COMMunicate:WLAN:PASSword", &Protocol::cmdWlan, kS, 2},
    {":SYSTem:COMMunicate:WLAN:SECurity", &Protocol::cmdWlan, kQ, 3},
    {":SYSTem:COMMunicate:WLAN:CLEar", &Protocol::cmdWlan, kS, 4},
    {":SYSTem:COMMunicate:WLAN:LINK", &Protocol::cmdWlan, kQ, 5},
    {":SYSTem:COMMunicate:WLAN:PENDing", &Protocol::cmdWlan, kQ, 6},
    {":SYSTem:COMMunicate:WLAN:SAVed", &Protocol::cmdWlan, kQ, 7},
    {":SYSTem:COMMunicate:WLAN:MAC", &Protocol::cmdWlan, kQ, 8},
    {":SYSTem:COMMunicate:WLAN:IPADdress", &Protocol::cmdWlan, kQ, 9},
    {":SYSTem:COMMunicate:WLAN:RSSI", &Protocol::cmdWlan, kQ, 10},
    {":SYSTem:COMMunicate:WLAN:PORT", &Protocol::cmdWlan, kQ, 11},
    {":SYSTem:COMMunicate:WLAN:CLIent", &Protocol::cmdWlan, kQ, 12},
    // diagnostics
    {":DIAGnostic:HARDware", &Protocol::cmdDiag, kQ, 0},
    {":DIAGnostic:CLOCk[:FREQuency]", &Protocol::cmdDiag, kQ, 1},
    {":DIAGnostic:CLOCk:MODE", &Protocol::cmdDiag, kQ, 2},
    {":DIAGnostic:VREG", &Protocol::cmdDiag, kQ, 3},
    {":DIAGnostic:RESet:CAUSe", &Protocol::cmdDiag, kQ, 4},
    {":DIAGnostic:RESet:RAW", &Protocol::cmdDiag, kQ, 5},
    {":DIAGnostic:WATChdog:RESets", &Protocol::cmdDiag, kQ, 6},
    {":DIAGnostic:WATChdog:PERiod", &Protocol::cmdDiag, kQ, 7},
    {":DIAGnostic:TXDRopped", &Protocol::cmdDiag, kQ, 8},
    {":DIAGnostic:UPTime", &Protocol::cmdDiag, kQ, 9},
};

struct Tok {
    const char *p;
    size_t n;
};

struct PatTok {
    const char *p;
    size_t n;
    bool optional;
};

// "[:SOURce]:FREQuency[:CW]" -> SOURce (optional), FREQuency, CW (optional).
size_t splitPattern(const char *pat, PatTok *out, size_t max) {
    size_t n = 0;
    bool optional = false;
    for (const char *s = pat; *s && n < max;) {
        if (*s == '[') {
            optional = true;
            ++s;
        } else if (*s == ']') {
            ++s;
        } else if (*s == ':') {
            ++s;
        } else {
            const char *b = s;
            while (*s && *s != ':' && *s != '[' && *s != ']') ++s;
            out[n++] = PatTok{b, (size_t)(s - b), optional};
            optional = false;
        }
    }
    return n;
}

// A mnemonic matches its short form (the capitals) or its long form, in any case.
bool mnemonicMatches(const Tok &u, const PatTok &m) {
    size_t sn = 0;
    while (sn < m.n && !islower((unsigned char)m.p[sn])) ++sn;
    return (u.n == sn && strncasecmp(u.p, m.p, sn) == 0) || (u.n == m.n && strncasecmp(u.p, m.p, m.n) == 0);
}

bool matchTokens(const PatTok *pt, size_t np, const Tok *ut, size_t nu) {
    if (np == 0) {
        return nu == 0;
    }
    if (pt[0].optional && matchTokens(pt + 1, np - 1, ut, nu)) {
        return true;
    }
    return nu > 0 && mnemonicMatches(ut[0], pt[0]) && matchTokens(pt + 1, np - 1, ut + 1, nu - 1);
}

// True if ut matches the start of the pattern and at least one more node follows.
bool matchPrefix(const PatTok *pt, size_t np, const Tok *ut, size_t nu) {
    if (nu == 0) {
        return np > 0;
    }
    if (np == 0) {
        return false;
    }
    if (pt[0].optional && matchPrefix(pt + 1, np - 1, ut, nu)) {
        return true;
    }
    return mnemonicMatches(ut[0], pt[0]) && matchPrefix(pt + 1, np - 1, ut + 1, nu - 1);
}

// True if the header ut names a node that has nodes below it, e.g. OUTPut (OUTPut:COMBine)
// or SYSTem:COMMunicate:WLAN. After such a header (used with its default node, like
// OUTPut ON for OUTPut:STATe ON), the current path ends at the header itself, so that
// "OUTP ON;COMB OFF" means OUTPut:COMBine OFF.
bool isInnerNode(const Tok *ut, size_t nu) {
    for (const ScpiCmd &cmd : kCommands) {
        if (cmd.pattern[0] == '*') continue;
        PatTok pt[8];
        const size_t np = splitPattern(cmd.pattern, pt, 8);
        if (matchPrefix(pt, np, ut, nu)) return true;
    }
    return false;
}

const ScpiCmd *findCommand(const Tok *ut, size_t nu, bool common) {
    for (const ScpiCmd &cmd : kCommands) {
        if ((cmd.pattern[0] == '*') != common) {
            continue;
        }
        if (common) {
            if (strlen(cmd.pattern) == ut[0].n && strncasecmp(cmd.pattern, ut[0].p, ut[0].n) == 0) {
                return &cmd;
            }
            continue;
        }
        PatTok pt[8];
        const size_t np = splitPattern(cmd.pattern, pt, 8);
        if (matchTokens(pt, np, ut, nu)) {
            return &cmd;
        }
    }
    return nullptr;
}

// Counts bytes (for the length of a definite-length block).
class CountPrint : public Print {
public:
    size_t write(uint8_t) override {
        ++n;
        return 1;
    }
    using Print::write;
    size_t n = 0;
};

void printHelpLines(Print &out) {
    for (const ScpiCmd &cmd : kCommands) {
        out.print(cmd.pattern);
        if (!(cmd.flags & kS)) {
            out.print(F("/qonly/"));
        } else if (!(cmd.flags & kQ)) {
            out.print(F("/nquery/"));
        }
        out.print(F("\r\n"));  // counted as sent: ReplyOut adds no CR before an LF that has one
    }
}

void printFieldValue(Print &out, const FieldDesc &f, uint32_t value, const RealizedTiming &r) {
    const uint32_t cycles = r.*(f.realized);
    switch (f.kind) {
        case FieldKind::Freq:
            if (r.clkHz && cycles) printSci(out, r.clkHz, cycles);
            else printSci(out, value, 1);
            break;
        case FieldKind::Time:
            if (r.clkHz) printSci(out, cycles, r.clkHz);
            else printSci(out, value, 1000000000ULL);
            break;
        case FieldKind::Bool:
            out.print(value ? 1 : 0);
            break;
        case FieldKind::PixGate:
            out.print(kPixGateNames[value < 3 ? value : 0]);
            break;
    }
}

// The human part of an echo line: " (100.000 ns, 15 cyc)" and the like.
void printFieldHint(Print &out, const FieldDesc &f, uint32_t value, const RealizedTiming &r) {
    char num[32];
    const uint32_t cycles = r.*(f.realized);
    switch (f.kind) {
        case FieldKind::Freq:
            if (!r.clkHz) return;
            pulseFormatHz(cycles, r.clkHz, num, sizeof(num));
            out.print(F(" ("));
            out.print(num);
            out.print(F(" Hz, period "));
            out.print(cycles);
            out.print(F(" cyc)"));
            break;
        case FieldKind::Time:
            if (!r.clkHz) return;
            pulseFormatNs(cycles, r.clkHz, num, sizeof(num));
            out.print(F(" ("));
            out.print(num);
            out.print(F(" ns, "));
            out.print(cycles);
            out.print(F(" cyc)"));
            break;
        case FieldKind::Bool:
            out.print(value ? F(" (CH1 + CH2 on LASER 1 and LASER 2)") : F(" (CH1 on LASER 1, CH2 on LASER 2)"));
            break;
        case FieldKind::PixGate:
            out.print(value == 0   ? F(" (off: no pixel reset)")
                      : value == 1 ? F(" (pixels reset between pulse pairs while armed)")
                                   : F(" (pixels reset between pulse pairs, also while disarmed)"));
            break;
    }
}

}  // namespace

// ---------------------------------------------------------------- handlers
void Protocol::cmdField(ScpiCtx &c) {
    const FieldDesc &f = kFieldDescs[c.cmd->arg];
    if (c.query) {
        if (!wantParams(c, 0)) return;
        beginResponse(c);
        printFieldValue(*g_out, f, params_->*(f.field), realized_);
        return;
    }
    if (!wantParams(c, 1)) return;
    const ScpiParam &p = c.params[0];
    const PulseParams defaults;
    uint32_t v = 0;
    switch (f.kind) {
        case FieldKind::Time:
            if (!parseField(c, p, Unit::Second, defaults.*(f.field), &v)) return;
            break;
        case FieldKind::Freq:
            if (!parseField(c, p, Unit::Hertz, defaults.*(f.field), &v)) return;
            break;
        case FieldKind::Bool: {
            bool b;
            if (paramIs(p, "DEF", "DEFAULT")) {
                b = defaults.*(f.field) != 0;
            } else if (!parseBool(c, p, &b)) {
                return;
            }
            v = b ? 1 : 0;
            break;
        }
        case FieldKind::PixGate:
            if (paramIs(p, "OFF", nullptr)) v = 0;
            else if (paramIs(p, "ARM", "ARMED")) v = 1;
            else if (paramIs(p, "ALW", "ALWAYS")) v = 2;
            else if (paramIs(p, "DEF", "DEFAULT")) v = defaults.*(f.field);
            else {
                error(c, -224, "use OFF, ARMed or ALWays");
                return;
            }
            break;
    }
    PulseParams candidate = *params_;
    candidate.*(f.field) = v;
    RealizedTiming realized;
    if (const char *why = hooks_.apply(candidate, &realized)) {
        error(c, -221, why);
        return;
    }
    *params_ = candidate;
    realized_ = realized;
    if (beginEcho(c)) {
        g_out->print(f.header);
        g_out->print(' ');
        printFieldValue(*g_out, f, v, realized_);
        printFieldHint(*g_out, f, v, realized_);
        g_out->println();
    }
}

void Protocol::cmdPeriod(ScpiCtx &c) {
    if (!wantParams(c, 0)) return;
    beginResponse(c);
    printSci(*g_out, realized_.periodCycles, realized_.clkHz);
}

void Protocol::cmdDouble(ScpiCtx &c) {  // both pulses of every pair: always on
    if (!wantParams(c, 0)) return;
    beginResponse(c);
    g_out->print('1');
}

void Protocol::cmdSync(ScpiCtx &c) {  // clk_sys / (divider in 16.16 fixed point)
    if (!wantParams(c, 0)) return;
    beginResponse(c);
    printSci(*g_out, (uint64_t)realized_.clkHz << 16, realized_.syncDiv);
}

void Protocol::cmdOutput(ScpiCtx &c) {
    if (c.query) {
        if (!wantParams(c, 0)) return;
        beginResponse(c);
        g_out->print(hooks_.isArmed() ? '1' : '0');
        return;
    }
    if (!wantParams(c, 1)) return;
    bool on;
    if (!parseBool(c, c.params[0], &on)) return;
    if (!on) {
        cmdAbort(c);
        return;
    }
    if (const char *why = hooks_.setArmed(true)) {
        error(c, -240, why);
        return;
    }
    if (beginEcho(c)) {
        g_out->print(F(":OUTP 1"));
        if (const uint32_t us = hooks_.startPendingUs ? hooks_.startPendingUs() : 0) {
            g_out->print(F(" (laser pulses start after a "));
            g_out->print(us);
            g_out->print(F(" us hold-off)"));
        }
        g_out->println();
    }
}

void Protocol::cmdAbort(ScpiCtx &c) {
    if (c.cmd->fn == &Protocol::cmdAbort && !wantParams(c, 0)) return;
    hooks_.setArmed(false);
    if (beginEcho(c)) {
        g_out->println(F(":OUTP 0"));
    }
}

void Protocol::cmdPending(ScpiCtx &c) {
    if (!wantParams(c, 0)) return;
    beginResponse(c);
    printSci(*g_out, hooks_.startPendingUs ? hooks_.startPendingUs() : 0, 1000000);
}

void Protocol::cmdPixWindow(ScpiCtx &c) {  // reset time per period, its start after CH1, pixels free
    if (!wantParams(c, 0)) return;
    beginResponse(c);
    const RealizedTiming &r = realized_;
    const uint32_t reset = r.pixGate ? r.pixResetCycles : 0;
    printSci(*g_out, reset, r.clkHz);
    g_out->print(',');
    printSci(*g_out, r.pixGate ? r.pixResetStartCycles : 0, r.clkHz);
    g_out->print(',');
    printSci(*g_out, r.periodCycles - reset, r.clkHz);
}

void Protocol::cmdIdn(ScpiCtx &c) {
    if (!wantParams(c, 0)) return;
    Identity id{"unknown", "0", "unknown"};
    if (hooks_.identity) hooks_.identity(&id);
    beginResponse(c);
    g_out->print(F("PiEBV,"));
    g_out->print(id.model);
    g_out->print(',');
    g_out->print(id.serial);
    g_out->print(',');
    g_out->print(id.firmware);
}

void Protocol::cmdRst(ScpiCtx &c) {  // disarmed, default settings; the Wi-Fi set-up and the link state stay
    if (!wantParams(c, 0)) return;
    hooks_.setArmed(false);
    PulseParams defaults;
    RealizedTiming realized;
    if (const char *why = hooks_.apply(defaults, &realized)) {
        error(c, -200, why);
        return;
    }
    *params_ = defaults;
    realized_ = realized;
    if (beginEcho(c)) g_out->println(F("*RST"));
}

void Protocol::cmdCls(ScpiCtx &c) {
    if (!wantParams(c, 0)) return;
    ScpiAccess::clear(*c.link);
    if (beginEcho(c)) g_out->println(F("*CLS"));
}

void Protocol::cmdEse(ScpiCtx &c) {
    uint8_t &reg = c.cmd->fn == &Protocol::cmdSre ? ScpiAccess::sre(*c.link) : ScpiAccess::ese(*c.link);
    const char *name = c.cmd->fn == &Protocol::cmdSre ? "*SRE " : "*ESE ";
    if (c.query) {
        if (!wantParams(c, 0)) return;
        beginResponse(c);
        g_out->print(reg);
        return;
    }
    if (!wantParams(c, 1)) return;
    uint8_t v;
    if (!parseByte(c, c.params[0], &v)) return;
    reg = c.cmd->fn == &Protocol::cmdSre ? (uint8_t)(v & ~0x40) : v;  // SRE bit 6 is not settable
    if (beginEcho(c)) {
        g_out->print(name);
        g_out->println(reg);
    }
}

void Protocol::cmdSre(ScpiCtx &c) {
    cmdEse(c);
}

void Protocol::cmdEsr(ScpiCtx &c) {  // read and clear
    if (!wantParams(c, 0)) return;
    uint8_t &esr = ScpiAccess::esr(*c.link);
    beginResponse(c);
    g_out->print(esr);
    esr = 0;
}

void Protocol::cmdStb(ScpiCtx &c) {
    if (!wantParams(c, 0)) return;
    ProtocolLink &l = *c.link;
    uint8_t stb = 0;
    if (ScpiAccess::count(l)) stb |= 0x04;                          // EAV: the error queue is not empty
    if (ScpiAccess::esr(l) & ScpiAccess::ese(l)) stb |= 0x20;       // ESB
    if (stb & ScpiAccess::sre(l)) stb |= 0x40;                      // MSS
    beginResponse(c);
    g_out->print(stb);
}

void Protocol::cmdOpc(ScpiCtx &c) {  // every command is complete when it returns
    if (!wantParams(c, 0)) return;
    if (c.query) {
        beginResponse(c);
        g_out->print('1');
        return;
    }
    ScpiAccess::esr(*c.link) |= kEsrOpc;
    if (beginEcho(c)) g_out->println(F("*OPC"));
}

void Protocol::cmdWai(ScpiCtx &c) {
    if (!wantParams(c, 0)) return;
    if (beginEcho(c)) g_out->println(F("*WAI"));
}

void Protocol::cmdTst(ScpiCtx &c) {  // no self-test: 0 = passed
    if (!wantParams(c, 0)) return;
    beginResponse(c);
    g_out->print('0');
}

void Protocol::cmdSysErr(ScpiCtx &c) {
    if (!wantParams(c, 0)) return;
    int code = 0;
    const char *text = "No error";
    ScpiAccess::pop(*c.link, &code, &text);
    beginResponse(c);
    g_out->print(code);
    g_out->print(',');
    printQuoted(*g_out, text);
}

void Protocol::cmdSysErrCount(ScpiCtx &c) {
    if (!wantParams(c, 0)) return;
    beginResponse(c);
    g_out->print((unsigned)ScpiAccess::count(*c.link));
}

void Protocol::cmdSysVersion(ScpiCtx &c) {
    if (!wantParams(c, 0)) return;
    beginResponse(c);
    g_out->print(F("1999.0"));
}

void Protocol::cmdSysEcho(ScpiCtx &c) {
    bool &echo = ScpiAccess::echo(*c.link);
    if (c.query) {
        if (!wantParams(c, 0)) return;
        beginResponse(c);
        g_out->print(echo ? '1' : '0');
        return;
    }
    if (!wantParams(c, 1)) return;
    bool on;
    if (!parseBool(c, c.params[0], &on)) return;
    echo = on;
    if (beginEcho(c)) g_out->println(F(":SYST:ECHO 1"));
}

void Protocol::cmdSysHelp(ScpiCtx &c) {  // <DEFINITE LENGTH ARBITRARY BLOCK RESPONSE DATA>
    if (!wantParams(c, 0)) return;
    CountPrint count;
    printHelpLines(count);
    char len[12];
    snprintf(len, sizeof(len), "%u", (unsigned)count.n);
    beginResponse(c);
    g_out->print('#');
    g_out->print((unsigned)strlen(len));
    g_out->print(len);
    printHelpLines(*g_out);
}

void Protocol::cmdDiag(ScpiCtx &c) {
    if (!wantParams(c, 0)) return;
    SystemInfo s{};
    s.resetCause = "UNKNOWN";
    if (hooks_.systemInfo) hooks_.systemInfo(&s);
    beginResponse(c);
    switch (c.cmd->arg) {
        case 0: printQuoted(*g_out, s.hw[0] ? s.hw : "OK"); break;
        case 1: g_out->print(s.clkHz); break;
        case 2: printQuoted(*g_out, s.clkMode); break;
        case 3: printSci(*g_out, s.vregMv, 1000); break;
        case 4: g_out->print(s.resetCause); break;
        case 5:
            g_out->print(s.wdReason);
            g_out->print(',');
            g_out->print(s.chipReset);
            break;
        case 6: g_out->print(s.wdtResets); break;
        case 7: printSci(*g_out, s.wdtMs, 1000); break;
        case 8: g_out->print(c.link->dropped()); break;
        case 9: printSci(*g_out, s.uptimeUs / 1000, 1000); break;  // seconds, to the millisecond
    }
}

// The network link. Settings only from the USB link, and only in a firmware with a radio.
void Protocol::cmdWlan(ScpiCtx &c) {
    const uint8_t arg = c.cmd->arg;
    if (c.query) {
        if (!wantParams(c, 0)) return;
        NetInfo n;
        if (hooks_.netInfo) hooks_.netInfo(&n);
        WifiConfig inUse{};
        if (hooks_.wifiGet) hooks_.wifiGet(&inUse);
        beginResponse(c);
        switch (arg) {
            case 0: g_out->print(inUse.enabled ? '1' : '0'); break;
            case 1: printQuoted(*g_out, inUse.ssid); break;
            case 3: g_out->print(inUse.pass[0] ? F("WPA2") : F("NONE")); break;
            case 5:
                g_out->print(n.state);
                g_out->print(',');
                printQuoted(*g_out, n.note);
                break;
            case 6:
                g_out->print(strcmp(wifi_.ssid, inUse.ssid) != 0 || strcmp(wifi_.pass, inUse.pass) != 0 ? '1' : '0');
                break;
            case 7: g_out->print(n.saved ? '1' : '0'); break;
            case 8: {
                char mac[18] = "";
                if (n.macKnown) {
                    snprintf(mac, sizeof(mac), "%02X:%02X:%02X:%02X:%02X:%02X", n.mac[0], n.mac[1], n.mac[2], n.mac[3],
                             n.mac[4], n.mac[5]);
                }
                printQuoted(*g_out, mac);
                break;
            }
            case 9: printQuoted(*g_out, n.ip); break;
            case 10:
                if (n.rssiKnown) g_out->print(n.rssi);
                else g_out->print(F("9.91E+37"));
                break;
            case 11: g_out->print(n.port); break;
            case 12: printQuoted(*g_out, n.client); break;
        }
        return;
    }
    if (!hooks_.wifiSet || !hooks_.wifiGet) {
        error(c, -241, "this firmware image has no Wi-Fi");
        return;
    }
    if (!ScpiAccess::usb(*c.link)) {
        error(c, -203, "the Wi-Fi set-up changes only from the Pico USB port");
        return;
    }
    switch (arg) {
        case 0: {
            if (!wantParams(c, 1)) return;
            bool on;
            if (!parseBool(c, c.params[0], &on)) return;
            wifiChange(c, on ? 0 : 1);
            return;
        }
        case 4:
            if (!wantParams(c, 0)) return;
            wifiChange(c, 2);
            return;
        case 1: {
            if (!wantParams(c, 1)) return;
            char ssid[kWifiSsidMax + 1];
            if (!parseString(c, c.params[0], ssid, kWifiSsidMax, "the network name is longer than 32 bytes")) return;
            if (const char *why = wifiCheckSsid(ssid)) {
                error(c, -222, why);
                return;
            }
            // A new name starts without a passphrase: the passphrase of one network
            // must never be tried on another one. PASSword comes after SSID.
            strcpy(wifi_.ssid, ssid);
            wifi_.pass[0] = '\0';
            if (beginEcho(c)) {
                g_out->print(F(":SYST:COMM:WLAN:SSID "));
                printQuoted(*g_out, wifi_.ssid);
                g_out->println(F(" (not in use yet: send :SYST:COMM:WLAN:PASS if it has a passphrase, then :SYST:COMM:WLAN ON)"));
            }
            return;
        }
        case 2: {
            if (!wantParams(c, 1)) return;
            char pass[kWifiPassMax + 1];
            if (!parseString(c, c.params[0], pass, kWifiPassMax, "the passphrase must have 8 to 63 characters")) return;
            if (const char *why = wifiCheckPass(pass)) {
                error(c, -222, why);
                return;
            }
            strcpy(wifi_.pass, pass);
            if (beginEcho(c)) {  // never the passphrase itself
                g_out->print(F(":SYST:COMM:WLAN:PASS "));
                g_out->print(wifi_.pass[0] ? F("(set") : F("(none: open network"));
                g_out->println(F("; not in use yet: send :SYST:COMM:WLAN ON)"));
            }
            return;
        }
    }
}

// WLAN ON (action 0), OFF (1) or CLEar (2). What was collected with SSID / PASSword
// ends here, on every path (see wifi_): ON takes it, OFF keeps the name and passphrase
// in use, CLEar erases them, and every refusal drops it.
void Protocol::wifiChange(ScpiCtx &c, int action) {
    const WifiConfig collected = wifi_;
    WifiConfig inUse{};
    hooks_.wifiGet(&inUse);
    wifi_ = inUse;
    const bool dropped = strcmp(collected.ssid, inUse.ssid) != 0 || strcmp(collected.pass, inUse.pass) != 0;
    char detail[kErrorTextMax];
    auto refuse = [&](int code, const char *why) {
        snprintf(detail, sizeof(detail), "%s%s", why, dropped ? " (what was sent with WLAN:SSID / WLAN:PASS is discarded)" : "");
        error(c, code, detail);
    };
    WifiConfig cfg = action == 0 ? collected : action == 1 ? inUse : WifiConfig{};
    cfg.enabled = action == 0;
    if (action == 0 && !cfg.ssid[0]) {
        refuse(-221, "no network name: send :SYST:COMM:WLAN:SSID first");
        return;
    }
    const char *notSaved = nullptr;
    if (const char *why = hooks_.wifiSet(cfg, &notSaved)) {
        hooks_.wifiGet(&wifi_);  // as the hook left it
        refuse(-200, why);
        return;
    }
    wifi_ = cfg;
    if (beginEcho(c)) {
        if (action == 2) {
            g_out->print(F(":SYST:COMM:WLAN:CLE"));
        } else {
            g_out->print(action == 0 ? F(":SYST:COMM:WLAN 1 (") : F(":SYST:COMM:WLAN 0 ("));
            printQuoted(*g_out, cfg.ssid);
            g_out->print(cfg.pass[0] ? F(", WPA2") : F(", open"));
            g_out->print(notSaved ? F(", not stored)") : F(", stored)"));
        }
        g_out->println();
    }
    if (notSaved) {  // a warning: the change is in use
        if (strncmp(notSaved, "not stored: ", 12) == 0) notSaved += 12;
        error(c, 101, notSaved);
        c.failed = false;
    }
}

// ---------------------------------------------------------------- program messages
void Protocol::reportError(ProtocolLink &link, int code, const char *detail) {
    ReplyOut *prev = g_out;
    g_out = &ScpiAccess::out(link);
    bool respStarted = false;
    ScpiCtx c{this, &link, nullptr, false, {}, 0, &respStarted, false};
    error(c, code, detail);
    g_out = prev;
}

// One program message: message units separated by ';'. An error that the parser
// finds in the message itself (-102, -103, -108, -113, -151 for a missing closing
// quote) ends the rest of the message. An error in a command's values or in its
// execution ends only that unit.
void Protocol::dispatch(ProtocolLink &link, char *line) {
    g_out->startCommand();
    bool respStarted = false;
    // The current path (IEEE 488.2 / SCPI): the nodes of the last header but its leaf.
    // After a header that names an inner node used with its default node (OUTPut ON),
    // the header itself is tried first (isInnerNode()).
    Tok path[16];
    size_t npath = 0;
    bool pathHasLeaf = false;  // path[npath - 1] is the last header's own last node
    const char *s = line;
    for (;;) {
        while (*s == ' ' || *s == '\t') ++s;
        if (!*s) break;
        if (*s == ';') {
            ++s;
            continue;
        }
        ScpiCtx c{this, &link, nullptr, false, {}, 0, &respStarted, false};
        Tok toks[8];
        size_t nt = 0;
        bool absolute = false;
        const bool common = *s == '*';
        const char *hdr = s;
        if (common) {
            ++s;
            while (isalpha((unsigned char)*s)) ++s;
            toks[nt++] = Tok{hdr, (size_t)(s - hdr)};
        } else {
            if (*s == ':') {
                absolute = true;
                ++s;
            }
            for (;;) {
                if (!isalpha((unsigned char)*s)) {
                    error(c, -102, "a header is made of words (letters and digits) joined by ':'");
                    goto done;
                }
                const char *b = s;
                while (isalnum((unsigned char)*s) || *s == '_') ++s;
                if (nt == 8) {
                    error(c, -113, hdr, (size_t)(s - hdr));
                    goto done;
                }
                toks[nt++] = Tok{b, (size_t)(s - b)};
                if (*s != ':') break;
                ++s;
            }
        }
        if (*s == '?') {
            c.query = true;
            ++s;
        }
        const size_t hdrLen = (size_t)(s - hdr);
        if (*s && *s != ';' && *s != ' ' && *s != '\t') {
            error(c, -102, "a space must come between the header and its value");
            goto done;
        }
        // Parameters: up to ';' outside quotes, separated by ','.
        while (*s == ' ' || *s == '\t') ++s;
        while (*s && *s != ';') {
            const char *b = s;
            while (*s && *s != ',' && *s != ';') {
                if (*s == '"' || *s == '\'') {
                    const char q = *s++;
                    while (*s && !(*s == q && s[1] != q)) s += (*s == q) ? 2 : 1;
                    if (!*s) {
                        error(c, -151, "the closing quote is missing");
                        goto done;
                    }
                }
                ++s;
            }
            const char *e = s;
            while (e > b && (e[-1] == ' ' || e[-1] == '\t')) --e;
            if (e == b) {
                error(c, -103, "a value is missing before ',' or ';'");
                goto done;
            }
            if (c.nparams == sizeof(c.params) / sizeof(c.params[0])) {
                error(c, -108);
                goto done;
            }
            c.params[c.nparams++] = ScpiParam{b, (size_t)(e - b)};
            if (*s == ',') {
                ++s;
                while (*s == ' ' || *s == '\t') ++s;
                if (!*s || *s == ';') {
                    error(c, -103, "a value is missing after ','");
                    goto done;
                }
            }
        }
        {
            // Resolve the header: relative to the current path, else (lenient) from the root.
            Tok full[16];
            size_t nf = 0;
            const ScpiCmd *cmd = nullptr;
            for (size_t drop = 0; !cmd && !common && !absolute && drop <= (pathHasLeaf ? 1u : 0u) && npath > drop; ++drop) {
                nf = 0;
                for (size_t i = 0; i + drop < npath; ++i) full[nf++] = path[i];
                for (size_t i = 0; i < nt; ++i) full[nf++] = toks[i];
                cmd = findCommand(full, nf, false);
            }
            if (!cmd) {
                nf = 0;
                for (size_t i = 0; i < nt; ++i) full[nf++] = toks[i];
                cmd = findCommand(full, nf, common);
            }
            if (!cmd) {
                error(c, -113, hdr, hdrLen);
                goto done;
            }
            if (c.query ? !(cmd->flags & kQ) : !(cmd->flags & kS)) {
                error(c, -113, c.query ? "this command has no query form" : "this is a query only: add '?'");
                goto done;
            }
            if (!common) {
                pathHasLeaf = isInnerNode(full, nf);
                npath = pathHasLeaf ? nf : nf - 1;
                for (size_t i = 0; i < npath; ++i) path[i] = full[i];
            }
            c.cmd = cmd;
            (this->*(cmd->fn))(c);
        }
    }
done:
    if (respStarted) g_out->println();
}

void ProtocolLink::reset() {
    out_.reset();
    len_ = 0;
    discarding_ = false;
    recentEnd_ = 0;
    recentLen_ = 0;
    errCount_ = 0;
    esr_ = ese_ = sre_ = 0;
    echo_ = false;
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
    if (link.echo_) {
        g_out->startCommand();
        g_out->println(F("OK :OUTP 0 (DISARM)"));
    }
}

void Protocol::feed(ProtocolLink &link, char c) {
    g_out = &link.out_;
    if (c == '\0') {
        return;  // a NUL would silently truncate the command (e.g. "OUTP ON<NUL>X")
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
        reportError(link, -363, "the line is longer than 255 characters; it is discarded");
        return;
    }
    link.buf_[link.len_++] = c;
}

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
    if (waitFromUs != 0) {  // the wait comes out of the link's budget, see kFairUsPerByte
        const uint64_t waited = time_us_64() - waitFromUs;
        const uint64_t fair = (sent && !inputPending_) ? (uint64_t)lineLen_ * kFairUsPerByte : 0;
        const uint64_t charge = waited > fair ? waited - fair : 0;
        budgetUs_ = (stalled_ || charge >= budgetUs_) ? 0 : budgetUs_ - charge;
    }
    if (!sent) {
        dropped_ += (uint32_t)lineLen_;
    }
    lineLen_ = 0;
}

