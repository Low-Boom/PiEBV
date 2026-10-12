"""The camera sync output is fixed at 1 MHz, independent of pulse settings."""
import os
import subprocess
from fractions import Fraction as F
from math import floor

HARNESS = os.environ.get("PIDG_HARNESS") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "harness.exe" if os.name == "nt" else "harness")


def rnd(x):
    return floor(x + F(1, 2))


def fmt3(x):
    v = rnd(x * 1000)
    return "%d.%03d" % (v // 1000, v % 1000)


clks = [150000000, 125000000, 133000000, 200000000, 48000000]
cases = [(clk, 1000, 100, 10000, 2000) for clk in clks]
inp = "\n".join(" ".join(map(str, c)) for c in cases) + "\n"
out = subprocess.run([HARNESS], input=inp, capture_output=True, text=True).stdout.splitlines()
assert len(out) == len(cases)
bad = 0
for clk, line in zip(clks, out):
    div = rnd(F(clk * 128, 1000000))
    if line.startswith("ERR"):
        bad += 1
        print("unexpected rejection", clk, line)
        continue
    fields = line.split()
    actual = fmt3(F(clk * 128, div))
    if int(fields[19]) != div or fields[20] != actual:
        bad += 1
        print("mismatch", clk, fields[19:21], div, actual)
    if clk == 150000000 and (div != 75 << 8 or actual != "1000000.000"):
        bad += 1
        print("board clock is not an exact 1 MHz divider", div, actual)
print("fixed 1 MHz sync clock rates", len(cases), "bad", bad)
