# EuroCard board review (commit 995759e)

A multi-agent review of the board at commit 995759e, made on 2026-11-05/06. Six lenses (power,
signal integrity, assembly, mechanics, routing, docs) gave 30 distinct findings. For each finding, one
agent measured it again and a second agent checked the proposed fix in a scratch rebuild of this
pipeline. 29 findings were confirmed; F19 was confirmed only as a doc gap. **No fix is applied yet.**
The board, DRC result (0 violations, 0 unconnected) and netlist are unchanged.

"Fix" gives the change that the fix check found correct. "Scratch-built" means that a rebuild with
the change gave KiCad DRC 0 violations and 0 unconnected.

## High

| ID | Finding (measured) | Fix |
|---|---|---|
| F1 | Buck GND has no via to In1. C12.2 and U15.4 have only the carried 2.35 mm link between them; the nearest GND via (stitch, 157.5,117.5) is 2.93 mm from C12.2 and 4.89 mm from U15.4, reached through 0.5 mm thermal spokes. The hand board had 2 vias 1.74/1.90 mm from C12.2. Cause: `LOCAL_PATHS` carries C12.2–U15.4, so `taps.py` counts both pads as tapped. | `place.py`: add `"C12"` to `CARRY_GND` (carries the 2 hand vias). Scratch-built: +1 GND via net, VBUS_PD changes locally only, camera lines and pulse lanes unchanged. |
| F2 | Camera meander arms touch. `--meander-spacing 1.0` gives an arm pitch of 0.30 mm with a 0.3 mm track, so the gap is 0 mm on 14 of 18 camera lines. The copper merges, so the real path is shorter than the measured length and the match is not real. | Apply together with F3. Spacing of 2 (0.3 mm gap) or more cannot fit in one pass. |
| F3 | The group targets come from lines routed late and the long way (Sync6 routed 48th of 49, 108.27 mm; Sync1–5 33.6–65.5 mm before matching). The meanders add 513 mm in 233 bumps. | `build.sh`: route the 18 camera lines first in their own `route.py` pass (with real arm spacing), lock them, then route the rest. A prototype of this flow is in the review scratch area. |
| F4 | `fab/PiDG_Pico_Gerbers.zip` (which `JLC_ORDER.md` says to upload) holds the d8f64cd routing. `fab/gerbers/` is current. | Rebuild the zip from `fab/gerbers` (14 files, no drill-map PDFs). Do this before an order. |
| F5 | `signal_sim` does not hang in ngspice. Hand check 4 walks a parent map, and two self-loop branches of `PWM_TRIG_TAP` (U19.2→U19.2, J10.2→J10.2) make the walk endless. Also, the option d cut names a branch (R9.1–U19.2) that no longer exists, so it cut nothing; and a branch-point via (VIA2, B.Cu to F.Cu) was not in the model (+14 to +66 ps). The doc tables are from 8db06a6. | Patch exists: Dijkstra path for check 4 (skips self-loops), branch-point vias in the model, option d cut from the geometry with an assert. Validation on the 126 mm geometry: largest change 0.0025 ns. Re-run on the final board, then update Hardware.md. |

## Medium

| ID | Finding (measured) | Fix |
|---|---|---|
| F6 | VBUS_PD (15 V): 191.9 mm against 107.4 mm on the hand board; 11.3 mm runs under the J17 body; it crosses +1V8 with 2 vias. | `LOCAL_PATHS`: carry the hand VBUS join at J17 (A9–B9), plus a stub clean-up step. Scratch-built. |
| F7 | +1V8: U9 is 46.5 mm from the buffer row; rail 116.5 mm with 5 vias (hand board: 88 mm, 0 vias). | `place.py`: U9 (216.0, 83.0), C7 (220.9, 82.05), C6 (214.5, 78.7, 90°), above the buffer row; silk entries. Scratch-built. |
| F8 | The laser lane balance (66.16 mm each) includes a 19.1 mm stub to R18 that the router made; it is not drawn by `place.py`. | `place.py`: R18 to (194.0, 66.5) and draw the R18 branch as part of the lane. |
| F9 | Fast lines on B.Cu (camera total 624 mm on B.Cu) return through the +5V plane; the nearest +5V-to-GND capacitors are far away. | `route_planes.py --add-gnd-vias --gnd-via-distance 1.5` adds 48 GND vias next to signal vias. The fix check rated the risk of 48 extra vias too high for the benefit (severity low, not medium): decide before use. |
| F10 | The Pico pin-1 mark `1` moved with TP3 to (135.2, 69.6). | `place.py` silk block: put it at (132.385, 56.6). |
| F11 | 45 tap vias have their ring 0.10 mm from their own pad (Rev 1: 12). Solder wicking risk on a hot plate. | `taps.py`: `SAME_PAD = 0.25`, and check the own pad by shape. |
| F12 | MH1–MH4 (y 34 and 126): the 7 mm washer reaches 0.5 mm from the long edges, 2.0 mm into the 2.5 mm card-guide strip. The docs say the board fits card guides. | `place.py`: MH at y 36 and 124 (rectangle 152 × 88 mm), before routing; `gaps.py` to check holes. |
| F13 | TP3 pin tips are 2.04 mm past the left edge; a flush end plate touches PWM_1MHz. | `place.py`: TP3 to (141.0, 67.0); tips 0.96 mm inside the edge. |
| F14 | Stale numbers in Hardware.md (tap count, camera range, pad span, PWM_TRIG_TAP length). | Tap count and CC width corrected in this commit. Do the rest after the rebuild. |

## Low

| ID | Finding | Fix |
|---|---|---|
| F15 | C17 is 8.0 mm from U17.11 (0.3 mm neck, via); C20 is 6.05 mm from U18.5. | `place.py`: C17 (235.6, 78.5, 180°), C20 (221.0, 71.9, 180°). |
| F16 | Buck output: L1.2 to C14.1 7.63 mm (hand 2.35 mm); 0.35 mm neck to U16.1. | `place.py`: absolute poses for C14/C15/U16 in a row next to L1.2. |
| F17 | CC lines are 0.3 mm, not 0.2 mm; the 0.2 mm setting in `build.sh` has no effect. | Doc corrected in this commit. |
| F18 | Sync4 is 1.27 mm past its target (router miss). Trigger4 and TDRSTN3/4 differ because the router and KiCad measure lengths differently. | New `ends.py`: trim track ends to the pad edge, as KiCad measures. |
| F19 | The input fan-outs (U1.4, U5.4, U3.4 to their six gate inputs) differ by 8–10 mm. The timing effect given in the finding was not confirmed. | Doc edit only: say that the match starts at the buffer output. |
| F20 | U3, U15 and U10 labels are nearer to a neighbour than to their part; TP3 label hidden. | `silk.py` entries. |
| F21 | U14 exposed-pad paste covers both via holes 100 % (solder wicking); U17 about 35 %. | `finish.py`: U14 paste as an "H" around the holes. |
| F22 | No paste method for the 0.65 mm-pitch parts (U16, U17) in the hot-plate notes. | Doc edit. |
| F23 | Enclosure notes: no 1455N1601 data or cut-out coordinates; the Pico USB face is 0.285 mm past the board edge. | Doc edit; module outline on F.Fab in `finish.py`. |
| F24 | BNC housing front is 0.32 mm behind the board edge, so a panel nut pulls on the solder joints. | Footprint silk and position change after routing; or a spacer note in the docs. |
| F25 | No exit for the camera ribbons and the J11 E-stop wires in the enclosure notes. | Doc edit. |
| F26 | F.Cu GND pour islands held by one via (C22.1, J17.A12, U3.3, U18.2, C21.1). | New `frag_stitch.py`: add vias to islands and necks. |
| F27 | Foreign-net F.Cu under SMD bodies: PIXRST_GATE between the C2 pads (0.275 mm from C2.1); +12V under R30 (2512) between its pads; +5V_PD over the corner of U15 pin 1, within 0.3 mm of C13.1. | Post-route repair of these nets. |
| F28 | 5 removable segments (LASER_EN 1.25 mm duplicate, a +1V8 sliver, 3 carried duplicates). | New `tidy.py` after stitching: remove only bridges added by the stitch step and slivers < 0.08 mm. |
| F29 | J17 pad gaps are 0.27 mm (not ≥ 0.3 mm); U18 is not a `_HandSolder` footprint. | Doc edit. |
| F30 | The README board diagram puts J11 above J20, TP3 and J8; on the board it is below them. | Doc edit. |

## Order of work

1. Placement and carry changes, one rebuild: F1, F6, F7, F8, F12, F13, F15, F16, then the
   camera-first routing pass (F2, F3).
2. Post-route steps: F18 `ends.py`, F26 `frag_stitch.py`, F27, F28 `tidy.py`, F21 paste, silk (F10, F20).
3. Checks: DRC, parity, netlist, `gaps.py`, KiCad-measured lengths, pulse lanes, CPL.
4. `signal_sim` patch (F5), re-run, then all doc edits (F14, F19, F22–F25, F29, F30) and the
   gerber zip (F4).
