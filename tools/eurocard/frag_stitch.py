# Post-stitch step (KiCad python), F26: GND vias for outer-layer GND pour pieces that the KRT stitch
# lattice skipped (route_planes.py only stitches sites with fill on both outer layers and on the main
# fill cluster). After a refill, per F.Cu / B.Cu GND fill:
#  (a) island (own outline, not the largest) >= MIN_ISLAND with < 2 GND vias -> add vias up to 2
#      (a GND THT pad on the island does not count: the target is 2 vias per island);
#  (b) piece left after cutting necks < 2*ERODE (erode, re-dilate, clip to fill) >= MIN_NECK with no
#      GND via / GND THT pad on it -> add 1 via.
# Via 0.6/0.3 F.Cu-B.Cu. Sites: 0.2 mm grid, deepest first (depth = number of 0.2 mm deflations the
# point survives; SHAPE_POLY_SET.SquaredDistance is 0 for inside points, so it cannot rank them),
# sites outside SMD courtyards first, a 2nd island via >= SPREAD from the 1st. Clearances as taps.py:
# other-net copper 0.2 on F/B, 0.1 to GND SMD pads (no via-in-pad), hole-to-hole 0.3, via keep-outs,
# board edge 0.6, none in the 2.5 mm card-guide strips. Only GND vias are added; nothing moves.
# usage: python.exe frag_stitch.py in.kicad_pcb out.kicad_pcb
import sys, wx; wx.DisableAsserts()
import pcbnew
from pcbnew import VECTOR2I, FromMM, ToMM
ERODE, MIN_ISLAND, MIN_NECK, GRID, STEP = 0.5, 1.0, 5.0, 0.2, 0.2   # mm, mm2, mm2, grid, depth step
VIA_D, VIA_DR = 0.6, 0.3
CLR, SAME_PAD, H2H, EDGE, STRIP = 0.2, 0.1, 0.3, 0.6, 2.5
SPREAD = 2.0
RA = pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS; ARC = FromMM(0.005)
LAYERS = (pcbnew.F_Cu, pcbnew.B_Cu)

b = pcbnew.LoadBoard(sys.argv[1])
pcbnew.ZONE_FILLER(b).Fill(b.Zones())
gnd = b.FindNet("GND")
bb = b.GetBoardEdgesBoundingBox()
X0, Y0, X1, Y1 = ToMM(bb.GetX()), ToMM(bb.GetY()), ToMM(bb.GetRight()), ToMM(bb.GetBottom())
keepouts = [z for z in b.Zones() if z.GetIsRuleArea() and z.GetDoNotAllowVias()]
tracks = list(b.GetTracks()); pads = list(b.GetPads())
anch = [t.GetPosition() for t in tracks if t.GetClass() == "PCB_VIA" and t.GetNetCode() == gnd.GetNetCode()]
tht = [p for p in pads if p.GetNetCode() == gnd.GetNetCode() and p.HasHole()]
smd_crt = [f.GetCourtyard(pcbnew.F_CrtYd) for f in b.GetFootprints()
           if any(p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD for p in f.Pads()) and f.GetCourtyard(pcbnew.F_CrtYd).OutlineCount()]
holes = [(t.GetPosition(), t.GetDrillValue()) for t in tracks if t.GetClass() == "PCB_VIA"] + \
        [(p.GetPosition(), max(p.GetDrillSize().x, p.GetDrillSize().y)) for p in pads if p.HasHole()]
obst = {lay: [] for lay in LAYERS}                     # (shape, bbox, gap) per layer
for lay in LAYERS:
    for p in pads:
        if not p.IsOnLayer(lay): continue
        if p.GetNetCode() != gnd.GetNetCode(): obst[lay].append((p.GetEffectiveShape(lay), p.GetBoundingBox(), CLR))
        elif not p.HasHole(): obst[lay].append((p.GetEffectiveShape(lay), p.GetBoundingBox(), SAME_PAD))
    for t in tracks:
        if t.GetNetCode() != gnd.GetNetCode() and t.IsOnLayer(lay): obst[lay].append((t.GetEffectiveShape(lay), t.GetBoundingBox(), CLR))

def ok(v):
    x, y = ToMM(v.x), ToMM(v.y); r = VIA_D / 2
    if not (X0 + EDGE + r <= x <= X1 - EDGE - r and Y0 + STRIP + r <= y <= Y1 - STRIP - r): return False
    if any(z.Outline().Collide(v, FromMM(r + 0.1)) for z in keepouts): return False
    if any((q - v).EuclideanNorm() < d / 2 + FromMM(VIA_DR / 2 + H2H) for q, d in holes): return False
    c = pcbnew.SHAPE_CIRCLE(v, FromMM(r)); reach = FromMM(r + 0.5)
    for lay in LAYERS:
        for sh, box, gap in obst[lay]:
            if v.x < box.GetX() - reach or v.x > box.GetRight() + reach or v.y < box.GetY() - reach or v.y > box.GetBottom() + reach: continue
            if sh.Collide(c, FromMM(gap)): return False
    return True

def sites(core):
    """Grid points of core, deepest first."""
    levels = [pcbnew.SHAPE_POLY_SET(core)]
    while True:
        n = pcbnew.SHAPE_POLY_SET(levels[-1]); n.Deflate(FromMM(STEP), RA, ARC); n.Simplify()
        if n.OutlineCount() == 0 or n.Area() < FromMM(0.05) ** 2: break
        levels.append(n)
    box = core.BBox(); out = []
    for gx in range(box.GetX(), box.GetRight() + 1, FromMM(GRID)):
        for gy in range(box.GetY(), box.GetBottom() + 1, FromMM(GRID)):
            v = VECTOR2I(gx, gy)
            if not core.Contains(v): continue
            d = 0
            while d + 1 < len(levels) and levels[d + 1].Contains(v): d += 1
            out.append((-d, gx, gy, v))
    out.sort(key=lambda s: s[:3])
    return [s[3] for s in out]

added = []
def place(cores, lay, area, why, away=()):
    """Add a via at the first clear site of cores (in order); with 'away', prefer sites >= SPREAD mm from those."""
    cand = [v for c in cores for v in sites(c)]
    def first(pred):                                   # stable partition: sites meeting pred first
        k = [pred(v) for v in cand]
        return [v for v, f in zip(cand, k) if f] + [v for v, f in zip(cand, k) if not f]
    cand = first(lambda v: not any(c.Collide(v, FromMM(VIA_D / 2)) for c in smd_crt))
    if away: cand = first(lambda v: min((v - a).EuclideanNorm() for a in away) >= FromMM(SPREAD))
    for v in cand:
        if ok(v):
            via = pcbnew.PCB_VIA(b); via.SetPosition(v); via.SetWidth(FromMM(VIA_D)); via.SetDrill(FromMM(VIA_DR))
            via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu); via.SetNet(gnd); b.Add(via)
            holes.append((v, FromMM(VIA_DR))); anch.append(v)
            added.append((b.GetLayerName(lay), why, round(ToMM(v.x), 2), round(ToMM(v.y), 2), round(area, 1))); return True
    bx = cores[0].BBox(); print("no site:", b.GetLayerName(lay), why, round(area, 1), round(ToMM(bx.GetX()), 2), round(ToMM(bx.GetY()), 2))
    return False

def vias_on(piece):                                    # GND via pad overlaps the piece
    return [a for a in anch if piece.Collide(a, FromMM(VIA_D / 2 + 0.05))]

def poly(src, i):
    p = pcbnew.SHAPE_POLY_SET(); p.AddOutline(src.Outline(i))
    for h in range(src.HoleCount(i)): p.AddHole(src.Hole(i, h))
    return p

for z in b.Zones():
    if z.GetIsRuleArea() or z.GetNetCode() != gnd.GetNetCode(): continue
    for lay in z.GetLayerSet().Seq():
        if lay not in LAYERS: continue
        fill = pcbnew.SHAPE_POLY_SET(z.GetFilledPolysList(lay)); fill.Unfracture(); fill.Simplify()
        # (a) islands: every outline but the largest
        outl = sorted((poly(fill, i) for i in range(fill.OutlineCount())), key=lambda p: -p.Area())
        for pc in outl[1:]:
            area = pc.Area() / 1e12
            if area < MIN_ISLAND: continue
            # sites: island eroded by ERODE, then (small islands, e.g. C21.1) by the via radius only, so the
            # via pad stays on the island copper; ok() still holds the 0.2 mm other-net clearance
            cores = []
            for d in (ERODE, VIA_D / 2):
                c = pcbnew.SHAPE_POLY_SET(pc); c.Deflate(FromMM(d), RA, ARC); c.Simplify(); cores.append(c)
            for _ in range(2 - len(vias_on(pc))):
                if not place(cores, lay, area, "island", away=vias_on(pc)): break
        # (b) necked pieces: opening by ERODE, re-dilated and clipped to the fill
        er = pcbnew.SHAPE_POLY_SET(fill); er.Deflate(FromMM(ERODE), RA, ARC); er.Simplify()
        for i in range(er.OutlineCount()):
            core = poly(er, i)
            dil = pcbnew.SHAPE_POLY_SET(core); dil.Inflate(FromMM(ERODE), RA, ARC); dil.BooleanIntersection(fill)
            area = dil.Area() / 1e12
            if area < MIN_NECK or vias_on(dil) or any(dil.Collide(p.GetEffectiveShape(lay), FromMM(0.6)) for p in tht): continue
            place([core], lay, area, "neck")
print("fragment vias:", len(added)); [print("  ", a) for a in added]
pcbnew.SaveBoard(sys.argv[2], b)
