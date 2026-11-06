# Region gap battery (KiCad python): for each named net, the smallest edge-to-edge gap to every other net with
# copper nearby, same copper layer only, counting only copper inside a box. Tracks are clipped to the box; vias
# and pads count if their centre is in the box. Copper as netgap.py: tracks, vias (circle per layer), exact pad
# outlines; zone fills not counted. Lines "NET OTHER gap_mm layer" (pairs with a gap < LIMIT), then "NET * min".
# usage: python.exe regiongap.py board.kicad_pcb x0 y0 x1 y1 NET [NET ...]
import sys, math, wx; wx.DisableAsserts()
import pcbnew
from pcbnew import ToMM

LIMIT = 3.0
LAYERS = (pcbnew.F_Cu, pcbnew.B_Cu)
b = pcbnew.LoadBoard(sys.argv[1]); X0, Y0, X1, Y1 = map(float, sys.argv[2:6]); NETS = sys.argv[6:]
inbox = lambda x, y: X0 <= x <= X1 and Y0 <= y <= Y1

def clip(x1, y1, x2, y2):
    """Liang-Barsky clip of a segment to the box, or None"""
    t0, t1, dx, dy = 0.0, 1.0, x2 - x1, y2 - y1
    for p, q in ((-dx, x1 - X0), (dx, X1 - x1), (-dy, y1 - Y0), (dy, Y1 - y1)):
        if p == 0:
            if q < 0: return None
        else:
            r = q / p
            if p < 0: t0 = max(t0, r)
            else: t1 = min(t1, r)
    return None if t0 > t1 else (x1 + t0 * dx, y1 + t0 * dy, x1 + t1 * dx, y1 + t1 * dy)

ITEMS = {}                          # net -> [(layer, halfwidth, (x1,y1,x2,y2), label)]
for t in b.GetTracks():
    n = t.GetNetname()
    if t.GetClass() == "PCB_TRACK":
        s, e = t.GetStart(), t.GetEnd(); g = clip(ToMM(s.x), ToMM(s.y), ToMM(e.x), ToMM(e.y))
        if g: ITEMS.setdefault(n, []).append((t.GetLayer(), ToMM(t.GetWidth()) / 2, g,
                                              "track(%.3f,%.3f)-(%.3f,%.3f)" % (ToMM(s.x), ToMM(s.y), ToMM(e.x), ToMM(e.y))))
    elif t.GetClass() == "PCB_VIA":
        x, y = ToMM(t.GetPosition().x), ToMM(t.GetPosition().y)
        if inbox(x, y):
            for L in LAYERS:
                if t.IsOnLayer(L): ITEMS.setdefault(n, []).append((L, ToMM(t.GetWidth(L)) / 2, (x, y, x, y), "via(%.3f,%.3f)" % (x, y)))
for p in b.GetPads():
    n = p.GetNetname(); c = p.GetPosition()
    if not n or not inbox(ToMM(c.x), ToMM(c.y)): continue
    for L in LAYERS:
        if not p.IsOnLayer(L) or not p.FlashLayer(L): continue
        poly = p.GetEffectivePolygon(L, pcbnew.ERROR_OUTSIDE); lab = f"pad {p.GetParentFootprint().GetReference()}.{p.GetNumber()}"
        for i in range(poly.OutlineCount()):
            ch = poly.Outline(i); k = ch.PointCount(); P = [(ToMM(ch.CPoint(j).x), ToMM(ch.CPoint(j).y)) for j in range(k)]
            ITEMS.setdefault(n, []).extend((L, 0.0, P[j] + P[(j + 1) % k], lab) for j in range(k))

def pt_seg(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1; L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / L2))
    return math.hypot(px - x1 - dx * t, py - y1 - dy * t)
def seg_seg(s, q):
    x1, y1, x2, y2 = s; x3, y3, x4, y4 = q
    d1x, d1y, d2x, d2y = x2 - x1, y2 - y1, x4 - x3, y4 - y3; den = d1x * d2y - d1y * d2x
    if den != 0:
        t = ((x3 - x1) * d2y - (y3 - y1) * d2x) / den; u = ((x3 - x1) * d1y - (y3 - y1) * d1x) / den
        if 0 <= t <= 1 and 0 <= u <= 1: return 0.0
    return min(pt_seg(x1, y1, *q), pt_seg(x2, y2, *q), pt_seg(x3, y3, *s), pt_seg(x4, y4, *s))

for net in NETS:
    lo = None
    for other in sorted(o for o in ITEMS if o and o != net):
        best = None
        for L1, h1, g1, l1 in ITEMS.get(net, ()):
            for L2, h2, g2, l2 in ITEMS[other]:
                if L1 != L2: continue
                d = seg_seg(g1, g2) - h1 - h2
                if best is None or d < best[0]: best = (d, b.GetLayerName(L1), l1, l2)
        if best and best[0] < LIMIT:
            print(f"{net:14s} {other:16s} {best[0]:7.3f}  {best[1]}  {best[2]} | {best[3]}")
        if best and (lo is None or best[0] < lo[0]): lo = best + (other,)
    if lo: print(f"{net:14s} {'*':16s} {lo[0]:7.3f}  {lo[1]}  {lo[2]} | {lo[4]} {lo[3]}")
