"""COMBINE 1: both laser outputs carry CH1's pulse and CH2's pulse.

1. Every accept/reject decision of the real src/pulse_timing.h (through the harness)
   matches an exact-rational model of the COMBINE limits: duty counts 2 pulses per
   period, and DELAY and period - DELAY are each >= kLaserMinSpacingNs (10 us).
2. For every accepted set, CH1 and CH2 run the dual-pin program (SET PINS,3) in the
   PIO model on the shared latch of the two laser pins, and BOTH pins show, every
   period: a pulse of WIDTH at CH1's rise, a pulse of WIDTH exactly DELAY later, and
   nothing else.
"""
import os
import random
import subprocess
from fractions import Fraction as F
from math import floor

from pio_model import PROG_DUAL, block_pins, falls, rises, run_writes

HARNESS = os.environ.get("PIDG_HARNESS") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "harness.exe" if os.name == "nt" else "harness")
MIN_SPACING_NS = 10000
random.seed(4242)


def rnd(x):
    return floor(x + F(1, 2))


clks = [150000000, 125000000, 133000000, 200000000, 48000000]
cases = []
for clk in clks:
    for _ in range(300):
        f = random.choice([1, 10, 100, 1000, 2000, 5000, 9999, 10000, 20000, 25000, 49999, 50000, 60000,
                           random.randint(1, 60000)])
        w = random.choice([17, 20, 50, 100, 500, 1000, 1003, 1004, random.randint(0, 1100)])
        P = rnd(F(clk, f))
        per_ns = int(P * F(10**9, clk))
        d = random.choice([0, 100, 9990, 9999, 10000, 10001, 10010, 20000, per_ns // 2,
                           per_ns - 10000 + random.randint(-15, 15), random.randint(0, max(1, per_ns))])
        cases.append((clk, f, w, max(0, d), 100 if f >= 4 else 1, 2000))
inp = "".join("%d %d %d %d %d %d 1000000 1\n" % c for c in cases)
out = subprocess.run([HARNESS], input=inp, capture_output=True, text=True).stdout.splitlines()
assert len(out) == len(cases), (len(out), len(cases))

nacc = nrej = nsim = 0
mism = []
for c, line in zip(cases, out):
    clk, f, w, d, md, mw = c
    P = rnd(F(clk, f)); Pm = P * md
    W = rnd(F(w * clk, 10**9)); D = rnd(F(d * clk, 10**9)); MW = rnd(F(mw * clk, 10**9))
    ok = (1 <= P <= 0xFFFFFFFF and Pm <= 0xFFFFFFFF and W >= 3 and MW >= 3 and
          F(W * 10**9, clk) <= 1000 and F(2 * W, P) <= F(1, 1000) and
          F(D * 10**9, clk) >= MIN_SPACING_NS and D <= P and F((P - D) * 10**9, clk) >= MIN_SPACING_NS and
          D + W + 5 <= P and MW + 5 <= Pm)
    if line.startswith("ERR"):
        nrej += 1
        if ok:
            mism.append(("rejected but legal", c, line))
        continue
    nacc += 1
    if not ok:
        mism.append(("accepted but illegal", c, line))
        continue
    t = line.split()
    if list(map(int, t[1:4])) != [P, W, D]:
        mism.append(("cycles", c, t[1:4]))
        continue
    w1 = tuple(map(int, t[10:13])); w2 = tuple(map(int, t[13:16]))
    K = 3
    until = K * P + D + 20
    pins = block_pins([run_writes(w1, until, PROG_DUAL), run_writes(w2, until, PROG_DUAL)], 2)
    good = pins[0] == pins[1]  # both laser outputs identical
    r, fl = rises(pins[0]), falls(pins[0])
    expect_r = sorted([8 + k * P for k in range(K + 1)] + [8 + k * P + D for k in range(K + 1)])
    expect_r = [x for x in expect_r if x < until]
    good = good and r == expect_r[:len(r)] and len(r) >= 2 * K
    good = good and all(b - a == W for a, b in zip(r, fl))
    nsim += 1
    if not good:
        mism.append(("sim", c, r[:6], fl[:6]))

print("combined: accepted", nacc, "rejected", nrej, "simulated", nsim, "mismatches", len(mism))
for m in mism[:10]:
    print(m)
