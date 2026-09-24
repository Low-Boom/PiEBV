import random, itertools
from pio_model import *
random.seed(7)
# 1) fast-forward == pure per-cycle
for _ in range(500):
    w = (random.randint(0,40), random.randint(0,40), random.randint(0,40))
    P = sum(w) + 8
    a = run(w, 6*P + 50, fast=False); b = run(w, 6*P + 50, fast=True)
    assert a == b, (w, a, b)
    # also check offset independence
    assert run(w, 6*P+50, offset=0, fast=False) == a
print("fast==slow, offset-independent: ok")
# 2) exhaustive small configs with FIXED math: CH1 (D=0), CH2 (D), marker (D=0, period P*M)
bad = 0; n = 0
for P in range(8, 48):
    for W in range(0, P + 2):
        w1 = fixed_words(P, 0, W)
        for D in range(0, P + 2):
            w2 = fixed_words(P, D, W)
            if w1 is None or w2 is None:
                # verify rejection is only when it truly cannot fit: D+W+5>P or W<3
                assert (W < 3) or (D + W + 5 > P) or (w1 is None and W + 5 > P), (P, D, W)
                continue
            K = 5
            e1 = run(w1, K*P + D + 20); e2 = run(w2, K*P + D + 20)
            r1, f1, r2, f2 = rises(e1), falls(e1), rises(e2), falls(e2)
            n += 1
            ok = (r1[0] == 8 and all(r1[i+1]-r1[i] == P for i in range(len(r1)-1)) and
                  all(r2[i]-r1[i] == D for i in range(min(len(r1), len(r2)))) and
                  all(f1[i]-r1[i] == W for i in range(len(f1))) and
                  all(f2[i]-r2[i] == W for i in range(len(f2))) and
                  all(r2[i+1]-r2[i] == P for i in range(len(r2)-1)) and len(r1) >= K)
            if not ok:
                bad += 1
                if bad < 5: print("BAD", P, D, W, r1[:3], r2[:3], f1[:3], f2[:3])
print("fixed exhaustive P=8..47:", n, "configs, bad =", bad)
# 3) current math error table
errs = {}
for P in range(8, 48):
    for W in range(3, P):
        for D in range(0, P):
            w1 = current_words(P, 0, W); w2 = current_words(P, D, W)
            if w1 is None or w2 is None: continue
            e1 = run(w1, 3*P + 20); e2 = run(w2, 3*P + 20)
            err = (rises(e2)[0] - rises(e1)[0]) - D
            errs.setdefault(min(D, 4), set()).add(err)
            assert rises(e1)[1] - rises(e1)[0] == P
print("current math CH2-CH1 error by D (4 = D>=4):", {k: sorted(v) for k, v in errs.items()})
