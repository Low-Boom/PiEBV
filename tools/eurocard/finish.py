# Final touches (KiCad python): title block names the EuroCard variant; optional U14 exposed-pad paste split.
# usage: python.exe finish.py in out      (EP_PASTE_SPLIT=1 in the environment enables the U14 paste split)
import os, sys, pcbnew
from pcbnew import VECTOR2I, FromMM
b = pcbnew.LoadBoard(sys.argv[1])
tb = b.GetTitleBlock(); tb.SetTitle("IDS EVS Event-camera Synchronizer (Pico 2, EuroCard 160 x 100)"); b.SetTitleBlock(tb)
# U14 EP paste (review F21): the library window (1.69 x 2.66) covers both 0.3 mm GND via holes at footprint
# (0, +-0.8). Replace it with an "H": two 0.545 x 2.66 strips at x = +-0.5725 and a 0.60 x 1.0 bar between
# the holes. 3.50 mm2 (50 % of EP), holes 0.15 mm clear, vent path to the pad ends. Paste only: copper
# On by default (build.sh exports EP_PASTE_SPLIT=1). KiCad DRC then reports
# lib_footprint_mismatch on U14 (1 warning); kicad-cli 10.0.6 does not apply a
# drc_exclusions entry for it, so the gate (drc_gate.py) counts non-warning
# severities only and prints the warning to the build log.
if os.environ.get("EP_PASTE_SPLIT") == "1":
    f = b.FindFootprintByReference("U14")
    old = [p for p in f.Pads() if p.GetNumber() == "" and not p.IsOnCopperLayer() and p.IsOnLayer(pcbnew.F_Paste)]
    if len(old) == 1:                      # library window still there (skip on a second run)
        f.Remove(old[0])
        for lx, ly, sx, sy in [(-0.5725, 0, 0.545, 2.66), (0.5725, 0, 0.545, 2.66), (0, 0, 0.60, 1.0)]:
            p = pcbnew.PAD(f); p.SetAttribute(pcbnew.PAD_ATTRIB_SMD); p.SetNumber("")
            ls = pcbnew.LSET(); ls.AddLayer(pcbnew.F_Paste); p.SetLayerSet(ls)
            p.SetShape(pcbnew.F_Cu, pcbnew.PAD_SHAPE_RECT)
            p.SetSize(pcbnew.F_Cu, VECTOR2I(FromMM(sx), FromMM(sy)))
            f.Add(p); p.SetFPRelativePosition(VECTOR2I(FromMM(lx), FromMM(ly)))
        print("U14 EP paste split into 3 windows")
pcbnew.SaveBoard(sys.argv[2], b)
