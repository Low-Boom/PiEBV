#!/usr/bin/env python3
"""Fine length trim of the camera lines, by KiCad's own length reading.

The autorouter matches the lines of a group on its own length model. KiCad reads the lengths a
little differently (track ends in pads, vias). This tool reads the KiCad lengths (kilen.py) and
moves every line of a group to one target length. In a meander (arm - cap - arm, the two arms
antiparallel) the cap moves along the arms, so both arms change by the same amount.
  Target: the shortest length that every line of the group can reach (a line with no meander
  cannot get shorter), and not less than the shortest line.
  Shorter: the cap moves toward the open end. Copper moves only into the area the meander
  already used, so no clearance gets smaller.
  Longer: the cap moves outward, at most 0.8 mm per meander, and only if the new copper keeps
  0.22 mm to all other copper on its layer (rule: 0.2 mm) and 0.44 mm to its own line.
  A line that is 0.3 mm or more short after that gets one square bump (0.75 mm wide) in a
  straight run, with the same clearance test.

usage (KiCad 10 Python): trim.py IN.kicad_pcb LENGTHS.txt OUT.kicad_pcb
"""
import collections
import math
import sys

import pcbnew
from shapely.geometry import LineString, Point
from shapely.ops import unary_union

b = pcbnew.LoadBoard(sys.argv[1])
mm, MM = pcbnew.ToMM, pcbnew.FromMM
L = dict((ln.split()[0], float(ln.split()[1])) for ln in open(sys.argv[2]))
KEEP = 0.45                                             # mm of arm that stays
TOL = 0.02                                              # mm: smaller differences are left
BUMP_W = 0.75                                           # mm: width of a new bump (centre line to centre line)
segs = [t for t in b.Tracks() if t.Type() != pcbnew.PCB_VIA_T]


def unit(a, c):
    d = math.hypot(c.x - a.x, c.y - a.y)
    return ((c.x - a.x) / d, (c.y - a.y) / d)


def others(net, layer):
    """Copper of all other nets on `layer` (tracks, vias, pads), as one shape."""
    sh = []
    for t in b.Tracks():
        if t.GetNetname() == net:
            continue
        if t.Type() == pcbnew.PCB_VIA_T:
            sh.append(Point(mm(t.GetPosition().x), mm(t.GetPosition().y)).buffer(mm(t.GetWidth(layer)) / 2))
        elif t.GetLayer() == layer:
            sh.append(LineString([(mm(t.GetStart().x), mm(t.GetStart().y)), (mm(t.GetEnd().x), mm(t.GetEnd().y))]).buffer(mm(t.GetWidth()) / 2))
    for f in b.GetFootprints():
        for p in f.Pads():
            if p.GetNetname() != net and p.IsOnLayer(layer):
                bb = p.GetBoundingBox()
                sh.append(LineString([(mm(bb.GetLeft()), mm(bb.GetTop())), (mm(bb.GetRight()), mm(bb.GetBottom()))]).envelope)
    return unary_union(sh)


def line(t, mv=None, d=(0, 0)):
    """Centre line of t; the end points listed in mv are moved by d."""
    pts = []
    for v in (t.GetStart(), t.GetEnd()):
        k = (v.x, v.y)
        pts.append((mm(v.x + d[0]), mm(v.y + d[1])) if mv and k in mv else (mm(v.x), mm(v.y)))
    return LineString(pts)


def meanders(mine):
    """All (a, mid, d, p1, pd, ua): arms a and d antiparallel, joined by 1 to 5 cap pieces of 3 mm or less."""
    ends = collections.defaultdict(list)
    for t in mine:
        for q in (t.GetStart(), t.GetEnd()):
            ends[(t.GetLayer(), q.x, q.y)].append(t)

    def nxt(t, q):
        k = ends[(t.GetLayer(), q.x, q.y)]
        return (k[0] if k[1] is t else k[1]) if len(k) == 2 else None

    def far(t, q):
        s, e = t.GetStart(), t.GetEnd()
        return e if (s.x, s.y) == (q.x, q.y) else s

    out, seen = [], set()
    for a in sorted(mine, key=lambda t: (-t.GetLength(), t.GetStart().x, t.GetStart().y)):
        for p1 in (a.GetStart(), a.GetEnd()):
            p0 = far(a, p1)
            ua = unit(p0, p1)
            mid, q, t, d = [], p1, a, None
            for _ in range(6):
                t2 = nxt(t, q)
                if t2 is None:
                    break
                q2 = far(t2, q)
                ut = unit(q, q2)
                if ut[0] * ua[0] + ut[1] * ua[1] < -0.999:
                    d, pd = t2, q
                    break
                mid.append(t2)
                t, q = t2, q2
            if d is None or not mid or sum(mm(m.GetLength()) for m in mid) > 3.0:
                continue
            key = frozenset(id(x) for x in mid)
            if key not in seen:
                seen.add(key)
                out.append((a, mid, d, p1, pd, ua))
    return out


for g in ("Sync", "Trigger", "TDRSTN"):
    names = ["%s%d" % (g, i) for i in range(1, 7)]
    nets = {n: [t for t in segs if t.GetNetname() == n] for n in names}
    # shortest length each line can reach; the target is the largest of these
    low = {n: L[n] - 2 * sum(max(0.0, min(mm(a.GetLength()), mm(d.GetLength())) - KEEP) for a, mid, d, p1, pd, ua in meanders(nets[n]))
           for n in names}
    target = max(min(L[n] for n in names), max(low.values()))
    for n in names:
        need = L[n] - target                            # mm to remove (negative: to add)
        if abs(need) < TOL:
            continue
        mine, used, done = nets[n], set(), 0.0
        for a, mid, d, p1, pd, ua in meanders(mine):
            if abs(need - done) < TOL:
                break
            if used & {id(a), id(d)} or used & {id(m) for m in mid}:
                continue
            pts = {(p1.x, p1.y), (pd.x, pd.y)}
            for m in mid:
                pts |= {(m.GetStart().x, m.GetStart().y), (m.GetEnd().x, m.GetEnd().y)}
            if need > 0:                                # shorter: cap toward the open end
                room = min(mm(a.GetLength()), mm(d.GetLength())) - KEEP
                if room < 0.05:
                    continue
                sgn, s = -1, min(room, (need - done) / 2)
            else:                                       # longer: cap outward, if the new copper is clear
                sgn, s = 1, min(0.8, (done - need) / 2)
                obst = others(n, a.GetLayer())
                own = unary_union([line(t) for t in mine if t is not a and t is not d and t not in mid and t.GetLayer() == a.GetLayer()] or [Point(0, 0)])
                while s > 0.02:
                    dv = (int(round(ua[0] * MM(s))), int(round(ua[1] * MM(s))))
                    new = unary_union([line(t, pts, dv) for t in mid] +          # moved cap and the two arm extensions
                                      [LineString([(mm(v.x), mm(v.y)), (mm(v.x + dv[0]), mm(v.y + dv[1]))]) for v in (p1, pd)])
                    if new.distance(obst) >= 0.15 + 0.22 and new.distance(own) >= 0.3 + 0.44:
                        break
                    s -= 0.05
                else:
                    continue
            dx, dy = int(round(sgn * ua[0] * MM(s))), int(round(sgn * ua[1] * MM(s)))
            for t3 in [a, d] + mid:                     # every end point at a cap vertex moves by (dx, dy)
                for get, put in ((t3.GetStart, t3.SetStart), (t3.GetEnd, t3.SetEnd)):
                    v = get()
                    if (v.x, v.y) in pts:
                        put(pcbnew.VECTOR2I(v.x + dx, v.y + dy))
                used.add(id(t3))
            done += -sgn * 2 * s
        left = done - need                              # mm still to add
        if left >= 0.3:                                 # no meander could take it: one square bump in a straight run
            lay_obst = {}
            for t in sorted(mine, key=lambda t: (-t.GetLength(), t.GetStart().x, t.GetStart().y)):
                ln = mm(t.GetLength())
                if ln < BUMP_W + 1.6:
                    break
                if t.GetLayer() not in lay_obst:
                    lay_obst[t.GetLayer()] = others(n, t.GetLayer())
                obst = lay_obst[t.GetLayer()]
                own = unary_union([line(x) for x in mine if x is not t and x.GetLayer() == t.GetLayer()] or [Point(0, 0)])
                p, q = pcbnew.VECTOR2I(t.GetStart().x, t.GetStart().y), pcbnew.VECTOR2I(t.GetEnd().x, t.GetEnd().y)   # copies:
                u = unit(p, q)                          # GetEnd() gives a reference that SetEnd() would change
                hit = None
                for side in (1, -1):
                    nv = (-u[1] * side, u[0] * side)    # bump direction, square to the run
                    k = 0
                    while 0.8 + 0.25 * k + BUMP_W + 0.8 <= ln and hit is None:
                        t0 = 0.8 + 0.25 * k
                        A = (mm(p.x) + u[0] * t0, mm(p.y) + u[1] * t0)
                        Bq = (A[0] + u[0] * BUMP_W, A[1] + u[1] * BUMP_W)
                        A2 = (A[0] + nv[0] * left / 2, A[1] + nv[1] * left / 2)
                        B2 = (Bq[0] + nv[0] * left / 2, Bq[1] + nv[1] * left / 2)
                        new = LineString([A, A2, B2, Bq])
                        inner = LineString([(A[0] + nv[0] * 0.5, A[1] + nv[1] * 0.5), A2, B2, (Bq[0] + nv[0] * 0.5, Bq[1] + nv[1] * 0.5)])
                        if new.distance(obst) >= 0.15 + 0.22 and inner.distance(own) >= 0.3 + 0.44 and new.distance(own) >= 0.3 + 0.2:
                            hit = (A, A2, B2, Bq)
                        k += 1
                    if hit:
                        break
                if hit:
                    V = [p] + [pcbnew.VECTOR2I(MM(x), MM(y)) for x, y in hit] + [q]
                    t.SetEnd(V[1])
                    for a2, c2 in zip(V[1:], V[2:]):
                        nt = pcbnew.PCB_TRACK(b)
                        nt.SetStart(a2)
                        nt.SetEnd(c2)
                        nt.SetWidth(t.GetWidth())
                        nt.SetLayer(t.GetLayer())
                        nt.SetNet(t.GetNet())
                        b.Add(nt)
                        mine.append(nt)
                    done -= left
                    break
        print("trim: %-8s %.3f -> target %.3f, changed by %+.3f mm%s"
              % (n, L[n], target, -done, "" if abs(need - done) < TOL else "  (%.3f mm left)" % (need - done)))
pcbnew.SaveBoard(sys.argv[3], b, True)
