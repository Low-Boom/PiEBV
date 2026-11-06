# Post-route straightening (KiCad python), F31b. Per net, the F.Cu / B.Cu track chains between terminals
# (pad, via, branch, width change) become vertex lists. Collinear vertices are merged, and a jog
# (a sub-path Pi..Pj) is replaced by a straight 0/45/90-degree run Pi-Pj, or by two such legs
# Pi-K-Pj (diagonal first or straight first), when that has fewer segments and is clear:
#  - other-net tracks, vias and pads: netclass clearance; other-net holes: hole clearance;
#  - board edge: copper-edge clearance; no new copper in the 2.5 mm card-guide strips along the long
#    edges; keep-out areas; no track across the pad gap of a foreign
#    front 2-pad SMD part (F27);
#  - no new segment < MIN_SEG except at a pad or via; no turn sharper than 90 degrees at Pi / Pj.
# The longest replacement is taken first (greedy), passes repeat until nothing changes. A replacement
# is never longer than the path it replaces. A segment that another own track touches off its ends,
# or that crosses an own pad or via off its ends, is not moved. Per net, the change is undone if
# KiCad's unconnected count or dangling ends go up or the pad groups change. Run DRC after it.
# Nets not touched: GND, +5V (plane taps), the matched camera lines, the pulse lanes, the carried
# laser / External Sync block. --protect P: also keep every segment of board P (e.g. tapped.kicad_pcb).
# usage: python.exe straighten.py in.kicad_pcb out.kicad_pcb [--protect tapped.kicad_pcb] [net-pattern ...]
import sys, math, fnmatch, wx; wx.DisableAsserts()
import pcbnew
from pcbnew import VECTOR2I, FromMM, ToMM
from collections import defaultdict
SKIP = ["GND", "+5V", "Sync?", "Trigger?", "TDRSTN?", "_PULSE_OUT_*", "CH?_GATED", "CH?_DRIVE_RAW", "CH?_DRIVE",
        "CH?_OUT", "CH?_TERM", "EXT_SYNC_DRIVE_RAW", "EXT_SYNC_DRIVE", "EXT_SYNC_OUT", "EXT_SYNC_TERM"]
MIN_SEG, CELL, STRIP = FromMM(0.5), FromMM(1.0), FromMM(2.5)
a = sys.argv[1:]; protect_f = a[a.index("--protect") + 1] if "--protect" in a else None
pats = [x for i, x in enumerate(a[2:], 2) if x != "--protect" and a[i - 1] != "--protect"] or ["*"]
b = pcbnew.LoadBoard(a[0]); ds = b.GetDesignSettings()
CLR = max(ds.m_NetSettings.GetDefaultNetclass().GetClearance(), ds.m_MinClearance)
HCLR, ECLR = ds.m_HoleClearance, ds.m_CopperEdgeClearance
LAYERS = (pcbnew.F_Cu, pcbnew.B_Cu)
T = list(b.GetTracks()); pads = list(b.GetPads())       # one GetTracks() call
isin = lambda t, lst: any(t is c for c in lst)
def gkey(s, e, L, n): s, e = (round(ToMM(s.x), 3), round(ToMM(s.y), 3)), (round(ToMM(e.x), 3), round(ToMM(e.y), 3)); return (L, n, min(s, e), max(s, e))
protect = {gkey(t.GetStart(), t.GetEnd(), t.GetLayer(), t.GetNetname()) for t in pcbnew.LoadBoard(protect_f).GetTracks()
           if t.GetClass() == "PCB_TRACK"} if protect_f else set()

# ---- obstacles: spatial hash per layer of (id, net, shape, bbox, clearance) ----
grid = {L: defaultdict(list) for L in LAYERS}; live = {}
def put(oid, net, L, sh, bb, clr):
    live[oid] = (net, sh, bb, clr)
    for i in range(bb.GetX() // CELL, bb.GetRight() // CELL + 1):
        for j in range(bb.GetY() // CELL, bb.GetBottom() // CELL + 1): grid[L][(i, j)].append(oid)
def add_item(t):
    for L in LAYERS:
        if t.IsOnLayer(L): put((id(t), L), t.GetNetCode(), L, t.GetEffectiveShape(L), t.GetBoundingBox(), CLR)
        if t.GetClass() == "PCB_VIA": put((id(t), L, "h"), t.GetNetCode(), L, t.GetEffectiveHoleShape(), t.GetBoundingBox(), HCLR)
for t in T: add_item(t)
for p in pads:
    for L in LAYERS:
        if p.IsOnLayer(L): put((id(p), L), p.GetNetCode(), L, p.GetEffectiveShape(L), p.GetBoundingBox(), CLR)
        if p.HasHole(): put((id(p), L, "h"), p.GetNetCode() if p.GetAttribute() != pcbnew.PAD_ATTRIB_NPTH else -1, L, p.GetEffectiveHoleShape(), p.GetBoundingBox(), HCLR)
keepouts = [z for z in b.Zones() if z.GetIsRuleArea() and z.GetDoNotAllowTracks()]
edge = pcbnew.SHAPE_POLY_SET(); b.GetBoardPolygonOutlines(edge, False); EB = edge.BBox()
def gaps():
    out = []
    for f in b.GetFootprints():
        pp = list(f.Pads())
        if len(pp) != 2 or any(p.GetAttribute() != pcbnew.PAD_ATTRIB_SMD or not p.IsOnLayer(pcbnew.F_Cu) for p in pp): continue
        p0, p1 = pp; A, B = p0.GetPosition(), p1.GetPosition(); L = (B - A).EuclideanNorm()
        if L == 0: continue
        ux, uy = (B.x - A.x) / L, (B.y - A.y) / L
        ins = lambda p, s: p.GetEffectivePolygon(pcbnew.F_Cu, pcbnew.ERROR_INSIDE).Contains(VECTOR2I(int(A.x + ux * s), int(A.y + uy * s)))
        s0 = next(s for s in range(0, int(L), 10000) if not ins(p0, s)); s1 = next(s for s in range(int(L), 0, -10000) if not ins(p1, s))
        if s1 - s0 < FromMM(0.3): continue
        h = min(p0.GetSize().x, p0.GetSize().y) / 2
        g = pcbnew.SHAPE_POLY_SET(); g.NewOutline()
        for s, v in ((s0, -h), (s1, -h), (s1, h), (s0, h)): g.Append(int(A.x + ux * s - uy * v), int(A.y + uy * s + ux * v))
        out.append(({p.GetNetCode() for p in pp}, g))
    return out
GAPS = gaps()

def clear(p, q, w, L, net):
    """True if a track p-q (width w, layer L, net) keeps every clearance."""
    sh = pcbnew.SHAPE_SEGMENT(p, q, int(w)); r = int(w) // 2
    x0, x1, y0, y1 = min(p.x, q.x) - r, max(p.x, q.x) + r, min(p.y, q.y) - r, max(p.y, q.y) + r
    inner = edge_in[int(w)]
    if not (inner.Contains(p) and inner.Contains(q)) or y0 < EB.GetY() + STRIP or y1 > EB.GetBottom() - STRIP: return False
    seen = set()
    for i in range((x0 - CELL) // CELL, (x1 + CELL) // CELL + 1):
        for j in range((y0 - CELL) // CELL, (y1 + CELL) // CELL + 1):
            for oid in grid[L].get((i, j), ()):
                if oid in seen or oid not in live: continue
                seen.add(oid); n, osh, bb, clr = live[oid]
                if n == net: continue
                if bb.GetRight() + clr < x0 or bb.GetX() - clr > x1 or bb.GetBottom() + clr < y0 or bb.GetY() - clr > y1: continue
                if osh.Collide(sh, clr - 1): return False
    if any(z.IsOnLayer(L) and z.Outline().Collide(sh, 0) for z in keepouts): return False
    if L == pcbnew.F_Cu and any(net not in own and g.Collide(sh, 0) for own, g in GAPS): return False
    return True
edge_in = {}
def prep_edge(w):
    if w not in edge_in:
        e = pcbnew.SHAPE_POLY_SET(edge); e.Deflate(int(ECLR + w // 2), pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS, FromMM(0.005)); edge_in[w] = e

def octi(dx, dy): return dx == 0 or dy == 0 or abs(dx) == abs(dy)
sgn = lambda v: (v > 0) - (v < 0)
def turn_ok(u, v):                                     # turn from direction u to v at most 90 degrees
    return u[0] * v[0] + u[1] * v[1] >= -1e-9 * math.hypot(*u) * math.hypot(*v)
def collinear(u, v): return u[0] * v[1] - u[1] * v[0] == 0 and u[0] * v[0] + u[1] * v[1] > 0
def plen(V): return sum(math.hypot(q[0] - p[0], q[1] - p[1]) for p, q in zip(V, V[1:]))

def straighten(V, w, L, net, pv_ends):
    """Vertex list V (tuples) of one chain -> simplified list. pv_ends: (start at pad/via, end at pad/via)."""
    def merge(V):
        out = [V[0]]
        for k in range(1, len(V) - 1):
            if collinear((V[k][0] - out[-1][0], V[k][1] - out[-1][1]), (V[k + 1][0] - V[k][0], V[k + 1][1] - V[k][1])): continue
            out.append(V[k])
        return out + [V[-1]]
    V = merge(V); changed = True
    while changed:
        changed = False; i = 0
        while i < len(V) - 2:
            done = False
            for j in range(len(V) - 1, i + 1, -1):
                P, Q = V[i], V[j]; dx, dy = Q[0] - P[0], Q[1] - P[1]
                m = min(abs(dx), abs(dy))
                cands = [[P, Q]] if octi(dx, dy) else \
                        [[P, (P[0] + sgn(dx) * m, P[1] + sgn(dy) * m), Q], [P, (Q[0] - sgn(dx) * m, Q[1] - sgn(dy) * m), Q]]
                for C in cands:
                    if len(C) - 1 >= j - i or plen(C) > plen(V[i:j + 1]) + 1: continue
                    if any(p == q for p, q in zip(C, C[1:])): continue
                    if i > 0 and not turn_ok((P[0] - V[i - 1][0], P[1] - V[i - 1][1]), (C[1][0] - P[0], C[1][1] - P[1])): continue
                    if j < len(V) - 1 and not turn_ok((Q[0] - C[-2][0], Q[1] - C[-2][1]), (V[j + 1][0] - Q[0], V[j + 1][1] - Q[1])): continue
                    W = merge(V[:i] + C + V[j + 1:])
                    # new segments: those of W not in V; < MIN_SEG only with an end at a pad / via chain end
                    old = set(zip(V, V[1:])); bad = False
                    for k, (p, q) in enumerate(zip(W, W[1:])):
                        if (p, q) in old: continue
                        if math.hypot(q[0] - p[0], q[1] - p[1]) < MIN_SEG and not ((k == 0 and pv_ends[0]) or (k == len(W) - 2 and pv_ends[1])): bad = True; break
                        if not clear(VECTOR2I(*p), VECTOR2I(*q), w, L, net): bad = True; break
                    if bad: continue
                    V = W; done = changed = True; break
                if done: break
            i += 1
    return V

def chains(code):
    """Chains of a net: (layer, width, vertex list, segments, (start at pad/via, end at pad/via))."""
    own = [t for t in T if t.GetNetCode() == code]
    segs = [t for t in own if t.GetClass() == "PCB_TRACK" and t.GetLayer() in LAYERS]
    vias = [t for t in own if t.GetClass() == "PCB_VIA"]; opads = [p for p in pads if p.GetNetCode() == code]
    at = defaultdict(list)
    for t in segs:
        for q in (t.GetStart(), t.GetEnd()): at[(q.x, q.y, t.GetLayer())].append(t)
    def padvia(k):
        q = VECTOR2I(k[0], k[1])
        return any(p.IsOnLayer(k[2]) and p.HitTest(q) for p in opads) or any((v.GetPosition() - q).EuclideanNorm() <= v.GetWidth(k[2]) // 2 for v in vias)
    # loose ends: own track ends joined to nothing exactly (no other end, pad or via there); such an end
    # may hold on by overlap with a neighbour, which must then stay
    loose = [k for k, ts in at.items() if len(ts) == 1 and not padvia(k)]
    def pinned(t):                                      # a loose end on it, or it crosses an own pad / via
        if t.IsLocked() or gkey(t.GetStart(), t.GetEnd(), t.GetLayer(), t.GetNetname()) in protect: return True
        s, e, L, sh = t.GetStart(), t.GetEnd(), t.GetLayer(), t.GetEffectiveShape(t.GetLayer())
        if any(k[2] == L and k[:2] not in ((s.x, s.y), (e.x, e.y)) and sh.Collide(VECTOR2I(k[0], k[1]), 0) for k in loose): return True
        for p in opads:
            if p.IsOnLayer(L) and not p.HitTest(s) and not p.HitTest(e) and p.GetEffectivePolygon(L, pcbnew.ERROR_INSIDE).Collide(sh, 0): return True
        for v in vias:
            c = v.GetPosition()
            if (c - s).EuclideanNorm() > v.GetWidth(L) // 2 and (c - e).EuclideanNorm() > v.GetWidth(L) // 2 and v.GetEffectiveShape(L).Collide(sh, 0): return True
        return False
    free = [t for t in segs if not pinned(t)]
    def term(k):
        ts = at[k]
        return len(ts) != 2 or not all(isin(t, free) for t in ts) or ts[0].GetWidth() != ts[1].GetWidth() or padvia(k)
    used = []; out = []
    for t0 in free:
        if isin(t0, used): continue
        # walk to one terminal, then collect the chain from there
        cur, k = t0, (t0.GetStart().x, t0.GetStart().y, t0.GetLayer()); seen = [t0]
        while not term(k):
            cur = [u for u in at[k] if u is not cur][0]
            if isin(cur, seen): break                   # closed loop: leave it
            seen.append(cur); s, e = cur.GetStart(), cur.GetEnd(); k = (e.x, e.y, k[2]) if (s.x, s.y) == k[:2] else (s.x, s.y, k[2])
        else:
            V = [k[:2]]; S = []; kk = k; nxt = [cur]        # cur: the chain segment at terminal k
            while True:
                cur = nxt[0]; S.append(cur); s, e = cur.GetStart(), cur.GetEnd()
                kk = (e.x, e.y, kk[2]) if (s.x, s.y) == kk[:2] else (s.x, s.y, kk[2]); V.append(kk[:2])
                if term(kk): break
                nxt = [u for u in at[kk] if u is not cur]
                if isin(nxt[0], S): break                   # closed loop
            used.extend(S)
            if len(S) >= 2: out.append((k[2], S[0].GetWidth(), V, S, (padvia(k), padvia(kk))))
            continue
        used.extend(seen)
    return out

def state(code):
    b.BuildConnectivity(); c = b.GetConnectivity()
    grp = {frozenset(f"{q.GetParentFootprint().GetReference()}.{q.GetNumber()}" for q in c.GetConnectedItems(p) if q.GetClass() == "PAD")
           | {f"{p.GetParentFootprint().GetReference()}.{p.GetNumber()}"} for p in pads if p.GetNetCode() == code}
    return c.GetUnconnectedCount(False), grp, sum(c.TestTrackEndpointDangling(t, False) for t in T if t.GetNetCode() == code and t.GetClass() == "PCB_TRACK")

for w in {t.GetWidth() for t in T if t.GetClass() == "PCB_TRACK"}: prep_edge(w)
nets = sorted({t.GetNetname() for t in T if t.GetClass() == "PCB_TRACK"})
nets = [n for n in nets if any(fnmatch.fnmatchcase(n, p) for p in pats) and not any(fnmatch.fnmatchcase(n, p) for p in SKIP)]
tot0 = tot1 = 0
for net in nets:
    code = b.GetNetcodeFromNetname(net); s0 = state(code); done = []
    for L, w, V, S, pv in chains(code):
        W = straighten(V, w, L, code, pv)
        if W == V: continue
        new = []
        for p, q in zip(W, W[1:]):
            n = pcbnew.PCB_TRACK(b); n.SetStart(VECTOR2I(*p)); n.SetEnd(VECTOR2I(*q)); n.SetWidth(w); n.SetLayer(L); n.SetNetCode(code); new.append(n)
        old = [(VECTOR2I(t.GetStart().x, t.GetStart().y), VECTOR2I(t.GetEnd().x, t.GetEnd().y), t.GetWidth(), t.GetLayer()) for t in S]   # copies: Remove() frees the item
        for t in S:
            for L2 in LAYERS: live.pop((id(t), L2), None)
            b.Remove(t)
        T[:] = [u for u in T if not isin(u, S)]
        for n in new: b.Add(n); T.append(n); add_item(n)
        done.append((old, new))
    s1 = state(code)
    if s1[0] > s0[0] or s1[1] != s0[1] or s1[2] > s0[2]:  # connectivity worse: undo this net
        for old, new in done:
            for n in new:
                for L2 in LAYERS: live.pop((id(n), L2), None)
                b.Remove(n)
            T[:] = [u for u in T if not isin(u, new)]
            for s, e, w, L in old:
                n = pcbnew.PCB_TRACK(b); n.SetStart(s); n.SetEnd(e); n.SetWidth(w); n.SetLayer(L); n.SetNetCode(code); b.Add(n); T.append(n); add_item(n)
        print(f"{net}: undone (connectivity)"); continue
    if done:
        a0 = sum(len(o) for o, n in done); a1 = sum(len(n) for o, n in done); tot0 += a0; tot1 += a1
        l0 = sum((e - s).EuclideanNorm() for o, n in done for s, e, w, L in o); l1 = sum(t.GetLength() for o, n in done for t in n)
        print(f"{net:16s} {len(done):3d} chains: {a0:4d} -> {a1:4d} segments, {ToMM(l0):7.2f} -> {ToMM(l1):7.2f} mm")
print(f"straighten: {tot0} -> {tot1} segments")
pcbnew.SaveBoard(a[1], b)
