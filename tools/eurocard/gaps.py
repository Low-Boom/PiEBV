# Courtyard gap check (KiCad python): pairs of top-side footprints whose courtyard polygons are
# closer than LIMIT mm; SMD parts outside the hot-plate window; parts inside the long-edge strips;
# mounting-hole washers in the long-edge strips or on a courtyard. usage: python.exe gaps.py board [LIMIT] [WX0,WX1]
# Deterministic (R2): every box is copied to Python ints (nm) once, before any comparison. The old pair
# prefilter, a.GetBoundingBox().Inflate(d).Intersects(...), called Inflate on a temporary SWIG BOX2I and used
# the reference it returns after Python had freed the temporary; the read of freed memory made the prefilter
# drop C17-U17 / C17-R12 in some runs (23 / 24 / 25 lines from one file). Gaps are compared in integer nm
# (gap_nm < LIMIT_nm, no float edge) and printed rounded to 0.01 mm; each line names its pair in sorted
# reference order and all lines are sorted, so footprint order in the file (it changes per save) is not seen.
import sys, wx; wx.DisableAsserts()
import pcbnew
from pcbnew import ToMM, FromMM
b = pcbnew.LoadBoard(sys.argv[1]); LIM = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
LIM_NM = FromMM(LIM)
WX0, WX1 = (float(v) for v in (sys.argv[3] if len(sys.argv) > 3 else "130,290").split(","))
Y0, Y1, STRIP = 30.0, 130.0, 2.5
fps = sorted((f for f in b.GetFootprints() if not f.GetReference().startswith("MH")), key=lambda f: f.GetReference())
box = lambda r: (r.GetX(), r.GetY(), r.GetRight(), r.GetBottom())   # BOX2I -> (x0, y0, x1, y1) ints, nm
cy, cyb = {}, {}   # reference -> courtyard SHAPE_POLY_SET (copy), courtyard bbox or None
for f in fps:
    s = f.GetCourtyard(pcbnew.F_CrtYd)
    if s.OutlineCount() == 0: f.BuildCourtyardCaches(); s = f.GetCourtyard(pcbnew.F_CrtYd)
    s = pcbnew.SHAPE_POLY_SET(s)   # own copy: not a reference into the footprint's cache
    cy[f.GetReference()] = s; cyb[f.GetReference()] = box(s.BBox()) if s.OutlineCount() else None
bad = []
for i, a in enumerate(fps):
    for c in fps[i + 1:]:
        ba, bc = cyb[a.GetReference()], cyb[c.GetReference()]
        if ba is None or bc is None: continue
        # courtyards are rectangles here; bbox gap (0 when the boxes touch or overlap)
        dx = max(0, max(ba[0], bc[0]) - min(ba[2], bc[2]))
        dy = max(0, max(ba[1], bc[1]) - min(ba[3], bc[3]))
        g = int(round((dx * dx + dy * dy) ** 0.5))
        if g < LIM_NM: bad.append((round(ToMM(g), 2), a.GetReference(), c.GetReference()))
for g, r1, r2 in sorted(bad): print(f"gap {g:5.2f}  {r1}-{r2}")
for f in fps:
    for p in sorted((p for p in f.Pads() if p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD), key=lambda p: p.GetNumber()):
        x = ToMM(p.GetPosition().x)
        if not (WX0 <= x <= WX1): print("SMD pad outside window:", f.GetReference(), p.GetNumber(), round(x, 2)); break
for f in fps:
    bb = cyb[f.GetReference()] or box(f.GetBoundingBox())
    t, bo = ToMM(bb[1]), ToMM(bb[3])
    if t < Y0 + STRIP or bo > Y1 - STRIP: print("in long-edge strip:", f.GetReference(), round(t, 2), round(bo, 2))
# Mounting holes (excluded above): the M3 washer circle (7 mm, DIN 125) must stay out of the long-edge
# strips and off every other courtyard.
WASHER_R = 3.5
for m in sorted((f for f in b.GetFootprints() if f.GetReference().startswith("MH")), key=lambda f: f.GetReference()):
    c = m.GetPosition(); x, y = ToMM(c.x), ToMM(c.y)
    e = min(y - Y0, Y1 - y) - WASHER_R
    if e < STRIP - 1e-6: print(f"MH washer in long-edge strip: {m.GetReference()} ({x:.2f},{y:.2f}) washer {e:.2f} mm from the edge")
    for f in fps:
        s = cy[f.GetReference()]
        if s.OutlineCount() == 0: continue
        d = 0.0 if s.Contains(c) else ToMM(int(s.SquaredDistance(c) ** 0.5))
        if d < WASHER_R: print(f"MH washer on courtyard: {m.GetReference()}-{f.GetReference()} {d - WASHER_R:.2f} mm")
