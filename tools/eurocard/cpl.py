# JLC CPL for the moved board: keep each part's JLC correction (rotation offset and centroid offset in
# the footprint frame, as fixed by tools/jlc_cpl on the old board) and apply it to the new pose.
# usage: python.exe cpl.py old.kicad_pcb old_cpl.csv new.kicad_pcb new_cpl.csv
import sys, math, csv, pcbnew
from pcbnew import ToMM
old, oldcpl, new, out = sys.argv[1:5]
def poses(p):
    b = pcbnew.LoadBoard(p)
    return {f.GetReference(): (ToMM(f.GetPosition().x), ToMM(f.GetPosition().y), f.GetOrientationDegrees()) for f in b.GetFootprints()}
po, pn = poses(old), poses(new)
rows = list(csv.reader(open(oldcpl, newline="")))
w = csv.writer(open(out, "w", newline=""), quoting=csv.QUOTE_ALL, lineterminator="\n")
w.writerow(rows[0])
for ref, mx, my, layer, rot in rows[1:]:
    X, Y, A = po[ref]; X2, Y2, A2 = pn[ref]
    cx, cy = float(mx) - X, -float(my) - Y                     # centroid offset, board frame (y down)
    a = math.radians(-A)                                        # into the footprint frame (KiCad: +angle CCW)
    lx, ly = cx * math.cos(a) + cy * math.sin(a), -cx * math.sin(a) + cy * math.cos(a)
    a2 = math.radians(A2)
    nx, ny = X2 + lx * math.cos(a2) + ly * math.sin(a2), Y2 - lx * math.sin(a2) + ly * math.cos(a2)
    r = (float(rot) - A + A2) % 360
    w.writerow([ref, f"{nx:.4f}", f"{-ny:.4f}", layer, f"{r:g}"])
print(len(rows) - 1, "rows")
