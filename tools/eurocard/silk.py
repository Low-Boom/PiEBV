# Reference labels that overlap other silkscreen after the re-placement: horizontal, beside the part.
# usage: python.exe silk.py in out
import sys, pcbnew
from pcbnew import VECTOR2I, FromMM, EDA_ANGLE, DEGREES_T
b = pcbnew.LoadBoard(sys.argv[1])
L, C, R = pcbnew.GR_TEXT_H_ALIGN_LEFT, pcbnew.GR_TEXT_H_ALIGN_CENTER, pcbnew.GR_TEXT_H_ALIGN_RIGHT
for ref, (x, y, j) in {"R18": (194.0, 68.4, C), "R29": (191.0, 72.3, C), "R10": (140.5, 123.4, C), "C16": (234.9, 82.645, R),
                       "C17": (232.9, 78.5, R),     # beside C16; clear of R12 pad 1
                       "U9": (217.2, 80.1, C), "C7": (220.9, 80.1, C), "C6": (212.6, 78.7, R),   # LDO above the buffer row
                       "U3": (217.79, 90.368, C),   # same offset as twin U1 (fp y - 2.539); clear of C2 courtyard
                       "U15": (150.7, 112.0, R),    # left of the U15 pin 1-3 row; clear of C13
                       "U10": (208.0, 70.9, C)}.items():   # below U10; clear of R3
    t = b.FindFootprintByReference(ref).Reference()
    t.SetTextAngle(EDA_ANGLE(0, DEGREES_T)); t.SetHorizJustify(j); t.SetPosition(VECTOR2I(FromMM(x), FromMM(y)))
# TP3 reference (hidden on Rev 1): shown, centred 2.9 mm below the footprint origin, so it follows TP3.
f = b.FindFootprintByReference("TP3"); t = f.Reference(); t.SetVisible(True)
t.SetTextAngle(EDA_ANGLE(0, DEGREES_T)); t.SetHorizJustify(C); t.SetPosition(f.GetPosition() + VECTOR2I(0, FromMM(2.9)))
pcbnew.SaveBoard(sys.argv[2], b)
