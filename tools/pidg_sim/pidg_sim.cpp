// PiDG simulator: the REAL firmware command protocol on a host computer.
//
// Compiles the unmodified src/protocol.cpp and src/pulse_timing.h against a small
// fake of the arduino-pico core (fake/), and emulates the hooks src/main.cpp installs
// (arming, the restart hold-off, applying a parameter set), with the PIO hardware
// calls removed. It reads the serial byte stream on stdin and writes the replies to
// stdout, so every reply, error message and realized value is exactly what the board
// prints. The PiDG web GUI (tools/pidg_gui) starts it when you choose "Simulator".
//
// It is a protocol simulator only: nothing is timed, and the reset registers in
// STATUS are placeholders. Keep the hook emulation in step with src/main.cpp.
//
// Option: --overclock simulates the clock jumper fitted (clk_sys 300 MHz, clock_mode.h).
//
// Build (any C++17 compiler), from this directory:
//   g++ -std=c++17 -O2 -I fake -I ../../src -o pidg_sim pidg_sim.cpp ../../src/protocol.cpp
//   (Windows: -o pidg_sim.exe; MSVC: cl /std:c++17 /EHsc /I fake /I ..\..\src pidg_sim.cpp ..\..\src\protocol.cpp)
#include "Arduino.h"
#include "clock_mode.h"
#include "protocol.h"
#include "pulse_timing.h"

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <thread>

#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif

FakeSerial Serial;

namespace {
const auto kStart = std::chrono::steady_clock::now();
uint64_t g_offsetUs = 0;  // fake_advance_us()
}  // namespace

uint64_t time_us_64() {
    return (uint64_t)std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now() - kStart)
               .count() + g_offsetUs;
}
void fake_advance_us(uint64_t us) { g_offsetUs += us; }

namespace {
uint32_t g_clk = kStandardClockHz;  // platformio.ini board_build.f_cpu; kOverclockHz with --overclock
ClockModeInfo g_clockMode{false, false, nullptr, 1100};  // as the board's pre-init hook leaves it (clock_mode.cpp)
constexpr uint32_t kWatchdogMs = 3000;

bool g_gateOpen = false;  // laser::gateIsOpen()
PulseParams g_params;
RealizedTiming g_rt;
Protocol g_protocol;
bool g_pioReady = true;
bool g_configured = false;
bool g_armed = false;
char g_hwWhy[112] = "";
uint64_t g_quietSinceUs = 0;
uint32_t g_lastLaserPeriodCycles = 0;
bool g_startPending = false;
uint64_t g_startDueUs = 0;
uint32_t g_pendingPeriodCycles = 0;

uint32_t clkHz() { return g_clk; }

void closeLaserGate() {
    const bool wasOpen = g_gateOpen;
    g_gateOpen = false;
    if (wasOpen) g_quietSinceUs = time_us_64();
}

// main.cpp restartPulses(), without the PIO calls (so no load can fail here).
void restartPulses(const RealizedTiming &rt, bool lasersLive) {
    g_startPending = false;
    closeLaserGate();
    if (!lasersLive) return;
    g_startDueUs = g_quietSinceUs + restartHoldUs(g_lastLaserPeriodCycles, rt.periodCycles, rt.clkHz);
    g_pendingPeriodCycles = rt.periodCycles;
    g_startPending = true;
}

void servicePendingStart() {
    if (!g_startPending || time_us_64() < g_startDueUs) return;
    g_startPending = false;
    g_gateOpen = true;
    g_lastLaserPeriodCycles = g_pendingPeriodCycles;
}

uint32_t startPendingUs() {
    if (!g_startPending) return 0;
    const uint64_t now = time_us_64();
    return now >= g_startDueUs ? 0u : (uint32_t)(g_startDueUs - now);
}

const char *setArmed(bool arm) {
    if (!arm) {
        closeLaserGate();
        g_startPending = false;
        g_armed = false;
        return nullptr;
    }
    if (!g_pioReady || !g_configured) return g_hwWhy[0] ? g_hwWhy : "refused: pulse outputs not running";
    if (g_armed) return nullptr;
    restartPulses(g_rt, true);
    g_armed = true;
    return nullptr;
}

bool isArmed() { return g_armed; }

// main.cpp applyPulseParams(), without the PIO and SYNC calls.
const char *applyPulseParams(const PulseParams &p, RealizedTiming *realized) {
    RealizedTiming rt;
    if (const char *why = realizeTiming(p, clkHz(), &rt)) return why;
    if (g_armed && g_configured && rt.combine != g_rt.combine) {
        return "DISARM first: COMBINE changes what both laser outputs carry";
    }
    if (!g_pioReady) return "pio0 unavailable";
    if (!g_configured || pulseLoadDiffers(g_rt, rt)) restartPulses(rt, g_armed);
    g_rt = rt;
    g_configured = true;
    *realized = rt;
    return nullptr;
}

void printSystemStatus(Print &out) {
    out.print(F("HW="));
    if (g_hwWhy[0]) {
        out.print(F("ERR "));
        out.println(g_hwWhy);
    } else {
        out.println(F("OK"));
    }
    out.print(F("START_PENDING_US="));
    out.println(startPendingUs());
    out.print(F("CLK="));
    out.println(clkHz());
    out.print(F("CLKMODE="));
    printClockMode(out, g_clockMode);
    out.print(F("VREG_MV="));
    out.println(g_clockMode.vregMv);
    out.println(F("RESET=POWER_ON"));
    out.println(F("RESET_RAW=WD:0x0 CHIP:0x0"));
    out.println(F("WDT_RESETS=0"));
    out.print(F("WDT_MS="));
    out.println(kWatchdogMs);
}

void printIdentity(Print &out) {
    out.println(F("PiDG delay generator (simulator), protocol and timing code from ../../src"));
}

void setup() {
    g_lastLaserPeriodCycles = clkHz();  // worst case (1 s), as on the board
    const char *why = g_protocol.begin(
        &g_params, ProtocolHooks{applyPulseParams, setArmed, isArmed, startPendingUs, printSystemStatus,
                                 printIdentity, clkHz});
    if (why) snprintf(g_hwWhy, sizeof(g_hwWhy), "outputs not started: %s", why);
    Serial.print(F("PiDG delay generator ready, lasers DISARMED (reset: POWER_ON"));
    Serial.print(clockModeBannerNote(g_clockMode));
    Serial.println(F("). Type HELP for commands."));
    if (g_hwWhy[0]) {
        Serial.print(F("ERR "));
        Serial.println(g_hwWhy);
    }
}
}  // namespace

int main(int argc, char **argv) {
    for (int i = 1; i < argc; ++i) {
        if (!strcmp(argv[i], "--overclock")) {
            g_clk = kOverclockHz;
            g_clockMode = ClockModeInfo{true, true, nullptr, 1300};
        } else {
            fprintf(stderr, "usage: pidg_sim [--overclock]\n");
            return 2;
        }
    }
#ifdef _WIN32
    _setmode(_fileno(stdin), _O_BINARY);
    _setmode(_fileno(stdout), _O_BINARY);
#endif
    setup();
    unsigned char buf[256];
    for (;;) {
        const size_t n = fread(buf, 1, 1, stdin);  // one byte at a time: DISARM acts on its last letter
        if (n == 0) break;                          // host closed the pipe
        g_protocol.feed((char)buf[0]);
        servicePendingStart();
    }
    return 0;
}
