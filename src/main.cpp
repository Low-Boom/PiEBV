// PiDG - PIV delay generator (Raspberry Pi Pico 2 W / RP2350 port)
// Built via the community arduino-pico core (see platformio.ini) since
// PlatformIO's official "raspberrypi" platform/Mbed core has no RP2350
// support; the wireless radio itself is unused by this firmware.
//
// Reimplements the Teensy 4.1 "IDS EVS Event-camera Synchronizer" firmware
// (see "Chris Teensy Version/IDS_EVS_Sync_v2.ino", kept as the reference
// baseline) using PIO state machines instead of CPU busy-waits:
//   - CH1 / CH2 (GP2 / GP3): the two laser trigger pulses, independently
//     timed (shared width, configurable inter-pulse delay).
//   - MARKER (GP4): a low-rate pulse, once every MARKERDIV pulse-pairs, that
//     the board's jumper (J10) can also select as the camera Trigger line
//     instead of the raw laser pulse (mirrors the original D5/"PWM_Trig").
//   - SYNC (GP5): the continuous camera sync clock (mirrors the original
//     D4/1MHz hardware-PWM output).
// See src/pio_pulse.h for the PIO program design and src/protocol.h for the
// serial command set.

#include <Arduino.h>
#include "hardware/clocks.h"
#include "hardware/pio.h"
#include "pio_pulse.h"
#include "protocol.h"

namespace {

// Raw RP2350 GPIO numbers, passed straight to pio_gpio_init().
// These MUST match the 4-layer board (Pico Version 4Layer/PiDG_Pico.kicad_sch).
// The Pico plugs into socket J14/J15; J14 pad n = Pico physical pin n.
//
//   constant     GPIO   Pico pin   J14 pad   board net         drives
//   ----------   ----   --------   -------   ---------------   ---------------------
//   kPinSync     GP10      14         14     PWM_1MHz          U1 -> U2 -> Sync1..6
//   kPinMarker   GP11      15         15     PWM_Trig          J10.3 -> U5 -> U6 -> Trigger1..6
//   kPinCh2      GP12      16         16     _PULSE_OUT_CH2    U8 -> U13 -> J8 (Laser 2)
//   kPinCh1      GP13      17         17     _PULSE_OUT_CH1    U7 -> U13 -> J7 (Laser 1)
//
// Note CH1 is the HIGHER GPIO and CH2 the lower -- the opposite order to the
// Teensy original (D2=CH1, D3=CH2), so do not "tidy" these into ascending order.
// GP2-GP5 (the previous values) are explicit no-connects on this board.
constexpr uint kPinCh1 = 13;
constexpr uint kPinCh2 = 12;
constexpr uint kPinMarker = 11;
constexpr uint kPinSync = 10;

PIO kPio = pio0;

PulseChannel g_ch1;
PulseChannel g_ch2;
PulseChannel g_marker;
SyncChannel g_sync;

PulseParams g_params;
Protocol g_protocol;
bool g_hwConfigured = false;

uint32_t clkHz() {
    return clock_get_hz(clk_sys);
}

// Applies a candidate parameter set. Only the sub-system whose inputs
// actually changed is stopped and reconfigured (e.g. changing SYNC never
// touches the running laser pulses, and vice versa), and every channel's
// timing is validated up front so a rejected change never leaves the
// hardware partway through a reconfiguration.
bool applyPulseParams(const PulseParams &p) {
    if (p.freqHz == 0 || p.markerDiv == 0 || p.syncHz == 0) {
        return false;
    }

    const uint32_t clk = clkHz();

    const bool pulseChanged = !g_hwConfigured || p.freqHz != g_params.freqHz ||
                               p.widthNs != g_params.widthNs || p.delayNs != g_params.delayNs ||
                               p.markerDiv != g_params.markerDiv ||
                               p.markerWidthNs != g_params.markerWidthNs;
    const bool syncChanged = !g_hwConfigured || p.syncHz != g_params.syncHz;

    if (pulseChanged) {
        const uint64_t periodNs64 = 1000000000ULL / p.freqHz;
        const uint64_t markerPeriodNs64 = periodNs64 * p.markerDiv;
        if (periodNs64 > 0xFFFFFFFFULL || markerPeriodNs64 > 0xFFFFFFFFULL) {
            return false;
        }
        const uint32_t periodNs = (uint32_t)periodNs64;
        const uint32_t markerPeriodNs = (uint32_t)markerPeriodNs64;

        // Validate every channel before committing any of them.
        if (!pulseTimingFits(periodNs, 0, p.widthNs, clk) ||
            !pulseTimingFits(periodNs, p.delayNs, p.widthNs, clk) ||
            !pulseTimingFits(markerPeriodNs, 0, p.markerWidthNs, clk)) {
            return false;
        }

        g_ch1.configure(periodNs, 0, p.widthNs, clk);
        g_ch2.configure(periodNs, p.delayNs, p.widthNs, clk);
        g_marker.configure(markerPeriodNs, 0, p.markerWidthNs, clk);

        PulseChannel *pulseChannels[] = {&g_ch1, &g_ch2, &g_marker};
        startPulseChannelsInSync(pulseChannels, 3);
    }

    if (syncChanged) {
        if (!g_sync.configure(p.syncHz, clk)) {
            return false;
        }
        g_sync.start();
    }

    g_hwConfigured = true;
    return true;
}

}  // namespace

void setup() {
    Serial.begin(115200);
    unsigned long start = millis();
    while (!Serial && (millis() - start) < 1500) {
        // give the USB CDC connection a moment, but don't hang forever
    }

    g_ch1.begin(kPio, 0, kPinCh1);
    g_ch2.begin(kPio, 1, kPinCh2);
    g_marker.begin(kPio, 2, kPinMarker);
    g_sync.begin(kPio, 3, kPinSync);

    g_protocol.begin(&g_params, applyPulseParams);
    applyPulseParams(g_params);  // establish the compiled-in defaults

    Serial.println(F("PiDG-Pico2W delay generator ready. Type HELP for commands."));
}

void loop() {
    while (Serial.available() > 0) {
        g_protocol.feed((char)Serial.read());
    }
}
