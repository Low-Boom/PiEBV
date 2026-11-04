# Reference labels that overlap other silkscreen after the re-placement: horizontal, beside the part.
# usage: python.exe silk.py in out
import sys, pcbnew
from pcbnew import VECTOR2I, FromMM, EDA_ANGLE, DEGREES_T
b = pcbnew.LoadBoard(sys.argv[1])
L = pcbnew.GR_TEXT_H_ALIGN_LEFT
for ref, (x, y, j) in {"R18": (194.4, 66.5, L), "R29": (194.4, 70.5, L)}.items():
    t = b.FindFootprintByReference(ref).Reference()
    t.SetTextAngle(EDA_ANGLE(0, DEGREES_T)); t.SetHorizJustify(j); t.SetPosition(VECTOR2I(FromMM(x), FromMM(y)))
pcbnew.SaveBoard(sys.argv[2], b)
