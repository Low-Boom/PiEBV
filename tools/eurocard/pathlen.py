# Copper path length between two pads of a net (KiCad python): shortest path through the net's
# tracks and vias (via barrel counted as 1.6 mm). usage: python.exe pathlen.py board REF.PAD REF.PAD [...]
# pairs of arguments: A1 B1 A2 B2 ...
import sys, math, heapq, pcbnew
from pcbnew import ToMM
b = pcbnew.LoadBoard(sys.argv[1])
VIA_LEN = 1.6
def pad(rp):
    r, n = rp.split(".")
    f = b.FindFootprintByReference(r)
    return [p for p in f.Pads() if p.GetNumber() == n][0]
def path(pa, pb):
    net = pa.GetNetname()
    items = [t for t in b.GetTracks() if t.GetNetname() == net]
    nodes = {}                                   # node key -> list of (neighbour, length)
    def key(x, y, l): return (round(x, 3), round(y, 3), l)
    def link(a, c, w): nodes.setdefault(a, []).append((c, w)); nodes.setdefault(c, []).append((a, w))
    pts = []                                     # all endpoints, to join coincident ones
    for t in items:
        if t.GetClass() == "PCB_VIA":
            x, y = ToMM(t.GetPosition().x), ToMM(t.GetPosition().y)
            link(key(x, y, "F.Cu"), key(x, y, "B.Cu"), VIA_LEN); pts += [(x, y, "F.Cu", t), (x, y, "B.Cu", t)]
        else:
            l = b.GetLayerName(t.GetLayer()); s, e = t.GetStart(), t.GetEnd()
            a, c = key(ToMM(s.x), ToMM(s.y), l), key(ToMM(e.x), ToMM(e.y), l)
            link(a, c, ToMM(int(t.GetLength())))
            pts += [(ToMM(s.x), ToMM(s.y), l, t), (ToMM(e.x), ToMM(e.y), l, t)]
    # join endpoints that touch (within 0.15 mm, e.g. track ends inside a via or on each other)
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            ti, tj = pts[i][3], pts[j][3]
            r = max(ToMM(ti.GetWidth()), ToMM(tj.GetWidth())) / 2 if ti.GetClass() != "PCB_VIA" and tj.GetClass() != "PCB_VIA" else 0.15
            if ti.GetClass() == "PCB_VIA" or tj.GetClass() == "PCB_VIA":   # anywhere inside the via ring
                r = ToMM((ti if ti.GetClass() == "PCB_VIA" else tj).GetWidth(pcbnew.F_Cu)) / 2
            if pts[i][2] == pts[j][2] and math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1]) < r:
                link(key(*pts[i][:3]), key(*pts[j][:3]), 0.0)
    # T-junctions: an endpoint on the interior of another same-layer segment joins both of its ends
    segs = [t for t in items if t.GetClass() != "PCB_VIA"]
    for x, y, l, t0 in pts:
        for t in segs:
            if t is t0 or b.GetLayerName(t.GetLayer()) != l: continue
            s, e = t.GetStart(), t.GetEnd(); ax, ay, bx, by = ToMM(s.x), ToMM(s.y), ToMM(e.x), ToMM(e.y)
            vx, vy = bx - ax, by - ay; L2 = vx * vx + vy * vy
            if L2 == 0: continue
            u = ((x - ax) * vx + (y - ay) * vy) / L2
            if not (0.001 < u < 0.999): continue
            if math.hypot(ax + u * vx - x, ay + u * vy - y) < ToMM(t.GetWidth()) / 2:
                Lt = math.sqrt(L2); k = key(x, y, l)
                link(k, key(ax, ay, l), u * Lt); link(k, key(bx, by, l), (1 - u) * Lt)
    def terminals(p):                            # track ends lying inside the pad shape
        out = []
        for x, y, l, t in pts:
            lid = b.GetLayerID(l)
            if p.IsOnLayer(lid) and p.GetEffectiveShape(lid).Collide(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)), pcbnew.FromMM(0.05)):
                c = p.GetPosition(); out.append((key(x, y, l), math.hypot(x - ToMM(c.x), y - ToMM(c.y))))
        return out
    src, dst = terminals(pa), dict(terminals(pb))
    dist = {}; q = [(d, k) for k, d in src]; heapq.heapify(q)
    while q:
        d, k = heapq.heappop(q)
        if k in dist: continue
        dist[k] = d
        if k in dst: return d + dst[k]
        for n, w in nodes.get(k, []):
            if n not in dist: heapq.heappush(q, (d + w, n))
    return None
args = sys.argv[2:]
for i in range(0, len(args), 2):
    L = path(pad(args[i]), pad(args[i + 1]))
    print(f"{args[i]:>8} -> {args[i+1]:<8} {L if L is None else round(L, 2)} mm")
