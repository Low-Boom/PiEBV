#pragma once
// Pure integer timing math for the PiDG pulse and sync programs. No hardware
// access and no Arduino dependency, so it also compiles on a host:
// tools/timing_check/ builds this exact header into a small harness and checks
// it cycle-for-cycle against a Python model of the RP2350 PIO (see its README).
//
// Every user-facing time/frequency is converted ONCE to whole PIO clock cycles
// here, all checks (including the laser safety limits) run on those REALIZED
// cycle counts, and the hardware is loaded from exactly the same numbers. So
// what STATUS reports is what the pins do, and the user never has to correct a
// setting for quantization or for fixed instruction overheads.
//
// Cycle model of the pulse program (checked cycle-exact against a model of the
// RP2350 PIO, datasheet ch. 11), counting from the cycle the state machines
// are enabled together with pio_enable_sm_mask_in_sync():
//   SET PINS,1 executes on cycle 7 + delay_loaded   (then once per period)
//   high time          = width_loaded + 3 cycles
//   period             = delay_loaded + width_loaded + tail_loaded + 8 cycles
// Every PulseChannel runs this same program and all of them are enabled on the
// same cycle, so the constant 7 cancels between channels:
//   CH2 rise - CH1 rise = delay_loaded(CH2) - delay_loaded(CH1)
// The requested delay is therefore loaded AS-IS. (An earlier version subtracted
// the 2 fixed cycles before the SET from every channel; CH1's delay of 0 could
// not go negative, so CH2 fired 2 cycles = 13.3 ns early.)

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cstdio>

// ---------------------------------------------------------------- limits
// No laser-driver ratings are imposed: pulse width, duty and pulse spacing all
// depend on the attached driver, and the unit is used with more than one. The
// firmware only enforces what the PIO programs physically need: widths of >= 3
// cycles (20 ns at 150 MHz), DELAY + WIDTH fitting in the period, the marker and
// SYNC counter ranges, and with COMBINE 1 (both pulses on both outputs, sharing
// the pins) DELAY >= WIDTH + 1 cycle so the two pulses never touch.
//
// Pixel-reset gate (PIXGATE 1/2): a fourth state machine runs the same pulse
// program on GP16, whose output is INVERTED in the GPIO block, so its "pulse" is the
// camera pixel reset (TDRSTN low). Every period it asserts reset PIXLAG after the
// last laser pulse falls (CH1 rise + DELAY + WIDTH + PIXLAG) and releases it PIXLEAD
// before the next CH1 rise; the pixels are free for the whole pulse pair. The
// program needs PIXLEAD >= 5 cycles and a reset of >= 3 cycles per period.
constexpr uint32_t kPixGateMinLeadCycles = 5;

// ---------------------------------------------------------------- parameters
struct PulseParams {
    uint32_t freqHz = 1000;         // pulse-pair repetition frequency
    uint32_t widthNs = 100;         // CH1/CH2 pulse width (inside every attached laser driver's range)
    uint32_t delayNs = 10000;       // CH2-after-CH1 delay (rising edge to rising edge)
    uint32_t markerDiv = 100;       // marker fires once every N pulse pairs
    uint32_t markerWidthNs = 2000;  // marker pulse width
    uint32_t syncHz = 1000000;      // camera sync clock frequency
    uint32_t combine = 0;           // 0: CH1 -> LASER 1, CH2 -> LASER 2. 1: both pulses on BOTH outputs
    uint32_t pixGate = 0;           // camera pixel reset between pulse pairs: 0 off, 1 while ARMED, 2 always
    uint32_t pixLeadNs = 10000;     // pixels released this long before CH1 rises
    uint32_t pixLagNs = 100000;     // pixels reset again this long after the last laser pulse falls
};

// What the hardware actually produces for a PulseParams, in PIO clock cycles.
struct RealizedTiming {
    uint32_t clkHz = 0;               // 0 = nothing realized yet
    uint32_t periodCycles = 0;        // CH1/CH2 period
    uint32_t widthCycles = 0;         // CH1/CH2 high time
    uint32_t delayCycles = 0;         // CH2 rising edge minus CH1 rising edge, exactly
    uint32_t markerPeriodCycles = 0;  // exactly periodCycles * markerDiv (phase-locked to CH1)
    uint32_t markerWidthCycles = 0;
    uint32_t syncDiv256 = 0;          // SYNC state-machine clock divider in 1/256 steps
    uint32_t combine = 0;             // 1: CH1 and CH2 pulses both drive both laser outputs
    uint32_t pixGate = 0;             // 0 off, 1 while ARMED, 2 always
    uint32_t pixLeadCycles = 0;       // PIXLEAD, realized (shown even while the gate is off)
    uint32_t pixLagCycles = 0;        // PIXLAG, realized
    uint32_t pixResetStartCycles = 0; // reset asserted this long after CH1 rises (gate SM delay); 0 = gate off
    uint32_t pixResetCycles = 0;      // reset length per period (gate SM high time); 0 = gate off
};

// ---------------------------------------------------------------- pulse program
constexpr uint32_t kPulseMinWidthCycles = 3;       // SET 1; MOV X,Y; JMP X-- (X=0)
constexpr uint32_t kPulseFixedOverheadCycles = 8;  // non-loop instructions per period

// One channel's timing in state-machine clock cycles.
struct PulseCycles {
    uint32_t period;  // rising edge to rising edge, the same for every period
    uint32_t delay;   // rising-edge offset from the common start; 0 for CH1 and marker
    uint32_t width;   // high time, >= kPulseMinWidthCycles
};

// The three TX FIFO words the program pulls in its preamble.
struct PulseWords {
    uint32_t delay;
    uint32_t width;
    uint32_t tail;
};

enum class PulseFit : uint8_t {
    Ok,
    WidthTooShort,  // width < kPulseMinWidthCycles
    DoesNotFit,     // delay + width + 5 > period
};

// ns -> nearest whole cycle (a tie rounds up). Exact for any 32-bit ns and clk_hz.
inline uint64_t pulseNsToCycles(uint64_t ns, uint32_t clk_hz) {
    return (ns * clk_hz + 500000000ULL) / 1000000000ULL;
}

// Repetition frequency -> nearest whole period in cycles (a tie rounds up).
// Returns 0 for freq_hz == 0.
inline uint64_t pulseHzToCycles(uint32_t freq_hz, uint32_t clk_hz) {
    return freq_hz ? ((uint64_t)clk_hz + freq_hz / 2) / freq_hz : 0;
}

// Feasibility check and FIFO words for one channel. Shared by realizeTiming()
// and PulseChannel::configure(), so both always agree. A tail of 0 is legal:
// the period is still exact.
inline PulseFit computePulseCounts(const PulseCycles &t, PulseWords *out) {
    if (t.width < kPulseMinWidthCycles) {
        return PulseFit::WidthTooShort;
    }
    const uint64_t widthLoaded = (uint64_t)t.width - kPulseMinWidthCycles;
    const uint64_t used = (uint64_t)t.delay + widthLoaded + kPulseFixedOverheadCycles;
    if (used > t.period) {
        return PulseFit::DoesNotFit;
    }
    if (out) {
        out->delay = t.delay;
        out->width = (uint32_t)widthLoaded;
        out->tail = (uint32_t)(t.period - used);
    }
    return PulseFit::Ok;
}

// Largest delay that still fits with this width and period (cycles), or -1 if none does.
inline int64_t pulseMaxDelayCycles(uint32_t period, uint32_t width) {
    if (width < kPulseMinWidthCycles) return -1;
    return (int64_t)period - (int64_t)(width - kPulseMinWidthCycles) - (int64_t)kPulseFixedOverheadCycles;
}

// ---------------------------------------------------------------- sync program
// The SYNC program toggles its pin every state-machine clock (2 cycles per output
// period), so the divider is clk / (2 * f). The PIO divider has an 8-bit fraction:
// div256 = round(clk * 128 / f), INT = div256 >> 8, FRAC = div256 & 0xFF. A nonzero
// FRAC gives the right average frequency with 1-cycle (6.667 ns) edge jitter.
constexpr uint32_t kSyncMinDiv256 = 1u << 8;              // INT 1, FRAC 0
constexpr uint32_t kSyncMaxDiv256 = (65535u << 8) | 0xFF;  // INT 65535, FRAC 255

inline uint64_t syncDiv256For(uint32_t freq_hz, uint32_t clk_hz) {
    return freq_hz ? ((uint64_t)clk_hz * 128u + freq_hz / 2) / freq_hz : 0;
}

// ---------------------------------------------------------------- formatting
// Writes num/den as a decimal with exactly 3 fractional digits, rounding half
// up, e.g. "1000.000". Needs den > 0 and den < 1.8e16. Uses no printf, since
// newlib-nano's printf has no 64-bit conversions. Truncates to fit len.
inline void pulseFormatFixed3(uint64_t num, uint64_t den, char *buf, size_t len) {
    if (den == 0) {
        if (len) buf[0] = '\0';
        return;
    }
    uint64_t whole = num / den;
    uint64_t frac = ((num % den) * 1000ULL + den / 2) / den;
    if (frac >= 1000) {
        ++whole;
        frac -= 1000;
    }
    char tmp[32];
    char *p = tmp + sizeof(tmp);
    *--p = '\0';
    for (int i = 0; i < 3; ++i) {
        *--p = (char)('0' + frac % 10);
        frac /= 10;
    }
    *--p = '.';
    do {
        *--p = (char)('0' + whole % 10);
        whole /= 10;
    } while (whole);
    if (len == 0) return;
    size_t n = 0;
    while (p[n] != '\0' && n + 1 < len) {
        buf[n] = p[n];
        ++n;
    }
    buf[n] = '\0';
}

// Realized duration of `cycles` in ns, 3 decimals ("6.667"). Valid for cycles < 1.8e10.
inline void pulseFormatNs(uint64_t cycles, uint32_t clk_hz, char *buf, size_t len) {
    pulseFormatFixed3(cycles * 1000000000ULL, clk_hz, buf, len);
}

// Realized repetition frequency for a period of `periodCycles`, in Hz, 3 decimals.
inline void pulseFormatHz(uint64_t periodCycles, uint32_t clk_hz, char *buf, size_t len) {
    pulseFormatFixed3(clk_hz, periodCycles, buf, len);
}

// Realized SYNC frequency for a divider of div256/256, in Hz, 3 decimals.
inline void syncFormatHz(uint32_t div256, uint32_t clk_hz, char *buf, size_t len) {
    pulseFormatFixed3((uint64_t)clk_hz * 128u, div256, buf, len);
}

// ---------------------------------------------------------------- validation
// Turns a parameter set into exact cycle counts and runs every check on the
// REALIZED values, without touching hardware. Periods are derived in cycles:
// the marker period is exactly periodCycles * markerDiv (never re-rounded from
// ns), so the marker stays phase-locked to CH1 for every FREQ.
// Returns nullptr and fills *rt on success, otherwise a short reason (valid
// until the next call).
inline const char *realizeTiming(const PulseParams &p, uint32_t clk, RealizedTiming *rt) {
    static char why[160];
    char a[32];
    if (p.freqHz == 0 || p.markerDiv == 0 || p.syncHz == 0) {
        return "value must be > 0";
    }
    if (p.combine > 1) {
        return "COMBINE must be 0 (split) or 1 (both pulses on both outputs)";
    }
    const uint64_t period = pulseHzToCycles(p.freqHz, clk);
    const uint64_t markerPeriod = period * p.markerDiv;
    if (period == 0 || period > 0xFFFFFFFFULL) {
        return "FREQ out of range";
    }
    if (markerPeriod > 0xFFFFFFFFULL) {
        return "marker period (MARKERDIV x period) is over 2^32-1 PIO cycles";
    }
    // ns < 2^32 always gives < 2^32 cycles at clk < 1 GHz.
    const uint32_t width = (uint32_t)pulseNsToCycles(p.widthNs, clk);
    const uint32_t delay = (uint32_t)pulseNsToCycles(p.delayNs, clk);
    const uint32_t markerWidth = (uint32_t)pulseNsToCycles(p.markerWidthNs, clk);

    if (width < kPulseMinWidthCycles || markerWidth < kPulseMinWidthCycles) {
        pulseFormatNs(kPulseMinWidthCycles, clk, a, sizeof(a));
        snprintf(why, sizeof(why), "%s realizes below the %lu-cycle minimum (%s ns)",
                 width < kPulseMinWidthCycles ? "WIDTH" : "MARKERWIDTH",
                 (unsigned long)kPulseMinWidthCycles, a);
        return why;
    }
    // COMBINE: both state machines write the same two pins, and a pin keeps the last
    // level written. If CH2 rose before CH1 fell, CH1's fall would cut CH2's pulse
    // off (DELAY == WIDTH merges them into one). So CH2 may rise no earlier than one
    // cycle after CH1 falls: DELAY >= WIDTH + 1 cycle, i.e. any low gap > 0. (The
    // gap from CH2's fall to the next CH1 rise is >= 5 cycles by the fit check.)
    if (p.combine && delay < width + 1) {
        pulseFormatNs(width + 1, clk, a, sizeof(a));
        snprintf(why, sizeof(why), "COMBINE needs DELAY > WIDTH so the two pulses stay separate (min DELAY %s ns)", a);
        return why;
    }
    // Pulse pairs stay separated: CH2 must end at least one WIDTH before the next
    // pair's CH1 rises, i.e. DELAY <= period - 2 x WIDTH. (The program itself also
    // needs DELAY <= period - WIDTH - 5 cycles, which only binds at WIDTH < 5 cycles.)
    {
        const int64_t maxDelay = std::min<int64_t>((int64_t)period - 2 * (int64_t)width,
                                                   pulseMaxDelayCycles((uint32_t)period, width));
        if (maxDelay < 0) {
            return "WIDTH too long for the period: 2 x WIDTH must fit in 1/FREQ";
        }
        if ((int64_t)delay > maxDelay) {
            pulseFormatNs((uint64_t)maxDelay, clk, a, sizeof(a));
            snprintf(why, sizeof(why),
                     "DELAY must leave >= WIDTH before the next pulse pair (DELAY <= 1/FREQ - 2 x WIDTH); max DELAY %s ns", a);
            return why;
        }
    }

    const PulseCycles ch1{(uint32_t)period, 0, width};
    const PulseCycles ch2{(uint32_t)period, delay, width};
    const PulseCycles marker{(uint32_t)markerPeriod, 0, markerWidth};
    if (computePulseCounts(ch1, nullptr) != PulseFit::Ok) {
        return "WIDTH does not fit in the period";
    }
    if (computePulseCounts(ch2, nullptr) != PulseFit::Ok) {
        const int64_t maxDelay = pulseMaxDelayCycles((uint32_t)period, width);
        pulseFormatNs(maxDelay > 0 ? (uint64_t)maxDelay : 0, clk, a, sizeof(a));
        snprintf(why, sizeof(why), "DELAY + WIDTH does not fit in the period; max DELAY %s ns", a);
        return why;
    }
    if (computePulseCounts(marker, nullptr) != PulseFit::Ok) {
        return "MARKERWIDTH does not fit in the marker period";
    }

    // Pixel-reset gate: reset from DELAY + WIDTH + PIXLAG after CH1 (the last laser pulse
    // falls at DELAY + WIDTH in both COMBINE modes) until PIXLEAD before the next CH1.
    if (p.pixGate > 2) {
        return "PIXGATE must be 0 (off), 1 (pixel reset between pulse pairs while ARMED) or 2 (always)";
    }
    const uint64_t pixLead = pulseNsToCycles(p.pixLeadNs, clk);
    const uint64_t pixLag = pulseNsToCycles(p.pixLagNs, clk);
    uint64_t pixStart = 0, pixReset = 0;
    if (p.pixGate) {
        if (pixLead < kPixGateMinLeadCycles) {
            pulseFormatNs(kPixGateMinLeadCycles, clk, a, sizeof(a));
            snprintf(why, sizeof(why), "PIXLEAD realizes below the %lu-cycle minimum (%s ns)",
                     (unsigned long)kPixGateMinLeadCycles, a);
            return why;
        }
        pixStart = (uint64_t)delay + width + pixLag;
        if (pixStart + kPulseMinWidthCycles + pixLead > period) {
            const int64_t maxLag = (int64_t)period - (int64_t)kPulseMinWidthCycles - (int64_t)pixLead -
                                   (int64_t)delay - (int64_t)width;
            if (maxLag < 0) {
                return "PIXLEAD + DELAY + WIDTH leave no time to reset the pixels in 1/FREQ: "
                       "lower PIXLEAD or FREQ";
            }
            pulseFormatNs((uint64_t)maxLag, clk, a, sizeof(a));
            snprintf(why, sizeof(why),
                     "PIXLEAD + DELAY + WIDTH + PIXLAG must leave >= %lu cycles of pixel reset in 1/FREQ; "
                     "max PIXLAG %s ns", (unsigned long)kPulseMinWidthCycles, a);
            return why;
        }
        pixReset = period - pixLead - pixStart;
        if (computePulseCounts(PulseCycles{(uint32_t)period, (uint32_t)pixStart, (uint32_t)pixReset}, nullptr) !=
            PulseFit::Ok) {
            return "pixel-reset gate does not fit in the period";  // unreachable: covered above
        }
    }

    const uint64_t div256 = syncDiv256For(p.syncHz, clk);
    if (div256 < kSyncMinDiv256 || div256 > kSyncMaxDiv256) {
        snprintf(why, sizeof(why), "SYNC out of range (%lu..%lu Hz)",
                 (unsigned long)(((uint64_t)clk * 128u) / (kSyncMaxDiv256 + 1) + 1),
                 (unsigned long)(clk / 2));
        return why;
    }

    rt->clkHz = clk;
    rt->periodCycles = (uint32_t)period;
    rt->widthCycles = width;
    rt->delayCycles = delay;
    rt->markerPeriodCycles = (uint32_t)markerPeriod;
    rt->markerWidthCycles = markerWidth;
    rt->syncDiv256 = (uint32_t)div256;
    rt->combine = p.combine;
    rt->pixGate = p.pixGate;
    rt->pixLeadCycles = (uint32_t)std::min<uint64_t>(pixLead, 0xFFFFFFFFULL);
    rt->pixLagCycles = (uint32_t)std::min<uint64_t>(pixLag, 0xFFFFFFFFULL);
    rt->pixResetStartCycles = (uint32_t)pixStart;
    rt->pixResetCycles = (uint32_t)pixReset;
    return nullptr;
}
