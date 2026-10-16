#pragma once
// HSTX bench test (hstx_bench.cpp): the pattern math, with no hardware access, so
// tools/hstx_check can test it on a host.
//
// The RP2350 HSTX drives each of its pins (GP12..GP19 = HSTX outputs 0..7) with two
// bits per clk_hstx cycle: BITx.SEL_P selects the bit for the first half of the
// cycle, SEL_N for the second half. One STEP below is half a clk_hstx cycle:
// 3.333 ns at 150 MHz, 1.667 ns at 300 MHz.
//
// Laser outputs: CH2 = GP12 = HSTX output 0, CH1 = GP13 = HSTX output 1 (board.h).
// CH1 rises at step 0 of every period, CH2 DELAY steps later; both last WIDTH steps.
// COMBINE puts both pulses on both pins.
//
// Two ways to feed the pins:
//  - DMA mode: DMA streams a command list for the HSTX command expander that holds one
//    or more whole periods of both waveforms (dmaRender()). clk_hstx may come from pll_sys, so the
//    HSTX can run faster than clk_sys.
//  - Coupled mode: four PIO state machines run the PiDG pulse program in whole
//    clk_sys cycles, one "line" per pin and half cycle (coupledPlan()). HSTX coupled
//    mode puts the P line on the pin in the first half of each cycle and the N line in
//    the second half. clk_hstx must then be clk_sys.

#include <cstddef>
#include <cstdint>
#include "../pulse_timing.h"

// ---------------------------------------------------------------- DMA mode
// Command expander words: the command in bits 15:12, a count in bits 11:0 (the values
// pico-examples hstx/dvi_out_hstx_encoder uses).
constexpr uint32_t kHstxCmdRaw = 0x0u << 12;        // the next COUNT FIFO words are data
constexpr uint32_t kHstxCmdRawRepeat = 0x1u << 12;  // the next FIFO word is data, used COUNT times
constexpr uint32_t kHstxCmdMaxCount = 0xFFFu;

// Data word layout (CSR SHIFT 4, N_SHIFTS 8; EXPAND_SHIFT RAW_N_SHIFTS 1, RAW_SHIFT 0):
// one word lasts 8 clk_hstx cycles = 16 steps. The shifter rotates right by 4 bits each
// cycle, so cycle c of a word outputs nibble c (bits 4c+3..4c), lowest nibble first.
// Within a nibble:
constexpr uint32_t kDmaBitCh2P = 0;  // CH2 (GP12), first half of the cycle
constexpr uint32_t kDmaBitCh2N = 1;  // CH2, second half
constexpr uint32_t kDmaBitCh1P = 2;  // CH1 (GP13), first half
constexpr uint32_t kDmaBitCh1N = 3;  // CH1, second half
constexpr uint32_t kDmaCyclesPerWord = 8;
constexpr uint32_t kDmaStepsPerWord = 2 * kDmaCyclesPerWord;  // 16

// Command-list buffer of the bench (80 KB). One period at 1 Hz needs about 9,200
// entries at clk_hstx 150 MHz and 18,400 at 300 MHz (tools/hstx_check prints them).
constexpr size_t kDmaListCap = 20480;

// One pass of the list lasts >= 16 words (128 clk_hstx cycles; 64 clk_sys cycles at
// HSTXCLK 300). Each wrap costs a control-channel transfer and two chain hops while
// the FIFO keeps the output going, so a period shorter than this is put in the list
// several times (dmaPasses()).
constexpr uint32_t kDmaMinListWords = 16;

struct BenchPulses {
    uint32_t periodSteps;  // DMA mode: a whole number of words
    uint32_t widthSteps;
    uint32_t delaySteps;   // CH2 rising edge after CH1's
    bool combine;          // both pulses on both pins
};

inline bool benchInPulse(uint32_t step, uint32_t start, uint32_t width) {
    return step >= start && step - start < width;
}

// Pin levels at `step` (0 <= step < period).
inline bool benchCh1High(const BenchPulses &p, uint32_t step) {
    return benchInPulse(step, 0, p.widthSteps) || (p.combine && benchInPulse(step, p.delaySteps, p.widthSteps));
}
inline bool benchCh2High(const BenchPulses &p, uint32_t step) {
    return benchInPulse(step, p.delaySteps, p.widthSteps) || (p.combine && benchInPulse(step, 0, p.widthSteps));
}

// Returns nullptr if DMA mode can produce `p`, else the reason.
inline const char *dmaCheck(const BenchPulses &p) {
    if (p.periodSteps == 0 || p.periodSteps % kDmaStepsPerWord != 0) {
        return "the period must be a whole number of 16-step words";
    }
    if (p.widthSteps == 0) {
        return "WIDTH must be >= 1 step";
    }
    if ((uint64_t)p.delaySteps + p.widthSteps > p.periodSteps) {
        return "DELAY + WIDTH must fit in the period";
    }
    // COMBINE: a gap of >= 1 step between the two pulses, and before the next period's
    // CH1 pulse, or they merge into one on each pin.
    if (p.combine && ((uint64_t)p.delaySteps < (uint64_t)p.widthSteps + 1 ||
                      (uint64_t)p.delaySteps + p.widthSteps + 1 > p.periodSteps)) {
        return "COMBINE needs a gap of >= 1 step: WIDTH + 1 <= DELAY <= period - WIDTH - 1";
    }
    return nullptr;
}

// Data word number `idx` of the period (both pins, 16 steps).
inline uint32_t dmaWord(const BenchPulses &p, uint32_t idx) {
    uint32_t v = 0;
    for (uint32_t c = 0; c < kDmaCyclesPerWord; ++c) {
        const uint32_t s = idx * kDmaStepsPerWord + 2 * c;
        v |= (uint32_t)benchCh2High(p, s) << (4 * c + kDmaBitCh2P) |
             (uint32_t)benchCh2High(p, s + 1) << (4 * c + kDmaBitCh2N) |
             (uint32_t)benchCh1High(p, s) << (4 * c + kDmaBitCh1P) |
             (uint32_t)benchCh1High(p, s + 1) << (4 * c + kDmaBitCh1N);
    }
    return v;
}

// The steps where a level can change inside a period (the period start is step 0).
inline void dmaEdges(const BenchPulses &p, uint32_t edges[3]) {
    edges[0] = p.widthSteps;
    edges[1] = p.delaySteps;
    edges[2] = p.delaySteps + p.widthSteps;
}

// True if no level changes strictly inside word number `idx` (a change at its first step is fine).
inline bool dmaWordUniform(const BenchPulses &p, uint32_t idx) {
    uint32_t edges[3];
    dmaEdges(p, edges);
    const uint32_t lo = idx * kDmaStepsPerWord;
    for (uint32_t e : edges) {
        if (e > lo && e < lo + kDmaStepsPerWord) {
            return false;
        }
    }
    return true;
}

// For a uniform word: the index of the first later word whose level may differ (the
// word that holds the next edge), at most nWords. Every word in between is identical.
inline uint32_t dmaRunEnd(const BenchPulses &p, uint32_t idx, uint32_t nWords) {
    uint32_t edges[3];
    dmaEdges(p, edges);
    const uint32_t lo = idx * kDmaStepsPerWord;
    uint32_t end = nWords;
    for (uint32_t e : edges) {
        if (e > lo && e / kDmaStepsPerWord < end) {
            end = e / kDmaStepsPerWord;
        }
    }
    return end;
}

// Periods in one pass of the list: the fewest that last >= kDmaMinListWords words.
// Needs a valid `p` (dmaCheck()).
inline uint32_t dmaPasses(const BenchPulses &p) {
    const uint32_t nWords = p.periodSteps / kDmaStepsPerWord;
    return (kDmaMinListWords + nWords - 1) / nWords;
}

// Renders dmaPasses() periods as one command list. A constant stretch of >= 2 words
// becomes RAW_REPEAT commands (2 FIFO entries for up to 4095 words); words that hold
// an edge, and constant stretches of 1 word, go out as RAW data (1 entry per word,
// plus 1 per RAW command; a RAW command runs on across a period boundary). So every
// 2 entries cover >= 1 word (8 clk_hstx cycles), which keeps the DMA far ahead of the
// HSTX. Returns the number of entries, or 0 if `p` is invalid or the list needs more
// than `cap` entries. With out == nullptr nothing is written and `cap` is ignored:
// the result is the number of entries the list needs.
inline size_t dmaRender(const BenchPulses &p, uint32_t *out, size_t cap) {
    if (dmaCheck(p)) {
        return 0;
    }
    if (!out) {
        cap = 0;
    }
    const uint32_t nWords = p.periodSteps / kDmaStepsPerWord;
    size_t n = 0;
    auto put = [&](uint32_t v) {
        if (n < cap) {
            out[n] = v;
        }
        ++n;
    };
    size_t rawAt = 0;       // entry index of the open RAW command
    uint32_t rawCount = 0;  // data words after it so far; 0 = no RAW command open
    for (uint32_t pass = dmaPasses(p); pass > 0; --pass) {
        uint32_t w = 0;
        while (w < nWords) {
            uint32_t run = dmaWordUniform(p, w) ? dmaRunEnd(p, w, nWords) - w : 1;
            if (run >= 2) {
                rawCount = 0;
                const uint32_t v = dmaWord(p, w);
                while (run > 0) {
                    const uint32_t k = run < kHstxCmdMaxCount ? run : kHstxCmdMaxCount;
                    put(kHstxCmdRawRepeat | k);
                    put(v);
                    run -= k;
                    w += k;
                }
            } else {
                if (rawCount == 0 || rawCount == kHstxCmdMaxCount) {
                    rawAt = n;
                    rawCount = 0;
                    put(kHstxCmdRaw);
                }
                put(dmaWord(p, w));
                ++rawCount;
                if (rawAt < cap) {
                    out[rawAt] = kHstxCmdRaw | rawCount;
                }
                ++w;
            }
        }
    }
    return (!out || n <= cap) ? n : 0;
}

// ---------------------------------------------------------------- coupled mode
// A pin is high over steps [s, s + w). In clk_sys cycle k it shows the P line in the
// first half (step 2k) and the N line in the second half (step 2k + 1), so:
//   P line high in cycle k  <=>  s <= 2k < s + w      <=>  ceil(s/2)  <= k < ceil((s+w)/2)
//   N line high in cycle k  <=>  s <= 2k + 1 < s + w  <=>  floor(s/2) <= k < floor((s+w)/2)
// Each line is an ordinary PiDG pulse (PulseCycles, whole cycles).
struct DdrLines {
    PulseCycles p;
    PulseCycles n;
};

inline DdrLines ddrSplit(uint32_t periodCycles, uint32_t startSteps, uint32_t widthSteps) {
    const uint64_t s = startSteps;
    const uint64_t e = s + widthSteps;
    DdrLines l;
    l.p = PulseCycles{periodCycles, (uint32_t)((s + 1) / 2), (uint32_t)((e + 1) / 2 - (s + 1) / 2)};
    l.n = PulseCycles{periodCycles, (uint32_t)(s / 2), (uint32_t)(e / 2 - s / 2)};
    return l;
}

struct CoupledPlan {
    PulseCycles ch1p, ch1n, ch2p, ch2n;
};

// Splits the pulse pair into the four lines and checks that the pulse program can make
// each: >= kPulseMinWidthCycles high (so WIDTH >= 6 steps) and fitting in the period.
// With COMBINE each line carries both pulses through the shared PIO output, where the
// last write wins, so CH2's line must rise >= 1 cycle after CH1's falls (as in the
// firmware's COMBINE rule). Returns nullptr and fills *out, or the reason.
inline const char *coupledPlan(uint32_t periodCycles, uint32_t widthSteps, uint32_t delaySteps, bool combine,
                               CoupledPlan *out) {
    if (periodCycles == 0) {
        return "FREQ out of range";
    }
    const DdrLines ch1 = ddrSplit(periodCycles, 0, widthSteps);
    const DdrLines ch2 = ddrSplit(periodCycles, delaySteps, widthSteps);
    const PulseCycles *lines[] = {&ch1.p, &ch1.n, &ch2.p, &ch2.n};
    for (const PulseCycles *l : lines) {
        if (computePulseCounts(*l, nullptr) != PulseFit::Ok) {
            return "each half-cycle line needs >= 3 cycles high and must fit in the period "
                   "(WIDTH >= 6 steps; DELAY + WIDTH <= 2 x period - 10 steps)";
        }
    }
    if (combine && (ch2.p.delay < ch1.p.delay + ch1.p.width + 1 || ch2.n.delay < ch1.n.delay + ch1.n.width + 1)) {
        return "COMBINE needs a gap of >= 1 cycle on each half-cycle line (about DELAY >= WIDTH + 2 steps)";
    }
    if (out) {
        *out = CoupledPlan{ch1.p, ch1.n, ch2.p, ch2.n};
    }
    return nullptr;
}
