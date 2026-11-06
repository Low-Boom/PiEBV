# Split a track where a same-net, same-layer track end lands on its interior (centre line within 0.01 mm),
# so KiCad sees a node there instead of a dangling end. If a same-net, same-layer, same-width segment p -> e
# (either direction, ends within 0.01 mm) exists already, the split only shortens the track to s -> p
# (no duplicate copy of p -> e; audit m1). usage: python.exe tjoin.py in out
import sys, math, pcbnew
from pcbnew import ToMM, FromMM
b = pcbnew.LoadBoard(sys.argv[1])
segs = [t for t in b.GetTracks() if t.GetClass() == "PCB_TRACK"]
ends = [(t.GetNetCode(), t.GetLayer(), p) for t in segs for p in (t.GetStart(), t.GetEnd())]
TOL = FromMM(0.01)
near = lambda a, c: math.hypot(a.x - c.x, a.y - c.y) <= TOL
def exists(net, lay, w, p, e):
    return any(u.GetNetCode() == net and u.GetLayer() == lay and u.GetWidth() == w and
               ((near(u.GetStart(), p) and near(u.GetEnd(), e)) or (near(u.GetStart(), e) and near(u.GetEnd(), p))) for u in segs)
n = dup = 0
for t in list(segs):
    s, e = t.GetStart(), t.GetEnd(); dx, dy = e.x - s.x, e.y - s.y; L2 = dx * dx + dy * dy
    if L2 == 0: continue
    for net, lay, p in ends:
        if net != t.GetNetCode() or lay != t.GetLayer(): continue
        u = ((p.x - s.x) * dx + (p.y - s.y) * dy) / L2
        if not (0.001 < u < 0.999): continue
        if math.hypot(s.x + u * dx - p.x, s.y + u * dy - p.y) > TOL: continue
        if exists(net, lay, t.GetWidth(), p, e): dup += 1
        else:
            # new segment p -> e with t's net, layer and width (PCB_TRACK(t) would take t as its parent, not copy it)
            c = pcbnew.PCB_TRACK(b); c.SetStart(p); c.SetEnd(e); c.SetWidth(t.GetWidth()); c.SetLayer(t.GetLayer())
            c.SetNet(t.GetNet()); b.Add(c); segs.append(c)
        t.SetEnd(p); n += 1
        print("split", t.GetNetname(), b.GetLayerName(lay), round(ToMM(p.x), 3), round(ToMM(p.y), 3)); break
print("T-joins split:", n, "(piece already present, not added:", dup, ")")
pcbnew.SaveBoard(sys.argv[2], b)
