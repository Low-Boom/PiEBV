# Exact minimum edge-to-edge copper gap between two net sets (KiCad python), same copper layer only.
# Copper: tracks (segment, width), vias (circle per layer), pads (KiCad effective polygon per layer, so
# rect / roundrect / oval / custom pads are exact). Zone fills are not included.
# Each group "A=B" prints the minimum over all A x B item pairs and where it is. A net set may name
# "*" (every net with copper) and exclude nets with "-NET": "LANE1,LANE2=*,-LANE1,-LANE2,-CH1_J10".
# --no-pads: tracks and vias only (run copper; the scope of the audit's distsets2.py, which skipped every
# pad because FOOTPRINT has no GetNetname()).
# usage: python.exe netgap.py [--no-pads] board.kicad_pcb "netA,netB=netC,netD|..."  (groups separated by |)
import sys, math, wx; wx.DisableAsserts()
import pcbnew
from pcbnew import ToMM

LAYERS = (pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.B_Cu)
args = [a for a in sys.argv[1:] if a != "--no-pads"]; PADS = "--no-pads" not in sys.argv

def pt_seg(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1; L2 = dx * dx + dy * dy
    if L2 == 0: return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / L2))
    return math.hypot(px - (x1 + dx * t), py - (y1 + dy * t))

def seg_seg(a, b):                                   # centre-line distance between two segments
    x1, y1, x2, y2 = a; x3, y3, x4, y4 = b
    d1x, d1y, d2x, d2y = x2 - x1, y2 - y1, x4 - x3, y4 - y3
    den = d1x * d2y - d1y * d2x
    if den != 0:                                     # proper crossing -> 0
        t = ((x3 - x1) * d2y - (y3 - y1) * d2x) / den; u = ((x3 - x1) * d1y - (y3 - y1) * d1x) / den
        if 0 <= t <= 1 and 0 <= u <= 1: return 0.0
    return min(pt_seg(x1, y1, *b), pt_seg(x2, y2, *b), pt_seg(x3, y3, *a), pt_seg(x4, y4, *a))

# shape := ('seg', halfwidth, (x1,y1,x2,y2)) ; a via / circle is a zero-length seg with halfwidth = radius
def gap(a, b): return seg_seg(a[2], b[2]) - a[1] - b[1]

b = pcbnew.LoadBoard(args[0])
items = {}                                           # net -> [(layer, shape, label)]
for t in b.GetTracks():
    n = t.GetNetname()
    if not n: continue
    if t.GetClass() == "PCB_VIA":
        x, y = ToMM(t.GetPosition().x), ToMM(t.GetPosition().y)
        for lay in LAYERS:
            if t.IsOnLayer(lay):
                items.setdefault(n, []).append((lay, ('seg', ToMM(t.GetWidth(lay)) / 2, (x, y, x, y)), f"via({x:.3f},{y:.3f})"))
    else:
        if t.GetClass() != "PCB_TRACK": sys.exit(f"unsupported track class {t.GetClass()}")
        s, e = t.GetStart(), t.GetEnd(); c = (ToMM(s.x), ToMM(s.y), ToMM(e.x), ToMM(e.y))
        items.setdefault(n, []).append((t.GetLayer(), ('seg', ToMM(t.GetWidth()) / 2, c),
                                        "track(%.3f,%.3f)-(%.3f,%.3f)" % c))
for p in (b.GetPads() if PADS else []):
    n = p.GetNetname()
    if not n: continue
    lab = f"pad {p.GetParentFootprint().GetReference()}.{p.GetNumber()}"
    for lay in LAYERS:
        if not p.IsOnLayer(lay) or not p.FlashLayer(lay): continue
        poly = p.GetEffectivePolygon(lay, pcbnew.ERROR_OUTSIDE)
        for i in range(poly.OutlineCount()):
            ch = poly.Outline(i); k = ch.PointCount()
            pts = [(ToMM(ch.CPoint(j).x), ToMM(ch.CPoint(j).y)) for j in range(k)]
            for j in range(k):                       # outline edges, zero width
                (x1, y1), (x2, y2) = pts[j], pts[(j + 1) % k]
                items.setdefault(n, []).append((lay, ('seg', 0.0, (x1, y1, x2, y2)), lab))

def netset(spec):
    out = set()
    for x in (s.strip() for s in spec.split(",")):
        if x == "*": out |= set(items)
        elif x.startswith("-"): out.discard(x[1:])
        elif x: out.add(x)
    return out

for group in args[1].split("|"):
    la, lb = group.split("=")
    A, B = netset(la), netset(lb); B -= A
    best = (1e9, None)
    for n1 in A:
        for l1, s1, lab1 in items.get(n1, ()):
            for n2 in B:
                for l2, s2, lab2 in items.get(n2, ()):
                    if l1 != l2: continue
                    d = gap(s1, s2)
                    if d < best[0]: best = (d, (n1, lab1, n2, lab2, b.GetLayerName(l1)))
    print(f"{group[:70]:<70} min gap {best[0]:.3f} mm  {best[1]}")
