#!/usr/bin/env bash
# Rev 2 board build: Rev 1 board + Rev 2 schematic -> Rev 2 board, checked.
#   sch_edit.py was run once (Rev 1 schematic -> Rev 2 schematic) and is not part of this build.
#   1. netlist from the schematic
#   2. pcb_edit.py: parts, hand-drawn copper, In2 islands; the Rev 1 camera copper is removed, the series
#      resistors R52-R69 and their header stubs are placed, Trigger3 is drawn
#   3. KiCadRoutingTools: the other 17 camera lines, buffer -> resistor, length-matched in each group
#   4. jogs.py (staircase merges, length kept), tidy.py (hand clean-up of two non-camera squiggles),
#      trim.py (camera lines of a group made equal by KiCad's length reading)
#   5. spokes.py (pour cut-outs at header GND pins with one thermal spoke), DRC gate
#   6. camera length check (KiCad reading), meander check, plane check; board copied to the repository root
# usage: bash tools/rev2/build.sh
#   KICAD_CLI / KICAD_PY: KiCad 10 kicad-cli and the Python that has pcbnew and shapely
#   KRT_DIR / KRT_PY: KiCadRoutingTools checkout (commit 8759686, built) and its Python (see tools/eurocard/README.md)
#   REV1: git revision that holds the Rev 1 board (default: the EuroCard merge 4381eab)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(cd "$HERE/../.." && pwd)"
KICAD_CLI="${KICAD_CLI:-kicad-cli}"; KICAD_PY="${KICAD_PY:-python3}"; REV1="${REV1:-4381eab}"
KRT_DIR="${KRT_DIR:-$ROOT/tools/eurocard/KiCadRoutingTools}"; KRT_PY="${KRT_PY:-$ROOT/tools/eurocard/.venv/bin/python}"
FPDIR="${KICAD_FOOTPRINT_DIR:-/usr/share/kicad/footprints}"
W="$HERE/work"; rm -rf "$W"; mkdir -p "$W/final"
q() { grep -v "swig/python\|image handler" || true; }
git -C "$ROOT" show "$REV1:PiEBV_Pico.kicad_pcb" > "$W/rev1.kicad_pcb"
cp "$ROOT/PiEBV_Pico.kicad_pro" "$W/rev1.kicad_pro"
"$KICAD_CLI" sch export netlist --format kicadsexpr -o "$W/rev2.net" "$ROOT/PiEBV_Pico.kicad_sch" >/dev/null
"$KICAD_PY" "$HERE/pcb_edit.py" "$W/rev1.kicad_pcb" "$W/rev2.net" "$W/a0.kicad_pcb" "$FPDIR" 2>&1 | q
python3 "$HERE/uuidfix.py" "$W/a0.kicad_pcb" "$W/a.kicad_pcb"
# 3. Camera lines. All other copper is locked, so the router goes round it and does not move it. Trigger3 is
#    already drawn and is the length target of the Trigger group. The net order and the via cost were searched
#    for this placement (about 200 trials): this one matches all three groups. The router result depends on the
#    order of the items in its input file, so uuidfix.py first gives that file a fixed order.
CAM='^(Sync|Trigger|TDRSTN)[1-6]$'
node "$ROOT/tools/eurocard/lock.js" "$W/a.kicad_pcb" "$W/a_l.kicad_pcb" "^(?!(Sync|Trigger|TDRSTN)[1-6]\$).*|^Trigger3\$"
CAM_ORDER=(Trigger1 Trigger4 TDRSTN3 TDRSTN5 Trigger5 Sync3 TDRSTN1 Sync5 TDRSTN4 Trigger6 TDRSTN2 Sync4 Sync1 Sync2 Trigger2 Sync6 TDRSTN6)
(cd "$KRT_DIR" && "$KRT_PY" py_router/route.py "$W/a_l.kicad_pcb" "$W/cam.kicad_pcb" --nets "${CAM_ORDER[@]}" --ordering original \
  --layers F.Cu In1.Cu In2.Cu B.Cu --layer-costs 1.0 -1 -1 1.0 --track-width 0.3 --clearance 0.2 --via-size 0.6 --via-drill 0.3 \
  --power-nets GND "+5V" "+12V" "VBUS_PD" "+5V_PD" "+3V3" "+1V8" "+VCAM" "Net-(U15-SW)" "Net-(J17-CC*)" PWM_1MHz \
  --power-nets-widths 0.4 0.5 0.5 0.5 0.5 0.5 0.5 0.5 0.6 0.2 0.5 \
  --escalation off --fab-tier standard --same-net-pad-clearance 0.1 --no-fix-drc-settings --direction-preference-cost 0 \
  --via-cost 225 --turn-cost 300 \
  --length-match-group "Sync[1-6]" --length-match-group "Trigger[1-6]" --length-match-group "TDRSTN[1-6]" \
  --meander-amplitude 2.0 --meander-spacing 2.5 --length-match-tolerance 0.5) > "$W/route_cam.log" 2>&1
grep -A2 '^Run complete' "$W/route_cam.log" | tail -1
grep -q '"failed_single": \[\]' "$W/route_cam.log" || { echo "build: camera routing failed"; exit 1; }
node "$ROOT/tools/eurocard/unlock.js" "$W/cam.kicad_pcb" "$W/b0.kicad_pcb"
# The router must not have changed any other copper: per-net segment count and length, before and after.
python3 - "$W/a.kicad_pcb" "$W/b0.kicad_pcb" <<'PY'
import collections, re, sys
def census(path):                                       # (net, kind) -> [count, rounded coordinate sum] of the other nets
    c = collections.defaultdict(lambda: [0, 0.0])
    for m in re.finditer(r'\n\t\((segment|via)\n(.*?)\n\t\)', open(path, encoding="utf-8").read(), re.S):
        net = re.search(r'\(net "([^"]*)"\)', m.group(2)).group(1)
        if re.match(r"(Sync|Trigger|TDRSTN)[1-6]$", net):
            continue
        e = c[(net, m.group(1))]
        e[0] += 1
        e[1] += sum(float(x) for x in re.findall(r"\((?:start|end|at) ([-\d. ]+)\)", m.group(2))[0].split())
    return {k: (v[0], round(v[1], 3)) for k, v in c.items()}
a, b = census(sys.argv[1]), census(sys.argv[2])
if a != b:
    sys.exit("build: the router changed other copper: %s" % sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k)))
print("router: copper of the %d other nets not changed" % len({k[0] for k in a}))
PY
"$KICAD_PY" "$HERE/jogs.py" "$W/b0.kicad_pcb" "$W/b.kicad_pcb" "$HERE/jog_choices.json" "$W/jogs.json" 2>&1 | q
"$KICAD_PY" "$HERE/tidy.py" "$W/b.kicad_pcb" "$W/c.kicad_pcb" 2>&1 | q
# Fine trim to KiCad's own length reading (it includes the via length), three passes: meander caps move, and a
# line with no meander gets one bump. c.kicad_pcb -> e.kicad_pcb.
"$KICAD_PY" "$HERE/viafix.py" "$W/c.kicad_pcb" "$W/c0.kicad_pcb" 2>&1 | q; cp "$W/c0.kicad_pcb" "$W/c.kicad_pcb"   # track ends on via centres; check of the via size
cp "$ROOT/PiEBV_Pico.kicad_pro" "$W/c.kicad_pro"
for pass in 1 2 3; do
  "$KICAD_PY" "$ROOT/tools/eurocard/kilen.py" "$W/c.kicad_pcb" "$W/c.kicad_pro" "$W/len_c.txt" "$KICAD_CLI" >/dev/null
  "$KICAD_PY" "$HERE/trim.py" "$W/c.kicad_pcb" "$W/len_c.txt" "$W/e.kicad_pcb" 2>&1 | q | { grep -c "changed by [+-]0*\.\?0*[1-9]" || true; } | sed "s/^/trim: pass $pass, lines changed: /"
  cp "$W/e.kicad_pcb" "$W/c.kicad_pcb"
done
mkdir -p "$W/pre"; cp "$W/c.kicad_pcb" "$W/pre/PiEBV_Pico.kicad_pcb"
cp "$ROOT/PiEBV_Pico.kicad_pro" "$ROOT/PiEBV_Pico.kicad_sch" "$ROOT/fp-lib-table" "$ROOT/sym-lib-table" "$W/pre/"; cp -r "$ROOT/libs" "$W/pre/"
"$KICAD_CLI" pcb drc --severity-all --refill-zones --format json -o "$W/pre/drc.json" "$W/pre/PiEBV_Pico.kicad_pcb" >/dev/null
"$KICAD_PY" "$HERE/spokes.py" "$W/c.kicad_pcb" "$W/pre/drc.json" "$W/d.kicad_pcb" 2>&1 | q
python3 "$HERE/uuidfix.py" "$W/d.kicad_pcb" "$W/final/PiEBV_Pico.kicad_pcb"
cp "$ROOT/PiEBV_Pico.kicad_pro" "$ROOT/PiEBV_Pico.kicad_sch" "$ROOT/fp-lib-table" "$ROOT/sym-lib-table" "$W/final/"; cp -r "$ROOT/libs" "$W/final/"
# DRC with the project rules; zones refilled and saved. Errors or unconnected items stop the build.
"$KICAD_CLI" pcb drc --schematic-parity --severity-all --refill-zones --save-board --format json -o "$W/final/drc.json" "$W/final/PiEBV_Pico.kicad_pcb" >/dev/null
"$KICAD_PY" "$ROOT/tools/eurocard/drc_gate.py" "$W/final/drc.json"
# Camera line lengths as KiCad reads them (buffer pad to resistor pad; the resistor-to-header stubs are the same
# for all six headers). Limit on the spread in each group: 0.1 mm.
"$KICAD_PY" "$ROOT/tools/eurocard/kilen.py" "$W/final/PiEBV_Pico.kicad_pcb" "$W/final/PiEBV_Pico.kicad_pro" "$W/len2.txt" "$KICAD_CLI" >/dev/null
python3 - "$W/len2.txt" <<'PY'
import sys
b = dict((l.split()[0], float(l.split()[1])) for l in open(sys.argv[1]))
bad = 0
for g, lim in (("Sync", 0.1), ("Trigger", 0.1), ("TDRSTN", 0.1)):
    v = [b["%s%d" % (g, i)] for i in range(1, 7)]
    print("lengths %-7s %.3f-%.3f mm, spread %.3f mm (limit %.1f)" % (g, min(v), max(v), max(v) - min(v), lim))
    bad += max(v) - min(v) > lim
sys.exit(1 if bad else 0)
PY
node "$ROOT/tools/eurocard/meander_check.js" "$W/final/PiEBV_Pico.kicad_pcb" 0.3 Sync Trigger TDRSTN
if ! "$KICAD_PY" "$HERE/plane_check.py" "$W/final/PiEBV_Pico.kicad_pcb" "$W/final/plane.json" > "$W/final/plane.txt" 2> "$W/final/plane.err"; then
  q < "$W/final/plane.err"; echo "build: plane_check.py failed"; exit 1
fi
if grep -q "NOT IN ISLAND" "$W/final/plane.txt"; then grep "NOT IN ISLAND" "$W/final/plane.txt"; exit 1; fi
tail -3 "$W/final/plane.txt"
cp "$W/final/PiEBV_Pico.kicad_pcb" "$ROOT/PiEBV_Pico.kicad_pcb"
echo "build: Rev 2 board written to $ROOT/PiEBV_Pico.kicad_pcb"
