# Copper hygiene after GND stitching (KiCad python), F28. Removes only copper-invisible track segments
# (other same-net copper on the layer covers them, < 0.001 mm2 left) of three kinds:
#  bridge  - off the 45-degree grid (> 0.1 deg): route_planes.py soft-joint / graze bridges; with
#            --before B: any segment that is not in board B (the stitch input, st_in);
#  in-pad  - both ends in the same own pad (carried pad-centre duplicates);
#  sliver  - shorter than 0.08 mm (below the router's 0.1 mm step, so no meander step qualifies).
# Router corner steps (0.1 / 0.141 mm, covered by the neighbours' round ends) are none of these.
# Guards: nets GND, +5V and the matched / drawn nets are never touched; --protect P: never a segment of
# board P (e.g. tapped.kicad_pcb: carried hand copper). One removal at a time, bridges first; undone if
# KiCad's unconnected count or the net's dangling track ends go up, or the pad groups of the net change.
# usage: python.exe tidy.py in.kicad_pcb out.kicad_pcb [--before st_in.kicad_pcb] [--protect tapped.kicad_pcb]
import sys, math, fnmatch, wx; wx.DisableAsserts()
import pcbnew
from pcbnew import FromMM, ToMM
KEEP_NETS = ["GND", "+5V", "Sync?", "Trigger?", "TDRSTN?", "_PULSE_OUT_*"]
SLIVER, ERR = FromMM(0.08), FromMM(0.001)
a = sys.argv[1:]; opt = {a[i]: a[i + 1] for i in range(2, len(a) - 1, 2)}

def key(t):                                             # geometry key, direction-free, 1 um
    s = (round(ToMM(t.GetStart().x), 3), round(ToMM(t.GetStart().y), 3)); e = (round(ToMM(t.GetEnd().x), 3), round(ToMM(t.GetEnd().y), 3))
    return (t.GetLayer(), t.GetNetname(), min(s, e), max(s, e))
def segs(path): return {key(t) for t in pcbnew.LoadBoard(path).GetTracks() if t.GetClass() == "PCB_TRACK"}
before = segs(opt["--before"]) if "--before" in opt else None
protect = segs(opt["--protect"]) if "--protect" in opt else set()

b = pcbnew.LoadBoard(a[0]); T = list(b.GetTracks()); pads = list(b.GetPads())   # one GetTracks() call
bynet = {}
for p in pads: bynet.setdefault(p.GetNetCode(), []).append(p)
def left(t, others):                                    # area of t not covered by others, mm2
    lay = t.GetLayer(); me = pcbnew.SHAPE_POLY_SET(); t.TransformShapeToPolygon(me, lay, 0, ERR, pcbnew.ERROR_INSIDE)
    rest = pcbnew.SHAPE_POLY_SET(); bb = t.GetBoundingBox()
    for o in others:
        if o is not t and o.IsOnLayer(lay) and o.GetBoundingBox().Intersects(bb): o.TransformShapeToPolygon(rest, lay, 0, ERR, pcbnew.ERROR_OUTSIDE)
    me.BooleanSubtract(rest); return me.Area() / 1e12
def kind(t):
    net = t.GetNetCode(); lay = t.GetLayer()
    if left(t, [u for u in T if u.GetNetCode() == net] + bynet.get(net, [])) >= 1e-3: return None
    if t.GetLength() < SLIVER: return "sliver"
    d = math.degrees(math.atan2(t.GetEnd().y - t.GetStart().y, t.GetEnd().x - t.GetStart().x)) % 45
    if (before is not None and key(t) not in before) or (before is None and min(d, 45 - d) > 0.1): return "bridge"
    for p in bynet.get(net, []):
        if p.IsOnLayer(lay) and p.HitTest(t.GetStart()) and p.HitTest(t.GetEnd()): return "in-pad"
    return None
def state(code):                                        # unconnected count, pad groups, dangling track ends
    b.BuildConnectivity(); c = b.GetConnectivity()
    grp = {frozenset(f"{q.GetParentFootprint().GetReference()}.{q.GetNumber()}" for q in c.GetConnectedItems(p) if q.GetClass() == "PAD")
           | {f"{p.GetParentFootprint().GetReference()}.{p.GetNumber()}"} for p in bynet.get(code, [])}
    dang = sum(c.TestTrackEndpointDangling(t, False) for t in T if t.GetNetCode() == code and t.GetClass() == "PCB_TRACK")
    return c.GetUnconnectedCount(False), grp, dang

cand = [t for t in T if t.GetClass() == "PCB_TRACK" and not any(fnmatch.fnmatchcase(t.GetNetname(), p) for p in KEEP_NETS)
        and key(t) not in protect]
cand = [(k, t) for t in cand for k in [kind(t)] if k]
cand.sort(key=lambda c: c[0] != "bridge")       # bridges first: they may make router copper look redundant
removed = []
for _, t in cand:
    k = kind(t)                                         # again: an earlier removal may have uncovered it
    if not k: continue
    code = t.GetNetCode(); s0 = state(code)
    s, e, w, lay, nm = t.GetStart(), t.GetEnd(), t.GetWidth(), t.GetLayer(), t.GetNetname()
    b.Remove(t); T[:] = [u for u in T if u is not t]
    s1 = state(code)
    if s1[0] > s0[0] or s1[1] != s0[1] or s1[2] > s0[2]:   # load-bearing after all: put it back
        n = pcbnew.PCB_TRACK(b); n.SetStart(s); n.SetEnd(e); n.SetWidth(w); n.SetLayer(lay); n.SetNetCode(code); b.Add(n); T.append(n)
        print(f"   kept {nm} ({ToMM(s.x):.3f},{ToMM(s.y):.3f}): connectivity would change"); continue
    removed.append(f"{nm} {b.GetLayerName(lay)} ({ToMM(s.x):.3f},{ToMM(s.y):.3f})-({ToMM(e.x):.3f},{ToMM(e.y):.3f}) "
                   f"w{ToMM(w):.2f} L{ToMM(math.hypot(e.x - s.x, e.y - s.y)):.3f} {k}")
print(f"tidy: removed {len(removed)}"); [print("  ", r) for r in removed]

# Sliver merge (R3): a sliver S (< 0.08 mm) that is not copper-invisible joins the end of track V to the end of
# track H (one other track at each end, same net / layer, neither protected). V and H are extended / cut to the
# intersection Q of their centre lines and S is removed, so V and H keep their directions (no off-grid stub).
# Only if Q is < 0.08 mm from both of S's ends and neither V nor H turns round; undone like a removal above.
# On this board: the router's +12V 0.5 mm run ends with a 0.051 mm step from (239.8, 76.8) to (239.808, 76.85),
# a point on the carried U17.11-U17.12 tie (0.4 mm); Q = (239.8, 76.85), H loses 0.008 mm under V's end cap.
P1 = lambda p: (round(ToMM(p.x), 3), round(ToMM(p.y), 3))
merged = []
for t in [t for t in T if t.GetClass() == "PCB_TRACK" and t.GetLength() < SLIVER and t.GetLength() > 0
          and not any(fnmatch.fnmatchcase(t.GetNetname(), p) for p in KEEP_NETS) and key(t) not in protect]:
    code, lay = t.GetNetCode(), t.GetLayer(); A, P = t.GetStart(), t.GetEnd()
    at = lambda q: [u for u in T if u is not t and u.GetClass() == "PCB_TRACK" and u.GetNetCode() == code
                    and u.GetLayer() == lay and (P1(u.GetStart()) == P1(q) or P1(u.GetEnd()) == P1(q))]
    va, hp = at(A), at(P)
    if len(va) != 1 or len(hp) != 1 or va[0] is hp[0] or key(va[0]) in protect or key(hp[0]) in protect: continue
    V, H = va[0], hp[0]
    vend = "s" if P1(V.GetStart()) == P1(A) else "e"; hend = "s" if P1(H.GetStart()) == P1(P) else "e"
    vf = V.GetEnd() if vend == "s" else V.GetStart(); hf = H.GetEnd() if hend == "s" else H.GetStart()   # fixed ends
    d1 = (A.x - vf.x, A.y - vf.y); d2 = (P.x - hf.x, P.y - hf.y); den = d1[0] * d2[1] - d1[1] * d2[0]
    if den == 0: continue                                                  # parallel: no intersection
    u = ((hf.x - vf.x) * d2[1] - (hf.y - vf.y) * d2[0]) / den; w_ = ((hf.x - vf.x) * d1[1] - (hf.y - vf.y) * d1[0]) / den
    if u <= 0 or w_ <= 0: continue                                         # V or H would turn round
    Q = pcbnew.VECTOR2I(int(round(vf.x + u * d1[0])), int(round(vf.y + u * d1[1])))
    if math.hypot(Q.x - A.x, Q.y - A.y) >= SLIVER or math.hypot(Q.x - P.x, Q.y - P.y) >= SLIVER: continue
    s0 = state(code); sw, nm = t.GetWidth(), t.GetNetname()
    setv = V.SetStart if vend == "s" else V.SetEnd; seth = H.SetStart if hend == "s" else H.SetEnd
    setv(Q); seth(Q); b.Remove(t); T[:] = [x for x in T if x is not t]
    s1 = state(code)
    if s1[0] > s0[0] or s1[1] != s0[1] or s1[2] > s0[2]:
        setv(A); seth(P)
        n = pcbnew.PCB_TRACK(b); n.SetStart(A); n.SetEnd(P); n.SetWidth(sw); n.SetLayer(lay); n.SetNetCode(code); b.Add(n); T.append(n)
        print(f"   kept {nm} ({ToMM(A.x):.3f},{ToMM(A.y):.3f}): merge would change connectivity"); continue
    merged.append(f"{nm} {b.GetLayerName(lay)} ({ToMM(A.x):.4f},{ToMM(A.y):.4f})-({ToMM(P.x):.4f},{ToMM(P.y):.4f}) "
                  f"L{ToMM(math.hypot(P.x - A.x, P.y - A.y)):.3f} -> joint ({ToMM(Q.x):.4f},{ToMM(Q.y):.4f})")
print(f"tidy: merged {len(merged)} sliver(s)"); [print("  ", r) for r in merged]
pcbnew.SaveBoard(a[1], b)
