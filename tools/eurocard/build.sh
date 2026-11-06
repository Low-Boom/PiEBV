#!/usr/bin/env bash
# Rebuild the EuroCard (160 x 100 mm) board from the hand-routed 126 x 126 mm Rev 1 board.
# Steps: place.py -> plane registration -> taps.py -> route.py camera lines (matched) -> lock.js -> route.py
# other nets (KiCadRoutingTools) -> unlock -> straighten.py -> repair.py -> GND stitching -> frag_stitch.py ->
# tjoin.py / dangling.py -> tidy.py -> silk.py -> finish.py -> ends.py -> camclean.py -> ends.py -> KiCad DRC -> gaps.py.
# Result: work/final/PiDG_Pico.kicad_pcb (DRC report drc.json, gap report gaps.txt)
# usage: bash build.sh            (KRT_DIR / KRT_PY / KICAD_PY / KICAD_CLI / SRC_REV override the defaults)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(cd "$HERE/../.." && pwd)"
SRC_REV="${SRC_REV:-3883378}"                     # main with the hand-routed 126 x 126 mm Rev 1 board
KRT_DIR="${KRT_DIR:-$HERE/KiCadRoutingTools}"     # github.com/drandyhaas/KiCadRoutingTools @ 8759686
KRT_PY="${KRT_PY:-$HERE/.venv/Scripts/python.exe}"
KICAD_PY="${KICAD_PY:-C:/Users/Flow-Lab/AppData/Local/Programs/KiCad/10.0/bin/python.exe}"
KICAD_CLI="${KICAD_CLI:-C:/Users/Flow-Lab/AppData/Local/Programs/KiCad/10.0/bin/kicad-cli.exe}"
export EP_PASTE_SPLIT="${EP_PASTE_SPLIT:-1}"    # U14 EP paste split (F21); set 0 for the library window
W="$HERE/work"; rm -rf "$W"; mkdir -p "$W"
project() { cp "$ROOT/PiDG_Pico.kicad_pro" "$ROOT/PiDG_Pico.kicad_sch" "$ROOT/fp-lib-table" "$ROOT/sym-lib-table" "$1/"; cp -r "$ROOT/libs" "$1/"; }
# Gate (F21, M8): count only non-warning severities as violations; warnings are printed so they stay in the log.
# drc_gate.py exits 1 on any violation or unconnected item, which stops the build (set -e). The two DRC runs that
# only make drc.json for dangling.py are not gates ("|| true").
drc() { "$KICAD_CLI" pcb drc --schematic-parity --severity-all --refill-zones --save-board --format json -o "$1/drc.json" "$1/PiDG_Pico.kicad_pcb" >/dev/null
  "$KICAD_PY" "$HERE/drc_gate.py" "$1/drc.json"; }
# Post-route script: post NAME[:LOG] FILTER args... -> stdout to work/LOG.log (LOG defaults to NAME), filtered lines
# shown; stderr appended to work/post.log. A script error stops the build and shows the end of post.log (n7).
post() { local s="${1%%:*}" l="${1#*:}" f="$2"; shift 2
  if ! "$KICAD_PY" "$HERE/$s.py" "$@" > "$W/$l.log" 2>> "$W/post.log"; then
    echo "post: $s.py failed (stderr in $W/post.log):"; grep -v "^swig/python\|image handler" "$W/post.log" | tail -20; exit 1; fi
  grep -v "^swig/python" "$W/$l.log" | grep -E "$f" || true; }
# R1: every via in a file KRT reads or writes must be a via KRT models as an obstacle (viaguard.py, KRT python).
# KRT's "3 via block(s) could not be read" warning is "(via J18 / J19 / J21 2-3)" text in three Description
# properties, not copper; viaguard counts the real (top-level) via blocks and stops the build on a mismatch.
vguard() { if ! "$KRT_PY" "$HERE/viaguard.py" "$KRT_DIR" "$@" >> "$W/viaguard.log" 2>&1; then
  grep '^viaguard' "$W/viaguard.log"; exit 1; fi; grep '^viaguard' "$W/viaguard.log" | tail -n "$#"; }

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

# 4. Autoroute: F.Cu/B.Cu only, fixed sizes, no via-in-pad. Two passes (F2, F3): the camera lines first, alone and
#    length-matched, then locked; then all other nets around them.
RARGS=(--layers F.Cu In1.Cu In2.Cu B.Cu --layer-costs 1.0 -1 -1 1.0 --track-width 0.3 --clearance 0.2
  --power-nets GND "+5V" "+12V" "VBUS_PD" "+5V_PD" "+3V3" "+1V8" "Net-(U15-SW)" "Net-(J17-CC*)" PWM_1MHz
  --power-nets-widths 0.4 0.5 0.5 0.5 0.5 0.5 0.5 0.6 0.2 0.5
  --escalation off --fab-tier standard --same-net-pad-clearance 0.1 --no-fix-drc-settings --direction-preference-cost 0)
# 4a. The 18 camera lines in a fixed order (searched for this placement; with the MPS order the group targets come
#     from lines routed late and the long way). --meander-spacing is in track widths: 2.5 x 0.3 = 0.75 mm arm
#     pitch, 0.45 mm gap between arms. Via cost 150: at 200 Sync5/Sync6 route 95-125 mm and Sync1 cannot match.
CAM_ORDER=(Trigger1 Trigger4 Trigger3 TDRSTN3 TDRSTN2 Trigger5 Sync1 TDRSTN1 Trigger6 TDRSTN4 Sync2 TDRSTN5 Sync4 TDRSTN6 Sync3 Sync5 Sync6 Trigger2)
(cd "$KRT_DIR" && "$KRT_PY" py_router/route.py "$W/tapped.kicad_pcb" "$W/cam.kicad_pcb" --nets "${CAM_ORDER[@]}" --ordering original \
  "${RARGS[@]}" --via-cost 150 --turn-cost 300 \
  --length-match-group "Sync*" --length-match-group "Trigger*" --length-match-group "TDRSTN*" \
  --meander-amplitude 2.0 --meander-spacing 2.5 --length-match-tolerance 0.5) > "$W/route_cam.log" 2>&1
grep -A2 '^Run complete' "$W/route_cam.log" | tail -1
grep -E 'Length matching group|NOT matched' "$W/route_cam.log" || true
node "$HERE/meander_check.js" "$W/cam.kicad_pcb" 0.3 Sync Trigger TDRSTN    # exit 1: arms (own copper) < 0.3 mm apart
node "$HERE/lock.js" "$W/cam.kicad_pcb" "$W/cam_l.kicad_pcb" '^(Sync|Trigger|TDRSTN)[1-6]$'
cp "$W/tapped.kicad_pro" "$W/cam_l.kicad_pro"
# 4b. All other nets around the locked camera copper, no length-match groups. Turn cost 2000 (F31; 300 before):
#     segments shorter than 0.5 mm 184 -> 79, +2 vias.
(cd "$KRT_DIR" && "$KRT_PY" py_router/route.py "$W/cam_l.kicad_pcb" "$W/routed.kicad_pcb" --nets "*" \
  "${RARGS[@]}" --via-cost 200 --turn-cost 2000 --mps-reverse-rounds --write-fill) > "$W/route.log" 2>&1
grep -A3 '^Run complete' "$W/route.log" | tail -2
vguard "$W/placed.kicad_pcb" "$W/tapped.kicad_pcb" "$W/cam_l.kicad_pcb" "$W/routed.kicad_pcb"

# 5. Unlock, straighten (F31b), repair (F27), refill, then GND stitching (edge fence 10 mm, area 15 mm)
#    across F.Cu / In1 / B.Cu. straighten before repair: it has no 0.3 mm keep rule round SMD bodies.
mkdir -p "$W/r"; node "$HERE/unlock.js" "$W/routed.kicad_pcb" "$W/r/PiDG_Pico.kicad_pcb"
post straighten '^straighten' "$W/r/PiDG_Pico.kicad_pcb" "$W/r/PiDG_Pico.kicad_pcb" --protect "$W/tapped.kicad_pcb"
# F27: every front SMD part except J17 (USB-C). A foreign-net F.Cu run within 0.3 mm of a part's pad hull is
# routed again; on this routing C2 (PIXRST_GATE), C3 / C22 (LASER_PWR_OK) and C4 / C5 (LASER_EN).
REPAIR_PARTS=(C1 C2 C3 C4 C5 C6 C7 C9 C10 C11 C12 C13 C14 C15 C16 C17 C18 C19 C20 C21 C22 L1
  R2 R3 R6 R7 R8 R9 R10 R12 R13 R16 R17 R18 R19 R20 R21 R22 R23 R24 R25 R26 R27 R28 R29 R30 R31 R32
  U1 U2 U3 U4 U5 U6 U7 U8 U9 U10 U13 U14 U15 U16 U17 U18 U19)
post repair 'run of|rerouted|no route' "$W/r/PiDG_Pico.kicad_pcb" "$W/r/PiDG_Pico.kicad_pcb" "${REPAIR_PARTS[@]}"
project "$W/r"; drc "$W/r"
cp "$W/r/PiDG_Pico.kicad_pcb" "$W/st_in.kicad_pcb"; cp "$W/tapped.kicad_pro" "$W/st_in.kicad_pro"
(cd "$KRT_DIR" && "$KRT_PY" py_router/route_planes.py "$W/st_in.kicad_pcb" "$W/st_out.kicad_pcb" --nets GND GND GND \
  --plane-layers F.Cu In1.Cu B.Cu --skip-existing-zones --thermal-relief --via-size 0.6 --via-drill 0.3 \
  --same-net-pad-clearance 0.1 --stitch-vias --stitch-edge-fence --stitch-pitch 15 --stitch-fence-pitch 10) > "$W/stitch.log" 2>&1
vguard "$W/st_in.kicad_pcb" "$W/st_out.kicad_pcb"

# 6. Final touches and DRC.
mkdir -p "$W/final"; project "$W/final"
cp "$W/st_out.kicad_pcb" "$W/final/PiDG_Pico.kicad_pcb"
# F26: GND vias for F.Cu / B.Cu pour islands with < 2 vias and for neck pieces the stitch lattice skipped.
post frag_stitch . "$W/final/PiDG_Pico.kicad_pcb" "$W/final/PiDG_Pico.kicad_pcb"
drc "$W/final" >/dev/null || true
# Router clean-up: split tracks at T-joins (an end on another track's interior), then remove the stubs that
# DRC still reports as dangling, if connectivity holds without them.
"$KICAD_PY" "$HERE/tjoin.py" "$W/final/PiDG_Pico.kicad_pcb" "$W/final/PiDG_Pico.kicad_pcb" 2>/dev/null | grep "T-joins" || true
drc "$W/final" >/dev/null || true
"$KICAD_PY" "$HERE/dangling.py" "$W/final/drc.json" "$W/final/PiDG_Pico.kicad_pcb" 2>/dev/null | grep dangling || true
# F28: remove copper-invisible stitch bridges and slivers < 0.08 mm; --protect keeps the carried hand copper.
# --before st_in (n5): a "bridge" is a copper-invisible segment that the stitch step and later steps added
# (absent from st_in), as F28 intends; without it, any off-grid copper-invisible segment counted.
post tidy . "$W/final/PiDG_Pico.kicad_pcb" "$W/final/PiDG_Pico.kicad_pcb" --before "$W/st_in.kicad_pcb" --protect "$W/tapped.kicad_pcb"
"$KICAD_PY" "$HERE/silk.py" "$W/final/PiDG_Pico.kicad_pcb" "$W/final/PiDG_Pico.kicad_pcb" 2>/dev/null
"$KICAD_PY" "$HERE/finish.py" "$W/final/PiDG_Pico.kicad_pcb" "$W/final/PiDG_Pico.kicad_pcb" 2>/dev/null
# F18: camera track ends trimmed to the pad edge, off-centre via ends joined to the via centre. KiCad's length
# reading changes here.
post ends . "$W/final/PiDG_Pico.kicad_pcb" "$W/final/PiDG_Pico.kicad_pcb" "Sync?" "Trigger?" "TDRSTN?"
# U1 (last copper change): camera-line clean-up, length kept (camclean.py: square meander caps, staircases and
# acute corners replaced by clean 0/45/90 runs, caps moved to restore each line's pad-edge length); then ends.py
# again, to trim a pad end that a new segment reaches through the pad. Read camera lengths / skew after this.
# KiCad reads a re-shaped meander up to ~0.1 mm differently from its centre-line sum, so the camera lengths are
# read with KiCad before (len0) and after (len1), and camclean --trim moves the caps by the difference (len2 = len0
# on every line with caps).
CAM=("Sync?" "Trigger?" "TDRSTN?"); B="$W/final/PiDG_Pico.kicad_pcb"; PRO="$W/final/PiDG_Pico.kicad_pro"
post kilen:kilen0 . "$B" "$PRO" "$W/len0.txt" "$KICAD_CLI"
post camclean '^camclean|LEFT' "$B" "$B" --protect "$W/tapped.kicad_pcb" "${CAM[@]}"
post ends:ends2 '^ends' "$B" "$B" "${CAM[@]}"
post kilen:kilen1 . "$B" "$PRO" "$W/len1.txt" "$KICAD_CLI"
post camclean:camtrim '^camclean|LEFT' "$B" "$B" --protect "$W/tapped.kicad_pcb" --trim "$W/len0.txt" "$W/len1.txt" "${CAM[@]}"
post ends:ends3 '^ends' "$B" "$B" "${CAM[@]}"
post kilen:kilen2 . "$B" "$PRO" "$W/len2.txt" "$KICAD_CLI"
drc "$W/final"
node "$HERE/meander_check.js" "$W/final/PiDG_Pico.kicad_pcb" 0.3 Sync Trigger TDRSTN
# Courtyard gaps, long-edge strips and mounting-hole washers (report; MH lines must be absent).
"$KICAD_PY" "$HERE/gaps.py" "$W/final/PiDG_Pico.kicad_pcb" > "$W/final/gaps.txt" 2>/dev/null || true
echo "gaps.py: $(grep -c . "$W/final/gaps.txt" || true) lines, MH lines: $(grep -c '^MH' "$W/final/gaps.txt" || true)"
echo "result: $W/final/PiDG_Pico.kicad_pcb"
