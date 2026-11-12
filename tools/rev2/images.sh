#!/usr/bin/env bash
# Documentation images of the board: one SVG per copper layer (with the outline), the top silkscreen view and
# 3-D renders. usage: bash tools/rev2/images.sh OUTDIR     (KICAD_CLI overrides the default)
# The SVG files are converted to the PNG files in docs/img with a headless browser (tools/rev2/svg2png.js).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(cd "$HERE/../.." && pwd)"
KICAD_CLI="${KICAD_CLI:-kicad-cli}"; O="${1:?output directory}"; B="$ROOT/PiEBV_Pico.kicad_pcb"
mkdir -p "$O"
svg() { "$KICAD_CLI" pcb export svg --layers "$2" --page-size-mode 2 --exclude-drawing-sheet -o "$O/$1.svg" "$B" >/dev/null; }
svg layer_1_F_Cu    "F.Cu,Edge.Cuts"
svg layer_2_In1_Cu  "In1.Cu,Edge.Cuts"
svg layer_3_In2_Cu  "In2.Cu,Edge.Cuts"
svg layer_4_B_Cu    "B.Cu,Edge.Cuts"
svg top_assembly    "F.Silkscreen,F.Mask,F.Fab,Edge.Cuts"
"$KICAD_CLI" pcb render --side top --width 2400 --height 1500 --quality high --background opaque -o "$O/render_top.png" "$B" >/dev/null
"$KICAD_CLI" pcb render --side bottom --width 2400 --height 1500 --quality high --background opaque -o "$O/render_bottom.png" "$B" >/dev/null
"$KICAD_CLI" pcb render --rotate "-55,0,-25" --perspective --width 2400 --height 1500 --quality high --background opaque --zoom 0.9 -o "$O/render_3d.png" "$B" >/dev/null
echo "images: written to $O"
