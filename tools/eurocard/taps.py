# Plane taps before routing (KiCad python): every SMD pad of a plane net (GND -> In1, +5V -> In2) gets
# a 0.6/0.3 mm through via close to the pad and a short F.Cu track to it, so the autorouter sees the
# planes as connected and only routes signals. Each candidate is checked against every other-net pad,
# track, via, hole and keep-out with pcbnew's own shape collision; the first clear site wins.
# usage: python.exe taps.py <in.kicad_pcb> <out.kicad_pcb>
import sys, math, pcbnew
from pcbnew import VECTOR2I, FromMM, ToMM

b = pcbnew.LoadBoard(sys.argv[1])
NETS = {"GND": 0.4, "+5V": 0.5}       # tap track width by net (necked to the pad below)
VIA_D, VIA_DR = 0.6, 0.3
CLR, HOLE_CLR, H2H, EDGE = 0.2, 0.25, 0.3, 0.6   # copper, copper-to-hole, hole-to-hole, edge (mm)
SAME_PAD = 0.1                         # via ring to same-net SMD pad (no via-in-pad)
F = pcbnew.F_Cu

bb = b.GetBoardEdgesBoundingBox()
X0, Y0, X1, Y1 = ToMM(bb.GetX()), ToMM(bb.GetY()), ToMM(bb.GetRight()), ToMM(bb.GetBottom())
keepouts = [z for z in b.Zones() if z.GetIsRuleArea()]
pads = [p for f in b.GetFootprints() for p in f.Pads()]
tracks = list(b.GetTracks())
new_vias = []                           # (x, y, net)

def circle(x, y, r): return pcbnew.SHAPE_CIRCLE(VECTOR2I(FromMM(x), FromMM(y)), FromMM(r))
def seg(x1, y1, x2, y2, w): return pcbnew.SHAPE_SEGMENT(VECTOR2I(FromMM(x1), FromMM(y1)), VECTOR2I(FromMM(x2), FromMM(y2)), FromMM(w))

def clear(shape, net, layers, own_pad, is_via):
    """True if shape (on the given copper layers) keeps clearance to all other copper."""
    for p in pads:
        if p is own_pad: continue
        same = p.GetNetname() == net
        for lay in layers:
            if not p.IsOnLayer(lay): continue
            gap = (SAME_PAD if is_via else -1) if same else CLR
            if gap < 0: continue
            if p.GetEffectiveShape(lay).Collide(shape, FromMM(gap)): return False
        if p.HasHole() and is_via and p.GetEffectiveHoleShape().Collide(shape, FromMM(HOLE_CLR if not same else 0.2)): return False
    for t in tracks:
        same = t.GetNetname() == net
        for lay in layers:
            if not t.IsOnLayer(lay) or same: continue
            if t.GetEffectiveShape(lay).Collide(shape, FromMM(CLR)): return False
    return True

def via_ok(x, y, net, own_pad):
    if not (X0 + EDGE + VIA_D / 2 <= x <= X1 - EDGE - VIA_D / 2 and Y0 + EDGE + VIA_D / 2 <= y <= Y1 - EDGE - VIA_D / 2): return False
    for z in keepouts:
        if z.GetIsRuleArea() and z.GetDoNotAllowVias() and z.Outline().Collide(VECTOR2I(FromMM(x), FromMM(y)), FromMM(VIA_D / 2 + 0.1)): return False
    for vx, vy, vn in new_vias:
        if math.hypot(vx - x, vy - y) < VIA_D + (CLR if vn != net else 0.1) or math.hypot(vx - x, vy - y) < VIA_DR + H2H: return False
    for p in pads:                       # hole-to-hole with drilled pads
        if p.HasHole():
            hp = p.GetPosition(); hr = ToMM(max(p.GetDrillSize().x, p.GetDrillSize().y)) / 2
            if math.hypot(ToMM(hp.x) - x, ToMM(hp.y) - y) < hr + VIA_DR / 2 + H2H: return False
    for t in tracks:
        if t.GetClass() == "PCB_VIA":
            tp = t.GetPosition()
            if math.hypot(ToMM(tp.x) - x, ToMM(tp.y) - y) < VIA_DR + H2H: return False
    layers = [pcbnew.F_Cu, pcbnew.B_Cu]  # inner layers are planes; the via joins its own plane
    return clear(circle(x, y, VIA_D / 2), net, layers, own_pad, True)

added = []
for f in b.GetFootprints():
    for p in f.Pads():
        net = p.GetNetname()
        if net not in NETS or p.GetAttribute() != pcbnew.PAD_ATTRIB_SMD or not p.IsOnLayer(F): continue
        if p.GetSize().x < FromMM(0.2): continue
        # already tapped by kept (hand-routed) copper: a same-net track or via touches the pad
        if any(t.GetNetname() == net and t.IsOnLayer(F) and p.GetEffectiveShape(F).Collide(t.GetEffectiveShape(F), 0) for t in tracks): continue
        px, py = ToMM(p.GetPosition().x), ToMM(p.GetPosition().y)
        sx, sy = ToMM(p.GetSize().x) / 2, ToMM(p.GetSize().y) / 2
        a = math.radians(p.GetOrientationDegrees())
        w = min(NETS[net], 2 * min(sx, sy))
        best = None
        # Directions in the pad frame, outward from the part body first (a tap under the package blocks
        # the pad's own thermal spokes), the pad's long axis before its short axis.
        fc = f.GetPosition(); ox, oy = px - ToMM(fc.x), py - ToMM(fc.y)
        def outward(d):
            lx, ly = d
            bx, by = lx * math.cos(a) + ly * math.sin(a), -lx * math.sin(a) + ly * math.cos(a)
            return -(bx * ox + by * oy) / math.hypot(lx, ly)
        dirs = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)]
        long = (lambda d: d[1] == 0) if sx >= sy else (lambda d: d[0] == 0)
        dirs.sort(key=lambda d: (d[0] != 0 and d[1] != 0, outward(d), not long(d)))
        for ext in [0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 2.5]:
            for dx, dy in dirs:
                n = math.hypot(dx, dy); dx, dy = dx / n, dy / n
                # distance from pad centre to the pad edge along this direction, then ring + gap
                edge = min(sx / abs(dx) if dx else 1e9, sy / abs(dy) if dy else 1e9)
                d = edge + SAME_PAD + VIA_D / 2 + ext
                lx, ly = dx * d, dy * d                       # pad frame -> board (KiCad +angle CCW, y down)
                x = px + lx * math.cos(a) + ly * math.sin(a); y = py - lx * math.sin(a) + ly * math.cos(a)
                if not via_ok(x, y, net, p): continue
                if not clear(seg(px, py, x, y, w), net, [F], p, False): continue
                best = (x, y); break
            if best: break
        if not best:
            print("NO TAP:", f.GetReference(), p.GetNumber(), net); continue
        x, y = best
        v = pcbnew.PCB_VIA(b); v.SetPosition(VECTOR2I(FromMM(x), FromMM(y))); v.SetWidth(FromMM(VIA_D)); v.SetDrill(FromMM(VIA_DR))
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu); v.SetNet(p.GetNet()); b.Add(v)
        t = pcbnew.PCB_TRACK(b); t.SetStart(p.GetPosition()); t.SetEnd(v.GetPosition()); t.SetWidth(FromMM(w)); t.SetLayer(F); t.SetNet(p.GetNet()); b.Add(t)
        v.SetLocked(True); t.SetLocked(True)
        tracks += [v, t]; new_vias.append((x, y, net)); added.append(f.GetReference() + "." + p.GetNumber())
print("taps:", len(added))
pcbnew.SaveBoard(sys.argv[2], b)
