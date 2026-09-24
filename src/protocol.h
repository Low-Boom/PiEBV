#pragma once
// Line-based ASCII serial protocol for the PiDG delay generator.
//
// One command per line, terminated by '\n', '\r' or "\r\n". Backspace (0x08)
// and DEL (0x7F) erase the previous character, so raw terminals work. A bare
// command name queries the current value; a command followed by one value sets
// it. See HELP output in protocol.cpp for the full command list.
//
// Time/frequency values are what the user asked for; every reply also shows
// the REALIZED value the PIO actually produces, e.g.
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
// again. A host that stops reading therefore delays a queued DISARM by at most
// about kReplyBudgetUs (250 ms) in total; lines that could not be sent are
// dropped whole and counted (STATUS TX_DROPPED).

#include <Arduino.h>
#include <cstddef>
#include <cstdint>
#include "pulse_timing.h"

struct ProtocolHooks {
    // Applies a candidate parameter set to the hardware. Returns nullptr on
    // success and fills *realized; otherwise returns a short reason, and the
    // previous configuration must be left running untouched.
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
};

class Protocol {
public:
    // Applies *params once (the compiled-in defaults). Returns nullptr on
    // success, or the reason they were rejected.
    const char *begin(PulseParams *params, const ProtocolHooks &hooks);

    // Feed characters one at a time (e.g. from Serial.read()); a command is
    // dispatched as soon as a complete line has been accumulated.
    void feed(char c);

    // Replies dropped because the host did not read them in time (see protocol.h top).
    uint32_t droppedReplyBytes() const;

private:
    void dispatch(char *line);
    void disarmNow();

    PulseParams *params_ = nullptr;
    ProtocolHooks hooks_{};
    RealizedTiming realized_{};
    char buf_[96];
    size_t len_ = 0;
    bool discarding_ = false;  // rest of the current line is dropped, never dispatched
    // Edit-aware history of the current line for the streaming DISARM match (kept
    // separately from buf_ because it must keep working in discard mode). As deep
    // as a line, so backspacing over a slid-out character still restores it.
    char recent_[96] = {};
    size_t recentLen_ = 0;
};
