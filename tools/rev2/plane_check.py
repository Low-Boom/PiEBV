#!/usr/bin/env python3
"""Reference-plane check of the B.Cu tracks against the In2.Cu power islands.

B.Cu tracks have In2.Cu as their reference plane (0.21 mm away). A track that goes from one
island to another crosses a gap in its reference plane. This tool lists, for each net with
B.Cu copper, the island under every part of its B.Cu route and the points where the route
changes island. It also checks that every pad and via of a plane net lies inside the island
of its net (a "tap"), and counts the taps.

usage (KiCad 10 Python):  plane_check.py BOARD.kicad_pcb [OUT.json]
"""
import json
import sys

import pcbnew

b = pcbnew.LoadBoard(sys.argv[1])
mm = pcbnew.ToMM
IN2, BCU = b.GetLayerID("In2.Cu"), pcbnew.B_Cu
STEP = 0.05                                             # mm between samples along a track

zones = []                                              # (priority, net, outline points); highest priority first
for z in b.Zones():
    if z.GetIsRuleArea() or not z.IsOnLayer(IN2):
        continue
    o = z.Outline().Outline(0)
    zones.append((z.GetAssignedPriority(), z.GetNetname(), [(mm(o.CPoint(i).x), mm(o.CPoint(i).y)) for i in range(o.PointCount())]))
zones.sort(key=lambda q: -q[0])


def inside(pts, x, y):
    n, c = len(pts), False
    for i in range(n):
        (x1, y1), (x2, y2) = pts[i], pts[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            c = not c
    return c


def island(x, y):
    """Net of the In2 zone outline that owns (x, y). The 0.5 mm gaps between islands belong to the GND fill outline."""
    for _, name, pts in zones:
        if inside(pts, x, y):
            return name
    return "none"


# ---- B.Cu routes -----------------------------------------------------------------------------------------
routes = {}
for t in b.Tracks():
    if t.Type() == pcbnew.PCB_VIA_T or t.GetLayer() != BCU:
        continue
    s, e = t.GetStart(), t.GetEnd()
    x1, y1, x2, y2 = mm(s.x), mm(s.y), mm(e.x), mm(e.y)
    ln = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
    k = max(1, int(ln / STEP))
    r = routes.setdefault(t.GetNetname(), dict(length=0.0, over={}, crossings=[]))
    r["length"] += ln
    prev = None
    for i in range(k + 1):
        x, y = x1 + (x2 - x1) * i / k, y1 + (y2 - y1) * i / k
        isl = island(x, y)
        r["over"][isl] = r["over"].get(isl, 0.0) + ln / (k + 1)
        if prev is not None and isl != prev:
            r["crossings"].append(dict(x=round(x, 2), y=round(y, 2), frm=prev, to=isl))
        prev = isl

# a crossing through the gap is seen as island -> GND -> island within 0.5-0.8 mm: merge those pairs
for r in routes.values():
    cr, out, i = r["crossings"], [], 0
    while i < len(cr):
        a = cr[i]
        if i + 1 < len(cr) and a["to"] == "GND" and cr[i + 1]["frm"] == "GND" and \
                abs(cr[i + 1]["x"] - a["x"]) + abs(cr[i + 1]["y"] - a["y"]) < 1.6:
            out.append(dict(x=a["x"], y=a["y"], frm=a["frm"], to=cr[i + 1]["to"]))
            i += 2
        else:
            out.append(a)
            i += 1
    r["crossings"] = [c for c in out if c["frm"] != c["to"]]

# ---- taps: pads and vias of the plane nets ---------------------------------------------------------------
PLANE = [n for _, n, _ in zones if n != "GND"]
taps = {n: dict(vias=0, tht_pads=0, wrong=[], other=[]) for n in PLANE}
for t in b.Tracks():
    if t.Type() == pcbnew.PCB_VIA_T and t.GetNetname() in taps:
        p = t.GetPosition()
        isl = island(mm(p.x), mm(p.y))
        if isl == t.GetNetname():
            taps[isl]["vias"] += 1
        else:
            taps[t.GetNetname()]["other"].append("via (%.2f, %.2f) over the %s zone: fed by its tracks, not by the plane" % (mm(p.x), mm(p.y), isl))
for f in b.GetFootprints():
    for p in f.Pads():
        if p.GetNetname() in taps and p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH:
            q = p.GetPosition()
            isl = island(mm(q.x), mm(q.y))
            if isl == p.GetNetname():
                taps[isl]["tht_pads"] += 1
            else:
                taps[p.GetNetname()]["wrong"].append("%s.%s over %s" % (f.GetReference(), p.GetNumber(), isl))

print("In2 zones (filled copper area, mm2; the board is 16000 mm2):")
for z in b.Zones():
    if not z.GetIsRuleArea() and z.IsOnLayer(IN2):
        z.CalculateFilledArea()
        print("  %-6s %8.0f" % (z.GetNetname(), z.GetFilledArea() / 1e12))
print("Taps (vias and through-hole pads inside the island of their net):")
bad = 0
for n in PLANE:
    print("  %-6s vias %2d, through-hole pads %d%s%s" % (n, taps[n]["vias"], taps[n]["tht_pads"],
                                                      "".join("\n      NOT IN ISLAND: " + w for w in taps[n]["wrong"]),
                                                      "".join("\n      note: " + w for w in taps[n]["other"])))
    bad += len(taps[n]["wrong"])
print("B.Cu routes over In2 (length mm; island changes):")
for name in sorted(routes):
    r = routes[name]
    over = ", ".join("%s %.1f" % (k, v) for k, v in sorted(r["over"].items(), key=lambda q: -q[1]))
    print("  %-22s %6.1f  over: %s" % (name, r["length"], over))
    for c in r["crossings"]:
        print("      crossing at (%.2f, %.2f): %s -> %s" % (c["x"], c["y"], c["frm"], c["to"]))
if len(sys.argv) > 2:
    json.dump(dict(routes=routes, taps=taps), open(sys.argv[2], "w"), indent=1)
sys.exit(1 if bad else 0)
