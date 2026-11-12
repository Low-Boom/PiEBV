#!/usr/bin/env python3
"""Router output clean-up at the camera vias.

1. The router makes 0.5 mm vias (0.3 mm hole, 0.1 mm annular ring). A via gets the board's via size (0.6 mm
   pad) if the larger pad keeps 0.22 mm to all other copper on F.Cu and B.Cu; the other vias stay at 0.5 mm.
2. A camera track end that is within 0.2 mm of a via of its net, but not on the via centre, moves to the centre.
trim.py runs after this tool and makes the lengths equal again. DRC then checks the clearances.

usage (KiCad 10 Python): viafix.py IN.kicad_pcb OUT.kicad_pcb
"""
import math
import re
import sys

import pcbnew
from shapely.geometry import LineString, Point
from shapely.ops import unary_union

b = pcbnew.LoadBoard(sys.argv[1])
MM, mm = pcbnew.FromMM, pcbnew.ToMM
CAM = re.compile(r"^(Sync|Trigger|TDRSTN)[1-6]$")
tracks = [t for t in b.Tracks() if CAM.match(t.GetNetname())]
vias = [t for t in tracks if t.Type() == pcbnew.PCB_VIA_T]
nv = ns = 0


def others(net):
    """Copper of all other nets on F.Cu and B.Cu (tracks, vias, pad boxes), as one shape."""
    sh = []
    for t in b.Tracks():
        if t.GetNetname() == net:
            continue
        if t.Type() == pcbnew.PCB_VIA_T:
            sh.append(Point(mm(t.GetPosition().x), mm(t.GetPosition().y)).buffer(0.3))
        elif t.GetLayer() in (pcbnew.F_Cu, pcbnew.B_Cu):
            sh.append(LineString([(mm(t.GetStart().x), mm(t.GetStart().y)), (mm(t.GetEnd().x), mm(t.GetEnd().y))]).buffer(mm(t.GetWidth()) / 2))
    for f in b.GetFootprints():
        for p in f.Pads():
            if p.GetNetname() != net:
                bb = p.GetBoundingBox()
                sh.append(LineString([(mm(bb.GetLeft()), mm(bb.GetTop())), (mm(bb.GetRight()), mm(bb.GetBottom()))]).envelope)
    return unary_union(sh)


obst = {}
for v in sorted(vias, key=lambda v: (v.GetNetname(), v.GetPosition().x, v.GetPosition().y)):
    n = v.GetNetname()
    if n not in obst:
        obst[n] = others(n)
    c = v.GetPosition()
    if v.GetWidth(pcbnew.F_Cu) < MM(0.6) and Point(mm(c.x), mm(c.y)).distance(obst[n]) >= 0.3 + 0.22:
        v.SetWidth(pcbnew.F_Cu, MM(0.6))
        nv += 1
for t in tracks:
    if t.Type() == pcbnew.PCB_VIA_T:
        continue
    for get, put in ((t.GetStart, t.SetStart), (t.GetEnd, t.SetEnd)):
        p = get()
        for v in vias:
            c = v.GetPosition()
            d = math.hypot(p.x - c.x, p.y - c.y)
            if v.GetNetname() == t.GetNetname() and 0 < d < MM(0.2):
                put(pcbnew.VECTOR2I(c.x, c.y))
                ns += 1
                break
pcbnew.SaveBoard(sys.argv[2], b, True)
print("viafix: %d of %d camera vias set to 0.6 mm, %d track ends moved to a via centre" % (nv, len(vias), ns))
