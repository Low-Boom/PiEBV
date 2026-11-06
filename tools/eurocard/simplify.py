# Post-route step (KiCad python), S1: re-shape of router jogs on non-camera nets in the R9 / J10 area, electrical
# length kept by geometry. Runs after the last camera step (kilen2), before the final DRC, so no camera copper,
# stitch via or plane tap changes.
#  PIXRST_GATE - B.Cu run from its via (205, 52.4) to its via (218.3, 86.1): 45, vertical x 208.2, 45 jog,
#                vertical x 210, 45 (5 segs) becomes 45, one vertical at X, 45 (3 segs). The two 45-degree legs
#                stay on their old lines (the first starts at the via, the last ends at the via on its old line),
#                so the sum of 45-degree runs and of vertical runs is unchanged: same length, no via change.
#                X is the 0.1 mm grid position in [XLO, XHI] with the largest smallest gap to other nets (the
#                PWM_TRIG_TAP via (210.2, 57.2) and the LASER_EN_TAP via (208.0, 68.5) bound it); ties to lower X.
# A window is the run of one net / layer between two existing vertices (anchors); it is changed only if the old
# run has exactly the expected vertices. Guards on the new copper (edge to edge, same layer, tracks / vias / pad
# outlines as netgap.py): octilinear; no segment < MINSEG; no turn > 90 degrees (joints included); length
# change <= LEN_TOL; to every other net not below min(the old window's gap to that net, FLOOR) and not below
# the smallest gap the net had before (whole net); own copper > SKIP mm further along >= OWN.
# usage: python.exe simplify.py in.kicad_pcb out.kicad_pcb
import sys, math, wx; wx.DisableAsserts()
import pcbnew
from pcbnew import ToMM, FromMM

FLOOR, OWN, SKIP, MINSEG, LEN_TOL, TOL = 0.45, 0.45, 2.0, 0.3, 0.001, 0.002
b = pcbnew.LoadBoard(sys.argv[1])
LAYERS = (pcbnew.F_Cu, pcbnew.B_Cu)

# ---------- plain copper data, read once (SWIG proxies break after Remove / Add) ----------
TRK = []                            # (net, layer, (x1,y1,x2,y2) mm, halfwidth, object)
ITEMS = {}                          # net -> [(layer, halfwidth, (x1,y1,x2,y2))]: tracks, vias, pad outline edges
for t in b.GetTracks():
    n = t.GetNetname()
    if t.GetClass() == "PCB_TRACK":
        s, e = t.GetStart(), t.GetEnd(); g = (ToMM(s.x), ToMM(s.y), ToMM(e.x), ToMM(e.y))
        TRK.append((n, t.GetLayer(), g, ToMM(t.GetWidth()) / 2, t)); ITEMS.setdefault(n, []).append((t.GetLayer(), ToMM(t.GetWidth()) / 2, g))
    elif t.GetClass() == "PCB_VIA":
        x, y = ToMM(t.GetPosition().x), ToMM(t.GetPosition().y)
        for L in LAYERS:
            if t.IsOnLayer(L): ITEMS.setdefault(n, []).append((L, ToMM(t.GetWidth(L)) / 2, (x, y, x, y)))
for p in b.GetPads():
    n = p.GetNetname()
    for L in LAYERS:
        if not n or not p.IsOnLayer(L) or not p.FlashLayer(L): continue
        poly = p.GetEffectivePolygon(L, pcbnew.ERROR_OUTSIDE)
        for i in range(poly.OutlineCount()):
            ch = poly.Outline(i); k = ch.PointCount(); P = [(ToMM(ch.CPoint(j).x), ToMM(ch.CPoint(j).y)) for j in range(k)]
            ITEMS.setdefault(n, []).extend((L, 0.0, P[j] + P[(j + 1) % k]) for j in range(k))
TRK.sort(key=lambda t: (t[0], t[1], min(t[2][:2], t[2][2:]), max(t[2][:2], t[2][2:])))   # file order is not stable

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
dist = lambda p, q: math.hypot(q[0] - p[0], q[1] - p[1])
ang = lambda p, q: math.degrees(math.atan2(q[1] - p[1], q[0] - p[0]))
turn = lambda p, q, r: abs((ang(q, r) - ang(p, q) + 180) % 360 - 180)
octi = lambda p, q: min(ang(p, q) % 45, 45 - ang(p, q) % 45) < 0.05
plen = lambda P: sum(dist(p, q) for p, q in zip(P, P[1:]))
near = lambda p, q: dist(p, q) <= TOL

def netgap(layer, segs, hw, other):
    """smallest edge gap from segs (centre lines, halfwidth hw) to net 'other' on layer"""
    return min((seg_seg(s, g) - hw - h for s in segs for L, h, g in ITEMS.get(other, ()) if L == layer), default=1e9)
def fresh(segs, oldsegs):
    """parts of segs not lying on a collinear old segment (new copper only)"""
    out = []
    for s in segs:
        p, q = s[:2], s[2:]; Ls = dist(p, q); ux, uy = (q[0] - p[0]) / Ls, (q[1] - p[1]) / Ls; cut = [(0.0, Ls)]
        for o in oldsegs:
            if pt_seg(*o[:2], *p, *q) > TOL and abs((o[0] - p[0]) * uy - (o[1] - p[1]) * ux) > TOL: continue
            if abs((o[2] - o[0]) * uy - (o[3] - o[1]) * ux) > TOL or abs((o[0] - p[0]) * uy - (o[1] - p[1]) * ux) > TOL: continue
            a, c = sorted(((o[0] - p[0]) * ux + (o[1] - p[1]) * uy, (o[2] - p[0]) * ux + (o[3] - p[1]) * uy))
            cut = [r for lo, hi in cut for r in ((lo, min(hi, a)), (max(lo, c), hi)) if r[1] - r[0] > TOL]
        out += [(p[0] + ux * lo, p[1] + uy * lo, p[0] + ux * hi, p[1] + uy * hi) for lo, hi in cut]
    return out
def netmin(net):
    """smallest edge gap from all copper of net to any other net, same layer (before this step)"""
    mine = ITEMS.get(net, ())
    return min((seg_seg(g1, g2) - h1 - h2 for o, its in ITEMS.items() if o and o != net
                for L2, h2, g2 in its for L1, h1, g1 in mine if L1 == L2), default=1e9)

# ---------- runs ----------
def run_of(net, layer, P):
    """ordered vertex list and track objects of the net's run on layer that passes through point P"""
    segs = [t for t in TRK if t[0] == net and t[1] == layer]; at = {}
    k = lambda x, y: (round(x, 4), round(y, 4)); raw = {}
    for t in segs:
        g = t[2]
        for e in (g[:2], g[2:]): at.setdefault(k(*e), []).append(t); raw.setdefault(k(*e), e)
    hit = [v for v in at if math.hypot(v[0] - P[0], v[1] - P[1]) <= TOL]
    if not hit: return None
    ends = [v for v, ts in at.items() if len(ts) != 2]
    for e0 in sorted(ends):
        pts, objs, cur, used = [e0], [], e0, set()
        while True:
            nxt = [t for t in at[cur] if id(t) not in used]
            if not nxt or (len(at[cur]) > 2 and cur != e0): break
            t = nxt[0]; used.add(id(t)); objs.append(t); g = t[2]
            cur = k(*g[2:]) if k(*g[:2]) == cur else k(*g[:2]); pts.append(cur)
            if len(at[cur]) != 2: break
        if hit[0] in pts: return [raw[v] for v in pts], objs
    return None

# ---------- windows: (net, layer, old vertices (anchors first / last), shape(old, X) -> new vertices, X range) ----------
def pix_shape(old, X):        # 45 from A on its old line to x X, vertical, 45 on B's old line into B
    A, B = old[0], old[-1]
    sa = 1 if old[1][1] > A[1] else -1                    # y direction of the first 45 leg (x increases)
    sb = 1 if B[1] > old[-2][1] else -1                   # y direction of the last 45 leg
    P1 = (X, A[1] + sa * (X - A[0])); P2 = (X, B[1] - sb * (B[0] - X))
    return [A, P1, P2, B]
WINDOWS = [("PIXRST_GATE", pcbnew.B_Cu,
            [(205.0, 52.4), (208.2, 55.6), (208.2, 57.9), (210.0, 59.7), (210.0, 77.8), (218.3, 86.1)],
            pix_shape, (208.6, 209.6))]

edits = []
for net, L, OLD, shape, (XLO, XHI) in WINDOWS:
    r = run_of(net, L, OLD[0]); why = []
    if not r: print(f"simplify {net}: anchors not found, LEFT AS IS"); continue
    pts, objs = r
    f = lambda P: next((i for i, v in enumerate(pts) if near(v, P)), None)
    i, j = f(OLD[0]), f(OLD[-1])
    if i is None or j is None: print(f"simplify {net}: anchors not found, LEFT AS IS"); continue
    if i > j: pts, objs = pts[::-1], objs[::-1]; i, j = len(pts) - 1 - i, len(pts) - 1 - j
    old = pts[i:j + 1]
    if len(old) != len(OLD) or not all(near(p, q) for p, q in zip(old, OLD)):
        print(f"simplify {net}: run is not the expected {len(OLD) - 1} segments, LEFT AS IS"); continue
    hw = objs[i][3]; Lold = plen(old); oldsegs = [old[k] + old[k + 1] for k in range(len(old) - 1)]
    span = oldsegs + [s for X in (XLO, XHI) for P in [shape(old, X)] for s in (P[k] + P[k + 1] for k in range(len(P) - 1))]
    others = sorted(n for n in ITEMS if n and n != net and netgap(L, span, hw, n) < 5)   # nets near old or any new run
    g0 = {n: netgap(L, oldsegs, hw, n) for n in others}; nmin = netmin(net)
    best = None                                            # 0.1 mm grid scan, largest smallest gap of the new copper
    for m in range(round(XLO * 10), round(XHI * 10) + 1):  # (parts not on an old segment); ties to lower X
        X = m / 10; new = shape(old, X); segs = fresh([new[k] + new[k + 1] for k in range(len(new) - 1)], oldsegs)
        g = min(netgap(L, segs, hw, n) for n in others)
        if best is None or g > best[0] + 1e-9: best = (g, X)
    X = best[1]; new = shape(old, X); segs = [new[k] + new[k + 1] for k in range(len(new) - 1)]
    full = pts[:i] + new + pts[j + 1:]; dl = plen(new) - Lold
    if any(not octi(new[k], new[k + 1]) for k in range(len(new) - 1)): why.append("not octilinear")
    if any(dist(new[k], new[k + 1]) < MINSEG for k in range(len(new) - 1)): why.append("segment < %.1f mm" % MINSEG)
    if any(turn(full[k - 1], full[k], full[k + 1]) > 90.01 for k in range(max(1, i), min(len(full) - 1, i + len(new)))): why.append("turn > 90")
    if abs(dl) > LEN_TOL: why.append("length %+.4f" % dl)
    msgs = []
    for n in others:
        g = netgap(L, segs, hw, n); need = max(min(g0[n], FLOOR), min(nmin, g0[n]))
        msgs.append(f"   {net} - {n}: window gap {g0[n]:.3f} -> {g:.3f} (need {need:.3f})")
        if g < need - 1e-4: why.append(f"gap to {n} {g:.3f} < {need:.3f}")
    cum = [0.0]
    for p, q in zip(full, full[1:]): cum.append(cum[-1] + dist(p, q))
    for k in range(i, i + len(new) - 1):                   # own copper of the run
        for m in range(len(full) - 1):
            sep = cum[m] - cum[k + 1] if m > k else cum[k] - cum[m + 1]
            if sep > SKIP and seg_seg(full[k] + full[k + 1], full[m] + full[m + 1]) - 2 * hw < OWN - 1e-4: why.append("own gap"); break
    print(f"simplify {net} {b.GetLayerName(L)}: " + ("applied" if not why else "LEFT AS IS: " + ", ".join(why)))
    print(f"   {len(old) - 1} -> {len(new) - 1} segs, vertical x {X:.1f}, run {Lold:.4f} -> {plen(new):.4f} mm ({dl:+.4f}); "
          f"net's smallest gap before {nmin:.3f}, new copper's smallest {best[0]:.3f}")
    for m in msgs: print(m)
    if not why: edits.append((net, L, hw, objs[i:j], new))
for net, L, hw, objs, new in edits:                         # edit the board only now
    code = b.GetNetcodeFromNetname(net)
    for o in objs: b.Remove(o[4])
    for p, q in zip(new, new[1:]):
        t = pcbnew.PCB_TRACK(b); t.SetStart(pcbnew.VECTOR2I(FromMM(p[0]), FromMM(p[1]))); t.SetEnd(pcbnew.VECTOR2I(FromMM(q[0]), FromMM(q[1])))
        t.SetWidth(FromMM(2 * hw)); t.SetLayer(L); t.SetNetCode(code); b.Add(t)
print(f"simplify: {len(edits)} windows changed")
pcbnew.SaveBoard(sys.argv[2], b)
