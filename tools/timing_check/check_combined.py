"""COMBINE 1: both laser outputs carry CH1's pulse and CH2's pulse.

1. Every accept/reject decision of the real src/pulse_timing.h (through the harness)
   matches an exact-rational model of the COMBINE rules: DELAY >= WIDTH + 1 cycle
   (the pulses must not touch) and DELAY + WIDTH fits in the period. No driver limits.
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
random.seed(4242)


def rnd(x):
    return floor(x + F(1, 2))


clks = [150000000, 125000000, 133000000, 200000000, 48000000]
cases = []
for clk in clks:
    for _ in range(300):
        f = random.choice([1, 10, 100, 1000, 2000, 5000, 9999, 10000, 20000, 25000, 49999, 50000, 60000,
                           random.randint(1, 60000)])
        w = random.choice([17, 20, 50, 100, 500, 1000, 1004, 5000, 20000, random.randint(0, 1100), random.randint(1000, 60000)])
        P = rnd(F(clk, f))
        per_ns = int(P * F(10**9, clk))
        wn = int(rnd(F(w * clk, 10**9)) * F(10**9, clk))  # realized width in ns (approx.)
        d = random.choice([0, 100, w, w + 1, w + 3, w + 7, w + 10, wn + random.randint(-8, 12), 10000, per_ns // 2,
                           per_ns - w - 40 + random.randint(-15, 15), random.randint(0, max(1, per_ns))])
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
          D >= W + 1 and
          D + W + 5 <= P and D + 2 * W <= P and MW + 5 <= Pm)
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
    r = [x for x in rises(pins[0]) if x < until]  # same window as the expectation below
    fl = falls(pins[0])
    expect_r = sorted([8 + k * P for k in range(K + 2)] + [8 + k * P + D for k in range(K + 2)])
    expect_r = [x for x in expect_r if x < until]
    good = good and r == expect_r and len(r) >= 2 * K
    good = good and all(b - a == W for a, b in zip(r, fl))
    nsim += 1
    if not good:
        mism.append(("sim", c, r[:6], fl[:6]))

print("combined: accepted", nacc, "rejected", nrej, "simulated", nsim, "mismatches", len(mism))
for m in mism[:10]:
    print(m)

# Boundary: why COMBINE needs DELAY >= WIDTH + 1 cycle. At DELAY == WIDTH, CH2 rises on
# the very cycle CH1 falls, and the higher-numbered SM (CH2) wins the shared latch, so
# the two pulses fuse into ONE pulse of 2 x WIDTH. One cycle later there is a 1-cycle gap.
P = 1000
bad = []
for W in (3, 15, 150):
    for D, want_pulses in ((W, 1), (W + 1, 2)):
        w1, w2 = (0, W - 3, P - (W - 3) - 8), (D, W - 3, P - D - (W - 3) - 8)
        pins = block_pins([run_writes(w1, P, PROG_DUAL), run_writes(w2, P, PROG_DUAL)], 2)
        n = len([x for x in rises(pins[0]) if x < P])
        widths = [b - a for a, b in zip(rises(pins[0]), falls(pins[0]))][:n]
        if n != want_pulses or (n == 1 and widths != [2 * W]) or (n == 2 and widths != [W, W]):
            bad.append((W, D, n, widths))
print("boundary DELAY=WIDTH merges, DELAY=WIDTH+1 cycle separates:", "ok" if not bad else bad)
