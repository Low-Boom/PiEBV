# Courtyard gap check (KiCad python): pairs of top-side footprints whose courtyard polygons are
# closer than LIMIT mm; SMD parts outside the hot-plate window; parts inside the long-edge strips.
import sys, pcbnew
from pcbnew import ToMM
b = pcbnew.LoadBoard(sys.argv[1]); LIM = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
WX0, WX1 = (float(v) for v in (sys.argv[3] if len(sys.argv) > 3 else "130,290").split(","))
Y0, Y1, STRIP = 30.0, 130.0, 2.5
fps = [f for f in b.GetFootprints() if not f.GetReference().startswith("MH")]
cy = {}
for f in fps:
    s = f.GetCourtyard(pcbnew.F_CrtYd)
    if s.OutlineCount() == 0: f.BuildCourtyardCaches(); s = f.GetCourtyard(pcbnew.F_CrtYd)
    cy[f.GetReference()] = s
bad = []
for i, a in enumerate(fps):
    for c in fps[i + 1:]:
        A, C = cy[a.GetReference()], cy[c.GetReference()]
        if A.OutlineCount() == 0 or C.OutlineCount() == 0: continue
        if not a.GetBoundingBox().Inflate(pcbnew.FromMM(LIM)).Intersects(c.GetBoundingBox()): continue
        ba, bc = A.BBox(), C.BBox()   # courtyards are rectangles here; bbox gap
        dx = max(0, max(ba.GetX(), bc.GetX()) - min(ba.GetRight(), bc.GetRight()))
        dy = max(0, max(ba.GetY(), bc.GetY()) - min(ba.GetBottom(), bc.GetBottom()))
        g = ToMM(int((dx * dx + dy * dy) ** 0.5))
        if g < LIM: bad.append((round(g, 2), a.GetReference(), c.GetReference()))
for g, r1, r2 in sorted(bad): print(f"gap {g:5.2f}  {r1}-{r2}")
smd = [f for f in fps if any(p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD for p in f.Pads())]
for f in smd:
    for p in f.Pads():
        if p.GetAttribute() != pcbnew.PAD_ATTRIB_SMD: continue
        x = ToMM(p.GetPosition().x)
        if not (WX0 <= x <= WX1): print("SMD pad outside window:", f.GetReference(), p.GetNumber(), round(x, 2)); break
for f in fps:
    bb = cy[f.GetReference()].BBox() if cy[f.GetReference()].OutlineCount() else f.GetBoundingBox()
    t, bo = ToMM(bb.GetY()), ToMM(bb.GetBottom())
    if t < Y0 + STRIP or bo > Y1 - STRIP: print("in long-edge strip:", f.GetReference(), round(t, 2), round(bo, 2))
