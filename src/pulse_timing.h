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

#include <cstddef>
#include <cstdint>
#include <cstdio>

// ---------------------------------------------------------------- laser limits
// Laser-driver safety limits, enforced on every change and checked against the
// REALIZED cycle counts. CH1 and CH2 share one pulse width, so the tightest
// attached driver governs the MAXIMUM width and the duty:
//
//   PicoLas LDP-V 10-70   : pulse 10 ns - 1 us,   max duty factor 0.1 %   <- governs
//   PicoLas LDP-V 240-100 : pulse 60 ns - >1 us,  max duty cycle  7.5 %
//
// Exceeding a driver's pulse width or duty rating risks the laser diode. Edit
// these if the attached drivers change.
// The minimum width is a performance limit, not a safety one, and is not
// enforced beyond the program's own 3-cycle floor (20 ns at 150 MHz), which
// meets the 10-70's 10 ns minimum. The 240-100's 60 ns minimum is NOT enforced:
// shorter widths only under-drive that driver.
constexpr uint32_t kLaserMaxWidthNs = 1000;
constexpr uint32_t kLaserMaxDutyPpm = 1000;  // 0.1 %
constexpr const char *kLaserLimitSource = "PicoLas LDP-V 10-70";
// COMBINE 1 puts both pulses of a pair on EACH laser output, so each driver sees
// two pulses per period: the duty counts both, and consecutive pulses must be at
// least this far apart (rising edge to rising edge). 10 us = the LDP-V 10-70's
// 100 kHz maximum repetition rate (the 240-100 allows 2 MHz, i.e. 500 ns). In the
// normal split mode each driver sees one pulse per period, and the duty limit
// already keeps that period >= 20 us.
constexpr uint32_t kLaserMinSpacingNs = 10000;

// ---------------------------------------------------------------- parameters
struct PulseParams {
    uint32_t freqHz = 1000;         // pulse-pair repetition frequency
    uint32_t widthNs = 100;         // CH1/CH2 pulse width (inside every attached laser driver's range)
    uint32_t delayNs = 10000;       // CH2-after-CH1 delay (rising edge to rising edge)
    uint32_t markerDiv = 100;       // marker fires once every N pulse pairs
    uint32_t markerWidthNs = 2000;  // marker pulse width
    uint32_t syncHz = 1000000;      // camera sync clock frequency
    uint32_t combine = 0;           // 0: CH1 -> LASER 1, CH2 -> LASER 2. 1: both pulses on BOTH outputs
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
    const uint32_t pulsesPerDriver = p.combine ? 2u : 1u;
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
    // Laser limits on what actually reaches the LDP-V: width_ns = width*1e9/clk,
    // duty = width/period.
    if ((uint64_t)width * 1000000000ULL > (uint64_t)kLaserMaxWidthNs * clk) {
        pulseFormatNs(width, clk, a, sizeof(a));
        snprintf(why, sizeof(why), "laser limit: realized WIDTH %s ns > %lu ns", a,
                 (unsigned long)kLaserMaxWidthNs);
        return why;
    }
    // Duty per driver: with COMBINE each driver carries both pulses of every pair.
    const uint64_t highPpm = (uint64_t)width * pulsesPerDriver * 1000000ULL;
    if (highPpm > (uint64_t)kLaserMaxDutyPpm * period) {
        // Highest FREQ that passes at this WIDTH (the period is rounded, so step down
        // from the continuous bound until the realized check passes).
        uint64_t fmax = (uint64_t)clk * kLaserMaxDutyPpm / highPpm;
        while (fmax > 0 && highPpm > (uint64_t)kLaserMaxDutyPpm * pulseHzToCycles((uint32_t)fmax, clk)) {
            --fmax;
        }
        pulseFormatFixed3(highPpm, period, a, sizeof(a));
        snprintf(why, sizeof(why), "laser limit: duty %s ppm > %lu ppm (max FREQ %lu Hz at this WIDTH%s)", a,
                 (unsigned long)kLaserMaxDutyPpm, (unsigned long)fmax, p.combine ? ", 2 pulses per output" : "");
        return why;
    }
    // Pulse spacing per driver with COMBINE: CH1 -> CH2 is DELAY, CH2 -> next CH1 is
    // period - DELAY; both must be >= kLaserMinSpacingNs. This also keeps the two
    // pulses from ever overlapping on the shared pins.
    if (p.combine) {
        const uint64_t minSpacing = (uint64_t)kLaserMinSpacingNs * clk;  // in cycles x 1e9
        if ((uint64_t)delay * 1000000000ULL < minSpacing) {
            pulseFormatNs(delay, clk, a, sizeof(a));
            snprintf(why, sizeof(why), "laser limit: COMBINE needs DELAY >= %lu ns (realized %s ns)",
                     (unsigned long)kLaserMinSpacingNs, a);
            return why;
        }
        if (delay > period || (uint64_t)(period - delay) * 1000000000ULL < minSpacing) {
            const uint64_t minCyc = (minSpacing + 999999999ULL) / 1000000000ULL;
            pulseFormatNs(period > minCyc ? period - minCyc : 0, clk, a, sizeof(a));
            snprintf(why, sizeof(why), "laser limit: COMBINE needs period - DELAY >= %lu ns; max DELAY %s ns",
                     (unsigned long)kLaserMinSpacingNs, a);
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
    return nullptr;
}
