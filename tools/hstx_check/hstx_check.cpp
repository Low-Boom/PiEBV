// Host check for src/bench/hstx_pattern.h, the pattern math of the HSTX bench test.
//
// 1. DMA mode: decodes every rendered command list the way hstx_bench.cpp sets up the
//    HSTX (command expander: RAW n = n data words follow, RAW_REPEAT n = the next word
//    is used n times; one word = 8 clk_hstx cycles, lowest nibble first; per pin, SEL_P
//    = first half of a cycle, SEL_N = second half) and compares both pins with an
//    independent model of the ideal waveform, step by step. Long repeated stretches are
//    checked run by run (no edge may fall inside one), so 1 Hz periods are covered.
//    Also checks the FIFO load: one pass of the looping list must last >= 16 words, and
//    any 8 consecutive entries, also across the wrap, must cover >= 32 cycles.
// 2. Coupled mode: rebuilds each pin from its P and N lines (first and second half of
//    each clk_sys cycle) and compares it with the ideal waveform, step by step; checks
//    every accept/reject decision against an independent model of the rules.
//
// These checks cover the arithmetic and the list format as the RP2350 HSTX registers
// describe them. Whether the hardware behaves the same is what the bench test measures.
//
// Build and run (any C++17 compiler), from this directory:
//   g++ -std=c++17 -O2 -Wall -Wextra -o hstx_check hstx_check.cpp && ./hstx_check
#include <cstdint>
#include <cstdio>
#include <random>
#include <vector>
#include "../../src/bench/hstx_pattern.h"

namespace {

int g_fail = 0;

void fail(const char *what, const BenchPulses &p) {
    if (g_fail < 10) {
        printf("FAIL %s: period %u width %u delay %u combine %d\n", what, p.periodSteps, p.widthSteps, p.delaySteps,
               (int)p.combine);
    }
    ++g_fail;
}

// ---------------------------------------------------------------- independent model
bool idealPulse(uint64_t s, uint64_t start, uint64_t width) { return s >= start && s < start + width; }
bool idealCh1(const BenchPulses &p, uint64_t s) {
    return idealPulse(s, 0, p.widthSteps) || (p.combine && idealPulse(s, p.delaySteps, p.widthSteps));
}
bool idealCh2(const BenchPulses &p, uint64_t s) {
    return idealPulse(s, p.delaySteps, p.widthSteps) || (p.combine && idealPulse(s, 0, p.widthSteps));
}
bool idealValid(const BenchPulses &p) {
    if (p.periodSteps == 0 || p.periodSteps % 16 != 0 || p.widthSteps == 0) return false;
    if ((uint64_t)p.delaySteps + p.widthSteps > p.periodSteps) return false;
    if (p.combine) {
        // On each pin: CH1 [0, W), gap, CH2 [D, D+W), gap, next period.
        if ((uint64_t)p.delaySteps <= p.widthSteps) return false;
        if ((uint64_t)p.delaySteps + p.widthSteps >= p.periodSteps) return false;
    }
    return true;
}

// ---------------------------------------------------------------- HSTX decode model
struct Segment {
    uint64_t start;    // first step
    uint32_t word;     // data word
    uint32_t repeats;  // consecutive uses of the word
};

// Expander model; returns false on a malformed list.
bool decode(const uint32_t *list, size_t n, std::vector<Segment> *segs, uint64_t *minCyclesPer8) {
    std::vector<uint32_t> cyclesOfEntry(n, 0);  // output cycles each FIFO entry accounts for
    uint64_t step = 0;
    size_t i = 0;
    while (i < n) {
        const uint32_t cmd = list[i] & 0xF000u;
        const uint32_t count = list[i] & 0x0FFFu;
        if ((list[i] & 0xFFFF0000u) != 0 || count == 0) return false;
        ++i;
        if (cmd == kHstxCmdRaw) {
            if (i + count > n) return false;
            for (uint32_t k = 0; k < count; ++k, ++i) {
                segs->push_back(Segment{step, list[i], 1});
                cyclesOfEntry[i] = 8;
                step += 16;
            }
        } else if (cmd == kHstxCmdRawRepeat) {
            if (i >= n) return false;
            segs->push_back(Segment{step, list[i], count});
            cyclesOfEntry[i] = 8ull * count;
            step += 16ull * count;
            ++i;
        } else {
            return false;
        }
    }
    // The DMA loops the list, so a window may wrap (more than once in a short list).
    uint64_t minWin = UINT64_MAX;
    for (size_t a = 0; a < n; ++a) {
        uint64_t c = 0;
        for (size_t b = a; b < a + 8; ++b) c += cyclesOfEntry[b % n];
        if (c < minWin) minWin = c;
    }
    *minCyclesPer8 = minWin;
    return true;
}

// Pin levels of word `w` at step `k` (0..15) of the word, per the bench's BIT config.
bool wordCh2(uint32_t w, uint32_t k) { return (w >> (4 * (k / 2) + (k % 2 ? kDmaBitCh2N : kDmaBitCh2P))) & 1u; }
bool wordCh1(uint32_t w, uint32_t k) { return (w >> (4 * (k / 2) + (k % 2 ? kDmaBitCh1N : kDmaBitCh1P))) & 1u; }

// `start` counts from the list start; the waveform repeats every period.
bool wordMatches(const BenchPulses &p, uint32_t w, uint64_t start) {
    for (uint32_t k = 0; k < 16; ++k) {
        const uint64_t s = (start + k) % p.periodSteps;
        if (wordCh1(w, k) != idealCh1(p, s) || wordCh2(w, k) != idealCh2(p, s)) return false;
    }
    return true;
}

uint64_t g_worstPer8 = UINT64_MAX;

void checkDma(const BenchPulses &p, std::vector<uint32_t> &buf) {
    const bool valid = idealValid(p);
    if ((dmaCheck(p) == nullptr) != valid) {
        fail("dmaCheck decision", p);
        return;
    }
    const size_t n = dmaRender(p, buf.data(), buf.size());
    if (!valid) {
        if (n != 0) fail("rendered an invalid set", p);
        return;
    }
    if (n == 0) {
        fail("render returned 0 (buffer too small?)", p);
        return;
    }
    if (dmaRender(p, nullptr, 0) != n) {
        fail("count-only render differs", p);
        return;
    }
    std::vector<Segment> segs;
    uint64_t per8 = 0;
    if (!decode(buf.data(), n, &segs, &per8)) {
        fail("malformed list", p);
        return;
    }
    if (per8 < g_worstPer8) g_worstPer8 = per8;
    if (per8 < 32) fail("8 FIFO entries cover < 32 cycles", p);
    uint64_t total = 0;
    for (const Segment &s : segs) {
        total += 16ull * s.repeats;
        if (!wordMatches(p, s.word, s.start)) {
            fail("word differs from the ideal waveform", p);
            return;
        }
        if (s.repeats > 1) {
            // A repeated word is only right if no level changes inside the stretch. The
            // check below works inside one period, so a stretch must not cross a period end.
            const uint64_t lo = s.start % p.periodSteps, hi = lo + 16ull * s.repeats;
            if (hi > p.periodSteps) {
                fail("a repeated stretch crosses a period end", p);
                return;
            }
            const uint64_t edges[] = {p.widthSteps, p.delaySteps, (uint64_t)p.delaySteps + p.widthSteps};
            for (uint64_t e : edges) {
                if (e > lo && e < hi && idealCh1(p, e) == idealCh1(p, e - 1) && idealCh2(p, e) == idealCh2(p, e - 1)) {
                    continue;  // not a real level change on either pin
                }
                if (e > lo && e < hi) {
                    fail("an edge falls inside a repeated stretch", p);
                    return;
                }
            }
            if (!wordMatches(p, s.word, hi - 16)) {
                fail("last repeat differs", p);
                return;
            }
        }
    }
    // One pass: the fewest whole periods that last >= 16 words (256 steps).
    uint64_t periods = 1;
    while (periods * p.periodSteps < 256) ++periods;
    if (total != periods * p.periodSteps) fail("list length is not the expected number of periods", p);
}

// ---------------------------------------------------------------- coupled mode
struct Line {
    uint64_t start, width;
};
bool lineFits(const Line &l, uint64_t period) { return l.width >= 3 && l.start + l.width + 5 <= period; }

void checkCoupled(uint32_t C, uint32_t W, uint32_t D, bool combine) {
    const BenchPulses p{2 * C, W, D, combine};
    // Independent model of the four lines.
    const Line c1p{0, (W + 1ull) / 2}, c1n{0, W / 2ull};
    const Line c2p{(D + 1ull) / 2, (D + W + 1ull) / 2 - (D + 1ull) / 2}, c2n{D / 2ull, (D + (uint64_t)W) / 2 - D / 2ull};
    bool valid = lineFits(c1p, C) && lineFits(c1n, C) && lineFits(c2p, C) && lineFits(c2n, C);
    if (combine) {
        valid = valid && c2p.start >= c1p.start + c1p.width + 1 && c2n.start >= c1n.start + c1n.width + 1;
    }
    CoupledPlan plan{};
    const bool accepted = coupledPlan(C, W, D, combine, &plan) == nullptr;
    if (accepted != valid) {
        fail("coupledPlan decision", p);
        return;
    }
    if (!accepted) return;
    auto same = [](const PulseCycles &a, const Line &b, uint32_t period) {
        return a.period == period && a.delay == b.start && a.width == b.width;
    };
    if (!same(plan.ch1p, c1p, C) || !same(plan.ch1n, c1n, C) || !same(plan.ch2p, c2p, C) || !same(plan.ch2n, c2n, C)) {
        fail("coupledPlan lines", p);
        return;
    }
    // Rebuild the pins: cycle k shows the P lines in step 2k and the N lines in step 2k+1.
    // With COMBINE each pin's line is the OR of both channels' lines.
    auto on = [](const PulseCycles &l, uint64_t k) { return k >= l.delay && k < (uint64_t)l.delay + l.width; };
    for (uint64_t k = 0; k < C; ++k) {
        const bool ch1P = on(plan.ch1p, k) || (combine && on(plan.ch2p, k));
        const bool ch1N = on(plan.ch1n, k) || (combine && on(plan.ch2n, k));
        const bool ch2P = on(plan.ch2p, k) || (combine && on(plan.ch1p, k));
        const bool ch2N = on(plan.ch2n, k) || (combine && on(plan.ch1n, k));
        if (ch1P != idealCh1(p, 2 * k) || ch1N != idealCh1(p, 2 * k + 1) || ch2P != idealCh2(p, 2 * k) ||
            ch2N != idealCh2(p, 2 * k + 1)) {
            fail("coupled waveform differs from the ideal", p);
            return;
        }
    }
    // Each line must also be loadable by the pulse program as-is.
    const PulseCycles *lines[] = {&plan.ch1p, &plan.ch1n, &plan.ch2p, &plan.ch2n};
    for (const PulseCycles *l : lines) {
        if (computePulseCounts(*l, nullptr) != PulseFit::Ok) fail("line rejected by computePulseCounts", p);
    }
}

}  // namespace

int main() {
    std::mt19937_64 rng(20261016);
    std::vector<uint32_t> buf(kDmaListCap);

    // DMA mode: every small configuration exhaustively, then random ones up to 1 Hz.
    size_t dmaCases = 0;
    for (uint32_t words = 1; words <= 6; ++words) {
        const uint32_t P = 16 * words;
        for (uint32_t W = 0; W <= P; ++W) {
            for (uint32_t D = 0; D <= P; ++D) {
                for (int cb = 0; cb < 2; ++cb) {
                    checkDma(BenchPulses{P, W, D, cb == 1}, buf);
                    ++dmaCases;
                }
            }
        }
    }
    for (int i = 0; i < 20000; ++i) {
        const uint64_t maxWords = (i % 4 == 0) ? 37500000ull : (i % 4 == 1 ? 20000ull : 300ull);  // 1 Hz at 300 MHz
        const uint32_t P = 16 * (uint32_t)(1 + rng() % maxWords);
        const uint32_t W = (uint32_t)(rng() % 3 == 0 ? 1 + rng() % 40 : 1 + rng() % P);
        const uint32_t D = (uint32_t)(rng() % 3 == 0 ? rng() % 64 : rng() % (P + 1));
        checkDma(BenchPulses{P, W, D, (rng() & 1) != 0}, buf);
        ++dmaCases;
    }
    // List size at 1 Hz (the longest period): must fit kDmaListCap at both clocks.
    for (uint32_t hstxMhz : {150u, 300u}) {
        const uint32_t P = 2u * hstxMhz * 1000000u;  // steps per second
        const BenchPulses worst{P, 30, 3001, false};
        const size_t n = dmaRender(worst, buf.data(), buf.size());
        printf("1 Hz at clk_hstx %u MHz: %zu list entries of %zu\n", hstxMhz, n, kDmaListCap);
        if (n == 0) fail("1 Hz list does not fit", worst);
    }
    printf("dma: %zu configurations, worst 8-entry window %llu cycles\n", dmaCases,
           (unsigned long long)g_worstPer8);

    // Coupled mode: exhaustive small periods, then random.
    size_t coupledCases = 0;
    for (uint32_t C = 1; C <= 40; ++C) {
        for (uint32_t W = 0; W <= 2 * C; ++W) {
            for (uint32_t D = 0; D <= 2 * C; ++D) {
                for (int cb = 0; cb < 2; ++cb) {
                    checkCoupled(C, W, D, cb == 1);
                    ++coupledCases;
                }
            }
        }
    }
    for (int i = 0; i < 20000; ++i) {
        const uint32_t C = 8 + (uint32_t)(rng() % 3000);
        const uint32_t W = (uint32_t)(rng() % (2 * C));
        const uint32_t D = (uint32_t)(rng() % (2 * C));
        checkCoupled(C, W, D, (rng() & 1) != 0);
        ++coupledCases;
    }
    printf("coupled: %zu configurations\n", coupledCases);
    printf("%s (%d failures)\n", g_fail ? "FAILED" : "all checks passed", g_fail);
    return g_fail ? 1 : 0;
}
