# Residuals report — PiEBV EuroCard board (branch `fix/residuals`, base a25983a)

Work list: FIX_AUDIT_REPORT.md section 3 and the prompt's items R1–R8. All work is in the worktree
`PiDG-wt/fix-residuals`. Local commits only. KRT came from the protected copy `PiDG-wt/_krt` (367 MB).
Tools: KiCad 10.0.6 python / kicad-cli, `fp.py`, `netgap.py`, `kilen.py`, `armgap.py` (p2m), `camgeo.py`,
`cpl_check.py`, `parity_check.py`.

Baseline check: the first build of a25983a gave `bcfae201ad1f65b2` (1061 segments, 194 vias), equal to
the committed board.

## 1. Per-item outcome

| Item | Outcome | Copper |
|---|---|---|
| R1 3 unparseable via blocks | Root cause found (they are not vias). Pipeline guard added (`viaguard.py`) | none |
| R2 gaps.py 24/25 flap | Fixed in the tool (a use-after-free, not a threshold effect) | none |
| R3 +12V 0.051 mm sliver | Fixed (merged by `tidy.py`). It was not load-bearing | 1061 → 1060 segs |
| R4 frag_stitch "no site" neck | Documented (no via site can exist; the piece is not floating) | none |
| R5 U1 staircases (Trigger1/2, Sync6) | Fixed (`camjoint.py`); census 8/74 → 5/31 | 1060 → 1022 segs |
| R6 Sync5 0.89 mm past target | Not attempted: R5 does not touch Sync5. The doc stays | none |
| R7 two Rev 1 GND vias 0.20 mm to own pad | Documented with the governing rule situation; vias not moved | none |
| R8 U14 the only DRC note | Verified; the "do not Update Footprint from Library" text is kept | none |

### R1 — the 3 "via blocks"

Root cause: KRT's `_via_blocks()` (`py_router/kicad_parser.py:5455`) finds via blocks with the regex
`\(via(?=[\s(])` on the whole file text. The string-aware part of the scan starts only after a match,
so a match **inside a quoted string** also counts. Three footprint `Description` properties contain
the text `(via J21 2-3)`, `(via J18 2-3)` and `(via J19 2-3)` ("Hi-Z-mode shunt to GND, 2 W 2512 (via
J.. 2-3)": R32 / R27 / R28 area, file lines 610 / 1162 / 9430 of `placed.kicad_pcb`). The geometry
parser finds no `at/size/drill/layers` in them and prints "3 via block(s) could not be read". They are
text, not copper. No real via is ungraded.

Proof (pcbnew count = KRT `parse_kicad_pcb().vias` count, every file that KRT reads or writes):
placed 19 = 19, tapped 64 = 64, cam_l 79 = 79, routed 107 = 107, st_in 111 = 111, st_out 178 = 178.
Because there are no 3 real vias, there are no clearance numbers for them. Every real via is a router
obstacle.

The syntax is legitimate KiCad (free text in a property). Therefore I chose a guard, not a syntax fix:
`tools/eurocard/viaguard.py` (KRT python) compares the string-aware count of top-level `(via` blocks
with `len(parse_kicad_pcb(board).vias)` and lists the quoted-string matches as text. build.sh runs it
after route (placed / tapped / cam_l / routed) and after stitching (st_in / st_out); a mismatch stops
the build. Negative test: one via with its `(size)` removed → "64 vias in file, 63 modelled by KRT
MISMATCH", exit 1.

### R2 — gaps.py flap

Reproduced on **one file**: 3 runs of the old gaps.py on the same board gave 25 / 24 / 25 lines, and
another board gave 24 / 23 / 24. In 6 more runs on the first board, `C17-U17` was present in 2. The lines that changed were `C17-U17 0.56` and `C17-R12 0.66`. Both
are far below the 1.0 mm limit, so this was not a threshold effect. Cause: the pair prefilter
`a.GetBoundingBox().Inflate(d).Intersects(c.GetBoundingBox())` calls `Inflate` on a temporary SWIG
`BOX2I` and uses the reference that `Inflate` returns after Python has freed the temporary (a read of
freed memory). Instrumented runs showed that the prefilter result for these two pairs changed from run
to run, while the courtyard boxes stayed the same.

Fix (tool only): all courtyard boxes are copied to Python ints once. There is no prefilter. The gap is
compared in integer nm (`gap_nm < LIMIT_nm`) and printed rounded to 0.01 mm. Pairs are named in sorted
reference order and every output block is sorted, so the footprint order in the file has no effect.
Result: 15 runs on 3 boards gave one output, 25 lines. The line nearest the limit is 0.95 mm. Some pair
names changed order (for example `U13-C9` → `C9-U13`).

### R3 — +12V sliver at (239.808, 76.85)

Copper: the router's +12V run (0.5 mm, F.Cu) `(243.2, 71.4) → (239.8, 74.8) → (239.8, 76.8)` ends with
a 0.0507 mm step `(239.8, 76.8) → (239.808, 76.85)`. That point is on the carried U17.11–U17.12 tie
(0.4 mm, `(240.025, 76.85) → (239.375, 76.85)`). `tjoin.py` split the tie there, and `tidy.py` removed
the piece toward U17.11 as an invisible bridge.

The documented reason ("load-bearing, kept by tidy's connectivity guard") was wrong. tidy.log has no
"kept" line for it. tidy never selected the sliver, because 0.00585 mm² of it is not covered by other
copper (its limit is 0.001 mm²). Removal test on the board: KiCad unconnected 0 → 0, +12V pad groups
1 → 1, dangling ends 0 → 0. The sliver is not load-bearing.

Fix: a sliver merge pass in `tidy.py`. A sliver shorter than 0.08 mm between the ends of exactly two
other tracks (not camera, GND or +5V nets; neither track protected) is removed. The two tracks then end
at the crossing of their centre lines, here (239.8, 76.85). The connectivity check is the same as for a
removal. On this board it acts on this one sliver only. The tie piece loses 0.008 mm under the run's
0.5 mm end cap. +12V minimum gap to other nets: 0.223 mm before and after. Short-segment census on
other nets: 26 → 25. Density (GND, +5V excluded): 2.758 → 2.751 per 10 mm (doc 2.76 → 2.75).

### R4 — frag_stitch "no site: F.Cu neck 5.6 192.71 93.59"

(192.71, 93.59) is the corner of the eroded core, not the centre of the piece. The piece is a **GND
pour piece** (zone fill, not a track) on F.Cu, (192.2, 93.1)–(194.8, 96.7), 5.6 mm². It joins the main
F.Cu GND fill outline (12954 mm²) through a neck about 0.72 mm wide, so it is not floating. All 41
candidate sites (0.2 mm grid) fail on one cause only: the B.Cu `Sync1` meander directly below it (arms
at y 93.33 / 94.08 / 94.83 / 95.58 / 96.33, a 0.45 mm gap). A 0.6 mm through via with a 0.2 mm
clearance needs 1.0 mm between two arms. A via needs the camera meander moved; removing the piece needs
a rule area in the GND pour. Neither is a cosmetic change with no connectivity effect, so I documented
it in Hardware.md "Known residuals".

### R5 — U1 staircases (joint re-shape)

New `tools/eurocard/camjoint.py`. It runs after the first `camclean.py` pass and before `kilen1`, so
`camclean --trim` restores Trigger2 with its caps. Windows are matched by anchor vertices (within
0.002 mm); a window whose anchors are not found is left unchanged. Tracks are sorted, so the result
does not depend on file order. The U6 pair is all-or-nothing, and each window is checked against the
other window's **new** copper.

| Window | Before | After | Window length |
|---|---|---|---|
| Trigger2 (221.6, 97.9) → U6.4 end | 20 segs (19-step staircase) | vertical x 221.6, 45° on the old end line (2 segs) | −0.2485 mm, then caps 5 × +0.025 mm (KiCad −0.2486 restored) |
| Trigger1 (216.56, 96.5) → U6.2 end | 18 segs (14-step staircase) | H, 45°, vertical x 220.85, 45° jog, vertical x 221.46, 45° on the old end line (6 segs) | +0.0020 mm (no meander; by geometry) |
| Sync6 (249.9, 110.6) → J6.5 end | 12 segs (10-step staircase) | vertical, 45°, horizontal, 45° (4 segs) | 0.0000 mm (no meander; by geometry) |

Guards (all passed): octilinear; no segment < 0.3 mm; no turn > 90° (joints included); camclean's gap
rules (another camera group: the group minimum before; STRICT nets: the gap before; other nets: min(gap
before, 0.21)), and also no window closer to any neighbour than its old window gap (up to 0.30 mm); own
copper more than 2 mm further along ≥ 0.45 mm; no-meander line change ≤ 0.15 mm.

Local gaps (window, edge to edge): Trigger1–Trigger2 0.371 → 0.435; Trigger2–GND (U6.7 tap via)
0.296 → 0.440; Trigger1–PIXRST_GATE 0.560 → 0.560; Trigger1–TRIG_N 0.481 → 0.481; Trigger2–TRIG_N
0.297 → 0.297; Trigger1–PIXRST_N 1.279 → 0.780; Trigger2–PIXRST_N 2.154 → 1.531; Sync6–TDRSTN6
1.192 → 1.203; Sync6–GND 0.837 → 0.837.

Census (camgeo): segments 585 → 547, short 96 → 63, acute 0 → 0, staircase runs / segments 8 / 74 →
**5 / 31**. The remaining runs: Trigger1 3-step jog at J1.4, the Trigger4 bump (6), the TDRSTN4 B.Cu bump
(13), and TDRSTN6 (bump and 3-step jog near U4). Camera density 5.62 → 5.25 per 10 mm. Short camera
segments with no pad or via end: 68 → 35.

The fix report's statement "every clean candidate crosses the other line's staircase" is true only when
the two lines change one at a time. Changed together, Trigger2 goes straight up on the left side of the
GND via, and Trigger1 jogs right under Trigger2's 45° turn. The Trigger1 and Sync6 length problem
("a clean path is 0.71 mm shorter") is solved by using horizontal + vertical in place of part of a 45°
run (every 1 mm of 45° run replaced adds 0.586 mm), so these two lines keep their length without a
meander.

### R6 — Sync5

Not attempted. R5 does not change Sync5 (83.0424 mm before and after). The Hardware.md text stays.

### R7 — the two Rev 1 GND vias

U13.3 via (236.0, 60.935) and U19.3 via (241.9, 98.435), 0.6 / 0.3 mm: ring 0.200 mm and hole edge
0.350 mm from the own GND pad (1.95 × 0.6 mm). There is no `.kicad_dru` file. The board rules are
netclass `Default` clearance 0.20, `min_clearance` 0.10, `min_hole_clearance` 0.20 and
`min_hole_to_hole` 0.25. KiCad 10 checks these only between different nets / holes. Test on a copy
(DRC `--severity-all --refill-zones`): the U13.3 via moved until its hole edge was 0.10 mm and then
0.00 mm from the pad. Each time DRC reported only the U14 warning. So **no** DRC rule allows or forbids
this gap. The 0.25 mm `SAME_PAD` is `taps.py`'s own rule. Both vias are tented (board setup `tenting
front yes / back yes`, no per-via override), so no via copper is open to solder next to the pad. I wrote
this in Hardware.md "Known residuals". The vias are not moved.

### R8 — U14

Final DRC: violations = 1 (`warning lib_footprint_mismatch`, footprint U14), unconnected 0. The text at
Hardware.md "Current state" ("**Do not run "Update Footprint from Library" on U14:** …") is unchanged.

## 2. Final gate table (HEAD eaacbe5 board = build #6 output)

| # | Gate | Result |
|---|---|---|
| 1 | build.sh exit 0 | exit 0 (builds #1–#6; #5 and #6 from the R5 tree) |
| 2 | DRC | 0 non-warning violations, 0 unconnected, 1 warning: U14 `lib_footprint_mismatch` |
| 3 | CPL (`cpl_check.py`) | 84 rows, 0 rotation / 0 position discrepancies; 9 spot checks OK |
| 4 | Parity vs ref-3883378 | 88 / 88 footprints, 108 nets, 0 nets only in one board, 0 pad-set differences, 0 inner tracks, 0 locked |
| 5 | Camera | 18/18 routed. Sync 81.8656–83.0424 (1.1768), Trigger **42.5632**–43.5978 (**1.0346**, was 1.0366), TDRSTN 51.6878–53.0545 (1.3667) mm |
| 6 | armgap | SKIP 2.0 min 0.450, SKIP 1.0 min 0.362, 18 lines |
| 7 | Separation battery (netgap, tracks + vias) | lanes–all 0.450; lanes–all except CH1_J10 0.538; lanes–all except CH1_J10, GND 0.538; lanes–PWM_1MHz + SYNC_N 21.700; CH1–CH2 2.240; Sync–Trigger 1.106; Trigger–TDRSTN 0.752; Sync–TDRSTN 0.323; PWM_1MHz–signal 0.650; PWM_1MHz–power 0.232; PWM_1MHz–+1V8 0.888; drive–EXT_SYNC 12.940. All equal to the ground truth |
| 8 | Fingerprint | builds #5 and #6 both `fcc9f88c90995994` = committed board; 1022 segs, 2490.8 mm, 194 vias, 0 dups. Before / after per change: `bcfae201ad1f65b2` (1061) → R3 `682459b0ba3e28f9` (1060; builds #3 = #4) → R5 `fcc9f88c90995994` (1022) |
| 9 | F.Fab | 4 drawings |
| 10 | Gerbers | re-exported after each copper commit with the board plot settings (export check: the HEAD board re-exported gave all 16 committed files equal except the timestamp lines, line ends ignored). Final zip: 14 files, sha256 `e9b22d0ddaa6da4e6d03f4414f1e6cb54d9c4907d331b34ce524706493ee2a52` (R3 zip: `3418098d90499fe89c45d0ddb7794b262130ace3b8950d0b120d22891564d5ea`) |
| — | gaps.py | 25 lines, MH lines 0, the same on every run |
| — | viaguard | file = KRT on all 6 files (19 / 64 / 79 / 107 / 111 / 178) |
| — | camgeo census | segs 547, short 63, acute 0, stair 5 (31 segs) |

The gerber zip is written with KiCad python's `zipfile` (deflate, sorted names), because `zip` is not
installed. The 14 files are the same as before (no drill-map PDFs, CRLF as KiCad writes them).

## 3. Commits (fix/residuals, on a25983a)

- af0aa9d EuroCard R1: via obstacle guard (viaguard.py) after the KRT steps
- 203c49a EuroCard R2: gaps.py deterministic (25 lines on every run)
- 01d2596 EuroCard R3: merge the +12V 0.051 mm sliver at (239.808, 76.85)
- b1ad2e9 EuroCard R4: document the F.Cu GND neck piece without a stitch via
- b8b642b EuroCard R7: name the rule situation for the two Rev 1 GND vias
- eaacbe5 EuroCard R5: joint re-shape of the Trigger1/Trigger2 (U6) and Sync6 (J6.5) staircases
- 7a58ae8 EuroCard residuals: RESIDUAL_REPORT.md (this report)

Note: the R3 commit did not update the "Totals: 1061 track segments" line in Hardware.md. The R5
commit sets it to 1022.

## 4. Recommendation

All gates pass. The board is deterministic (two builds equal) and the fab outputs match the committed
board. Nothing found here blocks a clean release state. What remains is a set of documented choices:
Sync5 0.89 mm past the router's group target (the spreads of 1.18 / 1.03 / 1.37 mm are about 8.5 ps at
most); 5 small camera length bumps / jogs (Trigger4, TDRSTN4, TDRSTN6, the Trigger1 J1.4 jog), which
carry length; the F.Cu GND pour piece over the Sync1 meander, which has no stitch via; the U14 library
warning (F21, accepted); and the 200 schematic-parity warnings that Hardware.md already explains.
Before release, a person should look at the three re-shaped camera windows in the KiCad GUI (Trigger1 /
Trigger2 at U6, Sync6 at J6.5): the gates check gaps and lengths, not appearance. Then merge
`fix/residuals` into `eurocard`.
