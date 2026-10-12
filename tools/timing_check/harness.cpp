// Host harness for the REAL firmware timing header (src/pulse_timing.h).
// Reads "clk freq width delay mwidth [combine [pixgate pixlead pixlag]]" lines,
// prints the realized cycles, formatted values and FIFO words in the format
// check_random.py, check_marker_lock.py, check_sync.py, check_combined.py and
// check_pixgate.py expect. The pixel-reset gate fields are appended at the end:
// pixResetStart pixReset gateDelay gateWidth gateTail (all 0 while PIXGATE is 0).
// The fourth output column is the marker period, which is always the pulse period (the
// marker fires with every pulse pair); it is kept so the column layout stays the same.
#include <cstdio>
#include <cstdint>
#include "../../src/pulse_timing.h"

int main() {
    char line[256];
    while (fgets(line, sizeof line, stdin)) {
        unsigned long clk, f, w, d, mw, cb = 0, pg = 0, pl = 10000, pa = 100000;
        int n = sscanf(line, "%lu %lu %lu %lu %lu %lu %lu %lu %lu", &clk, &f, &w, &d, &mw, &cb, &pg, &pl, &pa);
        if (n < 5) continue;
        PulseParams p;
        p.freqHz = (uint32_t)f; p.widthNs = (uint32_t)w; p.delayNs = (uint32_t)d;
        p.markerWidthNs = (uint32_t)mw;
        p.combine = (uint32_t)cb;
        p.pixGate = (uint32_t)pg; p.pixLeadNs = (uint32_t)pl; p.pixLagNs = (uint32_t)pa;
        RealizedTiming rt;
        const char *why = realizeTiming(p, (uint32_t)clk, &rt);
        if (why) { printf("ERR %s\n", why); continue; }
        char a[32], b[32], c[32], e[32], s[32];
        pulseFormatHz(rt.periodCycles, rt.clkHz, a, sizeof a);
        pulseFormatNs(rt.widthCycles, rt.clkHz, b, sizeof b);
        pulseFormatNs(rt.delayCycles, rt.clkHz, c, sizeof c);
        pulseFormatNs(rt.markerWidthCycles, rt.clkHz, e, sizeof e);
        syncFormatHz(rt.syncDiv256, rt.clkHz, s, sizeof s);
        PulseWords w1, w2, w3, wg{0, 0, 0};
        computePulseCounts(PulseCycles{rt.periodCycles, 0, rt.widthCycles}, &w1);
        computePulseCounts(PulseCycles{rt.periodCycles, rt.delayCycles, rt.widthCycles}, &w2);
        computePulseCounts(PulseCycles{rt.periodCycles, 0, rt.markerWidthCycles}, &w3);  // as main.cpp
        if (rt.pixGate) {
            computePulseCounts(PulseCycles{rt.periodCycles, rt.pixResetStartCycles, rt.pixResetCycles}, &wg);
        }
        printf("OK %u %u %u %u %u %s %s %s %s %u %u %u %u %u %u %u %u %u %u %s %u %u %u %u %u\n", rt.periodCycles,
               rt.widthCycles, rt.delayCycles, rt.periodCycles, rt.markerWidthCycles, a, b, c, e, w1.delay,
               w1.width, w1.tail, w2.delay, w2.width, w2.tail, w3.delay, w3.width, w3.tail, rt.syncDiv256, s,
               rt.pixResetStartCycles, rt.pixResetCycles, wg.delay, wg.width, wg.tail);
    }
}
