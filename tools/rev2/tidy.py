#!/usr/bin/env python3
"""Hand clean-up of router squiggles (Rev 2), after jogs.py.

Each entry replaces a chain of track vertices by a cleaner chain between the same two end
points. The length change of each edit is printed. No camera line is edited here: the camera
lines are routed again in Rev 2 (tools/rev2/build.sh) and only jogs.py changes them.

usage (KiCad 10 Python): tidy.py IN.kicad_pcb OUT.kicad_pcb
"""
import math
import sys

import pcbnew

b = pcbnew.LoadBoard(sys.argv[1])
MM, mm = pcbnew.FromMM, pcbnew.ToMM
OLD = [t for t in b.Tracks() if t.Type() != pcbnew.PCB_VIA_T]
GONE = []                                               # removed items stay referenced (see pcb_edit.py)

EDITS = [
    # +5V_PD (F.Cu): two small steps with a 0.2 mm flat between them -> one 45 deg run.
    ("+5V_PD", "F.Cu",
     [(167.0, 113.8), (167.6, 113.2), (167.8, 113.2), (167.98, 113.02), (168.72, 113.02)],
     [(167.0, 113.8), (167.78, 113.02), (168.72, 113.02)]),
    # +12V (F.Cu) at U19.6: four pieces of 0.1-0.7 mm -> one 45 deg run and one vertical run into the via.
    ("+12V", "F.Cu",
     [(246.2, 98.4), (246.7, 98.9), (246.7, 99.0), (246.9, 99.2), (246.9, 99.3)],
     [(246.2, 98.4), (246.9, 99.1), (246.9, 99.6)]),
]


def near(p, q):
    return abs(mm(p.x) - q[0]) < 0.002 and abs(mm(p.y) - q[1]) < 0.002


def seg(net, layer, a, c):
    for t in OLD:
        if t.GetNetname() == net and b.GetLayerName(t.GetLayer()) == layer and \
                ((near(t.GetStart(), a) and near(t.GetEnd(), c)) or (near(t.GetStart(), c) and near(t.GetEnd(), a))):
            return t
    raise SystemExit("tidy: %s %s segment %s - %s not found" % (net, layer, a, c))


def plen(pts):
    return sum(math.hypot(c[0] - a[0], c[1] - a[1]) for a, c in zip(pts, pts[1:]))


for net, layer, old, new in EDITS:
    olds = [seg(net, layer, a, c) for a, c in zip(old, old[1:])]
    w, lid, n = olds[0].GetWidth(), olds[0].GetLayer(), olds[0].GetNet()
    ends = (olds[0].GetStart() if near(olds[0].GetStart(), old[0]) else olds[0].GetEnd(),
            olds[-1].GetEnd() if near(olds[-1].GetEnd(), old[-1]) else olds[-1].GetStart())
    for t in olds:
        b.Remove(t)
        OLD.remove(t)
        GONE.append(t)
    pts = [ends[0]] + [pcbnew.VECTOR2I(MM(x), MM(y)) for x, y in new[1:-1]] + [ends[1]]
    if not near(ends[1], new[-1]):                      # the new chain ends at another point (a via or a track)
        pts[-1] = pcbnew.VECTOR2I(MM(new[-1][0]), MM(new[-1][1]))
    for a, c in zip(pts, pts[1:]):
        t = pcbnew.PCB_TRACK(b)
        t.SetStart(a)
        t.SetEnd(c)
        t.SetWidth(w)
        t.SetLayer(lid)
        t.SetNet(n)
        b.Add(t)
    print("tidy: %-8s %s  %d -> %d segments, length %+.3f mm" % (net, layer, len(old) - 1, len(new) - 1, plen(new) - plen(old)))
pcbnew.SaveBoard(sys.argv[2], b, True)
