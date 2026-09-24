import os, sys
HARNESS = os.environ.get("PIDG_HARNESS") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "harness.exe" if os.name == "nt" else "harness")
import subprocess
from pio_model import run, rises, falls
cases = []
for clk in (150000000, 133000000, 125000000, 200000000, 150000001):
    for f in (3000, 7000, 999, 1234, 1001, 50000, 1):
        for md in (2, 3, 7, 100):
            cases.append((clk, f, 100, 10000 if f < 50000 else 1000, md, 2000))
inp = "\n".join(" ".join(map(str, c)) for c in cases) + "\n"
out = subprocess.run([HARNESS], input=inp, capture_output=True, text=True).stdout.splitlines()
nok = 0
for c, line in zip(cases, out):
    if line.startswith("ERR"): print("rej", c, line); continue
    t = line.split(); P, W, D, Pm, MW = map(int, t[1:6])
    w1 = tuple(map(int, t[10:13])); w2 = tuple(map(int, t[13:16])); w3 = tuple(map(int, t[16:19]))
    K = 3 if Pm > 10**8 else 5
    horizon = K * Pm + 20
    r1 = rises(run(w1, horizon)); r2 = rises(run(w2, horizon)); r3 = rises(run(w3, horizon))
    md = c[4]
    assert all(r3[k] == r1[k * md] for k in range(len(r3)) if k * md < len(r1)), (c, r3[:3], [r1[k*md] for k in range(3)])
    assert all(b - a == D for a, b in zip(r1, r2))
    nok += 1
print("marker phase-lock and CH2-CH1 verified for", nok, "configs over", "3-5 marker periods")
