import os, sys
HARNESS = os.environ.get("PIDG_HARNESS") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "harness.exe" if os.name == "nt" else "harness")
import random, subprocess
from fractions import Fraction as F
from math import floor
random.seed(99)
def rnd(x): return floor(x + F(1, 2))
def fmt3(x):
    v = rnd(x * 1000); return "%d.%03d" % (v // 1000, v % 1000)
cases = []
for clk in (150000000, 125000000, 200000000, 133000000, 300000000):
    for _ in range(600):
        s = random.choice([1, 1000, 1144, 1145, 1146, 50000, 1000000, 999999, 7000000, 37500000, 75000000, 75000001,
                           75200000, 100000000, random.randint(1, 80000000), random.randint(1000, 2000000)])
        cases.append((clk, 1000, 100, 10000, 100, 2000, s))
inp = "\n".join(" ".join(map(str, c)) for c in cases) + "\n"
out = subprocess.run([HARNESS], input=inp, capture_output=True, text=True).stdout.splitlines()
assert len(out) == len(cases)
bad = 0; acc = 0
for c, line in zip(cases, out):
    clk, s = c[0], c[6]
    d = rnd(F(clk * 128, s))
    legal = 256 <= d <= (65535 << 8 | 255)
    if line.startswith("ERR"):
        if legal: bad += 1; print("rejected legal", c, line)
        continue
    acc += 1
    if not legal: bad += 1; print("accepted illegal", c, line); continue
    t = line.split()
    if int(t[19]) != d or t[20] != fmt3(F(clk * 128, d)):
        bad += 1; print("mismatch", c, t[19:], d, fmt3(F(clk * 128, d)))
print("sync cases", len(cases), "accepted", acc, "bad", bad)
