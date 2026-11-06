# Post-route repair (KiCad python), F27: foreign-net F.Cu tracks under / beside the given SMD parts.
# For each part REF, the protected region is the convex hull of its F.Cu pads (the pads plus the body
# between them). An unlocked F.Cu track of a net that is not on the part's pads and that comes within KEEP mm
# of the region is an offender. Its run (the chain of unlocked F.Cu segments between terminals: pad,
# via, branch or locked copper; it stops before a segment that crosses an own pad) is removed and routed again between the same two terminals by a
# local A* (0.1 mm grid, 8 directions, turn cost, F.Cu + B.Cu with 0.6/0.3 vias), with these rules:
#  - other-net copper on the layer: netclass clearance + MARG (a cost within SOFT beyond it); holes:
#    hole clearance; edge clearance; track and via keep-outs;
#  - every protected region: KEEP mm (for nets foreign to that part);
#  - no track across the pad gap of any other front 2-pad SMD part of a foreign net, no via there;
#  - vias: hole-to-hole, not in an SMD pad, not inside the courtyard of an SMD part.
# Width = widest track of the run. Only the run changes; terminals and all other copper stay.
# usage: python.exe repair.py in.kicad_pcb out.kicad_pcb [--dry] REF ...      (e.g. C2 R30 C13)
import sys, math, heapq, wx; wx.DisableAsserts()
import pcbnew
from pcbnew import VECTOR2I, FromMM, ToMM
KEEP, GRID, MARG = 0.3, 0.1, 0.02                      # mm: keep distance, grid, extra clearance margin
TURN45, TURN90, VIA_COST, VIA_D, VIA_DR = 0.3, 0.8, 4.0, 0.6, 0.3   # costs in mm of track
SOFT, SOFT_COST = 0.3, 2.0      # mm beyond clearance to other-net copper that costs SOFT_COST x step length
WINDOWS = (3.0, 6.0, 10.0)                              # search window margins around the run, mm
args = sys.argv[3:]; dry = "--dry" in args; refs = [a for a in args if a != "--dry"]
b = pcbnew.LoadBoard(sys.argv[1]); ds = b.GetDesignSettings()
F, B = pcbnew.F_Cu, pcbnew.B_Cu
CLR = max(ds.m_NetSettings.GetDefaultNetclass().GetClearance(), ds.m_MinClearance)
HCLR, H2H, ECLR = ds.m_HoleClearance, ds.m_HoleToHoleMin, ds.m_CopperEdgeClearance
T = list(b.GetTracks())                                 # one query only: Remove() breaks later wrappers
pads = list(b.GetPads())
mk = lambda x, y: VECTOR2I(int(round(x)), int(round(y)))

isin = lambda t, lst: any(t is c for c in lst)        # SWIG proxies: compare by identity

def region(f):
    """Convex hull of the F.Cu pads of footprint f: the pads plus the body between them."""
    pts = set()
    for p in f.Pads():
        if not p.IsOnLayer(F): continue
        ps = p.GetEffectivePolygon(F, pcbnew.ERROR_INSIDE)
        pts.update((ps.CVertex(i).x, ps.CVertex(i).y) for i in range(ps.TotalVertices()))
    pts = sorted(pts); cross = lambda o, a, c: (a[0] - o[0]) * (c[1] - o[1]) - (a[1] - o[1]) * (c[0] - o[0])
    lo, up = [], []                                     # monotone chain hull
    for q in pts:
        while len(lo) > 1 and cross(lo[-2], lo[-1], q) <= 0: lo.pop()
        lo.append(q)
    for q in reversed(pts):
        while len(up) > 1 and cross(up[-2], up[-1], q) <= 0: up.pop()
        up.append(q)
    h = pcbnew.SHAPE_POLY_SET(); h.NewOutline()
    for x, y in lo[:-1] + up[:-1]: h.Append(int(x), int(y))
    return h

def gap(f):
    """Pad gap rectangle of a front 2-pad SMD part (inner pad edges, pad width), or None."""
    pp = list(f.Pads())
    if len(pp) != 2 or any(p.GetAttribute() != pcbnew.PAD_ATTRIB_SMD or not p.IsOnLayer(F) for p in pp): return None
    a, c = pp; ax, ay, cx, cy = a.GetPosition().x, a.GetPosition().y, c.GetPosition().x, c.GetPosition().y
    L = math.hypot(cx - ax, cy - ay); ux, uy = (cx - ax) / L, (cy - ay) / L; vx, vy = -uy, ux
    ang = math.radians(a.GetOrientationDegrees()); sx, sy = a.GetSize().x / 2, a.GetSize().y / 2
    along = abs(sx * (ux * math.cos(ang) - uy * math.sin(ang))) + abs(sy * (ux * math.sin(ang) + uy * math.cos(ang)))
    across = abs(sx * (vx * math.cos(ang) - vy * math.sin(ang))) + abs(sy * (vx * math.sin(ang) + vy * math.cos(ang)))
    if L - 2 * along < FromMM(0.3): return None
    g = pcbnew.SHAPE_POLY_SET(); g.NewOutline()
    for t, s in ((along, -across), (L - along, -across), (L - along, across), (along, across)): g.Append(mk(ax + ux * t + vx * s, ay + uy * t + vy * s))
    return g

def segdist(px, py, ax, ay, bx, by):
    vx, vy = bx - ax, by - ay; L2 = vx * vx + vy * vy
    u = 0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / L2))
    return math.hypot(ax + u * vx - px, ay + u * vy - py)

def dist_to(poly, shape, lo=0, hi=FromMM(2)):
    """Distance from a shape to a polygon set (bisection on Collide), capped at hi."""
    if poly.Collide(shape, 0): return 0
    if not poly.Collide(shape, hi): return hi
    for _ in range(14):
        m = (lo + hi) // 2
        if poly.Collide(shape, m): hi = m
        else: lo = m
    return hi

fps = {f.GetReference(): f for f in b.GetFootprints()}
targets = [(r, fps[r], {p.GetNetCode() for p in fps[r].Pads()}, region(fps[r])) for r in refs]
gaps = [(f.GetReference(), {p.GetNetCode() for p in f.Pads()}, g) for f in b.GetFootprints() for g in [gap(f)] if g]

def foreign_min(ref, own, reg):
    """Min distance (mm) from foreign F.Cu tracks / vias to the part's region, and the nearest net."""
    best = (9.0, "")
    for t in T:
        if t.GetNetCode() in own or not t.IsOnLayer(F): continue
        bb = t.GetBoundingBox(); rb = reg.BBox()
        if bb.GetRight() < rb.GetX() - FromMM(2) or bb.GetX() > rb.GetRight() + FromMM(2) or bb.GetBottom() < rb.GetY() - FromMM(2) or bb.GetY() > rb.GetBottom() + FromMM(2): continue
        d = ToMM(dist_to(reg, t.GetEffectiveShape(F)))
        if d < best[0]: best = (d, t.GetNetname())
    return best

def split_t(code):
    """Split unlocked F.Cu segments of net code at T-junctions on their centreline (own track ends,
    via centres), so that the junction becomes a run terminal. Copper does not change."""
    own = [t for t in T if t.GetNetCode() == code and t.GetClass() == "PCB_TRACK" and t.GetLayer() == F]
    pts = {(e.x, e.y) for t in own for e in (t.GetStart(), t.GetEnd())} | \
          {(v.GetPosition().x, v.GetPosition().y) for v in T if v.GetNetCode() == code and v.GetClass() == "PCB_VIA"}
    for x, y in pts:
        for c in list(own):
            s, e = c.GetStart(), c.GetEnd()
            if c.IsLocked() or (x, y) in ((s.x, s.y), (e.x, e.y)) or segdist(x, y, s.x, s.y, e.x, e.y) >= 1000: continue
            n = pcbnew.PCB_TRACK(b); n.SetStart(VECTOR2I(x, y)); n.SetEnd(e); n.SetWidth(c.GetWidth()); n.SetLayer(F); n.SetNetCode(code)
            c.SetEnd(VECTOR2I(x, y)); b.Add(n); T.append(n); own.append(n)

def run_of(seg, code):
    """Chain of unlocked F.Cu segments of net code through seg, between terminals. -> (ends, segments)."""
    split_t(code)
    own = [t for t in T if t.GetNetCode() == code]
    segs = [t for t in own if t.GetClass() == "PCB_TRACK" and t.GetLayer() == F and not t.IsLocked()]
    at = {}
    for t in own:
        if t.GetClass() == "PCB_TRACK" and t.IsOnLayer(F):
            for e in (t.GetStart(), t.GetEnd()): at.setdefault((e.x, e.y), []).append(t)
    vias = [t for t in own if t.GetClass() == "PCB_VIA"]
    opads = [p for p in pads if p.GetNetCode() == code and p.IsOnLayer(F)]
    def terminal(k):
        e = VECTOR2I(*k); ts = at.get(k, [])
        return (len(ts) != 2 or any(t.IsLocked() for t in ts) or any(p.HitTest(e) for p in opads) or
                any((v.GetPosition() - e).EuclideanNorm() <= v.GetWidth(F) // 2 for v in vias))
    def through(t):                                     # crosses an own pad that holds neither of its ends
        sh = t.GetEffectiveShape(F)
        return any(p.GetEffectivePolygon(F, pcbnew.ERROR_INSIDE).Collide(sh, 0) and not p.HitTest(t.GetStart()) and not p.HitTest(t.GetEnd()) for p in opads)
    if through(seg): return [], None
    chain = [seg]; ends = []
    for k0 in ((seg.GetStart().x, seg.GetStart().y), (seg.GetEnd().x, seg.GetEnd().y)):
        cur, k = seg, k0
        while not terminal(k):
            nxt = [t for t in at[k] if t is not cur][0]
            if not isin(nxt, segs) or isin(nxt, chain) or through(nxt): break   # stop before a pad pass-through
            chain.append(nxt); cur = nxt
            s, e = nxt.GetStart(), nxt.GetEnd(); k = (e.x, e.y) if (s.x, s.y) == k else (s.x, s.y)
        ends.append(k)
    # Own copper that touches the chain off its end points (off-centre T) must reach a chain terminal
    # without the chain (union-find over the rest of the net); else removing the chain could cut it off.
    rest = [t for t in own if not isin(t, chain) and t.GetClass() == "PCB_TRACK"]
    up = {}
    def find(k):
        while up.get(k, k) != k: k = up[k]
        return k
    def join(a, c): up[find(a)] = find(c)
    keys = [((e.x, e.y, t.GetLayer()), e, t.GetLayer()) for t in rest for e in (t.GetStart(), t.GetEnd())]
    for t in rest: join((t.GetStart().x, t.GetStart().y, t.GetLayer()), (t.GetEnd().x, t.GetEnd().y, t.GetLayer()))
    for k, e, L in keys + [((x, y, F), VECTOR2I(x, y), F) for x, y in ends]:
        for p in pads:
            if p.GetNetCode() == code and p.IsOnLayer(L) and p.HitTest(e): join(k, ("pad", p.GetParentFootprint().GetReference(), p.GetNumber()))
        for v in vias:
            if (v.GetPosition() - e).EuclideanNorm() <= v.GetWidth(F) // 2: join(k, ("via", v.GetPosition().x, v.GetPosition().y))
    term = {find((x, y, F)) for x, y in ends}
    for k, e, L in keys:
        if L != F or k[:2] in ends: continue
        if any(segdist(e.x, e.y, c.GetStart().x, c.GetStart().y, c.GetEnd().x, c.GetEnd().y) < c.GetWidth() / 2 for c in chain) \
           and find(k) not in term: return ends, None
    return ends, chain

def route(code, w, p0, p1, chain, margin):
    """A* from p0 to p1 (F.Cu points) in the bbox of the chain + margin. -> [(layer, x, y)] or None."""
    g = FromMM(GRID); xs = [p0.x, p1.x] + [e.x for c in chain for e in (c.GetStart(), c.GetEnd())]
    ys = [p0.y, p1.y] + [e.y for c in chain for e in (c.GetStart(), c.GetEnd())]
    m = FromMM(margin); i0 = -int((p0.x - min(xs) + m) // g); i1 = int((max(xs) + m - p0.x) // g)
    j0 = -int((p0.y - min(ys) + m) // g); j1 = int((max(ys) + m - p0.y) // g)
    nx, ny = i1 - i0 + 1, j1 - j0 + 1
    X = lambda i: p0.x + (i + i0) * g; Y = lambda j: p0.y + (j + j0) * g
    wbox = (X(0) - m, Y(0) - m, X(nx - 1) + m, Y(ny - 1) + m)
    near = lambda bb: not (bb.GetRight() < wbox[0] or bb.GetX() > wbox[2] or bb.GetBottom() < wbox[1] or bb.GetY() > wbox[3])
    rt, rv, mg = w / 2, FromMM(VIA_D) / 2, FromMM(MARG)
    blk = {F: bytearray(nx * ny), B: bytearray(nx * ny)}; vblk = bytearray(nx * ny)
    soft = {F: bytearray(nx * ny), B: bytearray(nx * ny)}; sf = FromMM(SOFT)   # near other-net copper: allowed, costly
    def paint(arr, x0, y0, x1, y1, hit):
        for i in range(max(0, int((x0 - X(0)) // g)), min(nx - 1, int((x1 - X(0)) // g) + 1) + 1):
            for j in range(max(0, int((y0 - Y(0)) // g)), min(ny - 1, int((y1 - Y(0)) // g) + 1) + 1):
                k = j * nx + i
                if not arr[k] and hit(X(i), Y(j)): arr[k] = 1
    def capsule(arr, ax, ay, bx, by, r):
        paint(arr, min(ax, bx) - r, min(ay, by) - r, max(ax, bx) + r, max(ay, by) + r, lambda x, y: segdist(x, y, ax, ay, bx, by) < r)
    def polyset(arr, ps, r):
        bb = ps.BBox(); paint(arr, bb.GetX() - r, bb.GetY() - r, bb.GetRight() + r, bb.GetBottom() + r, lambda x, y: ps.Collide(VECTOR2I(int(x), int(y)), int(r)))
    for t in T:                                         # tracks and vias
        if isin(t, chain) or not near(t.GetBoundingBox()): continue
        if t.GetClass() == "PCB_VIA":
            c = t.GetPosition(); hr = t.GetDrillValue() / 2
            capsule(vblk, c.x, c.y, c.x, c.y, hr + FromMM(VIA_DR) / 2 + H2H + mg)
            if t.GetNetCode() != code:
                for L in (F, B): capsule(blk[L], c.x, c.y, c.x, c.y, t.GetWidth(L) / 2 + CLR + rt + mg); capsule(soft[L], c.x, c.y, c.x, c.y, t.GetWidth(L) / 2 + CLR + rt + sf)
                capsule(vblk, c.x, c.y, c.x, c.y, t.GetWidth(F) / 2 + CLR + rv + mg)
        elif t.GetNetCode() != code and t.GetLayer() in (F, B):
            s, e = t.GetStart(), t.GetEnd(); r = t.GetWidth() / 2 + CLR + mg
            capsule(blk[t.GetLayer()], s.x, s.y, e.x, e.y, r + rt); capsule(vblk, s.x, s.y, e.x, e.y, r + rv)
            capsule(soft[t.GetLayer()], s.x, s.y, e.x, e.y, r + rt + sf)
    for p in pads:
        if not near(p.GetBoundingBox()): continue
        for L in (F, B):
            if not p.IsOnLayer(L): continue
            ps = p.GetEffectivePolygon(L, pcbnew.ERROR_OUTSIDE)
            if p.GetNetCode() != code:
                polyset(blk[L], ps, CLR + rt + mg); polyset(vblk, ps, CLR + rv + mg)
            elif not p.HasHole(): polyset(vblk, ps, rv + FromMM(0.1))       # no via in own SMD pad
        if p.HasHole():
            c = p.GetPosition(); hr = max(p.GetDrillSize().x, p.GetDrillSize().y) / 2
            capsule(vblk, c.x, c.y, c.x, c.y, hr + FromMM(VIA_DR) / 2 + H2H + mg)
            if p.GetNetCode() != code:
                for L in (F, B): capsule(blk[L], c.x, c.y, c.x, c.y, hr + HCLR + rt + mg)
    for ref, own, reg in [(r, o, g) for r, f, o, g in targets]:   # protected regions
        if code in own: continue
        polyset(blk[F], reg, FromMM(KEEP) + rt + mg); polyset(vblk, reg, FromMM(KEEP) + rv + mg)
    for ref, own, gp in gaps:                           # pad gaps of foreign 2-pad parts
        if code in own: continue
        polyset(blk[F], gp, rt); polyset(vblk, gp, rv)
    for f in b.GetFootprints():                         # no via under an SMD part (courtyard)
        cy = f.GetCourtyard(pcbnew.F_CrtYd)
        if cy.OutlineCount() and near(f.GetBoundingBox()) and any(p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD for p in f.Pads()): polyset(vblk, cy, 0)
    for z in b.Zones():                                 # keep-out rule areas
        if not z.GetIsRuleArea(): continue
        for L in (F, B):
            if z.IsOnLayer(L) and z.GetDoNotAllowTracks(): polyset(blk[L], z.Outline(), rt + mg)
        if z.GetDoNotAllowVias(): polyset(vblk, z.Outline(), rv + mg)
    edge = pcbnew.SHAPE_POLY_SET(); b.GetBoardPolygonOutlines(edge, False)
    for arr, r in ((blk[F], rt), (blk[B], rt), (vblk, rv)):
        inner = pcbnew.SHAPE_POLY_SET(edge); inner.Deflate(int(ECLR + r + mg), pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS, FromMM(0.005))
        for k in range(nx * ny):
            if not arr[k] and not inner.Contains(VECTOR2I(int(X(k % nx)), int(Y(k // nx)))): arr[k] = 1
    # A*: state (layer, cell, dir); dir -1 = free (start, after a via)
    D8 = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]
    s = (-i0) + (-j0) * nx
    gi, gj = round((p1.x - X(0)) / g), round((p1.y - Y(0)) / g); goal = gj * nx + gi
    if blk[F][s] or blk[F][goal]: return None
    h = lambda k: (lambda dx, dy: (max(dx, dy) - min(dx, dy)) + math.sqrt(2) * min(dx, dy))(abs(k % nx - gi), abs(k // nx - gj)) * GRID
    best = {(F, s, -1): 0.0}; prev = {}; q = [(h(s), 0.0, F, s, -1)]
    while q:
        f_, c, L, k, d = heapq.heappop(q)
        if c > best.get((L, k, d), 1e18): continue
        if L == F and k == goal:
            path = []; st = (L, k, d)
            while st: path.append((st[0], X(st[1] % nx), Y(st[1] // nx))); st = prev.get(st)
            return path[::-1]
        i, j = k % nx, k // nx; nb = []
        for nd, (dx, dy) in enumerate(D8):
            if d >= 0:
                turn = min((nd - d) % 8, (d - nd) % 8)
                if turn > 2: continue
                tc = (0, TURN45, TURN90)[turn]
            else: tc = 0
            ii, jj = i + dx, j + dy
            if not (0 <= ii < nx and 0 <= jj < ny): continue
            kk = jj * nx + ii
            if blk[L][kk] or (dx and dy and (blk[L][j * nx + ii] and blk[L][jj * nx + i])): continue
            nb.append((L, kk, nd, c + GRID * (1.4142 if dx and dy else 1) * (1 + SOFT_COST * soft[L][kk]) + tc))
        if not vblk[k]: nb.append((B if L == F else F, k, -1, c + VIA_COST))
        for L2, kk, nd, c2 in nb:
            if L2 != L and blk[L2][kk]: continue
            if c2 < best.get((L2, kk, nd), 1e18):
                best[(L2, kk, nd)] = c2; prev[(L2, kk, nd)] = (L, k, d); heapq.heappush(q, (c2 + h(kk), c2, L2, kk, nd))
    return None

def build(path, code, w, p0, p1):
    """Path cells -> corner list with the exact terminals; tracks and vias added to the board."""
    pts = [(F, p0.x, p0.y)] + path[1:-1] + [(F, p1.x, p1.y)]
    out = [pts[0]]
    for a, c in zip(pts[1:], pts[2:] + [None]):         # keep corners and layer changes only
        p = out[-1]
        if c is not None and a[0] == p[0] == c[0] and (a[1] - p[1]) * (c[2] - a[2]) == (a[2] - p[2]) * (c[1] - a[1]): continue
        out.append(a)
    new = []
    for p, a in zip(out, out[1:]):
        if p[0] != a[0]:
            v = pcbnew.PCB_VIA(b); v.SetPosition(mk(a[1], a[2])); v.SetWidth(FromMM(VIA_D)); v.SetDrill(FromMM(VIA_DR))
            v.SetLayerPair(F, B); v.SetNetCode(code); new.append(v)
        elif (p[1], p[2]) != (a[1], a[2]):
            t = pcbnew.PCB_TRACK(b); t.SetStart(mk(p[1], p[2])); t.SetEnd(mk(a[1], a[2])); t.SetWidth(int(w)); t.SetLayer(p[0]); t.SetNetCode(code); new.append(t)
    return new

print("clearance to foreign F.Cu tracks/vias, before:")
for r, f, own, reg in targets: d, n = foreign_min(r, own, reg); print(f"  {r}: {d:.3f} mm ({n})")
done = []
for r, f, own, reg in targets:
    for t in [t for t in T if t.GetClass() == "PCB_TRACK" and t.GetLayer() == F and not t.IsLocked() and t.GetNetCode() not in own]:
        if isin(t, done) or not reg.Collide(t.GetEffectiveShape(F), FromMM(KEEP) - 1): continue
        code = t.GetNetCode(); ends, chain = run_of(t, code)
        if chain is None: print(f"{r}: {t.GetNetname()} run: other own copper joins it only mid-run, not repaired"); continue
        w = max(c.GetWidth() for c in chain); p0, p1 = VECTOR2I(*ends[0]), VECTOR2I(*ends[1])
        old = sum(c.GetLength() for c in chain)
        print(f"{r}: {t.GetNetname()} run of {len(chain)} segments, {ToMM(old):.2f} mm, ({ToMM(p0.x):.3f},{ToMM(p0.y):.3f}) -> ({ToMM(p1.x):.3f},{ToMM(p1.y):.3f}), width {ToMM(w):.2f}")
        done.extend(chain)
        if dry: continue
        for mgn in WINDOWS:
            path = route(code, w, p0, p1, chain, mgn)
            if path: break
        if not path: print(f"  no route found (window margins {WINDOWS} mm); left as is"); continue
        new = build(path, code, w, p0, p1)
        T[:] = [u for u in T if not isin(u, chain)]
        for c in chain: b.Remove(c)
        for n in new: b.Add(n); T.append(n)
        nl = sum(n.GetLength() for n in new if n.GetClass() == "PCB_TRACK"); nv = sum(n.GetClass() == "PCB_VIA" for n in new)
        print(f"  rerouted: {sum(n.GetClass() == 'PCB_TRACK' for n in new)} segments, {ToMM(nl):.2f} mm, {nv} vias")
print("clearance to foreign F.Cu tracks/vias, after:")
for r, f, own, reg in targets: d, n = foreign_min(r, own, reg); print(f"  {r}: {d:.3f} mm ({n})")
if not dry: pcbnew.SaveBoard(sys.argv[2], b)
