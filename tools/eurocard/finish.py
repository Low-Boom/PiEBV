# Final touches (KiCad python): title block names the EuroCard variant; F.Fab outlines (F23); optional U14
# exposed-pad paste split.
# usage: python.exe finish.py in out      (EP_PASTE_SPLIT=1 in the environment enables the U14 paste split)
import os, sys, pcbnew
from pcbnew import VECTOR2I, FromMM, ToMM
b = pcbnew.LoadBoard(sys.argv[1])
tb = b.GetTitleBlock(); tb.SetTitle("IDS EVS Event-camera Synchronizer (Pico 2, EuroCard 160 x 100)"); b.SetTitleBlock(tb)
# F23: outlines on F.Fab (not plotted into the gerbers): the 160 x 100 mm EuroCard, taken from the Edge.Cuts
# bounding box, and the Pico 2 W module (U11 has no footprint) with its micro-USB receptacle, taken from the
# J15 / J14 socket pins. Module: 51 x 21 mm, its end 1.37 mm before pin 1; receptacle 8.0 mm wide, its face
# 1.30 mm past the module end (KiCad Module:RaspberryPi_Pico_Common_THT). On this board the face is at
# x 129.715, 0.285 mm past the left edge. Skipped if the drawings are there already (second run).
def rect(x0, y0, x1, y1, w=0.1):
    s = pcbnew.PCB_SHAPE(b); s.SetShape(pcbnew.SHAPE_T_RECT); s.SetLayer(pcbnew.F_Fab); s.SetWidth(FromMM(w))
    s.SetStart(VECTOR2I(FromMM(x0), FromMM(y0))); s.SetEnd(VECTOR2I(FromMM(x1), FromMM(y1))); b.Add(s)
def text(t, x, y):
    s = pcbnew.PCB_TEXT(b); s.SetText(t); s.SetLayer(pcbnew.F_Fab); s.SetPosition(VECTOR2I(FromMM(x), FromMM(y)))
    s.SetTextSize(VECTOR2I(FromMM(1.0), FromMM(1.0))); s.SetTextThickness(FromMM(0.15)); b.Add(s)
if not any(d.GetLayer() == pcbnew.F_Fab for d in b.GetDrawings()):
    E = [q for d in b.GetDrawings() if d.GetLayer() == pcbnew.Edge_Cuts for q in (d.GetStart(), d.GetEnd())]   # line centres
    rect(ToMM(min(q.x for q in E)), ToMM(min(q.y for q in E)), ToMM(max(q.x for q in E)), ToMM(max(q.y for q in E)))
    p15 = next(p for p in b.FindFootprintByReference("J15").Pads() if p.GetNumber() == "1").GetPosition()
    p14 = next(p for p in b.FindFootprintByReference("J14").Pads() if p.GetNumber() == "1").GetPosition()
    x1, cy = ToMM(p15.x), (ToMM(p15.y) + ToMM(p14.y)) / 2         # pin 1 at the USB end, rows 17.78 mm apart
    rect(x1 - 1.37, cy - 10.5, x1 - 1.37 + 51.0, cy + 10.5)
    rect(x1 - 1.37 - 1.30, cy - 4.0, x1 - 1.37 - 1.30 + 5.6, cy + 4.0)
    text("Pico 2 W (U11)", x1 - 1.37 + 25.5, cy)
    print("F.Fab: EuroCard outline, Pico module and micro-USB outlines; USB face at x %.3f" % (x1 - 2.67))
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
