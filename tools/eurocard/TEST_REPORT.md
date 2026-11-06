# Post-route scripts: test report (F18, F26, F27, F28, F31b)

Fixture: a copy of the committed board `PiDG_Pico.kicad_pcb` at 8408895 (the old single-pass routing),
in a scratch folder with the project files. Each script ran on the unchanged fixture, then all five
ran in a chain. KiCad 10.0.6 (`python.exe`, `kicad-cli`). The committed board and `build.sh` are not changed.

Checks used for every script:

- **DRC**: `kicad-cli pcb drc --schematic-parity --severity-all --refill-zones`. The fixture gives
  0 violations, 0 unconnected, 200 parity warnings (174 `net_conflict`, 22 `footprint_symbol_field_mismatch`,
  4 `extra_footprint`). "DRC clean" below means the same result after the script.
- **Net topology**: pcbnew refill, then per net the groups of pads joined by copper (`GetConnectedItems`),
  the unconnected count and the dangling track ends (`TestTrackEndpointDangling`). Compared before/after.
- **KiCad length**: a temporary `.kicad_dru` rule `length (min 900mm)` on `Sync?`, `Trigger?`, `TDRSTN?`;
  the DRC message gives KiCad's own length.

All scripts: `python.exe <script> in.kicad_pcb out.kicad_pcb [options]`, KiCad python, `wx.DisableAsserts()`
before `import pcbnew`, one result line (or a short list) on stdout.

## ends.py (F18)

Trims each free track end of the given nets that stops inside an own pad back to 5 um inside the pad
outline (walks back over segments that lie fully inside the pad). Joins each free track end that stops
off a via centre (on the rim, for example) to the via centre. `--pads-only` skips the via part.
`python.exe ends.py in out "Sync?" "Trigger?" "TDRSTN?"`

Result on the fixture: 36 pad ends trimmed (0.023 to 0.995 mm of in-pad copper per end), 14 via ends joined
(+0.100 to +0.300 mm, all inside the via).

| Group | Electrical length\* before | after | KiCad length before | after |
|---|---|---|---|---|
| Sync1-6 | 104.966-107.567, spread 2.601 | spread 2.601 | 107.321-108.951, spread 1.630 | 106.249-108.178, spread 1.928 |
| Trigger1-6 | 53.911-55.872, spread 1.961 | spread 1.960 | 55.523-57.096, spread 1.574 | 54.874-55.881, spread 1.007 |
| TDRSTN1-6 | 51.345-52.657, spread 1.312 | spread 1.313 | 51.162-53.908, spread 2.746 | 51.955-52.692, spread 0.737 |

\* Track copper outside the net's own pads and via discs (2 um sampling) plus 1.586 mm per via. No net
changes by more than 0.004 mm in this metric.

- Spread acceptance (Sync and Trigger unchanged within 0.05 mm): **met in the electrical metric**
  (change 0.000 and 0.001 mm). **Not met in KiCad's own length reading** (Sync +0.298 mm, Trigger
  -0.567 mm). Cause, measured: KiCad 10.0.6 counts the in-pad copper when a track ends off the pad
  centre. The KiCad length of each net drops by exactly the trimmed copper (Sync1: 0.693 + 0.379 =
  1.072 mm, KiCad 107.321 -> 106.249). After the trim, the KiCad length of every net is its pad-edge
  length + 0.010 mm, on all 18 nets. Before, it held 0.02-0.99 mm of in-pad copper per end, different
  on each net.
- The via joins change KiCad's length only on TDRSTN4 (+1.887 mm) and TDRSTN5 (+1.886 mm): KiCad
  counts the via barrel again. Sync and Trigger KiCad lengths are the same with and without the via joins.
- Sync4 is still long in every metric (router overshoot). ends.py does not correct it; the camera-first
  re-route (F2/F3) must correct it.
- DRC clean. Topology unchanged. Track count +14 (the via joins); no other net changes.

## frag_stitch.py (F26)

Starts from the verified prototype (`verify-fix-F26/frag_stitch.py`). Changes: an island needs 2 GND
vias (a GND THT pad on it does not count); islands from 1 mm2 (was 5 mm2, which skipped the 2.92 mm2
C21.1 island); for small islands the sites come from the island eroded by the via radius when the
0.5 mm erosion has no clear site. Neck rule, clearances, site order, courtyard preference and
card-guide strips as in the verified version.
`python.exe frag_stitch.py in out`

| F.Cu GND island | GND vias before | after |
|---|---|---|
| 43.15 mm2 at C22.1 | 1 | 2 |
| 20.53 mm2 at J17.A12 (+ J17.SH THT) | 1 | 2 |
| 12.57 mm2 at U3.3 | 1 | 2 |
| 12.53 mm2 at U18.2 | 1 | 2 |
| 2.92 mm2 at C21.1 | 1 | 2 |

- 27 vias added (5 island, 16 F.Cu neck, 6 B.Cu neck). GND vias 115 -> 142, all vias 169 -> 196.
- Neck pieces (0.5 mm opening, >= 5 mm2, no GND via within 0.35 mm, no GND THT pad within 0.6 mm):
  F.Cu 17 pieces / 370.3 mm2 -> 0; B.Cu 7 pieces / 137.2 mm2 -> 0.
- Two added vias are inside a courtyard: (220.27, 107.05) in J3 (THT header) and (209.54, 88.55) in U4
  (that B.Cu piece is fully inside the U4 courtyard). The verified fix reported the same two.
- DRC clean. Topology unchanged; only the GND via count changes. A second run adds 0 vias.

## repair.py (F27)

For each part given, the protected region is the convex hull of its F.Cu pads (pads plus the body
between them). An unlocked F.Cu track of a net that is not on the part, closer than 0.3 mm to the region,
is an offender. Its run (unlocked F.Cu segments between terminals: pad, via, branch, locked copper; the
run stops before a segment that crosses an own pad) is removed and routed again between the same two
terminals by a local A* (0.1 mm grid, 8 directions, turn cost, F.Cu + B.Cu with 0.6/0.3 vias). Rules:
netclass clearance + 0.02 mm, hole clearance, edge clearance, keep-outs, 0.3 mm from every protected
region, no track across the pad gap of a foreign front 2-pad part, a cost for passing within 0.3 mm
beyond clearance of other-net copper, vias not in SMD pads or SMD courtyards. T-junctions on the run
are split first; a run is not repaired if other copper joins it only off its ends.
`python.exe repair.py in out C2 R30 C13` (`--dry`: report only)

| Part | Offender | Clearance before | after | Run before | after |
|---|---|---|---|---|---|
| C2 | PIXRST_GATE (between the pads) | 0.000 mm | 0.397 mm | 18.03 mm, 7 segs | 21.34 mm, 10 segs, +2 vias |
| R30 | +12V (under the body) | 0.000 mm | 3.918 mm (+12V); 0.700 mm nearest foreign (GND) | 18.74 mm, 4 segs | 10.43 mm, 4 segs, +2 vias |
| C13 | +5V_PD (0.243 mm from C13.1) | 0.243 mm | 0.325 mm | 14.75 mm, 4 segs | 14.34 mm, 4 segs |

- Clearance = shortest distance from foreign F.Cu tracks/vias to the pad hull. All three >= 0.3 mm.
- New copper: 17 segments, all on 0/45/90 degrees; 1 is < 0.5 mm, and it has an end in a pad.
- Side effects: PIXRST_GATE now comes 0.450 mm from Trigger2 (F.Cu); before, 0.832 mm. Without
  the proximity cost it was 0.225 mm. +12V to the EXT_SYNC / CH nets: 0.836 mm, unchanged.
  No new via is in a courtyard.
- DRC clean. Topology unchanged. A second run finds no offender.

## tidy.py (F28)

Removes only copper-invisible segments (other same-net copper on the layer covers them: < 0.001 mm2 left)
of three kinds: bridge (off the 45-degree grid; with `--before st_in.kicad_pcb`: not in the stitch input),
in-pad (both ends in the same own pad), sliver (< 0.08 mm). GND, +5V, camera nets and pulse lanes are
never touched. One at a time, bridges first; a removal is undone if KiCad's unconnected count or the
net's dangling ends go up or its pad groups change. `--protect tapped.kicad_pcb` keeps every segment of
that board. `python.exe tidy.py in out [--before st_in.kicad_pcb] [--protect tapped.kicad_pcb]`

Removed on the fixture (exactly the known set):

| Net | Segment | Kind |
|---|---|---|
| LASER_EN | F.Cu (223.900,63.400)-(222.650,63.350) w0.20, 1.251 mm | bridge |
| +1V8 | F.Cu (202.300,90.700)-(202.256,90.728) w0.50, 0.052 mm | sliver |
| Net-(U15-SW) | F.Cu (158.850,110.400)-(158.850,112.000) w0.30, 1.600 mm | in-pad (carried) |
| CH1_DRIVE | F.Cu (253.100,59.200)-(253.790,59.200) w0.30, 0.690 mm | in-pad (carried) |
| CH2_DRIVE_RAW | F.Cu (247.000,63.205)-(247.000,64.200) w0.30, 0.995 mm | in-pad (carried) |

- The router's LASER_EN segment under the bridge stays. A first draft without the kind filter removed
  both LASER_EN segments (and 67 segments in total, most of them router corner steps); the verified F28
  notes show that the route then ends outside the U8.1 pad.
- Pads per net: 381 pads / 109 nets before and after, no net differs. Copper image (union of tracks,
  vias, pads): F.Cu 1447.4489 -> 1447.4487 mm2 (0.000164 mm2 = polygon tolerance), B.Cu unchanged.
  Dangling track ends 1 -> 0 (the sliver was the one).
- DRC clean. Topology unchanged. A second run removes 0.
- `--protect` (fixture as P): 0 removed. `--before` (fixture as B): 4 removed (no bridge class).
- The 3 carried in-pad segments are not stitch bridges or slivers. They are removed here because the
  task lists them. The verified F28 fix says to keep carried copper: pass `--protect tapped.kicad_pcb`
  in the build if that rule applies.

## straighten.py (F31b)

Per net, the F.Cu / B.Cu chains between terminals (pad, via, branch, width change) become vertex
lists. Collinear vertices merge; a sub-path is replaced by one 0/45/90 run or two such legs (diagonal
or straight first) when that has fewer segments, is not longer and is clear: netclass and hole clearance
to other nets, edge clearance, no new copper in the 2.5 mm card-guide strips, keep-outs, no track across
a foreign 2-pad SMD gap, no new segment < 0.5 mm except at a pad or via, no turn sharper than 90 degrees.
Longest replacement first, repeated until nothing changes. A segment is not moved if a loose own end
holds on to it, or if it crosses an own pad or via off its ends. Per net, undone if connectivity gets
worse. Nets not touched: GND, +5V, camera lines, pulse lanes, the carried laser / External Sync nets;
`--protect` adds a board whose segments stay. Optional net patterns limit the nets.
`python.exe straighten.py in out [--protect tapped.kicad_pcb] [net-pattern ...]`

| Non-camera nets | Before | After | Hand board |
|---|---|---|---|
| Segments / length | 615 / 1531.3 mm | 478 / 1512.0 mm | |
| Segments per 10 mm | 4.02 | 3.16 | 2.8 |
| Segments < 0.5 mm (without a pad/via end) | 155 (114) | 77 (35) | |

- Changed nets: VBUS_PD 102 -> 20 segments in 7 chains (163.25 -> 147.20 mm), +1V8 64 -> 11 (79.32 ->
  76.34 mm), +3V3 4 -> 3, TRIG_N 3 -> 2.
- New segments: 33 (265.5 mm), 0 off 0/45/90 degrees, 1 < 0.5 mm (it has a pad/via end), 0 short
  without a pad/via end.
- Camera lengths (KiCad): all 18 nets identical to 0.001 mm (spreads 1.630 / 1.574 / 2.746).
- Not at 2.8: the remaining segments are mostly GND / +5V plane taps (100 segments, not touched),
  short pieces at branch points (degree-3 nodes are terminals), and carried copper.
- DRC clean. Topology unchanged. A second run changes nothing.

## All five in a chain

Order: straighten -> repair -> frag_stitch -> tidy -> ends (stitch by route_planes not run here).

- straighten 173 -> 36 segments; repair: C2 0.397, R30 0.700, C13 0.325 mm; frag_stitch 22 vias
  (the C22.1 and C21.1 islands joined the main pour after the +12V repair); tidy 7 removed (the 5
  above, plus in-pad pieces that repair and straighten left: +5V_PD in U15.1 0.200 mm, TRIG_N 0.600 mm);
  ends 36 trimmed, 14 via ends joined.
- DRC: 0 violations, 0 unconnected, 200 parity (as the fixture). Topology unchanged, 381 pads per net
  identical, dangling ends 1 -> 0.
- F.Cu GND islands: 3, each with 2 GND vias; B.Cu: one 130.9 mm2 island with 3 GND vias; 0 neck pieces.
- KiCad lengths: Sync spread 1.928, Trigger 1.007, TDRSTN 0.737 mm (the ends.py values).
- Non-camera nets: 3.16 segments per 10 mm. The camera count goes 10.16 -> 10.38 per 10 mm because
  of the 14 via-join segments of ends.py.

## Notes for the build.sh integration

- Argument style: `"$KICAD_PY" "$HERE/<script>.py" in.kicad_pcb out.kicad_pcb [options]`; in = out is allowed.
  Keep `2>/dev/null` (pcbnew image-handler and SWIG messages go to stderr).
- Order: straighten.py before repair.py (straighten has no 0.3 mm keep rule and could pull +5V_PD back
  to C13.1). Both before the stitch step (they move copper; the pour and stitch vias follow).
  frag_stitch.py right after route_planes stitching (it refills first). tidy.py after frag_stitch
  (`--before st_in.kicad_pcb` for stitch bridges only, `--protect tapped.kicad_pcb` to keep carried
  copper). ends.py last, after finish.py, before the final DRC.
- None of the scripts runs DRC. Connectivity guards in the scripts: tidy per removal, straighten per
  net (pcbnew connectivity, undo on loss); repair through its run rules. Clearance is checked in the
  scripts only for new copper (repair, straighten, frag_stitch). Run the DRC after the last step; it must
  stay 0 / 0.
- repair.py routes on a 0.1 mm grid from the exact terminals; if no route is found in windows of 3, 6
  and 10 mm around the run, it leaves the run and prints "no route found". The part list (C2 R30 C13)
  comes from the review of this routing; after a re-route, run `repair.py --dry` with a wider list to
  find new cases.
- ends.py changes KiCad's camera lengths by design (pad-edge metric). Any skew gate (F18
  `.kicad_dru`) must read the board after ends.py.
- The test helpers used for this report (drc.sh, lens.py, edgelen.py, topo.py, frag.py, segm.py,
  newsegs.py, netgap.py, netdist.py, img.py, padcount.py, viacrt.py, render.py) were in an uncommitted
  scratch folder, `work-test/`, of the `fix/p1-postroute` worktree; they are not in the repository.
  For the same checks use KiCad DRC, `kilen.py` (KiCad camera lengths) and `netgap.py` (copper gaps;
  not the scratch script of the same name).
