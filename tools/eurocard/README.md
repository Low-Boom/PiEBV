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

Copy `work/final/PiDG_Pico.kicad_pcb` over `../../PiDG_Pico.kicad_pcb`, then export the gerbers and
drill files and regenerate the JLC placement file:

```
python.exe cpl.py <old board> ../../fab/jlc/PiDG_Pico_JLC_CPL.csv <new board> <new CPL>
```

`cpl.py` keeps each part's JLC rotation and centroid correction (from `tools/jlc_cpl` on the old board)
and applies it to the new pose.

## Steps

| Script | What it does |
|---|---|
| `place.py` | New outline. Moves the parts in rigid groups (the laser / External Sync output block keeps its hand-routed copper), spreads the machine-assembly clusters for hand placement, moves text, mounting holes and zones. Draws the two equal-length laser pulse lanes. Removes all other copper. |
| `route_planes.py` (KRT) | Registers the In1 GND and In2 +5V planes with the router. |
| `taps.py` | Every SMD GND / +5V pad gets a short track to a via into its plane (clearance-checked with KiCad's shapes), outward from the part body first so the pad keeps its thermal spokes. Without this the router draws +5V as a ~190 mm surface tree. |
| `route.py` (KRT) | Routes everything else on F.Cu/B.Cu (inner layers forbidden), fixed sizes, no via-in-pad, via cost 150, length-matched Sync*, Trigger*, TDRSTN* (meander amplitude 1.5 mm, spacing 1.0 mm; the best of 12 setting variants for this placement). |
| `unlock.js` | Removes the `locked` marks the router input needed. |
| `route_planes.py` (KRT) | GND stitching: edge fence at 10 mm, area lattice at 15 mm. |
| `silk.py`, `finish.py` | Moves reference labels clear of other silkscreen; title block. |

Checks: `gaps.py` (courtyard gaps, long-edge strips), `pathlen.py` (pad-to-pad copper length).

## Laser pulse lanes

`place.py` draws `_PULSE_OUT_CH1` (J14.17 to U7.2) and `_PULSE_OUT_CH2` (J14.16 to U8.2) itself: each
runs from the J14 pad to the U7/U8 input's row with one 45-degree corner. The shorter lane then gets a
45-degree bump, so that GPIO pin to U13 input is equal on both channels with the carried `CHn_GATED`
copper: 55.75 + 10.41 = 56.49 + 9.67 = 66.16 mm. The router's length match only meanders the longest MST
edge of a multi-pad net, so it cannot do this itself.
