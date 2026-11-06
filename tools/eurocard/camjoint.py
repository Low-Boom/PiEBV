# Post-route step (KiCad python), R5: joint re-shape of the three camera staircases that camclean.py cannot
# replace one line at a time. Runs after camclean.py (first pass), before ends.py / kilen.py / camclean --trim.
#  U6 pair - Trigger1 and Trigger2 leave U6.2 / U6.4 side by side between PIXRST_GATE (x 220.6) and the U6.7
#            GND tap via (222.49, 96.08). Trigger2 becomes one vertical at its window start x and one 45-degree
#            leg on its old end line (shorter; camclean --trim puts the length back with the meander caps).
#            Trigger1 (no meander) becomes vertical X_LO, a 45-degree jog to X_HI below Trigger2's turn, and
#            its old 45-degree end leg; the 45-degree entry from its y-96.5 horizontal is placed so that the
#            window length is kept (+ T1_BIAS: Trigger1 is the shortest Trigger line).
#  J6.5    - Sync6 (no meander) from its via leg to J6.5: vertical, 45, horizontal, 45 (equal 45 legs), with
#            the horizontal sized so that the window length is kept.
#  J6 tail - Trigger6 (no meander) into J6: the 7-segment router jog at (241.6, 102.5) becomes one horizontal
#            run at the window start y and one 45-degree leg to the window end (a review edit 2026-11-06; the
#            window shortens the line by 1.657 mm, which the window's ltol allows).
# A window is the run of one net / layer between two existing vertices (anchors). Guards, on the new copper
# (edge to edge, same layer, tracks / vias / pad outlines as netgap.py): octilinear, no segment < MINSEG,
# no turn > 90 degrees (joints included); to a line of another camera group the smallest gap between the
# two groups before; to a STRICT net its gap before; to any other net min(gap before, FLOOR) - the camclean.py
# rules - and not below min(the old window's gap to that net, LOCAL), so a window does not move closer to a
# neighbour than it was (up to LOCAL = 0.30 mm); own copper more than
# SKIP mm further along the run >= OWN; window length change <= the window ltol (NOCAP_TOL unless the window
# sets one) on a line without a meander.
# A group (U6 pair) is applied only if all its windows pass; a window whose anchors are not found is left.
# usage: python.exe camjoint.py in.kicad_pcb out.kicad_pcb
import sys, math, fnmatch, wx; wx.DisableAsserts()
import pcbnew
from pcbnew import ToMM, FromMM

FLOOR, OWN, SKIP, NOCAP_TOL, MINSEG, TOL, LOCAL = 0.21, 0.45, 2.0, 0.15, 0.3, 0.002, 0.30
STRICT = ["_PULSE_OUT_*", "PWM_1MHz", "SYNC_N"]
CAM = ("Sync", "Trigger", "TDRSTN")
X_LO, X_HI, Y_JOG, T1_BIAS = 220.85, 221.46, 93.2, 0.002     # Trigger1: verticals, jog end y; length bias (mm)
J6T_LTOL = 1.70                                              # Trigger6 tail: allowed window shortening (mm, review edit 2026-11-06)
R2 = math.sqrt(2)
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
group = lambda n: next((g for g in CAM if n.startswith(g) and n[len(g):].isdigit()), None)

def netgap(net, layer, segs, hw, other):
    """smallest edge gap from segs (centre lines, halfwidth hw) to net 'other' on layer"""
    return min((seg_seg(s, g) - hw - h for s in segs for L, h, g in ITEMS.get(other, ()) if L == layer), default=1e9)
PAIR = {}
def before(n1, n2):
    """smallest gap between two nets before this step, any copper layer"""
    k = tuple(sorted((n1, n2)))
    if k not in PAIR:
        PAIR[k] = min((seg_seg(g1, g2) - h1 - h2 for L1, h1, g1 in ITEMS0.get(n1, ()) for L2, h2, g2 in ITEMS0.get(n2, ()) if L1 == L2), default=1e9)
    return PAIR[k]
ITEMS0 = {n: list(v) for n, v in ITEMS.items()}
GMIN = {}
def groupmin(g1, g2):
    k = tuple(sorted((g1, g2)))
    if k not in GMIN:
        GMIN[k] = min(before(a, c) for a in ITEMS0 if group(a) == g1 for c in ITEMS0 if group(c) == g2)
    return GMIN[k]
def req(net, other):
    g1, g2 = group(net), group(other)
    if g2 is not None and g1 != g2: return groupmin(g1, g2)
    if any(fnmatch.fnmatchcase(other, p) for p in STRICT): return before(net, other)
    return min(before(net, other), FLOOR)

# ---------- runs ----------
def run_of(net, layer, P):
    """ordered vertex list and track objects of the net's run on layer that passes through point P"""
    segs = [t for t in TRK if t[0] == net and t[1] == layer]; at = {}
    k = lambda x, y: (round(x, 4), round(y, 4)); raw = {}             # key -> exact coordinates (first seen)
    for t in segs:
        g = t[2]
        for e in (g[:2], g[2:]): at.setdefault(k(*e), []).append(t); raw.setdefault(k(*e), e)
    near = [v for v in at if math.hypot(v[0] - P[0], v[1] - P[1]) <= TOL]
    if not near: return None
    ends = [v for v, ts in at.items() if len(ts) != 2]       # walk from the first end of the run holding P
    for e0 in sorted(ends):
        pts, objs, cur, used = [e0], [], e0, set()
        while True:
            nxt = [t for t in at[cur] if id(t) not in used]
            if not nxt or (len(at[cur]) > 2 and cur != e0): break
            t = nxt[0]; used.add(id(t)); objs.append(t); g = t[2]
            cur = k(*g[2:]) if k(*g[:2]) == cur else k(*g[:2]); pts.append(cur)
            if len(at[cur]) != 2: break
        if near[0] in pts: return [raw[v] for v in pts], objs
    return None

def window(net, layer, A, B):
    """(run points, run objects, i, j): vertices i (A) .. j (B) of the run, i < j, or None"""
    r = run_of(net, layer, A)
    if not r: return None
    pts, objs = r
    f = lambda P: next((i for i, v in enumerate(pts) if math.hypot(v[0] - P[0], v[1] - P[1]) <= TOL), None)
    i, j = f(A), f(B)
    if i is None or j is None: return None
    if i > j: pts, objs = pts[::-1], objs[::-1]; i, j = len(pts) - 1 - i, len(pts) - 1 - j
    return pts, objs, i, j

# ---------- the three windows ----------
def trigger2(A, B, Lold):     # vertical at A.x, then the old 45-degree end line x + y = B.x + B.y
    return [A, (A[0], B[0] + B[1] - A[0]), B]
def trigger1(A, B, Lold):     # A on the y-96.5 horizontal (entry H then 45), X_LO vertical, jog to X_HI, old end line
    yt = B[0] + B[1] - X_HI; js = (X_LO, Y_JOG + X_HI - X_LO)
    fixed = (X_HI - X_LO) * R2 + (Y_JOG - yt) + (B[0] - X_HI) * R2
    # entry: H to (X_LO - D, A.y), 45 to (X_LO, A.y - D), vertical to js: length = (X_LO - A.x - D) + D*R2 + (A.y - D - js.y)
    D = ((X_LO - A[0]) + (A[1] - js[1]) + fixed - (Lold + T1_BIAS)) / (2 - R2)
    return [A, (X_LO - D, A[1]), (X_LO, A[1] - D), js, (X_HI, Y_JOG), (X_HI, yt), B]
def sync6(A, B, Lold):        # V, 45 (a/2), H, 45 (a/2): length (dy - a) + (dx - a) + a*R2
    dx, dy = B[0] - A[0], B[1] - A[1]; a = (dx + dy - Lold) / (2 - R2)
    P1 = (A[0], A[1] + dy - a); P2 = (P1[0] + a / 2, P1[1] + a / 2); P3 = (B[0] - a / 2, P2[1])
    return [A, P1, P2, P3, B]
def trig6(A, B, Lold):        # J6 tail: horizontal run at A.y, then one 45-degree leg to B (turn x from the leg)
    return [A, (B[0] - (B[1] - A[1]), A[1]), B]
GROUPS = [("U6 pair", [("Trigger2", pcbnew.F_Cu, (221.6, 97.9), (223.1315, 92.5686), trigger2, True, NOCAP_TOL),
                       ("Trigger1", pcbnew.F_Cu, (216.5619, 96.5), (223.0435, 89.8565), trigger1, False, NOCAP_TOL)]),
          ("J6.5", [("Sync6", pcbnew.F_Cu, (249.9, 110.6), (252.2321, 116.3321), sync6, False, NOCAP_TOL)]),
          ("J6 tail", [("Trigger6", pcbnew.F_Cu, (241.6, 102.5), (254.98424, 109.58424), trig6, False, J6T_LTOL)])]

edits, nchg = [], 0
def netgap0(layer, segs, hw, other):                    # as netgap, against the copper before this step
    return min((seg_seg(s, g) - hw - h for s in segs for L, h, g in ITEMS0.get(other, ()) if L == layer), default=1e9)
for gname, wins in GROUPS:
    plan, msgs, saved = [], [], {n: list(v) for n, v in ITEMS.items()}
    for net, L, A, B, shape, has_caps, ltol in wins:          # 1. all new windows of the group, into the live copper
        w = window(net, L, A, B)
        if not w: msgs.append(f"{net}: anchors not found"); plan = None; break
        pts, objs, i, j = w; old = pts[i:j + 1]; Lold = plen(old)
        new = [old[0]] + shape(old[0], old[-1], Lold)[1:-1] + [old[-1]]; hw = objs[0][3]
        segs = [new[k] + new[k + 1] for k in range(len(new) - 1)]
        gone = [tuple(o[2]) for o in objs[i:j]]
        ITEMS[net] = [it for it in ITEMS[net] if not (it[0] == L and it[2] in gone)] + [(L, hw, s) for s in segs]
        plan.append((net, L, hw, objs[i:j], new, pts, i, j, old, Lold, has_caps, ltol))
    ok = plan is not None
    for net, L, hw, objs, new, pts, i, j, old, Lold, has_caps, ltol in (plan or []):   # 2. check each against the others' new copper
        full = pts[:i] + new + pts[j + 1:]; dl = plen(new) - Lold
        lo, hi = max(1, i), min(len(full) - 1, i + len(new))                          # joints included
        segs = [new[k] + new[k + 1] for k in range(len(new) - 1)]; oldsegs = [old[k] + old[k + 1] for k in range(len(old) - 1)]
        why = []
        if any(not octi(new[k], new[k + 1]) for k in range(len(new) - 1)): why.append("not octilinear")
        if any(dist(new[k], new[k + 1]) < MINSEG for k in range(len(new) - 1)): why.append("segment < %.1f mm" % MINSEG)
        if any(turn(full[k - 1], full[k], full[k + 1]) > 90.01 for k in range(lo, hi)): why.append("turn > 90")
        if not has_caps and abs(dl) > ltol: why.append("length %+.3f" % dl)
        for other in sorted(n for n in ITEMS if n and n != net):
            g = netgap(net, L, segs, hw, other)
            if g > 3: continue
            g0 = netgap0(L, oldsegs, hw, other); need = max(req(net, other), min(g0, LOCAL))
            msgs.append(f"   {net} - {other}: window gap {g0:.3f} -> {g:.3f} (need {need:.3f})")
            if g < need - 1e-4: why.append(f"gap to {other} {g:.3f} < {need:.3f}")
        cum = [0.0]
        for p, q in zip(full, full[1:]): cum.append(cum[-1] + dist(p, q))
        for k in range(i, i + len(new) - 1):                                        # own copper of the run
            for m in range(len(full) - 1):
                sep = cum[m] - cum[k + 1] if m > k else cum[k] - cum[m + 1]
                if sep > SKIP and seg_seg(full[k] + full[k + 1], full[m] + full[m + 1]) - 2 * hw < OWN - 1e-4: why.append("own gap"); break
        msgs.append(f"{net} {b.GetLayerName(L)}: {len(old) - 1} -> {len(new) - 1} segs, window {Lold:.4f} -> {plen(new):.4f} mm ({dl:+.4f})"
                    + (f"  FAIL: {', '.join(why)}" if why else ""))
        if why: ok = False
    print(f"camjoint {gname}: " + ("applied" if ok else "LEFT AS IS"))
    for m in msgs: print("  " + m)
    if ok: edits += [(net, L, hw, objs, new) for net, L, hw, objs, new, *_ in plan]; nchg += len(plan)
    else: ITEMS.clear(); ITEMS.update(saved)
for net, L, hw, objs, new in edits:                     # edit the board only now
    code = b.GetNetcodeFromNetname(net)
    for o in objs: b.Remove(o[4])
    for p, q in zip(new, new[1:]):
        t = pcbnew.PCB_TRACK(b); t.SetStart(pcbnew.VECTOR2I(FromMM(p[0]), FromMM(p[1]))); t.SetEnd(pcbnew.VECTOR2I(FromMM(q[0]), FromMM(q[1])))
        t.SetWidth(FromMM(2 * hw)); t.SetLayer(L); t.SetNetCode(code); b.Add(t)
print(f"camjoint: {nchg} windows changed")
pcbnew.SaveBoard(sys.argv[2], b)
