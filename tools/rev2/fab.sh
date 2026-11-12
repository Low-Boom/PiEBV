#!/usr/bin/env bash
# Rev 2 fabrication package: DRC gate, gerbers, drill files, job file, zip.
# usage: bash tools/rev2/fab.sh        (KICAD_CLI / KICAD_PY override the defaults; run from any directory)
# The CPL is made by tools/rev2/cpl.py; the two BOM files are maintained by hand.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(cd "$HERE/../.." && pwd)"
KICAD_CLI="${KICAD_CLI:-kicad-cli}"; KICAD_PY="${KICAD_PY:-python3}"
B="$ROOT/PiEBV_Pico.kicad_pcb"; G="$ROOT/fab/gerbers"; T="$(mktemp -d)"
# 1. DRC with the project rules, zones refilled and saved. Any error or unconnected item stops the script.
"$KICAD_CLI" pcb drc --schematic-parity --severity-all --refill-zones --save-board --format json -o "$T/drc.json" "$B" >/dev/null
"$KICAD_PY" "$ROOT/tools/eurocard/drc_gate.py" "$T/drc.json"
# 2. Reference planes: every via and through-hole pad of a plane net over its island; B.Cu island changes listed.
"$KICAD_PY" "$HERE/plane_check.py" "$B" > "$T/plane.txt" 2>/dev/null
grep -q "NOT IN ISLAND" "$T/plane.txt" && { grep "NOT IN ISLAND" "$T/plane.txt"; exit 1; }
# 3. Gerbers (the board's stored plot settings), Excellon drill files with map PDFs, job file.
rm -f "$G"/*
"$KICAD_CLI" pcb export gerbers --board-plot-params -o "$G/" "$B" >/dev/null
"$KICAD_CLI" pcb export drill --format excellon --excellon-separate-th --generate-map --map-format pdf -o "$G/" "$B" >/dev/null
# 4. Zip for the fabricator: the 14 gerber, drill and job files (no map PDFs), fixed order and time stamps,
#    so the same board gives the same zip.
"$KICAD_PY" - "$G" "$ROOT/fab/PiEBV_Pico_Gerbers.zip" <<'PY'
import os, sys, zipfile
g, out = sys.argv[1:3]
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for n in sorted(os.listdir(g)):
        if not n.endswith(".pdf"):
            zi = zipfile.ZipInfo(n, (2026, 11, 12, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            z.writestr(zi, open(os.path.join(g, n), "rb").read())
PY
echo "fab: $(ls "$G" | wc -l) files in fab/gerbers, zip sha256 $(sha256sum "$ROOT/fab/PiEBV_Pico_Gerbers.zip" | cut -c1-64)"
rm -rf "$T"
