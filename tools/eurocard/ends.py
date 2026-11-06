# Post-route step (KiCad python), F18: trim the free track ends of the given nets to the pad edge.
# The router stops a track anywhere inside the target pad (0.02-0.97 mm from the centre here). KiCad
# counts that in-pad copper when the end is off the pad centre, and cuts it at the pad outline when
# the end is on the centre, so equal router lengths read differently. After this step every pad end
# sits 5 um (EDGE) inside the pad outline, and KiCad's length is pad edge to pad edge on all nets.
# Track ends that stop off a via centre (e.g. on the rim) are joined to the centre; KiCad drops
# the via barrel (about 1.59 mm) from the length when no run reaches the via centre (--pads-only: skip).
# Only free ends (one track end at that point on that layer) change; branches, via-in-pad and other
# nets are not touched. All removed copper is inside the pad; all added copper is inside the via.
# usage: python.exe ends.py in.kicad_pcb out.kicad_pcb [--pads-only] "Sync?" "Trigger?" "TDRSTN?"
import sys, math, fnmatch, wx; wx.DisableAsserts()
import pcbnew
from collections import defaultdict
EDGE = 5000                                         # nm the trimmed end stays inside the outline
args = sys.argv[3:]; vias_too = "--pads-only" not in args; pats = [a for a in args if a != "--pads-only"]
b = pcbnew.LoadBoard(sys.argv[1]); mm = lambda v: v / 1e6
V = lambda x, y: pcbnew.VECTOR2I(int(round(x)), int(round(y)))
nets = sorted(n for n in map(str, b.GetNetsByName().keys()) if any(fnmatch.fnmatchcase(n, p) for p in pats))
trimmed = removed = joined = 0
for net in nets:
    code = b.GetNetcodeFromNetname(net)
    pads = [p for p in b.GetPads() if p.GetNetCode() == code]
    items = [t for t in b.GetTracks() if t.GetNetCode() == code]
    vias = [t for t in items if t.GetClass() == "PCB_VIA"]
    at = defaultdict(list)                          # (x, y, layer) -> segments with an end there
    for t in items:
        if t.GetClass() == "PCB_TRACK":
            for e in (t.GetStart(), t.GetEnd()): at[(e.x, e.y, t.GetLayer())].append(t)
    def drop(t, e): at[(e.x, e.y, L)][:] = [u for u in at[(e.x, e.y, L)] if u is not t]
    in_via = lambda e, L: next((v for v in vias if math.hypot(e.x - v.GetPosition().x, e.y - v.GetPosition().y)
                                <= v.GetWidth(L) / 2 + 1000), None)
    for (x, y, L), ts in list(at.items()):
        if len(ts) != 1: continue
        e = V(x, y); t = ts[0]
        pad = next((p for p in pads if p.IsOnLayer(L) and p.GetEffectivePolygon(L, pcbnew.ERROR_INSIDE).Contains(e)), None)
        v = in_via(e, L)
        if pad is None:
            if v is None or not vias_too: continue
            c = v.GetPosition()
            if math.hypot(e.x - c.x, e.y - c.y) < 1000: continue
            s = pcbnew.PCB_TRACK(b); s.SetStart(e); s.SetEnd(c); s.SetWidth(t.GetWidth()); s.SetLayer(L); s.SetNetCode(code)
            b.Add(s); joined += 1
            print(f"{net:9s} via end ({mm(e.x):.3f},{mm(e.y):.3f}) +{mm(math.hypot(e.x - c.x, e.y - c.y)):.3f} mm to centre")
            continue
        if v is not None: continue                  # via in pad: leave it
        poly = pad.GetEffectivePolygon(L, pcbnew.ERROR_INSIDE); cut = 0.0
        while True:                                 # walk back from the free end until the track leaves the pad
            s0, s1 = t.GetStart(), t.GetEnd()
            far = s1 if (s0.x, s0.y) == (e.x, e.y) else s0
            if poly.Contains(far):
                nxt = [u for u in at[(far.x, far.y, L)] if u is not t]
                if len(nxt) != 1 or in_via(far, L): break       # branch or via inside the pad: stop here
                cut += t.GetLength(); drop(t, far); drop(t, e); b.Remove(t); removed += 1
                t, e = nxt[0], far; continue
            lo, hi = 0.0, 1.0                       # fraction from far end; outline crossing by bisection
            for _ in range(40):
                m = (lo + hi) / 2
                if poly.Contains(V(far.x + (e.x - far.x) * m, far.y + (e.y - far.y) * m)): hi = m
                else: lo = m
            seg = math.hypot(e.x - far.x, e.y - far.y)
            k = min(1.0, hi + EDGE / seg)
            if (1 - k) * seg < 1000: break          # already at the edge
            n = V(far.x + (e.x - far.x) * k, far.y + (e.y - far.y) * k)
            if (s0.x, s0.y) == (e.x, e.y): t.SetStart(n)
            else: t.SetEnd(n)
            drop(t, e)                              # old end key now empty: not visited again
            cut += (1 - k) * seg; trimmed += 1; break
        if cut: print(f"{net:9s} {pad.GetParentFootprint().GetReference()}.{pad.GetNumber()} -{mm(cut):.3f} mm in pad")
print(f"ends: {trimmed} trimmed, {removed} in-pad segments removed, {joined} via ends joined")
pcbnew.SaveBoard(sys.argv[2], b)
