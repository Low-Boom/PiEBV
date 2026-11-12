#!/usr/bin/env python3
"""Coloured map of the In2.Cu power islands (filled copper) with the B.Cu tracks on top.

usage (KiCad 10 Python with matplotlib): island_map.py BOARD.kicad_pcb OUT.png
"""
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import PathPatch
from matplotlib.path import Path
import pcbnew

b = pcbnew.LoadBoard(sys.argv[1])
mm = pcbnew.ToMM
IN2 = b.GetLayerID("In2.Cu")
COL = {"+5V": "#f4a742", "+3V3": "#58b368", "+1V8": "#2aa6c9", "+VCAM": "#b9b23a", "+12V": "#b565c9", "GND": "#c9c9c9"}
fig, ax = plt.subplots(figsize=(16, 10), dpi=110)
for z in b.Zones():
    if z.GetIsRuleArea() or not z.IsOnLayer(IN2):
        continue
    ps = z.GetFilledPolysList(IN2)
    for i in range(ps.OutlineCount()):
        verts, codes = [], []
        for ring in [ps.Outline(i)] + [ps.Hole(i, h) for h in range(ps.HoleCount(i))]:
            pts = [(mm(ring.CPoint(k).x), mm(ring.CPoint(k).y)) for k in range(ring.PointCount())]
            verts += pts + [pts[0]]
            codes += [Path.MOVETO] + [Path.LINETO] * (len(pts) - 1) + [Path.CLOSEPOLY]
        ax.add_patch(PathPatch(Path(verts, codes), fc=COL.get(z.GetNetname(), "#dddddd"), ec="none"))
for t in b.Tracks():
    if t.Type() != pcbnew.PCB_VIA_T and t.GetLayer() == pcbnew.B_Cu:
        s, e = t.GetStart(), t.GetEnd()
        ax.plot([mm(s.x), mm(e.x)], [mm(s.y), mm(e.y)], color="#1d3f8f", lw=0.9, solid_capstyle="round")
for name, x, y in (("+5V", 160, 85), ("+3V3", 190, 35.5), ("+VCAM", 222, 118), ("+12V", 241.5, 68), ("GND", 272, 110),
                   ("+VCAM\ncorridor", 230.3, 62), ("+1V8", 225.2, 44.6)):
    ax.text(x, y, name, ha="center", va="center", fontsize=15 if "\n" not in name and name != "+1V8" else 8, weight="bold")
bb = b.GetBoardEdgesBoundingBox()
ax.set_xlim(mm(bb.GetLeft()), mm(bb.GetRight()))
ax.set_ylim(mm(bb.GetBottom()), mm(bb.GetTop()))
ax.set_aspect("equal")
ax.set_title("In2.Cu power islands (filled copper) and B.Cu tracks (blue). Board coordinates in mm.")
ax.tick_params(labelsize=8)
plt.tight_layout()
plt.savefig(sys.argv[2])
