// PiDG - PIV delay generator (Raspberry Pi Pico 2 / Pico 2 W, RP2350)
// Built via the community arduino-pico core (see platformio.ini) since
// PlatformIO's official "raspberrypi" platform/Mbed core has no RP2350
// support; the wireless radio of a Pico 2 W is unused by this firmware.
//
// IDS EVS event-camera synchronizer, implemented with PIO state machines and the
// RP2350 clock generator (no CPU busy-waits). Outputs (the GPIO map is in board.h):
//   - CH1 / CH2 (GP13 / GP12): the two laser trigger pulses. Shared width; CH2's
//     rising edge follows CH1's by exactly DELAY (to the nearest PIO cycle).
//     COMBINE 1 puts BOTH pulses on BOTH outputs (two light sources fired in sync
//     with the same double pulse): the CH1 and CH2 state machines then each drive
//     GP12 and GP13 together (pio_pulse.cpp, dual-pin program).
//   - MARKER (GP11): a pulse of MARKERWIDTH with every pulse pair, rising with
//     CH1, that the board's jumper (J10) selects as the camera Trigger line
//     instead of the raw laser pulse. Each camera timestamps it into its event
//     stream.
//   - SYNC (GP15): the continuous 1 MHz camera sync clock, clk_gpout1 dividing clk_sys
//     by exactly 150, or 300 with the clock jumper (sync_clock.cpp). No PIO: it is
//     independent of the laser timing, and it runs even if pio0 cannot be claimed.
//   - PIXGATE (GP16): optional camera pixel reset between pulse pairs. pio0 SM3
//     runs the pulse program with the pin's output inverted, so its pulse holds
//     every camera's TDRSTN low from PIXLAG after the last laser pulse until
//     PIXLEAD before the next CH1. U3 ANDs it with the J12 BNC input, so either
//     source resets the pixels; stopped, the gate is high and J12 alone rules.
//
// Laser arming. The firmware boots DISARMED: CH1/CH2 are held LOW by
// laser_gate (from a pre-init hook, before anything else runs), while SYNC and
// MARKER run. ARM restarts CH1, CH2 and MARKER together after the restart
// hold-off, so the first laser pulse after ARM is full width and correctly
// phased; DISARM gates CH1/CH2 LOW immediately and cancels a pending start. The
// hardware interlock (J11 / U10) and power-good gate (U18) act independently of
// this.
//
// Watchdog. A hardware watchdog (kWatchdogMs) resets the chip if loop() stops
// running. The chip then comes back up DISARMED, and STATUS reports
// RESET=WATCHDOG.
//
// Clock. clk_sys is 150 MHz (6.667 ns per PIO cycle), or 300 MHz (3.333 ns) when the
// clock jumper is fitted at boot (clock_mode.h). All timing follows clock_get_hz().
//
// See src/pio_pulse.h for the PIO program design, src/pulse_timing.h for the
// cycle math and timing checks, and src/protocol.h for the serial command set.

#include <Arduino.h>
#include <cstdio>
#include <iterator>
#include "board.h"
#include "clock_mode.h"
#include "hardware/clocks.h"
#include "hardware/gpio.h"
#include "hardware/pio.h"
#include "hardware/structs/powman.h"
#include "hardware/structs/watchdog.h"
#include "hardware/timer.h"
#include "laser_gate.h"
#include "pio_pulse.h"
#include "protocol.h"
#include "pulse_timing.h"
#include "reset_scratch.h"
#include "sync_clock.h"

namespace {

PIO kPio = pio0;
constexpr uint kSmCh1 = 0;
constexpr uint kSmCh2 = 1;
constexpr uint kSmMarker = 2;
constexpr uint kSmPixGate = 3;
constexpr uint32_t kSmMask = (1u << kSmCh1) | (1u << kSmCh2) | (1u << kSmMarker) | (1u << kSmPixGate);

// SYNC needs a pin with a clk_gpout function (sync_clock.h); catch a wrong board.h at build time.
static_assert(GPIO_TO_GPOUT_CLOCK_HANDLE(kPinSync, CLK_COUNT) != CLK_COUNT, "kPinSync has no clk_gpout function");

// Firmware version for ID?: `git describe --always --dirty` of the source tree, passed in
// by tools/firmware_version.py (platformio.ini extra_scripts). It replaces the build
// date and time, so two builds of the same commit are the same image.
#ifndef PIDG_FIRMWARE_VERSION
#define PIDG_FIRMWARE_VERSION "unknown"
#endif

#if defined(ARDUINO_RASPBERRY_PI_PICO_2W)
constexpr const char *kBoardName = "Pico 2 W";
#elif defined(ARDUINO_RASPBERRY_PI_PICO_2)
constexpr const char *kBoardName = "Pico 2";
#else
constexpr const char *kBoardName = "unknown board";
#endif

// Hardware watchdog. Fed only from loop(), never from an IRQ or timer, so a stuck
// main loop is caught. Nothing in one loop() iteration blocks for long: the restart
// hold-off is serviced from loop() rather than waited out, and every reply is
// written within the protocol's 250 ms output budget (protocol.cpp, ReplyOut). 3 s
// leaves a wide margin above that and is well under the RP2350 maximum of 0xFFFFFF
// us = 16.7 s. If it ever fires, the chip reboots DISARMED.
constexpr uint32_t kWatchdogMs = 3000;

// SCRATCH4 as the SDK's watchdog_enable() left it (WATCHDOG_NON_REBOOT_MAGIC, private to
// hardware_watchdog/watchdog.c; getResetReason() relies on it). Read back after
// wdt_begin() instead of copied, so an SDK change cannot stop the feeding. A deliberate
// reboot through watchdog_reboot() overwrites SCRATCH4 (0, or 0xb007c0d3 for a reboot to
// an address) and arms a short timeout; feeding after that would keep postponing the
// reboot, so feedWatchdog() only feeds while SCRATCH4 still holds this value. The default
// build never calls watchdog_reboot() (the 1200-baud BOOTSEL request goes through the
// bootrom and does not return); a core built with ENABLE_PICOTOOL_USB does, for
// picotool's reboot request. 0 = not read yet, or unusable because a plain reboot also
// writes 0: then feedWatchdog() always feeds.
uint32_t g_wdtRunMagic = 0;

PulseChannel g_ch1;
PulseChannel g_ch2;
PulseChannel g_marker;
PulseChannel g_pixGate;  // pixel-reset gate: output INVERTED, latch high = pixels in reset
SyncClock g_sync;  // clk_gpout, not PIO
// Started and stopped together. The first three always run; the gate (last) runs only
// while PIXGATE asks for it (pulseGroupCount()).
PulseChannel *const g_group[] = {&g_ch1, &g_ch2, &g_marker, &g_pixGate};
constexpr size_t kGroupAll = std::size(g_group);
PulseChannel *const g_pixGateOnly[] = {&g_pixGate};

PulseParams g_params;
RealizedTiming g_rt;  // what is loaded in the state machines now
Protocol g_protocol;
bool g_pioReady = false;
bool g_configured = false;  // g_rt is loaded and running; false again after a failed load
bool g_armed = false;  // always false after any reset
char g_hwWhy[112] = "";  // boot-time hardware problem ("" = none); stays for the session
const char *g_loadFailWhy = nullptr;  // why the last pulse load failed; nullptr after a clean load

// Restart hold-off bookkeeping (see restartPulses()).
uint64_t g_quietSinceUs = 0;           // when the laser pads last stopped carrying pulses
uint32_t g_lastLaserPeriodCycles = 0;  // period of the last pulse train on the laser pads
bool g_startPending = false;           // the group is loaded, waiting out the hold-off
uint64_t g_startDueUs = 0;             // the next three are set together with g_startPending
uint32_t g_pendingPeriodCycles = 0;
size_t g_pendingGroupCount = 0;

struct ResetInfo {
    RP2040::resetReason_t reason = RP2040::UNKNOWN_RESET;
    uint32_t wdReason = 0;   // WATCHDOG_REASON raw (bit0 TIMER, bit1 FORCE)
    uint32_t chipReset = 0;  // POWMAN_CHIP_RESET raw (last chip-level reset)
    uint32_t wdtCount = 0;   // watchdog timeouts since the last POR/BOR/RUN
} g_reset;

uint32_t clkHz() {
    return clock_get_hz(clk_sys);
}

const char *resetReasonName(RP2040::resetReason_t r) {
    switch (r) {
        case RP2040::PWRON_RESET: return "POWER_ON";
        case RP2040::RUN_PIN_RESET: return "RUN_PIN";
        case RP2040::SOFT_RESET: return "SOFT";
        case RP2040::WDT_RESET: return "WATCHDOG";
        case RP2040::DEBUG_RESET: return "DEBUG";
        case RP2040::GLITCH_RESET: return "GLITCH";
        case RP2040::BROWNOUT_RESET: return "BROWNOUT";
        default: return "UNKNOWN";
    }
}

// Must run before rp2040.wdt_begin(): watchdog_enable() rewrites SCRATCH4, and that
// register is how getResetReason() tells a watchdog timeout (SCRATCH4 = enable magic)
// from a deliberate reboot.
void captureResetInfo() {
    g_reset.reason = rp2040.getResetReason();
    g_reset.wdReason = watchdog_hw->reason;
    g_reset.chipReset = powman_hw->chip_reset;
    // The watchdog-timeout counter (reset_scratch.h).
    if (watchdog_hw->scratch[kWdtCountMagicScratch] != kWdtCountMagic) {
        watchdog_hw->scratch[kWdtCountScratch] = 0;
        watchdog_hw->scratch[kWdtCountMagicScratch] = kWdtCountMagic;
    }
    if (g_reset.reason == RP2040::WDT_RESET) {
        watchdog_hw->scratch[kWdtCountScratch] = watchdog_hw->scratch[kWdtCountScratch] + 1;
    }
    g_reset.wdtCount = watchdog_hw->scratch[kWdtCountScratch];
}

void feedWatchdog() {
    if (g_wdtRunMagic == 0 || watchdog_hw->scratch[4] == g_wdtRunMagic) {
        rp2040.wdt_reset();
    }
}

// Claims the pio0 state machines of the pulse group (kSmMask) before anything else
// can. If any is already taken, nothing is claimed and ARM is refused. (On a Pico 2 W
// the core's CYW43 init in initVariant() has already claimed a state machine, but the
// SDK allocates from the highest PIO down, so it lands on pio2.)
bool claimPioStateMachines() {
    for (uint sm = 0; sm < NUM_PIO_STATE_MACHINES; ++sm) {
        if (((kSmMask >> sm) & 1u) && pio_sm_is_claimed(kPio, sm)) {
            return false;
        }
    }
    pio_claim_sm_mask(kPio, kSmMask);
    return true;
}

// Routes GP16 to pio0 with its output INVERTED before the pad is driven, so the gate
// pin goes straight from "input, pulled high by R24" to "driven high" (latch LOW ->
// pin HIGH = pixels free) with no reset glitch. pio_gpio_init() rewrites GPIO_CTRL
// (clearing OUTOVER), so the inversion is set after it and before the pin direction.
void initPixGatePin() {
    pio_gpio_init(kPio, kPinPixGate);
    gpio_set_outover(kPinPixGate, GPIO_OVERRIDE_INVERT);
    pio_sm_set_consecutive_pindirs(kPio, kSmPixGate, kPinPixGate, 1, true);
}

// How many of g_group run for a pulse train: the gate joins under PIXGATE 2 always,
// and under PIXGATE 1 only while the laser pads carry pulses.
size_t pulseGroupCount(const RealizedTiming &rt, bool lasersLive) {
    return (rt.pixGate == 2 || (rt.pixGate == 1 && lasersLive)) ? kGroupAll : kGroupAll - 1;
}

// Gates the laser pads LOW; if they were live, the quiet period starts now (the
// timestamp is taken AFTER the pads are LOW, so no pulse can hide behind it).
void closeLaserGate() {
    const bool wasOpen = laser::gateIsOpen();
    laser::gateClose();
    if (wasOpen) {
        g_quietSinceUs = time_us_64();
    }
}

// (Re)loads CH1, CH2, MARKER and the pixel-reset gate from `rt` and restarts them
// together:
//  1. Gate the laser pads LOW if they are live (a pulse in flight is cut short,
//     never stretched) and start the quiet period.
//  2. Halt all four state machines with one CTRL write and force their PIO output
//     latches LOW (stopPulseChannelsLow).
//  3. Load the new cycle counts. If any load fails, stop here and start nothing.
//  4. Lasers not live: enable the group now, on the same clock cycle (MARKER runs,
//     CH1/CH2 run behind the closed gate, the gate SM only under PIXGATE 2).
//     Lasers live: leave everything stopped and schedule the start for the end of
//     the restart hold-off. servicePendingStart(), called from loop(), then opens
//     the gate (latch LOW -> no edge) and enables the group together, so the first
//     CH1 pulse, the first CH2 pulse (DELAY later) and the first MARKER pulse are
//     complete and in phase. DISARM before then cancels the start.
// Returns nullptr, or why a load failed. Then every pulse state machine stays halted
// with its latch LOW and the laser pads stay gated LOW; the caller must call
// pulseLoadFailed().
//
// Restart hold-off: every restart fires a CH1 pulse ~8 cycles after the enable,
// however recently the last one fired. Without a hold-off, a host looping ARM/DISARM
// or changing settings fast would set the pulse rate by its command rate, faster than
// the set FREQ. Waiting until one full period -- the longer of the old and
// new laser periods -- has passed since the pads last carried pulses keeps the
// spacing between laser pulses >= the set period under any command sequence. At boot
// the old period is taken as the worst case (1 s, FREQ >= 1 Hz), which also covers a
// reset that happened while armed. MARKER pauses during the hold-off, and the pixel-
// reset gate stays open (latch LOW -> pin HIGH) until the train starts.
const char *restartPulses(const RealizedTiming &rt, bool lasersLive) {
    g_startPending = false;
    closeLaserGate();
    stopPulseChannelsLow(g_group, kGroupAll);  // gate latch LOW = pixels free
    // Pin mapping for this pulse train (all state machines are stopped, latches LOW):
    // split = CH1 -> GP13, CH2 -> GP12; COMBINE = both drive GP12..GP13.
    static_assert(kPinCh1 == kPinCh2 + 1, "COMBINE needs the laser pins consecutive");
    const uint lasers = rt.combine ? 2u : 1u;
    // No step should fail: both programs are loaded at boot, and realizeTiming() ran
    // the same feasibility checks as configure(). If one did fail anyway, its state
    // machine would keep its old program position and registers and replay the OLD
    // timing once enabled, so nothing is started then.
    const bool loaded =
        g_ch1.setOutputs(rt.combine ? kPinCh2 : kPinCh1, lasers) && g_ch2.setOutputs(kPinCh2, lasers) &&
        g_ch1.configure(PulseCycles{rt.periodCycles, 0, rt.widthCycles}) &&
        g_ch2.configure(PulseCycles{rt.periodCycles, rt.delayCycles, rt.widthCycles}) &&
        g_marker.configure(PulseCycles{rt.periodCycles, 0, rt.markerWidthCycles}) &&  // every pulse pair
        (!rt.pixGate || g_pixGate.configure(PulseCycles{rt.periodCycles, rt.pixResetStartCycles, rt.pixResetCycles}));
    if (!loaded) {
        return "pulse state machines could not be loaded";
    }
    if (!lasersLive) {
        startPulseChannelsInSync(g_group, pulseGroupCount(rt, false));
        return nullptr;
    }
    g_startDueUs = g_quietSinceUs + restartHoldUs(g_lastLaserPeriodCycles, rt.periodCycles, rt.clkHz);
    g_pendingPeriodCycles = rt.periodCycles;
    g_pendingGroupCount = pulseGroupCount(rt, true);
    g_startPending = true;
    return nullptr;
}

// A load failed (restartPulses()): nothing runs and the laser pads stay gated LOW.
// Disarms, and refuses ARM until a later setting loads cleanly; STATUS shows the
// reason as HW=ERR. Returns `why`.
const char *pulseLoadFailed(const char *why) {
    g_armed = false;
    g_configured = false;
    g_loadFailWhy = why;
    return why;
}

// Called from loop(): starts a scheduled laser pulse train once its hold-off is over.
void servicePendingStart() {
    if (!g_startPending || time_us_64() < g_startDueUs) {
        return;
    }
    g_startPending = false;
    laser::gateOpen(kPio, kSmCh1);  // SMs are still disabled: SIO LOW -> PIO latch LOW, no edge
    g_lastLaserPeriodCycles = g_pendingPeriodCycles;
    startPulseChannelsInSync(g_group, g_pendingGroupCount);
}

// Protocol hook: microseconds until a pending laser start, or 0.
uint32_t startPendingUs() {
    if (!g_startPending) {
        return 0;
    }
    const uint64_t now = time_us_64();
    return now >= g_startDueUs ? 0u : (uint32_t)(g_startDueUs - now);
}

// Protocol hook: ARM (true) / DISARM (false).
const char *setArmed(bool arm) {
    if (!arm) {
        closeLaserGate();  // re-asserted even if already closed
        if (g_startPending) {
            // A start was waiting out the hold-off: cancel it, and restart the loaded
            // channels behind the closed gate so MARKER resumes.
            g_startPending = false;
            startPulseChannelsInSync(g_group, pulseGroupCount(g_rt, false));
        } else if (g_armed && g_rt.pixGate == 1) {
            // PIXGATE 1 gates only while ARMED: stop the gate, which leaves its latch
            // LOW, i.e. the pixels free. A reset in progress ends at the halt (at most a
            // few cycles later, the time to its forced SET PINS 0).
            stopPulseChannelsLow(g_pixGateOnly, 1);
        }
        g_armed = false;
        return nullptr;
    }
    if (!g_pioReady || !g_configured) {
        if (g_hwWhy[0]) {
            return g_hwWhy;
        }
        return g_loadFailWhy ? g_loadFailWhy : "refused: pulse outputs not running";
    }
    if (g_armed) {
        return nullptr;  // already armed: no restart, no phase jump
    }
    if (const char *why = restartPulses(g_rt, true)) {
        return pulseLoadFailed(why);
    }
    g_armed = true;
    return nullptr;
}

bool isArmed() {
    return g_armed;
}

// Protocol hook: applies a candidate parameter set. The whole set is realized and
// checked first (realizeTiming), so a rejected change never touches the pulse group.
// SYNC starts at its fixed 1 MHz when the defaults are applied, also when pio0 is
// unavailable (it needs no PIO). Only the pulse group restarts on settings changes,
// and only if a realized cycle count changed (WIDTH 100 -> 101 ns is the same 15
// cycles and does not restart anything). While armed, a pulse change goes through the
// same safe restart as ARM, lasers staying armed.
const char *applyPulseParams(const PulseParams &p, RealizedTiming *realized) {
    RealizedTiming rt;
    if (const char *why = realizeTiming(p, clkHz(), &rt)) {
        return why;
    }
    if (g_armed && g_configured && rt.combine != g_rt.combine) {
        return "DISARM first: COMBINE changes what both laser outputs carry";
    }
    g_sync.start(rt.syncDiv);  // does nothing while SYNC already runs at this divider
    if (!g_pioReady) {
        return "pio0 unavailable";
    }
    if (!g_configured || pulseLoadDiffers(g_rt, rt)) {
        if (const char *why = restartPulses(rt, g_armed)) {
            return pulseLoadFailed(why);
        }
        g_loadFailWhy = nullptr;  // a clean load ends an earlier load failure
    }
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
    } else if (g_loadFailWhy) {
        out.print(F("ERR outputs stopped: "));
        out.println(g_loadFailWhy);
    } else {
        out.println(F("OK"));
    }
    out.print(F("START_PENDING_US="));
    out.println(startPendingUs());
    out.print(F("CLK="));
    out.println(clkHz());
    out.print(F("CLKMODE="));
    printClockMode(out, clockModeInfo());
    out.print(F("RESET="));
    out.println(resetReasonName(g_reset.reason));
    out.print(F("RESET_RAW=WD:0x"));
    out.print(g_reset.wdReason, HEX);
    out.print(F(" CHIP:0x"));
    out.println(g_reset.chipReset, HEX);
    out.print(F("WDT_RESETS="));
    out.println(g_reset.wdtCount);
    out.print(F("WDT_MS="));
    out.println(kWatchdogMs);
}

void printIdentity(Print &out) {
    out.print(F("PiDG delay generator ("));
    out.print(kBoardName);
    out.println(F("), firmware " PIDG_FIRMWARE_VERSION));
}

}  // namespace

void setup() {
    // The laser pads were already gated LOW by the pre-init hook (laser_gate.cpp);
    // re-assert it before anything else touches the hardware.
    laser::gateClose();
    captureResetInfo();  // before wdt_begin() (SCRATCH4)
    g_lastLaserPeriodCycles = clkHz();  // worst case (1 s at FREQ = 1 Hz): covers a reset while armed

    // SYNC first and on its own: it uses the clock generator, not PIO, so a pio0
    // problem cannot stop it. begin() drives the pin LOW until the defaults start it.
    const bool syncReady = g_sync.begin(kPinSync);
    g_pioReady = claimPioStateMachines() &&
                 g_ch1.begin(kPio, kSmCh1, kPinCh1, false) &&   // laser pins: routed by laser_gate
                 g_ch2.begin(kPio, kSmCh2, kPinCh2, false) &&
                 pulseReserveDualProgram(kPio) &&  // COMBINE mode: never fails later
                 g_marker.begin(kPio, kSmMarker, kPinMarker, true) &&
                 g_pixGate.begin(kPio, kSmPixGate, kPinPixGate, false);  // pin: initPixGatePin()
    if (g_pioReady) {
        initPixGatePin();
    }

    // Applies the compiled-in defaults: SYNC and MARKER start, lasers stay DISARMED.
    // (The hooks are installed even if pio0 is unavailable, so commands still get
    // an answer -- applyPulseParams() then starts SYNC only, refuses every change, and
    // ARM is refused.)
    const char *why = g_protocol.begin(
        &g_params, ProtocolHooks{applyPulseParams, setArmed, isArmed, startPendingUs, printSystemStatus,
                                 printIdentity, clkHz});
    if (!g_pioReady) {
        why = "pio0 unavailable (state machine already claimed or instruction memory full)";
    } else if (!syncReady) {  // not reachable with the static_assert on kPinSync; reported, not ignored
        why = "SYNC pin has no clock output";
    } else if (g_loadFailWhy) {
        // A failed load is not a boot-time hardware problem: it stays in g_loadFailWhy
        // ("outputs stopped"), which the next clean load clears.
        why = nullptr;
    }
    if (why) {
        snprintf(g_hwWhy, sizeof(g_hwWhy), "outputs not started: %s", why);  // copy: `why` may be a reused buffer
    }

    Serial.begin(115200);
    const unsigned long start = millis();
    while (!Serial && (millis() - start) < 1500) {
        // give the USB CDC connection a moment, but don't hang forever
    }

    // One line: hosts recognize a reboot by its start (tools/pidg_gui/pidg_device.py).
    Serial.print(F("PiDG delay generator ready, lasers DISARMED (reset: "));
    Serial.print(resetReasonName(g_reset.reason));
    Serial.print(clockModeBannerNote(clockModeInfo()));
    Serial.println(F("). Type HELP for commands."));
    if (g_hwWhy[0]) {
        Serial.print(F("ERR "));
        Serial.println(g_hwWhy);
    } else if (g_loadFailWhy) {
        Serial.print(F("ERR outputs stopped: "));
        Serial.println(g_loadFailWhy);
    }

    rp2040.wdt_begin(kWatchdogMs);  // last: every boot-time wait above is finished
    g_wdtRunMagic = watchdog_hw->scratch[4];  // as watchdog_enable() left it (see g_wdtRunMagic)
}

void loop() {
    feedWatchdog();
    servicePendingStart();
    // One USB call per byte. read() returns -1 when nothing is left, also when the data
    // went away after a check (e.g. a USB bus reset), so -1 is never fed as a character.
    for (int c; (c = Serial.read()) >= 0;) {
        g_protocol.feed((char)c);
        servicePendingStart();
        feedWatchdog();  // a long burst of input is still progress
    }
}
