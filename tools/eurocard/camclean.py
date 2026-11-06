# Post-route step (KiCad python), U1: clean the router artefacts of the matched camera lines, length kept.
# Three edits per line, each on one layer run (pad / via / branch to pad / via / branch):
#  caps    - a meander cap of two short stubs (KRT's chamfered cap; on a 45-degree base it shows as an
#            orthogonal "L") becomes one straight cap, with both arms longer by the same amount, so the cap
#            keeps its length and the comb its 0.75 mm pitch (gap between arms unchanged, 90-degree turns);
#  windows - a staircase (>= 3 consecutive segments < 1 mm) or an acute corner (turn > 90 degrees, legs
#            whose copper meets at the apex) becomes 0-2 octilinear segments; the window ends may slide
#            along the adjoining segments, a pad end may move to the pad centre (ends.py trims it back to
#            the pad edge); no turn may exceed 90 degrees; one window changes the length by <= WIN_TOL;
#  length  - the line's pad-edge length (the ends.py metric) is put back by moving all caps of the
#            line (all its runs) outward or inward by one small distance. A line without caps may change by
#            <= 0.15 mm and must stay within its group's shortest-to-longest range before this step.
# Guards: only the given nets. Gaps are edge to edge on one layer, to pads, vias and tracks, measured before
# this step ("before"). New copper of a line keeps: to a line of another camera group (Sync / Trigger /
# TDRSTN), the smallest gap between the two groups before; to a STRICT net (laser pulse lanes, PWM_1MHz,
# SYNC_N), its smallest gap to that net before; to any other net, the smaller of its gap before and FLOOR.
# To its own copper more than 2 mm further along the line: >= 0.45 mm (the meander arm gap). A line that
# fails a check is left as it was.
# --protect P: never change a segment of board P. --dry: report only. Run ends.py again after this step:
# it trims a pad end that a new segment reaches through the pad (the length here is measured that way).
# --trim BEFORE AFTER (kilen.py files): only move the caps of each line with caps by the difference KiCad reads
# (AFTER - BEFORE); KiCad's length of a re-shaped meander can differ from its centre-line sum by up to ~0.1 mm.
# usage: python.exe camclean.py in.kicad_pcb out.kicad_pcb [--dry] [--protect P] [--trim A B] "Sync?" "Trigger?" "TDRSTN?"
import sys, math, fnmatch, wx; wx.DisableAsserts()
import pcbnew
from collections import defaultdict
from pcbnew import ToMM, FromMM

SHORT, MINRUN = 1.0, 3              # staircase: >= MINRUN consecutive segments shorter than SHORT (mm)
ARM, OWN, SKIP = 1.0, 0.45, 2.0     # arm: >= ARM mm; own-copper gap OWN for copper > SKIP mm along the line
NOCAP_TOL, MAXSHIFT = 0.15, 0.6     # length budget of a line without caps; largest cap shift (mm)
CAP_TOL, LENW = 2.0, 2.0            # length budget of a line with caps (mm); ranking weight per mm of change
WIN_TOL = 0.7                       # largest length change of one window (mm): a window must not cut off a meander
R = 5.0                             # search radius for other-net copper (mm)
FLOOR = 0.21                        # new copper to other nets: 0.01 mm over the 0.20 mm clearance the router used
STRICT = ["_PULSE_OUT_*", "PWM_1MHz", "SYNC_N"]
EPS = 1e-4

a = sys.argv[1:]; dry = "--dry" in a; a = [x for x in a if x != "--dry"]
prot_path = None
if "--protect" in a:
    i = a.index("--protect"); prot_path = a[i + 1]; del a[i:i + 2]
TRIM = None
if "--trim" in a:
    i = a.index("--trim"); rd = lambda f: {l.split()[0]: float(l.split()[1]) for l in open(f) if l.strip()}
    A_, B_ = rd(a[i + 1]), rd(a[i + 2]); TRIM = {n: B_[n] - A_[n] for n in A_ if n in B_}; del a[i:i + 3]
src, dst, pats = a[0], a[1], a[2:]
b = pcbnew.LoadBoard(src)
LAYERS = (pcbnew.F_Cu, pcbnew.B_Cu)
# All measuring is done on plain data read here; the board is edited only at the end (SWIG proxies of
# tracks, pads and polygons stop working after a Remove / Add).
TRK, VIA = [], []                   # tracks: net, code, layer, (x1,y1,x2,y2) nm, width nm, object; vias: net, code, x, y mm, {layer: r}
for t in b.GetTracks():
    if t.GetClass() == "PCB_TRACK":
        s_, e_ = t.GetStart(), t.GetEnd()
        TRK.append((t.GetNetname(), t.GetNetCode(), t.GetLayer(), (s_.x, s_.y, e_.x, e_.y), t.GetWidth(), t))
    elif t.GetClass() == "PCB_VIA":
        VIA.append((t.GetNetname(), t.GetNetCode(), ToMM(t.GetPosition().x), ToMM(t.GetPosition().y),
                    {L: ToMM(t.GetWidth(L)) / 2 for L in LAYERS if t.IsOnLayer(L)}))
# Canonical order: KiCad writes items in a different order on each build, and the edits below are order
# dependent (run order, run direction), so tracks are sorted here and runs are oriented and sorted below.
TRK.sort(key=lambda t: (t[0], t[2], min(t[3][:2], t[3][2:]), max(t[3][:2], t[3][2:]), t[4]))
VIA.sort(key=lambda v: (v[0], v[2], v[3]))
LIVE = defaultdict(list)            # net -> [(layer, (x1,y1,x2,y2) mm, halfwidth)]: track copper as edited so far
for n, c, L, g, w, o in TRK: LIVE[n].append((L, tuple(ToMM(v) for v in g), ToMM(w) / 2))

def key(x1, y1, x2, y2, lay, net):
    s, e = (round(x1, 3), round(y1, 3)), (round(x2, 3), round(y2, 3)); return (lay, net, min(s, e), max(s, e))
protect = set()
if prot_path:
    pb = pcbnew.LoadBoard(prot_path)
    for t in pb.GetTracks():
        if t.GetClass() == "PCB_TRACK":
            s, e = t.GetStart(), t.GetEnd(); protect.add(key(ToMM(s.x), ToMM(s.y), ToMM(e.x), ToMM(e.y), t.GetLayer(), t.GetNetname()))

# ---------- geometry ----------
def pt_seg(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1; L2 = dx * dx + dy * dy
    if L2 == 0: return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / L2))
    return math.hypot(px - x1 - dx * t, py - y1 - dy * t)
def seg_seg(s, q):
    x1, y1, x2, y2 = s; x3, y3, x4, y4 = q
    d1x, d1y, d2x, d2y = x2 - x1, y2 - y1, x4 - x3, y4 - y3; den = d1x * d2y - d1y * d2x
    if den != 0:
        t = ((x3 - x1) * d2y - (y3 - y1) * d2x) / den; u = ((x3 - x1) * d1y - (y3 - y1) * d1x) / den
        if 0 <= t <= 1 and 0 <= u <= 1: return 0.0
    return min(pt_seg(x1, y1, *q), pt_seg(x2, y2, *q), pt_seg(x3, y3, *s), pt_seg(x4, y4, *s))
def ang(p, q): return math.degrees(math.atan2(q[1] - p[1], q[0] - p[0]))
def turn(p, q, r): return abs((ang(q, r) - ang(p, q) + 180) % 360 - 180)
def octi(p, q): a_ = ang(p, q) % 45; return min(a_, 45 - a_) < 0.05
def dist(p, q): return math.hypot(q[0] - p[0], q[1] - p[1])
def unit(p, q): L = dist(p, q); return ((q[0] - p[0]) / L, (q[1] - p[1]) / L)
DIRS = [(math.cos(math.radians(45 * k)), math.sin(math.radians(45 * k))) for k in range(8)]

# ---------- other-net copper (index) and original per-net-pair minimum gaps ----------
def copper(net_filter):
    """[(net, layer, (x1,y1,x2,y2), halfwidth)] for tracks, vias and pad outline edges, mm"""
    out = [(n, L, (x, y, x, y), r) for n, c, x, y, rs in VIA if n and net_filter(n) for L, r in rs.items()]
    out += [(n, L, g, h) for n in LIVE if n and net_filter(n) for L, g, h in LIVE[n]]
    return out + [it for it in PAD_EDGES if net_filter(it[0])]
def outline(p, L, err):
    poly = p.GetEffectivePolygon(L, err)
    for i in range(poly.OutlineCount()):
        ch = poly.Outline(i); yield [(ToMM(ch.CPoint(j).x), ToMM(ch.CPoint(j).y)) for j in range(ch.PointCount())]
# pads do not change here; read their shapes once, before any edit (SWIG pad / polygon proxies break after one)
PAD_EDGES, PAD_POLY = [], defaultdict(list)       # outline edges (ERROR_OUTSIDE); (netcode, layer) -> polygons
for p in [p for f in b.GetFootprints() for p in f.Pads()]:
    n = p.GetNetname()
    for L in LAYERS:
        if not n or not p.IsOnLayer(L) or not p.FlashLayer(L): continue
        for P in outline(p, L, pcbnew.ERROR_OUTSIDE):
            PAD_EDGES.extend((n, L, P[j] + P[(j + 1) % len(P)], 0.0) for j in range(len(P)))
        for P in outline(p, L, pcbnew.ERROR_INSIDE):            # polygon with its bounding box and the pad centre
            PAD_POLY[(p.GetNetCode(), L)].append((P, min(x for x, y in P), min(y for x, y in P), max(x for x, y in P), max(y for x, y in P),
                                                  (ToMM(p.GetPosition().x), ToMM(p.GetPosition().y))))
class Index:
    def __init__(s, items, cell=2.0):
        s.c = cell; s.g = defaultdict(list)
        for it in items:
            x1, y1, x2, y2 = it[2]; r = it[3]
            for gx in range(int((min(x1, x2) - r) // cell), int((max(x1, x2) + r) // cell) + 1):
                for gy in range(int((min(y1, y2) - r) // cell), int((max(y1, y2) + r) // cell) + 1):
                    s.g[(it[1], gx, gy)].append(it)
    def near(s, lay, seg, rad):
        x1, y1, x2, y2 = seg; seen = set()
        for gx in range(int((min(x1, x2) - rad) // s.c), int((max(x1, x2) + rad) // s.c) + 1):
            for gy in range(int((min(y1, y2) - rad) // s.c), int((max(y1, y2) + rad) // s.c) + 1):
                for it in s.g.get((lay, gx, gy), ()):
                    if id(it) not in seen: seen.add(id(it)); yield it

nets = sorted(n for n in map(str, b.GetNetsByName().keys()) if any(fnmatch.fnmatchcase(n, p) for p in pats))
ALL0 = copper(lambda n: True)                                   # original copper, all nets
by_net0 = defaultdict(list)
for it in ALL0: by_net0[it[0]].append(it)
IDX0 = Index(ALL0)
pairmin = {}
def before(net, other):
    """smallest gap between net and other before this step (same layer; 1e9 if more than R)"""
    k = (net, other) if net < other else (other, net)
    if k not in pairmin:
        best = 1e9
        for n_, L, s, h in by_net0[net]:
            for it in IDX0.near(L, s, R + h):
                if it[0] == other: best = min(best, seg_seg(s, it[2]) - h - it[3])
        pairmin[k] = best
    return pairmin[k]
group = lambda n: n.rstrip("0123456789") if n in nets else None
GROUPS = sorted({group(n) for n in nets}); groupmin = {}
for g1 in GROUPS:
    for g2 in GROUPS:
        if g1 < g2: groupmin[(g1, g2)] = groupmin[(g2, g1)] = min(before(x, y) for x in nets if group(x) == g1 for y in nets if group(y) == g2)
reqc = {}
def req(net, other):
    """the smallest gap new copper of net may have to other"""
    if (net, other) not in reqc:
        g1, g2 = group(net), group(other)
        if g2 is not None and g1 != g2: r = groupmin[(g1, g2)]
        elif any(fnmatch.fnmatchcase(other, p) for p in STRICT): r = before(net, other)
        else: r = min(before(net, other), FLOOR)
        reqc[(net, other)] = r
    return reqc[(net, other)]

# ---------- per-net chain model ----------
def runs_of(code):
    segs = [t for t in TRK if t[1] == code]
    at = defaultdict(list)
    for t in segs:
        g = t[3]
        for e in ((g[0], g[1]), (g[2], g[3])): at[(e[0], e[1], t[2])].append(t)
    used, runs = set(), []
    for k0, ts in sorted(at.items(), key=lambda kv: kv[0]):
        if len(ts) == 2: continue
        for t0 in ts:
            if id(t0) in used: continue
            pts, objs, node, cur = [k0[:2]], [], k0, t0
            while True:
                used.add(id(cur)); objs.append(cur); g = cur[3]
                nxt = (g[2], g[3], node[2]) if (g[0], g[1]) == node[:2] else (g[0], g[1], node[2])
                pts.append(nxt[:2]); node = nxt
                if len(at[nxt]) != 2: break
                cur = [u for u in at[nxt] if u is not cur][0]
                if id(cur) in used: break
            runs.append({"layer": k0[2], "objs": objs, "w": ToMM(objs[0][4]),
                         "pts": [(ToMM(x), ToMM(y)) for x, y in pts]})
    if len(used) != len(segs): return None                      # a loop: not a simple line, leave it
    for r in runs:                                              # first point the smaller one; runs sorted
        if r["pts"][0] > r["pts"][-1]: r["pts"].reverse(); r["objs"].reverse()
    runs.sort(key=lambda r: (r["layer"], r["pts"][0], r["pts"][-1]))
    return runs

def pad_polys(code, lay): return PAD_POLY[(code, lay)]
def inside(polys, p):
    """even-odd ray test; a point within 0.01 mm of the outline counts as inside (an ends.py end sits 5 um
    inside the true pad edge, which can be outside the polygon's chords)"""
    x, y = p
    for P, x0, y0, x1_, y1_, _ in polys:
        if not (x0 - 0.01 <= x <= x1_ + 0.01 and y0 - 0.01 <= y <= y1_ + 0.01): continue
        c = False
        for (x1, y1), (x2, y2) in zip(P, P[1:] + P[:1]):
            if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1): c = not c
        if c or any(pt_seg(x, y, x1, y1, x2, y2) < 0.01 for (x1, y1), (x2, y2) in zip(P, P[1:] + P[:1])): return True
    return False
INPAD = {}
def inpad(pts, polys):
    """in-pad centre-line length from pts[0] while the line stays in the pad that holds pts[0]"""
    k = (tuple(pts[:3]), id(polys))                             # cached: candidates share their pad-end segments
    if k in INPAD: return INPAD[k]
    tot = 0.0
    if inside(polys, pts[0]):
        for p, q in zip(pts, pts[1:]):
            if inside(polys, q): tot += dist(p, q); continue
            lo, hi = 0.0, 1.0
            for _ in range(30):
                m = (lo + hi) / 2
                if inside(polys, (p[0] + (q[0] - p[0]) * m, p[1] + (q[1] - p[1]) * m)): lo = m
                else: hi = m
            tot += dist(p, q) * lo; break
    INPAD[k] = tot
    return tot
def pad_at(polys, p):
    """centre of the own pad that holds point p, or None"""
    return next((c for P in polys for c in [P[5]] if inside([P], p)), None)
def eff_len(pts, polys):
    return sum(dist(p, q) for p, q in zip(pts, pts[1:])) - inpad(pts, polys) - inpad(pts[::-1], polys)

# ---------- checks ----------
def other_ok(net, lay, segs, w, IDX):
    for s in segs:
        for it in IDX.near(lay, s, R + w / 2):
            if it[0] == net: continue
            g = seg_seg(s, it[2]) - w / 2 - it[3]
            if g < R and g < req(net, it[0]) - EPS: return False
    return True
def own_ok(pts, w, lo, hi, others):
    """segments lo..hi-1 of polyline pts vs the polyline's segments more than SKIP away along it, and others"""
    cum = [0.0]
    for p, q in zip(pts, pts[1:]): cum.append(cum[-1] + dist(p, q))
    for i in range(lo, hi):
        s = pts[i] + pts[i + 1]
        for j in range(len(pts) - 1):
            if j == i: continue
            sep = cum[j] - cum[i + 1] if j > i else cum[i] - cum[j + 1]
            if sep <= SKIP: continue
            if seg_seg(s, pts[j] + pts[j + 1]) - w < OWN - EPS: return False
        for o in others:
            if seg_seg(s, o) - w < OWN - EPS: return False
    return True
def clean_pts(pts):
    out = [pts[0]]
    for p in pts[1:]:
        if dist(out[-1], p) > 1e-6: out.append(p)
    k = 1
    while k < len(out) - 1:                                     # merge collinear same-direction neighbours
        if turn(out[k - 1], out[k], out[k + 1]) < 0.01: del out[k]
        else: k += 1
    return out
def score(pts):
    sc = 0.0
    for p, q in zip(pts, pts[1:]):
        L = dist(p, q); sc += 3 + (3 if L < 0.5 else 0) + (2 if not octi(p, q) else 0)
    for k in range(1, len(pts) - 1):
        t = turn(pts[k - 1], pts[k], pts[k + 1]); sc += 5 if t > 90.5 else (1 if t > 45.5 else 0)
    return sc

# ---------- caps ----------
def caps(pts):
    """[(a, b)]: segment a (arm), short stubs, segment b anti-parallel arm; cap vertices a+1..b"""
    L = [dist(p, q) for p, q in zip(pts, pts[1:])]; out = []
    for i in range(len(L)):
        if L[i] < ARM: continue
        for nb in (1, 2):
            j = i + nb + 1
            if j < len(L) and all(L[k] < SHORT for k in range(i + 1, j)) and L[j] >= ARM:
                u, v = unit(pts[i], pts[i + 1]), unit(pts[j], pts[j + 1])
                if u[0] * v[0] + u[1] * v[1] < -0.9999: out.append((i, j)); break
    return out
def shift_cap(pts, cap, d):
    i, j = cap; u = unit(pts[i], pts[i + 1])
    return pts[:i + 1] + [(p[0] + u[0] * d, p[1] + u[1] * d) for p in pts[i + 1:j + 1]] + pts[j + 1:]
def square_cap(pts, cap):
    i, j = cap
    if j - i != 3: return None                                  # two stubs only
    A, B = pts[i + 1], pts[j]; u = unit(pts[i], pts[i + 1])
    if not octi(A, B) or abs(u[0] * (B[0] - A[0]) + u[1] * (B[1] - A[1])) > 1e-3: return None
    d = (dist(pts[i + 1], pts[i + 2]) + dist(pts[i + 2], pts[j]) - dist(A, B)) / 2
    return pts[:i + 1] + [(A[0] + u[0] * d, A[1] + u[1] * d), (B[0] + u[0] * d, B[1] + u[1] * d)] + pts[j + 1:]

# ---------- windows ----------
def windows(pts, fixed):
    L = [dist(p, q) for p, q in zip(pts, pts[1:])]; W = []
    i = 0
    while i < len(L):
        j = i
        while j < len(L) and L[j] < SHORT: j += 1
        if j - i >= MINRUN: W.append((i, j))
        i = max(j, i + 1)
    for k in range(1, len(pts) - 1):
        if turn(pts[k - 1], pts[k], pts[k + 1]) > 90.5: W.append((k - 1, k + 1))
    W.sort(); out = []
    for w in W:                                                 # merge overlapping windows
        if out and w[0] <= out[-1][1]: out[-1] = (out[-1][0], max(out[-1][1], w[1]))
        else: out.append(w)
    return [w for w in out if not any(f in fixed for f in range(w[0] + 1, w[1]))]
def line_x(p, u, q, v):
    """t, s with p + t u = q + s v, or None if parallel"""
    den = u[0] * v[1] - u[1] * v[0]
    if abs(den) < 1e-9: return None
    dx, dy = q[0] - p[0], q[1] - p[1]
    return (dx * v[1] - dy * v[0]) / den, (dx * u[1] - dy * u[0]) / den
def candidates(pts, i, j, fixed):
    n = len(pts) - 1
    slideP = i > 0 and i not in fixed                         # the window end may move along the adjoining segment
    slideQ = j < n and j not in fixed
    P, Q = pts[i], pts[j]
    up = unit(pts[i - 1], P) if i > 0 else None; uq = unit(Q, pts[j + 1]) if j < n else None
    Lp = dist(pts[i - 1], P) if i > 0 else 0; Lq = dist(Q, pts[j + 1]) if j < n else 0
    tr = (-(Lp - 0.1), 2.0) if slideP else (0, 0); sr = (-2.0, Lq - 0.1) if slideQ else (0, 0)
    okT = lambda t: tr[0] - 1e-9 <= t <= tr[1] + 1e-9; okS = lambda s: sr[0] - 1e-9 <= s <= sr[1] + 1e-9
    Pt = lambda t: (P[0] + up[0] * t, P[1] + up[1] * t) if t else P
    Qs = lambda s: (Q[0] + uq[0] * s, Q[1] + uq[1] * s) if s else Q
    grid = lambda r, st: sorted({0.0} | {round(r[0] + st * k, 6) for k in range(int((r[1] - r[0]) / st) + 1)})
    out = []
    if slideP and slideQ:                                       # (A) meet at the two lines' crossing
        x = line_x(P, up, Q, uq)
        if x and okT(x[0]) and okS(x[1]): out.append([Pt(x[0])])
    for d in DIRS:                                              # (B) one octilinear segment P' -> Q'
        if slideP and slideQ:
            for t in grid(tr, 0.05):
                x = line_x(Pt(t), d, Q, uq)
                if x and x[0] > 0.05 and okS(x[1]): out.append([Pt(t), Qs(x[1])])
        elif slideP:                                            # Q fixed: P' where the ray to Q meets the line
            x = line_x(P, up, Q, (-d[0], -d[1]))
            if x and x[1] > 0.05 and okT(x[0]): out.append([Pt(x[0]), Q])
        elif slideQ:
            x = line_x(P, d, Q, uq)
            if x and x[0] > 0.05 and okS(x[1]): out.append([P, Qs(x[1])])
        elif octi(P, Q) and abs(ang(P, Q) - math.degrees(math.atan2(d[1], d[0]))) % 360 < 0.05:
            out.append([P, Q])
    for t in (grid(tr, 0.1) if slideP else [0.0]):              # (C) two octilinear segments
        for s in (grid(sr, 0.1) if slideQ else [0.0]):
            A, B = Pt(t), Qs(s); dx, dy = B[0] - A[0], B[1] - A[1]; m = min(abs(dx), abs(dy))
            sx, sy = math.copysign(1, dx), math.copysign(1, dy)
            for C in ((A[0] + sx * m, A[1] + sy * m), (B[0] - sx * m, B[1] - sy * m)):
                if dist(A, C) > 0.05 and dist(C, B) > 0.05: out.append([A, C, B])
    return [clean_pts(pts[:i] + mid + pts[j + 1:]) for mid in out]   # mid replaces pts[i..j]

# ---------- main ----------
# Line length as KiCad reads it after ends.py: pad-edge centre line + a constant per via. Used for the group
# bounds of a line without caps (it may not leave its group's [shortest, longest] before this step).
VIAH = ToMM(b.GetDesignSettings().GetBoardThickness())
def ctx_of(net):
    code = b.GetNetcodeFromNetname(net); runs = runs_of(code)
    if runs is None: return None
    vp = {(round(v[2], 4), round(v[3], 4)) for v in VIA if v[1] == code}
    for r in runs:
        r["polys"] = pad_polys(code, r["layer"])
        r["fixed"] = lambda pts, r=r: {0, len(pts) - 1} | {k for k, p in enumerate(pts) if (round(p[0], 4), round(p[1], 4)) in vp or inside(r["polys"], p)}
        r["e0"] = eff_len(r["pts"], r["polys"])
        r["prot"] = {j for k, o in enumerate(r["objs"]) if key(*(ToMM(v) for v in o[3]), r["layer"], net) in protect for j in (k, k + 1)}
    return {"code": code, "runs": runs, "len0": sum(r["e0"] for r in runs) + VIAH * len(vp)}
CTX = {n: ctx_of(n) for n in nets}
bounds = {}
for g in GROUPS:
    L = [CTX[n]["len0"] for n in nets if group(n) == g and CTX[n]]
    for n in nets:
        if group(n) == g and CTX[n]: bounds[n] = (max(-NOCAP_TOL, min(L) - CTX[n]["len0"] + 0.02), min(NOCAP_TOL, max(L) - CTX[n]["len0"] - 0.02))

def valid(net, r, IDX, others_same, cur, new):
    """new replaces polyline cur of run r: turns, octilinear new segments, other-net and own-copper gaps"""
    lo = 0
    while lo < min(len(new), len(cur)) and new[lo] == cur[lo]: lo += 1
    hi = 0
    while hi < min(len(new), len(cur)) - lo and new[-1 - hi] == cur[-1 - hi]: hi += 1
    a_, b_ = max(0, lo - 1), min(len(new) - 1, len(new) - hi)     # changed segments a_..b_-1
    if any(turn(new[k - 1], new[k], new[k + 1]) > 90.5 for k in range(max(1, a_), min(len(new) - 1, b_ + 1))): return False
    old = set(zip(cur, cur[1:]))
    if any(not octi(new[k], new[k + 1]) for k in range(a_, b_) if (new[k], new[k + 1]) not in old): return False
    return other_ok(net, r["layer"], [new[k] + new[k + 1] for k in range(a_, b_)], r["w"], IDX) and own_ok(new, r["w"], a_, b_, others_same)

report, changed, edits = [], 0, []
for net in nets:
    C_ = CTX[net]
    if C_ is None: report.append(f"{net:9s} skipped: not a simple line"); continue
    code, runs = C_["code"], C_["runs"]
    IDX = Index(copper(lambda n: n != net))                     # live: lines edited earlier in this run included
    others = {id(r): [q["pts"][k] + q["pts"][k + 1] for q in runs if q is not r and q["layer"] == r["layer"] for k in range(len(q["pts"]) - 1)] for r in runs}
    cur = {id(r): r["pts"] for r in runs}
    ok_w = {id(r): all(abs(ToMM(o[4]) - r["w"]) < 1e-6 for o in r["objs"]) for r in runs}
    dl = lambda: sum(eff_len(cur[id(r)], r["polys"]) - r["e0"] for r in runs)
    has_caps = any(caps(r["pts"]) for r in runs if ok_w[id(r)])
    lo_b, hi_b = (-CAP_TOL, CAP_TOL) if has_caps else bounds[net]
    st = {id(r): [0, 0] for r in runs}                          # caps squared, windows
    if TRIM is not None and (not has_caps or abs(TRIM.get(net, 0)) < 0.002): continue
    for r in runs:
        if not ok_w[id(r)] or TRIM is not None: continue
        V = lambda c, n_, r=r: valid(net, r, IDX, others[id(r)], c, n_)
        fixed = r["fixed"](r["pts"]) | r["prot"]
        for cap in reversed(caps(cur[id(r)])):                  # 1. caps (length kept)
            if any(f in fixed for f in range(cap[0], cap[1] + 2)): continue
            new = square_cap(cur[id(r)], cap)
            if new and V(cur[id(r)], new): cur[id(r)] = new; st[id(r)][0] += 1
        tried = set()
        for _ in range(60):                                     # 2. windows
            c = cur[id(r)]; fixed_c = r["fixed"](c) | (r["prot"] if c is r["pts"] else set())
            W = [w_ for w_ in windows(c, fixed_c) if (c[w_[0]], c[w_[1]]) not in tried]
            if not W: break
            i, j = W[0]; tried.add((c[i], c[j]))
            lo_, hi_ = max(0, i - 1), min(len(c) - 1, j + 1); old_sc = score(c[lo_:hi_ + 1])
            base = dl() - (eff_len(c, r["polys"]) - r["e0"]); ranked = []
            alt = []                                            # a pad end may also go to the pad centre (ends.py trims it)
            if j == len(c) - 1 and pad_at(r["polys"], c[j]): alt += candidates(c[:-1] + [pad_at(r["polys"], c[j])], i, j, fixed_c)
            if i == 0 and pad_at(r["polys"], c[0]): alt += candidates([pad_at(r["polys"], c[0])] + c[1:], i, j, fixed_c)
            for new in candidates(c, i, j, fixed_c) + alt:
                e_new = eff_len(new, r["polys"]); d_win = e_new - eff_len(c, r["polys"]); d_net = base + e_new - r["e0"]
                if not (lo_b <= d_net <= hi_b) or abs(d_win) > WIN_TOL: continue
                sc = score(new[lo_:len(new) - (len(c) - hi_) + 1]) + LENW * abs(d_win)
                if sc < old_sc - 0.5: ranked.append((sc, new))
            for sc, new in sorted(ranked, key=lambda x: x[0]):
                if V(c, new): cur[id(r)] = new; st[id(r)][1] += 1; break
    # 3. length, per line: all caps of all runs move out (or in) by one distance
    d0 = dl() if TRIM is None else TRIM[net]; target = 0.0 if TRIM is None else -TRIM[net]   # centre-line change wanted
    nshift, dshift, ok = 0, 0.0, True
    if abs(d0) > 0.005 and has_caps:
        C = [(r, cp) for r in runs if ok_w[id(r)] for cp in caps(cur[id(r)]) if not any(f in r["fixed"](cur[id(r)]) for f in range(cp[0], cp[1] + 2))]
        while C:
            d = -d0 / (2 * len(C))
            if abs(d) > MAXSHIFT: C = []; break
            trial = dict(cur)
            for r, cp in C: trial[id(r)] = shift_cap(trial[id(r)], cp, d)
            if all(trial[id(r)] is cur[id(r)] or valid(net, r, IDX, others[id(r)], cur[id(r)], trial[id(r)]) for r in runs):
                cur = trial; nshift, dshift = len(C), d; break
            bad = next(((r, cp) for r, cp in C if not valid(net, r, IDX, others[id(r)], cur[id(r)], shift_cap(cur[id(r)], cp, d))), C[-1])
            C.remove(bad)
    d1 = dl()
    if has_caps and abs(d1 - target) > 0.005 or not has_caps and not (bounds[net][0] - 1e-9 <= d1 <= bounds[net][1] + 1e-9):
        report.append(f"{net:9s} LEFT AS IS: length {d1:+.3f} mm not restored"); continue
    parts = [f"{b.GetLayerName(r['layer'])} {len(r['pts']) - 1}->{len(cur[id(r)]) - 1} segs" + (f" (caps {st[id(r)][0]}, windows {st[id(r)][1]})" if cur[id(r)] is not r["pts"] else "") for r in runs]
    report.append(f"{net:9s} " + ("trim KiCad %+.4f mm: " % TRIM[net] if TRIM is not None else "") + ", ".join(parts) + f"; caps shifted {nshift} x {dshift:+.3f} mm; length {d1:+.4f} mm")
    LIVE[net] = []
    for r in runs:
        pts = cur[id(r)]
        LIVE[net] += [(r["layer"], p + q, r["w"] / 2) for p, q in zip(pts, pts[1:])]
        if pts is r["pts"]: continue
        changed += 1; edits.append((r, pts, code))
for line in report: print(line)
print(f"camclean: {changed} runs changed{' (dry run, not saved)' if dry else ''}")
if not dry:
    for r, pts, code in edits:                                  # edit the board only now
        for o in r["objs"]: b.Remove(o[5])
        for p, q in zip(pts, pts[1:]):
            t = pcbnew.PCB_TRACK(b); t.SetStart(pcbnew.VECTOR2I(FromMM(p[0]), FromMM(p[1])))
            t.SetEnd(pcbnew.VECTOR2I(FromMM(q[0]), FromMM(q[1]))); t.SetWidth(FromMM(r["w"])); t.SetLayer(r["layer"])
            t.SetNetCode(code); b.Add(t)
    pcbnew.SaveBoard(dst, b)
