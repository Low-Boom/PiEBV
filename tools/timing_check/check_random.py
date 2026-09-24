import os, sys
HARNESS = os.environ.get("PIDG_HARNESS") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "harness.exe" if os.name == "nt" else "harness")
import random, subprocess
from fractions import Fraction as F
from math import floor
from pio_model import run, rises, falls
random.seed(12345)
def rnd(x): return floor(x + F(1, 2))
def fmt3(x):  # exact half-up to 3 decimals
    v = rnd(x * 1000); return "%d.%03d" % (v // 1000, v % 1000)
clks = [150000000, 125000000, 133000000, 200000000, 150000001, 48000000, 300000000, 250000000, 99999999]
cases = []
for clk in clks:
    for _ in range(400):
        f = random.choice([1, 2, 3, 7, 10, 999, 1000, 1001, 1234, 3000, 7000, 9999, 20000, 50000, 99999, 150000,
                           random.randint(1, 60000), random.randint(1, 3000000)])
        w = random.choice([0, 1, 6, 7, 10, 13, 14, 16, 17, 19, 20, 21, 23, 24, 26, 27, 1000, 1003, 1004, 1010,
                           random.randint(0, 1100)])
        P = rnd(F(clk, f))
        d = random.choice([0, 1, 3, 4, 6, 7, 10, 13, 14, 20, 10000, random.randint(0, 2*10**6),
                           max(0, int((P - rnd(F(w*clk, 10**9)) - 5) * F(10**9, clk)) + random.randint(-20, 20))])
        md = random.choice([1, 2, 3, 7, 100, 300, random.randint(1, 30000)])
        mw = random.choice([0, 13, 20, 2000, random.randint(0, 50000)])
        cases.append((clk, f, w, d, md, mw))
inp = "\n".join(" ".join(map(str, c)) for c in cases) + "\n"
out = subprocess.run([HARNESS], input=inp, capture_output=True, text=True).stdout.splitlines()
assert len(out) == len(cases)
nacc = nrej = nsim = 0; mism = []
for c, line in zip(cases, out):
    clk, f, w, d, md, mw = c
    P = rnd(F(clk, f)); Pm = P * md
    W = rnd(F(w * clk, 10**9)); D = rnd(F(d * clk, 10**9)); MW = rnd(F(mw * clk, 10**9))
    ok = (1 <= P <= 0xFFFFFFFF and Pm <= 0xFFFFFFFF and W >= 3 and MW >= 3 and
          F(W * 10**9, clk) <= 1000 and F(W, P) <= F(1, 1000) and D + W + 5 <= P and MW + 5 <= Pm)
    if line.startswith("ERR"):
        nrej += 1
        if ok: mism.append(("rejected but legal", c, line))
        continue
    nacc += 1
    if not ok: mism.append(("accepted but illegal", c, line)); continue
    t = line.split()
    got = list(map(int, t[1:6]))
    if got != [P, W, D, Pm, MW]: mism.append(("cycles", c, got, [P, W, D, Pm, MW])); continue
    if t[6:10] != [fmt3(F(clk, P)), fmt3(F(W * 10**9, clk)), fmt3(F(D * 10**9, clk)), fmt3(F(MW * 10**9, clk))]:
        mism.append(("format", c, t[6:10])); continue
    w1 = tuple(map(int, t[10:13])); w2 = tuple(map(int, t[13:16])); w3 = tuple(map(int, t[16:19]))
    # simulate: CH1, CH2 for 4 periods, marker for 3 marker periods (only if cheap)
    K = 4
    e1 = run(w1, K * P + D + 20); e2 = run(w2, K * P + D + 20)
    r1, r2 = rises(e1), rises(e2)
    good = (r1[0] == 8 and all(b - a == P for a, b in zip(r1, r1[1:])) and
            all(y - x == D for x, y in zip(r1, r2)) and
            all(fl - r == W for r, fl in zip(r1, falls(e1))) and all(fl - r == W for r, fl in zip(r2, falls(e2))) and
            all(b - a == P for a, b in zip(r2, r2[1:])))
    if Pm < 2**31:
        e3 = run(w3, 3 * Pm + 20); r3 = rises(e3)
        good = good and r3[0] == 8 and all(b - a == Pm for a, b in zip(r3, r3[1:])) and \
               all(fl - r == MW for r, fl in zip(r3, falls(e3)))
    nsim += 1
    if not good: mism.append(("sim", c, r1[:3], r2[:3]))
print("accepted", nacc, "rejected", nrej, "simulated", nsim, "mismatches", len(mism))
for m in mism[:10]: print(m)
