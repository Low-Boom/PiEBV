#!/usr/bin/env bash
# Rebuild the EuroCard (160 x 100 mm) board from the hand-routed 126 x 126 mm Rev 1 board.
# Steps: place.py -> plane registration -> taps.py -> route.py (KiCadRoutingTools) -> unlock ->
# GND stitching -> silk.py -> finish.py -> KiCad DRC. Result: work/final/PiDG_Pico.kicad_pcb
# usage: bash build.sh            (KRT_DIR / KRT_PY / KICAD_PY / KICAD_CLI / SRC_REV override the defaults)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(cd "$HERE/../.." && pwd)"
SRC_REV="${SRC_REV:-3883378}"                     # main with the hand-routed 126 x 126 mm Rev 1 board
KRT_DIR="${KRT_DIR:-$HERE/KiCadRoutingTools}"     # github.com/drandyhaas/KiCadRoutingTools @ 8759686
KRT_PY="${KRT_PY:-$HERE/.venv/Scripts/python.exe}"
KICAD_PY="${KICAD_PY:-C:/Users/Flow-Lab/AppData/Local/Programs/KiCad/10.0/bin/python.exe}"
KICAD_CLI="${KICAD_CLI:-C:/Users/Flow-Lab/AppData/Local/Programs/KiCad/10.0/bin/kicad-cli.exe}"
W="$HERE/work"; rm -rf "$W"; mkdir -p "$W"
project() { cp "$ROOT/PiDG_Pico.kicad_pro" "$ROOT/PiDG_Pico.kicad_sch" "$ROOT/fp-lib-table" "$ROOT/sym-lib-table" "$1/"; cp -r "$ROOT/libs" "$1/"; }
drc() { "$KICAD_CLI" pcb drc --schematic-parity --severity-all --refill-zones --save-board --format json -o "$1/drc.json" "$1/PiDG_Pico.kicad_pcb" | grep Found; }

# 1. Placement on the new outline; carried copper and the equal-length pulse lanes are locked.
git -C "$ROOT" show "$SRC_REV:PiDG_Pico.kicad_pcb" > "$W/src.kicad_pcb"
"$KICAD_PY" "$HERE/place.py" "$W/src.kicad_pcb" "$W/placed.kicad_pcb" 2>/dev/null | grep -i 'carried\|lane' || true
cp "$ROOT/PiDG_Pico.kicad_pro" "$W/placed.kicad_pro"

# 2. Register the In1 GND / In2 +5V planes with the router (keeps the existing zones).
(cd "$KRT_DIR" && "$KRT_PY" py_router/route_planes.py "$W/placed.kicad_pcb" "$W/planes.kicad_pcb" --nets GND +5V \
  --plane-layers In1.Cu In2.Cu --skip-existing-zones --thermal-relief --via-size 0.6 --via-drill 0.3 \
  --same-net-pad-clearance 0.1) > "$W/planes.log" 2>&1

# 3. Locked plane taps (every SMD GND / +5V pad -> via), so the router routes signals only.
"$KICAD_PY" "$HERE/taps.py" "$W/planes.kicad_pcb" "$W/tapped.kicad_pcb" 2>/dev/null | grep -i 'tap' || true
cp "$W/planes.kicad_pro" "$W/tapped.kicad_pro"

# 4. Autoroute: F.Cu/B.Cu only, fixed sizes, no via-in-pad, matched camera lines.
(cd "$KRT_DIR" && "$KRT_PY" py_router/route.py "$W/tapped.kicad_pcb" "$W/routed.kicad_pcb" --nets "*" \
  --layers F.Cu In1.Cu In2.Cu B.Cu --layer-costs 1.0 -1 -1 1.0 --track-width 0.3 --clearance 0.2 \
  --power-nets GND "+5V" "+12V" "VBUS_PD" "+5V_PD" "+3V3" "+1V8" "Net-(U15-SW)" "Net-(J17-CC*)" PWM_1MHz \
  --power-nets-widths 0.4 0.5 0.5 0.5 0.5 0.5 0.5 0.6 0.2 0.5 \
  --escalation off --fab-tier standard --same-net-pad-clearance 0.1 --no-fix-drc-settings \
  --via-cost 150 --turn-cost 300 --direction-preference-cost 0 \
  --length-match-group "Sync*" --length-match-group "Trigger*" --length-match-group "TDRSTN*" \
  --meander-amplitude 1.5 --meander-spacing 1.0 --write-fill) > "$W/route.log" 2>&1
grep -A3 '^Run complete' "$W/route.log" | tail -2

# 5. Unlock, refill, then GND stitching (edge fence 10 mm, area 15 mm) across F.Cu / In1 / B.Cu.
mkdir -p "$W/r"; node "$HERE/unlock.js" "$W/routed.kicad_pcb" "$W/r/PiDG_Pico.kicad_pcb"; project "$W/r"; drc "$W/r"
cp "$W/r/PiDG_Pico.kicad_pcb" "$W/st_in.kicad_pcb"; cp "$W/tapped.kicad_pro" "$W/st_in.kicad_pro"
(cd "$KRT_DIR" && "$KRT_PY" py_router/route_planes.py "$W/st_in.kicad_pcb" "$W/st_out.kicad_pcb" --nets GND GND GND \
  --plane-layers F.Cu In1.Cu B.Cu --skip-existing-zones --thermal-relief --via-size 0.6 --via-drill 0.3 \
  --same-net-pad-clearance 0.1 --stitch-vias --stitch-edge-fence --stitch-pitch 15 --stitch-fence-pitch 10) > "$W/stitch.log" 2>&1

# 6. Final touches and DRC.
mkdir -p "$W/final"; project "$W/final"
cp "$W/st_out.kicad_pcb" "$W/final/PiDG_Pico.kicad_pcb"
drc "$W/final" >/dev/null
"$KICAD_PY" "$HERE/silk.py" "$W/final/PiDG_Pico.kicad_pcb" "$W/final/PiDG_Pico.kicad_pcb" 2>/dev/null
"$KICAD_PY" "$HERE/finish.py" "$W/final/PiDG_Pico.kicad_pcb" "$W/final/PiDG_Pico.kicad_pcb" 2>/dev/null
drc "$W/final"
echo "result: $W/final/PiDG_Pico.kicad_pcb"
