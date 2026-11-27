#pragma once
// Boot-time clock choice from the clock jumper (board.h kPinClockSel).
//
//   Jumper open (or no header): clk_sys stays at the SDK's 150 MHz, the RP2350's rated
//   speed: 6.667 ns per PIO cycle.
//   Jumper fitted: a pre-init hook (clock_mode.cpp) raises clk_sys to 300 MHz before
//   main(): 3.333 ns per PIO cycle. This is TWICE THE RATED SPEED. Soak-test each Pico
//   first (Hardware.md, "Clock jumper").
//
// The pulse, SYNC and protocol code needs no change for 300 MHz: it all follows
// clock_get_hz(clk_sys), and DIAGnostic:CLOCk? and DIAGnostic:CLOCk:MODE? show it.
//
// The choice is made once per boot: moving the jumper takes effect at the next reset.
// After any watchdog timeout since the last power-up or RUN reset (DIAGnostic:WATChdog:RESets?
// counter, reset_scratch.h), the clock stays at 150 MHz even with the jumper fitted, so
// an unstable chip cannot crash in a loop at 300 MHz. Power-cycle to try again.
//
// This header has no SDK dependency, so the simulator (tools/piebv_sim) prints the same
// DIAGnostic:CLOCk:MODE? text.

#include <cstdint>

constexpr uint32_t kStandardClockHz = 150000000;
constexpr uint32_t kOverclockHz = 300000000;

struct ClockModeInfo {
    bool jumperFitted;  // the jumper read LOW at boot
    bool overclocked;   // clk_sys was raised to kOverclockHz
    const char *why;    // jumper fitted but not overclocked: the reason; else nullptr
    uint32_t vregMv;    // core voltage setting as the hook left it, mV (DIAGnostic:VREG?, in volts)
};

// The state the pre-init hook left (all false / nullptr before it runs).
const ClockModeInfo &clockModeInfo();

// The reply text of DIAGnostic:CLOCk:MODE? (printed with a line end; the caller removes it):
//   STANDARD
//   OVERCLOCK (jumper fitted)
//   STANDARD (jumper fitted, overclock off: <why>)
// `Out` is anything with print(const char *) / println(const char *) (Arduino Print).
template <class Out>
void printClockMode(Out &out, const ClockModeInfo &m) {
    if (m.overclocked) {
        out.println("OVERCLOCK (jumper fitted)");
    } else if (m.jumperFitted) {
        out.print("STANDARD (jumper fitted, overclock off: ");
        out.print(m.why ? m.why : "unknown reason");
        out.println(")");
    } else {
        out.println("STANDARD");
    }
}
