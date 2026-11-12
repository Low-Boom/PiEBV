#!/usr/bin/env python3
"""Board numbers for the documentation: copper totals, vias per net, parts, fingerprint.

usage (KiCad 10 Python): stats.py BOARD.kicad_pcb
Fingerprint: first 16 hex digits of the SHA-256 of the sorted list of
"T net layer x1 y1 x2 y2 width" (end points in ascending order) and "V net x y diameter drill" lines, in nm.
"""
import collections
import hashlib
import sys

import pcbnew

b = pcbnew.LoadBoard(sys.argv[1])
mm = pcbnew.ToMM
seg, ln, vias, lines = collections.Counter(), collections.Counter(), collections.Counter(), []
for t in b.Tracks():
    n = t.GetNetname()
    if t.Type() == pcbnew.PCB_VIA_T:
        p = t.GetPosition()
        vias[n] += 1
        lines.append("V %s %d %d %d %d" % (n, p.x, p.y, t.GetWidth(pcbnew.F_Cu), t.GetDrill()))
    else:
        a, c = sorted([(t.GetStart().x, t.GetStart().y), (t.GetEnd().x, t.GetEnd().y)])
        L = b.GetLayerName(t.GetLayer())
        seg[L] += 1
        ln[L] += mm(t.GetLength())
        lines.append("T %s %s %d %d %d %d %d" % (n, L, a[0], a[1], c[0], c[1], t.GetWidth()))
dup = len(lines) - len(set(lines))
fp = hashlib.sha256("\n".join(sorted(lines)).encode()).hexdigest()[:16]
print("segments %d (%s), length %.1f mm (%s)" % (sum(seg.values()), ", ".join("%s %d" % kv for kv in sorted(seg.items())),
                                               sum(ln.values()), ", ".join("%s %.1f" % kv for kv in sorted(ln.items()))))
plane = ("+5V", "+3V3", "+1V8", "+VCAM", "+12V")
print("vias %d: GND %d, %s, other %d" % (sum(vias.values()), vias["GND"], ", ".join("%s %d" % (n, vias[n]) for n in plane),
                                       sum(v for n, v in vias.items() if n != "GND" and n not in plane)))
print("duplicates %d, fingerprint %s" % (dup, fp))
fps = list(b.GetFootprints())
placed = [f for f in fps if not f.GetReference().startswith("MH") and not (f.GetAttributes() & pcbnew.FP_EXCLUDE_FROM_POS_FILES)]
print("footprints %d: placed parts %d, test pads %d, mounting holes %d" % (
    len(fps), len(placed), sum(f.GetReference().startswith("TP") and f not in placed for f in fps), sum(f.GetReference().startswith("MH") for f in fps)))
smd = sum(1 for f in placed if all(p.GetAttribute() != pcbnew.PAD_ATTRIB_PTH for p in f.Pads()))
print("placed: %d SMD, %d through-hole" % (smd, len(placed) - smd))
