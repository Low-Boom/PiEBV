"""The marker fires with every pulse pair: in the PIO model it rises on exactly the
same cycle as every CH1 rise, stays high for MARKERWIDTH, and never drifts, for
frequencies whose period is not a whole number of cycles. Also the fit boundary:
MARKERWIDTH <= 1/FREQ - 5 cycles, and the rejection names the largest width that fits.
"""
import os
import subprocess

from pio_model import falls, rises, run

HARNESS = os.environ.get("PIDG_HARNESS") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "harness.exe" if os.name == "nt" else "harness")

cases = []
for clk in (150000000, 133000000, 125000000, 200000000, 150000001):
    for f in (3000, 7000, 999, 1234, 1001, 50000, 1):
        for mw in (20, 500, 2000, 9000):
            cases.append((clk, f, 100, 10000 if f < 50000 else 1000, mw))
inp = "\n".join(" ".join(map(str, c)) for c in cases) + "\n"
out = subprocess.run([HARNESS], input=inp, capture_output=True, text=True).stdout.splitlines()
assert len(out) == len(cases)
nok = nrej = 0
for c, line in zip(cases, out):
    if line.startswith("ERR"):
        nrej += 1
        assert "MARKERWIDTH" in line, (c, line)  # the only rejection these cases can hit
        continue
    t = line.split()
    P, W, D, Pm, MW = map(int, t[1:6])
    assert Pm == P, (c, Pm, P)
    w1 = tuple(map(int, t[10:13])); w2 = tuple(map(int, t[13:16])); w3 = tuple(map(int, t[16:19]))
    K = 3 if P > 10**7 else 6
    horizon = K * P + 20
    e1, e3 = run(w1, horizon), run(w3, horizon)
    r1, r2, r3 = rises(e1), rises(run(w2, horizon)), rises(e3)
    assert len(r3) >= K and r3 == r1, (c, r1[:3], r3[:3])          # rises with every CH1
    assert all(fl - r == MW for r, fl in zip(r3, falls(e3))), c    # MARKERWIDTH high
    assert all(b - a == D for a, b in zip(r1, r2)), c
    nok += 1
print("marker rises with every CH1 and CH2-CH1 = DELAY for", nok, "configs;", nrej, "rejected (MARKERWIDTH too long)")

# Boundary: the marker must fit in the period, MARKERWIDTH <= period - 5 cycles.
# 100 kHz at 150 MHz: period 1500 cycles. 9966 ns -> 1495 cycles (fits), 9973 ns -> 1496 (does not).
lines = subprocess.run([HARNESS], input="150000000 100000 100 1000 9966\n150000000 100000 100 1000 9973\n",
                       capture_output=True, text=True).stdout.splitlines()
ok = lines[0].startswith("OK") and lines[1].startswith("ERR") and "max MARKERWIDTH 9966.667 ns" in lines[1]
print("boundary MARKERWIDTH <= 1/FREQ - 5 cycles:", "ok" if ok else lines)
