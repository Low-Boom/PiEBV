#pragma once
// Line-based ASCII serial protocol for the PiDG delay generator.
//
// One command per line, terminated by '\n' ("\r\n" also accepted). A bare
// command name queries the current value; a command followed by a value sets
// it. See HELP output in protocol.cpp for the full command list.

#include <cstddef>
#include <cstdint>

struct PulseParams {
    uint32_t freqHz = 1000;         // pulse-pair repetition frequency
    uint32_t widthNs = 2000;        // CH1/CH2 pulse width
    uint32_t delayNs = 10000;       // CH2-after-CH1 delay
    uint32_t markerDiv = 100;       // marker fires once every N pulses
    uint32_t markerWidthNs = 2000;  // marker pulse width
    uint32_t syncHz = 1000000;      // camera sync clock frequency
};

// Applies a candidate parameter set to the hardware. Returns false if it
// could not be realized (e.g. width+delay doesn't fit in the period at the
// running clock), in which case the caller must leave the previous
// configuration running untouched.
using ApplyParamsFn = bool (*)(const PulseParams &params);

class Protocol {
public:
    void begin(PulseParams *params, ApplyParamsFn apply);

    // Feed characters one at a time (e.g. from Serial.read()); a command is
    // dispatched as soon as a complete line has been accumulated.
    void feed(char c);

private:
    void dispatch(char *line);

    PulseParams *params_ = nullptr;
    ApplyParamsFn apply_ = nullptr;
    char buf_[96];
    size_t len_ = 0;
};
