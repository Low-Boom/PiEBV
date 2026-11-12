#!/usr/bin/env python3
"""JLC placement file (CPL) for the Rev 2 board.

Parts that are on the Rev 1 board keep their JLC correction (rotation offset and centroid offset
in the footprint frame, as tools/jlc_cpl found them); it is applied to the part's Rev 2 pose.
The correction is taken per footprint type and LCSC part from the Rev 1 CPL. One Rev 1 row was
stale (C6: the CPL was not regenerated after C6 moved by 2.2 mm), so a part whose correction
differs from the other parts of its footprint type gets the type's correction.

New parts: two-pad chip parts need no correction; J22 uses the correction of J20 (same part).
Parts in UNVERIFIED get the KiCad rotation unchanged: their JLC footprints were not read (no
access to JLC's library from the build machine). Run tools/jlc_cpl before an order.

usage (KiCad 10 Python): cpl.py REV1.kicad_pcb REV1_CPL.csv REV2.kicad_pcb OUT_CPL.csv
"""
import collections
import csv
import math
import sys

import pcbnew
from pcbnew import ToMM

old, oldcpl, new, out = sys.argv[1:5]
UNVERIFIED = ("LED_0805_2012Metric_Pad1.15x1.40mm_HandSolder", "SOT-23", "SSOP-8_2.95x2.8mm_P0.65mm", "SOT-583-8")
NO_CORR = ("C_0805_2012Metric_Pad1.18x1.45mm_HandSolder", "R_0805_2012Metric_Pad1.20x1.40mm_HandSolder")


def poses(p):
    b = pcbnew.LoadBoard(p)
    return {f.GetReference(): (ToMM(f.GetPosition().x), ToMM(f.GetPosition().y), f.GetOrientationDegrees(),
                               str(f.GetFPID().GetLibItemName()), f.GetAttributes()) for f in b.GetFootprints()}


po, pn = poses(old), poses(new)
rows = list(csv.reader(open(oldcpl, newline="")))
corr, bytype = {}, collections.defaultdict(collections.Counter)
for ref, mx, my, layer, rot in rows[1:]:
    X, Y, A, fp, _ = po[ref]
    cx, cy = float(mx) - X, -float(my) - Y                  # centroid offset, board frame (y down)
    a = math.radians(-A)                                     # into the footprint frame (KiCad: +angle CCW)
    c = (round((float(rot) - A) % 360), round(cx * math.cos(a) + cy * math.sin(a), 3), round(-cx * math.sin(a) + cy * math.cos(a), 3))
    corr[ref] = c
    bytype[fp][c] += 1
for ref in list(corr):                                      # outlier within a footprint type of 3 or more parts: stale row
    cnt = bytype[po[ref][3]]
    best, n = cnt.most_common(1)[0]
    if corr[ref] != best and sum(cnt.values()) >= 3 and cnt[corr[ref]] == 1 and po[ref][3] in NO_CORR:
        print("stale Rev 1 CPL row %s: correction %s replaced by %s" % (ref, corr[ref], best))
        corr[ref] = best

w = csv.writer(open(out, "w", newline=""), quoting=csv.QUOTE_ALL, lineterminator="\n")
w.writerow(rows[0])
n = 0
unv = []


def key(r):
    i = next(k for k, ch in enumerate(r) if ch.isdigit())
    return (r[:i], int(r[i:]))


order = [r[0] for r in rows[1:]] + sorted((r for r in pn if r not in corr), key=key)
for ref in order:
    X, Y, A, fp, attr = pn[ref]
    if ref.startswith("MH") or attr & pcbnew.FP_EXCLUDE_FROM_POS_FILES:
        continue
    if ref in corr:
        c = corr[ref]
    elif fp in NO_CORR:
        c = (0, 0.0, 0.0)
    elif fp == "PinHeader_1x02_P2.54mm_Vertical":
        c = corr["J20"]
    else:
        assert fp in UNVERIFIED, (ref, fp)
        c = (0, 0.0, 0.0)
        unv.append(ref)
    a2 = math.radians(A)
    nx, ny = X + c[1] * math.cos(a2) + c[2] * math.sin(a2), Y - c[1] * math.sin(a2) + c[2] * math.cos(a2)
    w.writerow([ref, "%.4f" % nx, "%.4f" % -ny, "Top", "%g" % ((A + c[0]) % 360)])
    n += 1
print("%d rows; KiCad rotation, JLC footprint not checked: %s" % (n, " ".join(unv)))
