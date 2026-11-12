#!/usr/bin/env python3
"""Fit jog_choices.json to a new routing (run by hand after the camera routing changes).

Loop: jogs.py with the current choices -> DRC -> every staircase merge whose box holds a clearance,
short-circuit or track-crossing violation goes from "A" to "B", and from "B" to "skip". The loop ends
when no violation lies in a merge box. tools/rev2/build.sh then uses the file as it is.

usage: jogfit.py WORK_DIR   (after a build.sh run: reads WORK_DIR/b0.kicad_pcb; KICAD_CLI / KICAD_PY as build.sh)
"""
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
W = os.path.abspath(sys.argv[1])
CLI, PY = os.environ.get("KICAD_CLI", "kicad-cli"), os.environ.get("KICAD_PY", "python3")
CH = os.path.join(HERE, "jog_choices.json")
choice = json.load(open(CH))
D = os.path.join(W, "jf")
os.makedirs(D, exist_ok=True)
shutil.copy(os.path.join(ROOT, "PiEBV_Pico.kicad_pro"), D)
BAD = ("clearance", "shorting_items", "tracks_crossing", "hole_clearance", "copper_edge_clearance")
for it in range(12):
    json.dump(choice, open(CH, "w"), indent=1, sort_keys=True)
    subprocess.run([PY, os.path.join(HERE, "jogs.py"), os.path.join(W, "b0.kicad_pcb"), os.path.join(D, "PiEBV_Pico.kicad_pcb"),
                    CH, os.path.join(D, "jogs.json")], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run([CLI, "pcb", "drc", "--severity-all", "--refill-zones", "--format", "json", "-o", os.path.join(D, "drc.json"),
                    os.path.join(D, "PiEBV_Pico.kicad_pcb")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    pts = [(i["pos"]["x"], i["pos"]["y"]) for v in json.load(open(os.path.join(D, "drc.json")))["violations"]
           if v["type"] in BAD for i in v["items"]]
    flip = set()
    for m in json.load(open(os.path.join(D, "jogs.json"))):
        x0, y0, x1, y1 = m["box"]
        if any(x0 - 0.5 <= x <= x1 + 0.5 and y0 - 0.5 <= y <= y1 + 0.5 for x, y in pts):
            flip.add(m["key"])
    print("jogfit: pass %d, %d violation points, %d merges changed" % (it + 1, len(pts), len(flip)))
    if not flip:
        break
    for k in flip:
        choice[k] = "B" if choice.get(k, "A") == "A" else "skip"
json.dump(choice, open(CH, "w"), indent=1, sort_keys=True)
