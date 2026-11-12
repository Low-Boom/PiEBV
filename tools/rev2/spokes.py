#!/usr/bin/env python3
"""Pour cut-outs for pads with too few thermal spokes.

A camera track that passes a through-hole GND pin can cut off all but one thermal spoke of the
F.Cu or B.Cu pour (DRC: starved_thermal). Such a pin has its full connection to the GND plane
on In1.Cu. This tool reads the DRC report and puts a small pour keep-out (a rule area that
excludes zone fill, on that one layer) round each reported pad. The pour then does not touch
the pad on that layer; the In1.Cu connection is not changed.

usage (KiCad 10 Python): spokes.py IN.kicad_pcb DRC.json OUT.kicad_pcb
"""
import json
import math
import sys

import pcbnew

b = pcbnew.LoadBoard(sys.argv[1])
MM = pcbnew.FromMM
done = set()
for v in json.load(open(sys.argv[2]))["violations"]:
    if v["type"] != "starved_thermal":
        continue
    layer = b.GetLayerID(v["description"].split("layer ")[1].split(";")[0].split(")")[0].strip())
    pad = [i for i in v["items"] if " pad " in i["description"]][0]
    key = (layer, round(pad["pos"]["x"], 3), round(pad["pos"]["y"], 3))
    if key in done:
        continue
    done.add(key)
    assert "[GND]" in pad["description"] and "PTH" in pad["description"], pad["description"]
    z = pcbnew.ZONE(b)                                  # rule area: no zone fill inside, tracks and vias allowed
    z.SetIsRuleArea(True)
    z.SetDoNotAllowZoneFills(True)
    z.SetDoNotAllowTracks(False)
    z.SetDoNotAllowVias(False)
    z.SetDoNotAllowPads(False)
    z.SetDoNotAllowFootprints(False)
    z.SetLayer(layer)
    z.SetZoneName("no pour: %s" % pad["description"].split(" on ")[0])
    o = z.Outline()
    o.NewOutline()
    for k in range(16):                                 # 16-gon, 1.5 mm radius (pad radius 0.85 mm)
        a = 2 * math.pi * k / 16
        o.Append(MM(key[1] + 1.5 * math.cos(a)), MM(key[2] + 1.5 * math.sin(a)))
    b.Add(z)
pcbnew.SaveBoard(sys.argv[3], b, True)
print("spokes: %d pour cut-outs" % len(done))
