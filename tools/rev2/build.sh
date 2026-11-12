#!/usr/bin/env bash
# Rev 2 board build: Rev 1 board + Rev 2 schematic -> Rev 2 board, checked.
#   sch_edit.py was run once (Rev 1 schematic -> Rev 2 schematic) and is not part of this build.
#   1. netlist from the schematic        4. tidy.py   (hand clean-up of squiggles)
#   2. pcb_edit.py (parts, copper, In2)  5. DRC gate, camera length check, meander check, plane check
#   3. jogs.py     (staircase merges)    6. board copied to the repository root
# usage: bash tools/rev2/build.sh        (KICAD_CLI / KICAD_PY / REV1 override the defaults)
# REV1: git revision that holds the Rev 1 board (default: the EuroCard merge 4381eab).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(cd "$HERE/../.." && pwd)"
KICAD_CLI="${KICAD_CLI:-kicad-cli}"; KICAD_PY="${KICAD_PY:-python3}"; REV1="${REV1:-4381eab}"
FPDIR="${KICAD_FOOTPRINT_DIR:-/usr/share/kicad/footprints}"
W="$HERE/work"; rm -rf "$W"; mkdir -p "$W/final"
q() { grep -v "swig/python\|image handler" || true; }
git -C "$ROOT" show "$REV1:PiEBV_Pico.kicad_pcb" > "$W/rev1.kicad_pcb"
cp "$ROOT/PiEBV_Pico.kicad_pro" "$W/rev1.kicad_pro"
"$KICAD_CLI" sch export netlist --format kicadsexpr -o "$W/rev2.net" "$ROOT/PiEBV_Pico.kicad_sch" >/dev/null
"$KICAD_PY" "$HERE/pcb_edit.py" "$W/rev1.kicad_pcb" "$W/rev2.net" "$W/a.kicad_pcb" "$FPDIR" 2>&1 | q
"$KICAD_PY" "$HERE/jogs.py" "$W/a.kicad_pcb" "$W/b.kicad_pcb" "$HERE/jog_choices.json" "$W/jogs.json" 2>&1 | q
"$KICAD_PY" "$HERE/tidy.py" "$W/b.kicad_pcb" "$W/final/PiEBV_Pico.kicad_pcb" 2>&1 | q
cp "$ROOT/PiEBV_Pico.kicad_pro" "$ROOT/PiEBV_Pico.kicad_sch" "$ROOT/fp-lib-table" "$ROOT/sym-lib-table" "$W/final/"; cp -r "$ROOT/libs" "$W/final/"
# DRC with the project rules; zones refilled and saved. Errors or unconnected items stop the build.
"$KICAD_CLI" pcb drc --schematic-parity --severity-all --refill-zones --save-board --format json -o "$W/final/drc.json" "$W/final/PiEBV_Pico.kicad_pcb" >/dev/null
"$KICAD_PY" "$ROOT/tools/eurocard/drc_gate.py" "$W/final/drc.json"
# Camera line lengths as KiCad reads them, Rev 1 against Rev 2: no group may get a larger spread, Sync must not change.
"$KICAD_PY" "$ROOT/tools/eurocard/kilen.py" "$W/rev1.kicad_pcb" "$W/rev1.kicad_pro" "$W/len1.txt" "$KICAD_CLI" >/dev/null
"$KICAD_PY" "$ROOT/tools/eurocard/kilen.py" "$W/final/PiEBV_Pico.kicad_pcb" "$W/final/PiEBV_Pico.kicad_pro" "$W/len2.txt" "$KICAD_CLI" >/dev/null
"$KICAD_PY" - "$W/len1.txt" "$W/len2.txt" <<'PY'
import sys
a, b = (dict((l.split()[0], float(l.split()[1])) for l in open(f)) for f in sys.argv[1:3])
bad = 0
for g in ("Sync", "Trigger", "TDRSTN"):
    s1 = [a["%s%d" % (g, i)] for i in range(1, 7)]; s2 = [b["%s%d" % (g, i)] for i in range(1, 7)]
    d = max(abs(x - y) for x, y in zip(s1, s2))
    print("lengths %-7s Rev 1 %.2f-%.2f (spread %.2f)  Rev 2 %.2f-%.2f (spread %.2f)  largest change %.4f mm"
          % (g, min(s1), max(s1), max(s1) - min(s1), min(s2), max(s2), max(s2) - min(s2), d))
    bad += (max(s2) - min(s2) > max(s1) - min(s1) + 0.002) or (g == "Sync" and d > 0.002)
sys.exit(1 if bad else 0)
PY
node "$ROOT/tools/eurocard/meander_check.js" "$W/final/PiEBV_Pico.kicad_pcb" 0.3 Sync Trigger TDRSTN
"$KICAD_PY" "$HERE/plane_check.py" "$W/final/PiEBV_Pico.kicad_pcb" "$W/final/plane.json" 2>/dev/null > "$W/final/plane.txt"
grep -q "NOT IN ISLAND" "$W/final/plane.txt" && { grep "NOT IN ISLAND" "$W/final/plane.txt"; exit 1; }
grep -A1 "PWM_1MHz\|PWM_TRIG_TAP " "$W/final/plane.txt" | grep -v "^--"
cp "$W/final/PiEBV_Pico.kicad_pcb" "$ROOT/PiEBV_Pico.kicad_pcb"
echo "build: Rev 2 board written to $ROOT/PiEBV_Pico.kicad_pcb"
