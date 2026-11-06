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
pcbnew.SaveBoard(a[1], b)
