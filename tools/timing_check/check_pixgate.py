"""PIXGATE: the camera pixel-reset gate between pulse pairs.

1. Every accept/reject decision of the real src/pulse_timing.h (through the harness)
   matches an exact-rational model of the gate rules: PIXLEAD >= 5 cycles and
   PIXLEAD + DELAY + WIDTH + PIXLAG + 3 cycles <= 1/FREQ (plus all the ordinary
   rules, in both COMBINE modes). With PIXGATE 0 the lead/lag values are ignored.
2. For every accepted set, CH1, CH2 and the gate state machine run in the PIO model,
   enabled on the same cycle. The gate pin is the INVERTED output latch (GPIO
   OUTOVER), so reset = latch high. Every period, the reset must begin exactly PIXLAG
   after the last laser pulse falls and end exactly PIXLEAD before the next CH1 rise:
   the pixels are free for the whole pulse pair and reset the rest of the period.
   From the start, the pixels are free until the first reset (no reset before the
   first pair).
"""
import os
import random
import subprocess
from fractions import Fraction as F
from math import floor

from pio_model import falls, rises, run

HARNESS = os.environ.get("PIDG_HARNESS") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "harness.exe" if os.name == "nt" else "harness")
random.seed(3700)


def rnd(x):
    return floor(x + F(1, 2))


clks = [150000000, 125000000, 133000000, 200000000]
cases = []
for clk in clks:
    for _ in range(400):
        f = random.choice([1, 10, 100, 1000, 2000, 5000, 10000, 20000, 50000, random.randint(1, 60000)])
        per_ns = 10**9 // f
        w = random.choice([20, 50, 100, 1000, random.randint(0, 5000)])
        d = random.choice([0, 100, w + 7, 10000, random.randint(0, max(1, per_ns // 3))])
        cb = random.choice([0, 0, 1])
        pg = random.choice([0, 1, 1, 2, 3])
        lead = random.choice([0, 20, 33, 34, 40, 1000, 10000, random.randint(0, max(1, per_ns // 4))])
        lag = random.choice([0, 1, 1000, 100000, per_ns - lead - d - w - 25 + random.randint(-12, 12),
                             random.randint(0, max(1, per_ns))])
        cases.append((clk, f, w, max(0, d), 2000, cb, pg, max(0, lead), max(0, lag)))
inp = "".join("%d %d %d %d %d %d %d %d %d %d\n" % c for c in cases)
out = subprocess.run([HARNESS], input=inp, capture_output=True, text=True).stdout.splitlines()
assert len(out) == len(cases), (len(out), len(cases))

nacc = nrej = nsim = ngate = 0
mism = []
for c, line in zip(cases, out):
    clk, f, w, d, mw, cb, pg, lead_ns, lag_ns = c
    P = rnd(F(clk, f))
    W = rnd(F(w * clk, 10**9)); D = rnd(F(d * clk, 10**9)); MW = rnd(F(mw * clk, 10**9))
    L = rnd(F(lead_ns * clk, 10**9)); G = rnd(F(lag_ns * clk, 10**9))
    ok = (1 <= P <= 0xFFFFFFFF and W >= 3 and MW >= 3 and
          (not cb or D >= W + 1) and D + W + 5 <= P and D + 2 * W <= P and MW + 5 <= P and pg <= 2)
    if pg in (1, 2):
        ok = ok and L >= 5 and L + D + W + G + 3 <= P
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
    start, reset = int(t[21]), int(t[22])
    wg = tuple(map(int, t[23:26]))
    if not pg:
        if (start, reset, wg) != (0, 0, (0, 0, 0)):
            mism.append(("gate off but loaded", c, t[21:26]))
        continue
    if (start, reset) != (D + W + G, P - L - (D + W + G)):
        mism.append(("gate cycles", c, (start, reset), (D + W + G, P - L - D - W - G)))
        continue
    ngate += 1
    w1 = tuple(map(int, t[10:13])); w2 = tuple(map(int, t[13:16]))
    K = 3
    until = K * P + 20
    e1, e2, eg = run(w1, until), run(w2, until), run(wg, until)
    ch1r = rises(e1)
    last_fall = falls(e2)  # CH2 falls last (DELAY >= 0, equal widths)
    gr, gf = rises(eg), falls(eg)  # latch: rise = reset asserted, fall = reset released
    good = len(ch1r) >= K and ch1r[:K] == [8 + k * P for k in range(K)]
    for k in range(K - 1):
        good = good and gr[k] == last_fall[k] + G          # reset PIXLAG after the pair
        good = good and gf[k] == ch1r[k + 1] - L           # released PIXLEAD before the next CH1
        good = good and gr[k] > last_fall[k] - 1 and gf[k] <= ch1r[k + 1]
    good = good and (not gr or gr[0] > ch1r[0])            # nothing reset before the first pair
    nsim += 1
    if not good:
        mism.append(("sim", c, ch1r[:3], last_fall[:3], gr[:3], gf[:3]))

print("pixgate: accepted", nacc, "rejected", nrej, "gated", ngate, "simulated", nsim, "mismatches", len(mism))
for m in mism[:10]:
    print(m)

# Boundaries: PIXLEAD = 5 cycles is the minimum; a reset of exactly 3 cycles is the minimum.
P, W, D = 1000, 15, 100
bad = []
for L, G, want in ((5, 0, True), (4, 0, False), (5, P - 5 - D - W - 3, True), (5, P - 5 - D - W - 2, False)):
    ok = L >= 5 and L + D + W + G + 3 <= P
    if ok != want:
        bad.append((L, G))
    if ok:
        start, reset = D + W + G, P - L - (D + W + G)
        eg = run((start, reset - 3, P - (start + reset - 3 + 8)), 3 * P)
        if falls(eg)[0] != 8 + P - L or rises(eg)[0] != 8 + start:
            bad.append(("edges", L, G, rises(eg)[:2], falls(eg)[:2]))
print("boundary PIXLEAD >= 5 cycles, reset >= 3 cycles:", "ok" if not bad else bad)
