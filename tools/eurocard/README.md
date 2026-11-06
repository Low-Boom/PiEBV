# EuroCard re-layout (160 x 100 mm)

These scripts turn the hand-routed 126 x 126 mm Rev 1 board (main at `3883378`) into the EuroCard
board on this branch. The schematic, netlist and footprints do not change; only placement, routing,
outline and silkscreen do. `bash build.sh` gives the same copper as the committed board.

## Setup (once)

From this folder, with git, Node 18+ and KiCad 10:

```
git clone https://github.com/drandyhaas/KiCadRoutingTools.git
git -C KiCadRoutingTools checkout 8759686
"C:\Users\Flow-Lab\AppData\Local\Programs\KiCad\10.0\bin\python.exe" -m venv .venv
.venv\Scripts\python.exe -m pip install -r KiCadRoutingTools\requirements.txt
cd KiCadRoutingTools && ..\.venv\Scripts\python.exe build_router.py
```

`KiCadRoutingTools/`, `.venv/` and `work/` are git-ignored. Set `KRT_DIR`, `KRT_PY`, `KICAD_PY` or
`KICAD_CLI` for other locations, and `SRC_REV` for another source board.

## Run

```
bash build.sh       # about 3 minutes; result and DRC report in work/final/
```

Copy `work/final/PiEBV_Pico.kicad_pcb` over `../../PiEBV_Pico.kicad_pcb`, then export the gerbers and
drill files and regenerate the JLC placement file:

```
python.exe cpl.py <old board> ../../fab/jlc/PiEBV_Pico_JLC_CPL.csv <new board> <new CPL>
```

`cpl.py` keeps each part's JLC rotation and centroid correction (from `tools/jlc_cpl` on the old board)
and applies it to the new pose.

## Steps

| Script | What it does |
|---|---|
| `place.py` | New outline. Moves the parts in rigid groups (the laser / External Sync output block keeps its hand-routed copper), spreads the machine-assembly clusters for hand placement (not U15/C12/L1/C13: the buck's hot loop stays as drawn), keeps the hand-routed local paths of parts that move together (`LOCAL_PATHS`: buffer decoupling, buck input/GND/SW/BST), moves text, mounting holes and zones. Draws the two equal-length laser pulse lanes. Removes all other copper. |
| `route_planes.py` (KRT) | Registers the In1 GND and In2 +5V planes with the router. |
| `taps.py` | Every SMD GND / +5V pad gets a short track to a via into its plane (clearance-checked with KiCad's shapes), outward from the part body first so the pad keeps its thermal spokes. Without this the router draws +5V as a ~190 mm surface tree. |
| `route.py` (KRT), camera pass | Routes the 18 camera lines first, alone, in a fixed order (`--ordering original`, searched for this placement), and length-matches Sync*, Trigger*, TDRSTN*: via cost 150, meander amplitude 2.0 mm, spacing 2.5 track widths (0.75 mm arm pitch, 0.45 mm gap between arms), tolerance 0.5 mm. F.Cu/B.Cu only (inner layers forbidden), fixed sizes, no via-in-pad. |
| `meander_check.js` | Stops the build if a camera line comes within 0.3 mm of its own copper 2 mm or more further along the line (merged or too-close meander arms). Runs on the camera pass and on the final board. |
| `lock.js` | Locks the camera copper, so that the second pass routes around it and does not re-route it. |
| `route.py` (KRT), other nets | Routes all other nets around the locked camera copper: via cost 200, turn cost 2000 (fewer short jogs), `--mps-reverse-rounds`, no length matching. |
| `viaguard.py` (KRT python) | R1: after each KRT step, every via block in the files KRT read and wrote must be a via KRT models as an obstacle; a mismatch stops the build. KRT's "3 via block(s) could not be read" warning comes from the text "(via J18 / J19 / J21 2-3)" in three Description properties (KRT's via scan also matches inside quoted strings); those are not copper, and every real via is modelled. |
| `unlock.js` | Removes the `locked` marks the router input needed. |
| `straighten.py` | F31: merges collinear segments and replaces jogs with one or two 0/45/90-degree runs where clearance allows. Not on GND, +5V, camera lines, pulse lanes or carried copper (`--protect tapped.kicad_pcb`). Runs before `repair.py`, because it has no 0.3 mm keep rule round SMD bodies. |
| `repair.py` | F27: routes again each foreign-net F.Cu run that comes within 0.3 mm of the pad hull of a front SMD part (all except J17). On this routing: C2 (PIXRST_GATE), C3 / C22 (LASER_PWR_OK), C4 / C5 (LASER_EN). Prints `no route found` if it cannot. |
| `route_planes.py` (KRT) | GND stitching: edge fence at 10 mm, area lattice at 15 mm. |
| `frag_stitch.py` | F26: GND vias for F.Cu / B.Cu pour islands with fewer than 2 vias and for neck pieces that the stitch lattice skipped. |
| `tjoin.py`, `dangling.py` | Split tracks at T-joins; remove the stubs DRC reports as dangling, if connectivity holds. |
| `tidy.py` | F28: removes copper-invisible stitch bridges, slivers < 0.08 mm and in-pad duplicates; `--protect tapped.kicad_pcb` keeps the carried hand copper. R3: a sliver < 0.08 mm between the ends of two other tracks (not camera, GND, +5V) is merged: both tracks end at the crossing of their centre lines, with no connectivity change. |
| `silk.py`, `finish.py` | Moves reference labels clear of other silkscreen; title block; F.Fab outlines of the 160 x 100 mm board and of the Pico module with its micro-USB receptacle (F23). |
| `ends.py` | F18: trims camera track ends to the pad edge and joins off-centre via ends to the via centre, so KiCad measures every camera line pad edge to pad edge. |
| `camclean.py` | U1 (last copper change): cleans the router artefacts of the camera lines with the length kept. Meander caps of two stubs become one straight cap (arms longer by the same amount); staircases (3 or more segments < 1 mm) and acute corners become 0-2 straight 0/45/90-degree segments; all caps of a line then move by one small distance to restore its pad-edge length. New copper keeps the old group-to-group gaps (Sync / Trigger / TDRSTN), the old gap to the pulse lanes, `PWM_1MHz` and `SYNC_N`, at least 0.21 mm (or the old gap, if smaller) to other nets, and 0.45 mm to its own copper more than 2 mm further along. `--dry` reports only. `ends.py` runs again after it. |
| `camjoint.py` | R5: after the first `camclean.py` pass, re-shapes the three staircases camclean cannot replace one line at a time: Trigger1 and Trigger2 at U6 (together: all windows of a group or none) and Sync6 at J6.5. Trigger1 and Sync6 (no meander) keep their window length by the geometry; Trigger2 is put back by `camclean.py --trim` with its caps. camclean's gap rules, and no window closer to a neighbour than before (up to 0.30 mm); a window whose anchor points are not found is left as it is. |
| `simplify.py` | S1: after the last camera step, re-shapes router jogs on non-camera nets with the length kept by the geometry and no via change. On this board: `PIXRST_GATE` on B.Cu between its vias (205, 52.4) and (218.3, 86.1), 45 / vertical / 45 / vertical / 45 (5 segments) to 45 / vertical at x 209.1 / 45 (3 segments). The vertical is the 0.1 mm grid position with the largest smallest gap of the new copper. Guards: the old run must have the expected vertices; octilinear, no segment < 0.3 mm, no turn > 90 degrees, length change <= 0.001 mm; to every other net not below min(old gap, 0.45 mm) or the net's smallest gap before. |
| `kilen.py` | Camera lengths as KiCad reads them (a DRC length rule that every line fails). Read before and after `camclean.py`; `camclean.py --trim` then moves the caps of each meandered line by the difference, so its KiCad length is as before. Read camera lengths / skew after this. |

Checks: `gaps.py` (courtyard gaps, long-edge strips), `netgap.py` (smallest copper gap between two net sets, edge to edge on one layer: tracks, vias and exact pad shapes; `--no-pads` for tracks and vias only), `regiongap.py` (per-pair copper gaps of named nets inside a box, edge to edge on one layer; tracks clipped to the box), `netdiff.py` (per-net segment count and length, two boards), `pathlen.py` (pad-to-pad centre-line length;
right for the drawn pulse lanes, but it reads meanders short because it merges track ends closer
than 0.15 mm; measure the matched camera lines with KiCad's length tool instead).

## Laser pulse lanes

`place.py` draws `_PULSE_OUT_CH1` (J14.17 to U7.2) and `_PULSE_OUT_CH2` (J14.16 to U8.2) itself: each
runs from the J14 pad to the U7/U8 input's row with one 45-degree corner. The shorter lane then gets a
45-degree bump, so that GPIO pin to U13 input is equal on both channels with the carried `CHn_GATED`
copper: 55.75 + 10.41 = 56.49 + 9.67 = 66.16 mm. The router's length match only meanders the longest MST
edge of a multi-pad net, so it cannot do this itself.
