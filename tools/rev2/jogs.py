#!/usr/bin/env python3
"""Staircase clean-up with the track length kept.

The autorouter left runs of the form  run - step - run - step - run  where the three runs have
one direction and the two steps have one direction (a staircase). Such a run can be drawn as
run - one long step - run: the two steps are moved together. The path length does not change,
because the same vectors are added in another order. So the camera line lengths (and their
match) stay exactly as they were.

For each staircase there are two ways to merge: both steps at the start of the middle run
("A") or both at its end ("B"). The tool draws A, unless the choice file lists the merge as
"B" (drawn the other way) or "skip" (left as routed). tools/rev2/jogfit.py fits the choice
file: a merge that makes a DRC violation is set to "B", and to "skip" if B also fails.

Not touched: meander combs (their arms alternate direction, so they are not staircases), the
laser pulse lanes, the carried output-block copper, joints at a via, at a pad or at a branch.

usage (KiCad 10 Python): jogs.py IN.kicad_pcb OUT.kicad_pcb [CHOICES.json] [REPORT.json]
"""
import collections
import json
import math
import sys

import pcbnew

SRC, DST = sys.argv[1:3]
CHOICE = json.load(open(sys.argv[3])) if len(sys.argv) > 3 else {}
REPORT = sys.argv[4] if len(sys.argv) > 4 else None
MAX_STEP = 1.6          # mm: a step longer than this is a deliberate lane change
MAX_MID = 8.0           # mm: longest middle run between two steps that are merged
SKIP_NETS = ("_PULSE_OUT_CH1", "_PULSE_OUT_CH2", "CH1_", "CH2_", "EXT_SYNC_", "GND")

b = pcbnew.LoadBoard(SRC)
mm = pcbnew.ToMM
tracks = list(b.Tracks())
segs = [t for t in tracks if t.Type() != pcbnew.PCB_VIA_T]
via_at = {(t.GetNetname(), t.GetPosition().x, t.GetPosition().y) for t in tracks if t.Type() == pcbnew.PCB_VIA_T}
pads = [p for f in b.GetFootprints() for p in f.Pads()]


def at_pad(net, layer, q):
    for p in pads:
        if p.GetNetname() == net and p.IsOnLayer(layer) and p.HitTest(q):
            return True
    return False


segs_now = list(segs)
before = collections.Counter()
for t in segs:
    before[t.GetNetname()] += t.GetLength()
done, removed = [], []
changed = True
while changed:
    changed = False
    ends = collections.defaultdict(list)
    for t in segs_now:
        for q in (t.GetStart(), t.GetEnd()):
            ends[(t.GetNetname(), t.GetLayer(), q.x, q.y)].append(t)

    def joint(t, q):
        """The one other segment at end q of t, if q is a plain 2-segment joint."""
        k = (t.GetNetname(), t.GetLayer(), q.x, q.y)
        if len(ends[k]) != 2 or (t.GetNetname(), q.x, q.y) in via_at or at_pad(t.GetNetname(), t.GetLayer(), q):
            return None
        return ends[k][0] if ends[k][1] is t else ends[k][1]

    def far(t, q):
        s, e = t.GetStart(), t.GetEnd()
        return e if (s.x, s.y) == (q.x, q.y) else s

    def vec(a, c):
        return (c.x - a.x, c.y - a.y)

    def same_dir(u, w):
        lu, lw = math.hypot(*u), math.hypot(*w)
        return lu > 0 and lw > 0 and (u[0] * w[0] + u[1] * w[1]) / (lu * lw) > 0.9995

    for s0 in segs_now:
        net = s0.GetNetname()
        if any(net == n or (n.endswith("_") and net.startswith(n)) for n in SKIP_NETS):
            continue
        for p1 in (s0.GetStart(), s0.GetEnd()):          # walk s0 -> d1 -> s1 -> d2 -> s2 from p1
            p0 = far(s0, p1)
            d1 = joint(s0, p1)
            if d1 is None:
                continue
            p2 = far(d1, p1)
            s1 = joint(d1, p2)
            if s1 is None:
                continue
            p3 = far(s1, p2)
            d2 = joint(s1, p3)
            if d2 is None:
                continue
            p4 = far(d2, p3)
            s2 = joint(d2, p4)
            if s2 is None:
                continue
            p5 = far(s2, p4)
            u, w = vec(p0, p1), vec(p1, p2)
            if not (same_dir(u, vec(p2, p3)) and same_dir(u, vec(p4, p5)) and same_dir(w, vec(p3, p4))) or same_dir(u, w):
                continue
            if mm(d1.GetLength()) > MAX_STEP or mm(d2.GetLength()) > MAX_STEP or mm(s1.GetLength()) > MAX_MID:
                continue
            if len({x.GetWidth() for x in (s0, d1, s1, d2, s2)}) != 1:
                continue
            key = "%s %s %.3f %.3f" % (net, b.GetLayerName(s0.GetLayer()), mm(min(p1.x, p4.x)), mm(min(p1.y, p4.y)))
            how = CHOICE.get(key, "A")
            if how == "skip":
                continue
            if how == "A":      # both steps first: p1 -> p1 + d1 + d2 -> (run) -> p5
                q = pcbnew.VECTOR2I(p1.x + (p2.x - p1.x) + (p4.x - p3.x), p1.y + (p2.y - p1.y) + (p4.y - p3.y))
                new = [(p0, p1), (p1, q), (q, p5)]
            else:               # both steps last: p0 -> p1 + s1 -> p4 -> p5
                q = pcbnew.VECTOR2I(p1.x + (p3.x - p2.x), p1.y + (p3.y - p2.y))
                new = [(p0, q), (q, p4), (p4, p5)]
            for old in (s0, d1, s1, d2, s2):
                b.Remove(old)
                segs_now.remove(old)
                removed.append(old)                      # keep the Python objects alive (see pcb_edit.py)
            for a, c in new:
                t = pcbnew.PCB_TRACK(b)
                t.SetStart(a)
                t.SetEnd(c)
                t.SetWidth(s0.GetWidth())
                t.SetLayer(s0.GetLayer())
                t.SetNet(s0.GetNet())
                b.Add(t)
                segs_now.append(t)
            done.append(dict(key=key, how=how, net=net, x=mm(q.x), y=mm(q.y),
                             box=[mm(min(p0.x, p5.x, q.x)), mm(min(p0.y, p5.y, q.y)), mm(max(p0.x, p5.x, q.x)), mm(max(p0.y, p5.y, q.y))]))
            changed = True
            break
        if changed:
            break

after = collections.Counter()
for t in segs_now:
    after[t.GetNetname()] += t.GetLength()
worst = max((abs(after[n] - before[n]) for n in before), default=0)
assert worst <= 200, "length changed by %.6f mm" % mm(worst)      # nm: rounding of the merged end points only
pcbnew.SaveBoard(DST, b, True)
nets = collections.Counter(d["net"] for d in done)
print("jogs: %d staircases merged on %d nets, %d -> %d segments, largest length change %.6f mm"
      % (len(done), len(nets), len(segs), len(segs_now), mm(worst)))
print("jogs: " + ", ".join("%s %d" % kv for kv in sorted(nets.items())))
if REPORT:
    json.dump(done, open(REPORT, "w"), indent=1)
