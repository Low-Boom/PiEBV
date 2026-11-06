# PiEBV EuroCard board — independent design review (Fable pass)

- Date: 2026-11-06
- Commit reviewed: `418488f` (branch `eurocard`; board file last changed in `2e1baaf`)
- Reviewer: Claude Fable 5.1 via `claude -p`, worktree `PiDG-wt/review-fable`
- Scope: fresh adversarial review of `PiDG_Pico.kicad_pcb`, the fab package, `tools/signal_sim`
  and the documents. No board or pipeline file was changed. All values below were measured in this
  session (KiCad 10.0.6 python / kicad-cli, a quote-aware S-expression census, `netgap.py`,
  `pathlen.py`, `meander_check.js`, `fp.py` from `audit-tools-fixagent`, `cpl_check.py`,
  `parity_check.py`).

## 1. State verification

| Gate | Expected (task brief) | Measured | Result |
|---|---|---|---|
| Full rebuild (`build.sh`, KRT at `_krt`) | exit 0, about 90 s | exit 0; all post steps ran; `meander_check: ok`; `gaps.py: 25 lines, MH lines: 0` | pass |
| DRC gate (`drc_gate.py`, final) | 0 non-warning violations, 0 unconnected; U14 warning expected | `Found 0 violations, 0 unconnected items, 200 schematic parity issues`; 1 warning `lib_footprint_mismatch` U14. Parity issues: 174 `net_conflict` (board net `X` vs schematic `/X`, label prefix only), 22 field mismatches (`Datasheet` `~` vs empty), 4 `extra_footprint` (MH1–MH4). All severity `warning` | pass |
| Copper fingerprint (fp.py: sha256 of sorted track/via tuples) | `c27822f7b03012e7` (1015 segs / 2489.2 mm / 194 vias / 0 dups) | committed board **`98a60c3b4332d6e9`**, 1015 segs, 2489.2 mm (F.Cu 1474.5, B.Cu 1014.7), 194 vias, 0 dups. Rebuild output: **`98a60c3b4332d6e9`** (identical). Cross-check: the same script gives `2b251adc9d235000` on the `c2bb8c1` board, the value the S1 report states, so the script matches the project's | **reproducible; the brief's / commit-message hash is wrong** (finding 3) |
| CPL cross-check (`cpl_check.py`, kpads from this board, committed CPL and `rot_report.txt`) | 84 rows, 0 / 0 | 84 rows, 88 footprints (MH1–MH4 excluded), rotation discrepancies 0, position discrepancies 0, 9 spot checks OK. JLC BOM designators 84 = CPL designators 84 | pass |
| Pad-net parity vs `ref-3883378.kicad_pcb` | 88 footprints, 0 discrepancies | ref 88 / new 88 footprints, 108 / 108 nets, 0 nets only in one board, 0 pad-set differences, 0 inner tracks, 0 locked items | pass |
| Camera lengths (KiCad pad-edge, `len2.txt` of the rebuild = committed board) | Sync 81.9–83.0 (1.18), Trigger 41.1–43.6 (2.47), TDRSTN 51.7–53.1 (1.37) | Sync 81.8656–83.0424 (**1.1768**); Trigger 41.1239–43.5978 (**2.4739**); TDRSTN 51.6878–53.0545 (**1.3667**). Per line: Sync1 81.8656, Sync2 82.5781, Sync3 81.9748, Sync4 82.0379, Sync5 83.0424, Sync6 82.2750; Trigger1 42.5632, Trigger2 43.3233, Trigger3 42.7163, Trigger4 43.5978, Trigger5 42.8968, Trigger6 41.1239; TDRSTN1 52.0103, TDRSTN2 52.1670, TDRSTN3 52.5191, TDRSTN4 53.0545, TDRSTN5 52.1323, TDRSTN6 51.6878 | pass |
| Fab package vs this board | fresh | **stale by one commit.** `fab/gerbers/*` and the zip were last committed in `c2bb8c1`; the board changed again in `2e1baaf` (Trigger6 tail). Fresh `kicad-cli pcb export gerbers --board-plot-params` from the committed board differs from `fab/gerbers` in F.Cu (147 sorted lines) and B.Cu (45) after sorting and dropping the date lines; In1/In2, mask, paste, silk, edge, both drill files: 0. A fresh export of the `c2bb8c1` board equals `fab/gerbers` exactly (only the ProjectId name line differs). Zip: 14 members, every member byte-equal to `fab/gerbers` (drill-map PDFs excluded as documented). All gerber headers carry `CreationDate 2026-11-06T15:37:15`, i.e. before the 16:59 commit | **fail** (finding 1) |
| signal_sim | geometry fresh; 169 runs, levels clean, timing checks pass | `geometry.json` last committed in `92386e5` (13:35); re-extracted from the committed board into a temp copy: 4 nets differ — Sync6 78.0198 → 78.5026 mm (40 → 32 segs), Trigger1 42.0697 → 42.4132 (33 → 21), Trigger2 42.3162 → 43.3233 (39 → 21), Trigger6 39.1319 → 37.6751 (17 → 12). Fresh run: 169 ngspice runs, 93.3 s, exit 0; all 16 hand-calculation checks 0.000 (two first-arrival checks −0.009 / −0.008 ns, as before); ring-back risk `no` in all 18 GP11 rows; time-step check 2.5 ps vs 1.25 ps unchanged. Result deltas ≤ 0.02 ns (camera trigger spread rise 0.055 → 0.044 ns); every number quoted in Hardware.md (10.2/21.6/33.7, 9.7/20.9/32.2, 6.7/10.8/19.1, 7.2/11.1/19.6, −8.2/+10.8/+26.5, −9.1/+9.8/+24.2 ns) still holds at the printed precision | **stale inputs, clean result** (finding 4) |
| Gaps report | 25 lines, deterministic, 0 MH | 25 lines, 0 MH lines; nearest to the 1.0 mm limit 0.95 (C18–R20, C4–C5); the five carried pairs 0.03 / 0.03 / 0.08 / 0.23 ×3 / 0.36 as documented | pass |
| Meander arm gap (`meander_check.js`, SKIP 2) | ≥ 0.3 mm | ok at CLR 0.3, 0.44 and 0.449; 8 lines fail at CLR 0.45 (equality), so the minimum own-copper gap 2 mm+ along the line is exactly 0.450 mm | pass |

## 2. Findings

Severity: High = blocks an order or breaks a stated guarantee; Medium = should be fixed before
release; Low = cosmetic, documentation or accepted residual with a number attached.

### F-1 (High, Docs / fab) — Fab package does not match the committed board (regression of F4)

- Location: `fab/gerbers/PiDG_Pico-F_Cu.gbr`, `-B_Cu.gbr`, `fab/PiDG_Pico_Gerbers.zip`.
- Evidence: fresh export of the committed board vs `fab/gerbers`, sorted, date lines removed: F.Cu
  147 differing lines, B.Cu 45, all other 11 files 0. The differing F.Cu lines include the Trigger6
  tail region (x 241.37–241.88, y 102.02–102.95, and x 241.1–241.7, y 107.2–107.8) that `2e1baaf`
  re-shaped, plus GND pour vertices around it; B.Cu differs in GND pour vertices at x 183.7–221.0,
  y 99.3–110.3 (pour re-fill after the F.Cu change; no B.Cu track changed). A fresh export of the
  `c2bb8c1` board equals `fab/gerbers` byte-for-byte except the ProjectId line, so the package is the
  `c2bb8c1` copper. Git confirms it: last change to the fab files `c2bb8c1` 15:37, board `2e1baaf`
  16:59. The zip matches the gerber folder, so `JLC_ORDER.md` would upload the old Trigger6 routing
  (41.12 mm line shipped as 42.78 mm).
- Recommendation: re-export gerbers and drill with the board plot settings, rebuild the 14-file zip,
  and add the export to the commit checklist (the RESIDUAL and SIMPLIFY reports did this per copper
  commit; the T6 commit did not).
- Status: new (regression of REVIEW F4).

### F-2 (Medium, Docs / process) — Trigger group spread doubled by the T6 edit and now exceeds every other group; FIX_PLAN gate 4 is stale

- Location: Trigger6, F.Cu, J6 tail (241.6, 102.5) → (247.9, 102.5) → (254.98, 109.58);
  `tools/eurocard/FIX_PLAN.md` line 26–27.
- Evidence: Trigger group 41.1239–43.5978 mm, spread 2.4739 mm (was 1.0346 at `c2bb8c1`); the other
  five Trigger lines span 42.5632–43.5978 (1.0346). 2.47 mm on this stackup is about 15 ps (the doc
  says the same). The build's `--length-match-tolerance 0.5` is now exceeded 5× on this group;
  Hardware.md records it as a review edit, but `FIX_PLAN.md` still states gate 4 as "Trigger
  42.56–43.60, spread 1.04", so the plan's gate no longer matches the board the plan claims to gate.
- Recommendation: either restore Trigger6 to the group (a 1.66 mm meander fits in the straight run
  x 241.6–247.9, 2.45 mm from +12V and 2.35 mm from U19.OUTB) or state the new 2.47 mm gate in
  FIX_PLAN.md and accept it. 15 ps is far below the 6.667 ns timing step, so this is a consistency
  item, not a timing defect.
- Status: new.

### F-3 (Low, Docs) — Commit `2e1baaf` and the review brief quote a copper fingerprint that the board does not have

- Location: commit message of `2e1baaf`; `PiDG-wt/prompts/fable-design-review.md`.
- Evidence: `fp.py` on the committed board = `98a60c3b4332d6e9`; on the rebuild output =
  `98a60c3b4332d6e9`; on the `c2bb8c1` board = `2b251adc9d235000` (the value SIMPLIFY_REPORT.md
  gives, so the script is the project's). The stated `c27822f7b03012e7` matches neither. Segment /
  length / via counts in the message (1015 / 2489.2 / 194) are correct. The board is reproducible;
  only the recorded hash is wrong.
- Recommendation: record `98a60c3b4332d6e9` wherever the T6 state is cited; note that the hash in the
  commit message cannot be amended without a rewrite, so put the correction in Hardware.md or the
  next report.
- Status: new.

### F-4 (Low, Docs / signal) — `tools/signal_sim/geometry.json` and `results.md` predate the R5 and T6 copper

- Location: `tools/signal_sim/geometry.json` (committed `92386e5`), `results.md`.
- Evidence: see the state table; Sync6, Trigger1, Trigger2 and Trigger6 trees differ from the board.
  The fresh run changes the camera-trigger spread from 0.055 to 0.044 ns (rise) and the J12-minus-
  camera limits by ≤ 0.01 ns; every value quoted in Hardware.md holds at the printed precision.
  The sim README says to re-run after a change to the routing of a simulated net; the R5 and T6
  commits changed four simulated nets and did not.
- Recommendation: commit the re-extracted geometry and results (the fresh run is in
  `%LOCALAPPDATA%/Temp/claude/fable-review/sim/tools/signal_sim/`, exit 0, 169 runs).
- Status: new (same class as REVIEW F5 close-out, not a regression of its code fix).

### F-5 (Low, Power / signal) — Return-path stitching for B.Cu fast lines: five signal vias have no GND via within 5 mm (F9 decision stands)

- Location: `PWM_Trig` via (176.4, 56.3): nearest GND via 11.16 mm; `Sync3` vias (199.5, 118.4)
  10.98 mm and (199.5, 103.2) 9.39 mm; `CH1_J10` via (192.9, 52.9) 6.90 mm; `LASER_PWR_OK` via
  (231.6, 87.5) 5.62 mm. Of 31 camera / fast-net signal vias, 16 have no GND via within 3 mm.
- Evidence: measured centre-to-centre to all 134 GND vias. Sync3 is the only Sync line with two
  vias (F.Cu 35.7 mm, B.Cu 43.1 mm) and both are the farthest from a GND return. Hardware.md records
  the F9 decision (no extra GND vias, 1.8 V LVC edges 1–3 ns, 18.9 pF/cm² pour return).
- Recommendation: none required for function. If the `--add-gnd-vias` option is ever enabled,
  these five vias are the ones that matter; a single GND via each near the two Sync3 vias and the
  PWM_Trig via would cover the worst cases without the full 50-via set.
- Status: closed-ok (decision recorded), measurement added.

### F-6 (Low, Routing) — Router power nets sit at the 0.2 mm clearance floor against GND vias

- Location: `+12V` track (225.5, 77.4)–(221.4, 73.3) B.Cu to GND via (224.844, 75.650): 0.223 mm;
  `+1V8` track (218.5, 84.8)–(216.3, 87.0) F.Cu to `PIXRST_GATE` via (218.3, 86.1): 0.228 mm;
  `VBUS_PD` carried track (136.58, 107.52)–(140.7, 107.52) F.Cu to `Net-(J17-CC2)` via
  (137.9, 106.8): 0.220 mm; camera `TDRSTN5` B.Cu to GND via (222.49, 96.082): 0.210 mm;
  `PWM_1MHz` B.Cu to GND via (194.844, 87.251): 0.232 mm (documented).
- Evidence: `netgap.py --no-pads` battery. All are ≥ the 0.20 mm netclass clearance and DRC is clean;
  the margin over the rule is 0.01–0.03 mm because the router runs at `--clearance 0.2` with no
  extra margin for power nets. JLC's 4-layer capability (0.127 mm) covers it.
- Recommendation: optional: give the power nets a 0.25 mm clearance netclass before the next
  re-route so the 15 V and 12 V rails are not at the rule floor next to GND vias.
- Status: new (informational).

### F-7 (Low, Docs) — Schematic-parity warnings are 200 and all are label-prefix noise; nothing in the build log says so

- Location: `work/final/drc.json` `schematic_parity`; `drc_gate.py` output line.
- Evidence: 174 `net_conflict` are all of the form "Pad net (X) doesn't match net given by schematic
  (/X)" (12 VBUS_PD, 7 each LASER_PWR_OK / SYNC_N / PIXRST_N / TRIG_N, …); 22 are `Datasheet` `~` vs
  empty; 4 are the MH footprints absent from the schematic. Hardware.md explains them (RESIDUAL
  report section 4 says so); the build log prints only the count.
- Recommendation: have `drc_gate.py` print the three class counts, so a real parity error (a pad on
  the wrong net) is not hidden in "200".
- Status: new (informational).

### Checked and found correct (no finding)

- Power: buck hot loop carried from Rev 1 unchanged (SW 0.6 mm U15.5 → L1.1 3.14 mm; the three
  0.3 mm SW pieces (158.0375, 108.6)–(158.85, 112.0) are the bootstrap-capacitor branch, identical in
  the reference board at (229.0375, 40.6)–(229.85, 44.0)); C12.2 GND vias at 1.738 and 1.900 mm;
  SW node to GND 0.400 mm (tracks), 0.300 mm at the U15.5/U15.6 pads (pin pitch). Rail widths:
  VBUS_PD 0.5 mm (two 0.4 mm J17 joins in parallel, one 0.3 mm pin tie U15.2–U15.3), +12V 0.5 mm
  (0.4 mm carried U17 tie), +5V_PD / +1V8 / +3V3 / PWM_1MHz 0.5 mm; worst rail current 360 mA
  (U17 limit) and 50 mA on +1V8, so IPC-2221 external 1 oz margins are ≥ 2.5× everywhere. All 194
  vias 0.6 / 0.3 mm; +12V has 7 vias in its chain, +1V8 2, +5V 12 taps.
- Signal: lanes 55.75 + 10.41 = 56.49 + 9.67 = 66.16 mm (`pathlen.py`); lane to nearest copper
  0.450 mm (CH1_J10 via, F.Cu) and 0.538 mm excluding CH1_J10 (CLK_SEL parallel run), as
  documented; with pads 0.220 mm at U7.2 vs LASER_EN (pin pitch). Sync–Trigger 1.106, Trigger–TDRSTN
  0.752, Sync–TDRSTN 0.323 mm; parallel same-layer runs between different camera nets under 0.5 mm
  gap total 10.5 mm in 10 pairs, longest 2.17 mm (Trigger1/Trigger2 at x 221.6, gap 0.45) — no
  crosstalk concern at these edge rates. Camera density 5.21 segs/10 mm, non-camera (GND, +5V
  excluded) 2.74; segments < 0.5 mm with no pad or via end: 36 camera, 30 other (doc 37 / 35, the
  doc's pad-centre rule counts slightly differently).
- Assembly: U14 paste is three paste-only rectangles 0.545 × 2.66 (x 142.2275 and 143.3725) and
  0.6 × 1.0 (x 142.8, y 115.0–116.0) = 3.50 mm² of the 6.93 mm² EP (50 %); the EP vias at
  (142.8, 114.7) and (142.8, 116.3) are outside the paste. 45 tap vias all 0.25 mm from their pad;
  22 vias under 0.25 mm are router signal vias (0.161–0.239 mm) and the two Rev 1 GND vias at
  0.200 mm (R7); no 0.10 mm case. Courtyard gaps as documented.
- Mechanics: MH1–MH4 at (134, 36), (286, 36), (134, 124), (286, 124), 3.2 mm; 7 mm washer courtyard
  2.5 mm from the long edges (touches the card-guide strip, documented). J17 pads 1.75 mm inside the
  left edge, F.Fab body 0.05 mm past it (flush). TP3 courtyard 0.42 mm inside. BNC courtyards 20.8 mm
  past the right edge (barrels). Pico micro-USB F.Fab 0.335 mm past the edge with a 0.1 mm line
  (0.285 mm face, as documented). Minimum copper to outline 1.2 mm (fence via rings at 1.5 mm
  centres). F.Fab has 4 drawings. README board diagram order (J18/J7 at y 48–50, J10 56, TP3/J20
  67–70, J19/J8 70–73, J11 77.5, J21/J12 88–90, J17 106, J1–J6 111.5) matches the board.
- Routing: no GND pour island with fewer than 2 vias on any layer (F.Cu 4 islands, B.Cu 1, In1 1,
  In2 +5V 1); 0 duplicate segments; all vias 0.6 / 0.3.
- Docs: Hardware.md totals (1015 / 2489 / 1474 / 1015 / 194), camera ranges and spreads, density,
  short-segment counts, MH insets, hot-plate pairs, lane and PWM separations, and all sim numbers
  match the measurements above. JLC_ORDER.md: 84 CPL rows, 41 BOM lines, zip description correct.

## 3. Prior-findings spot-check (current board geometry)

| Finding | Check | Measurement | Status |
|---|---|---|---|
| F1 C12 in CARRY_GND | the two carried GND vias exist near C12.2 (155.5625, 115.3) | GND vias (157.3, 115.3) at 1.738 mm and (155.5625, 117.2) at 1.900 mm; U15.4 to the first 2.837 mm | CLOSED |
| F2 / F3 camera-first pass, arm gap ≥ 0.3 mm | build.sh step 4a routes the 18 camera nets alone with `--meander-spacing 2.5`, then `lock.js`; `meander_check.js` | `meander_check` ok at CLR 0.3 / 0.44 / 0.449, 8 lines fail at exactly 0.45 → minimum arm gap 0.450 mm (0.75 mm pitch) on every line | CLOSED |
| F9 48 GND return vias | decision and board state | Decision "no extra GND vias" recorded in FIX_PLAN.md and Hardware.md; board has 194 vias (GND 134), no `--add-gnd-vias` in build.sh; worst signal-via-to-GND-via distances 11.16 / 10.98 / 9.39 mm (F-5) | CLOSED (decision: not applied) |
| F11 tap vias 0.25 mm from own pad | ring edge to own pad edge, all vias | 45 taps at 0.250 mm (list in session), minimum over all vias 0.161 mm (CH1_J10 router via at R19.2), two Rev 1 vias 0.200 mm (R7); zero cases at 0.10 mm | CLOSED |
| F12 MH at y 36 / 124 | MH centres and washer | MH1 (134, 36), MH2 (286, 36), MH3 (134, 124), MH4 (286, 124); 7 mm washer courtyard y 32.5–39.5 / 120.5–127.5, i.e. 2.5 mm from the long edges = 0.0 mm clearance to the 2.5 mm card-guide strip; docs say to fit no hardware in card guides | CLOSED (as documented) |
| F21 U14 paste H | F.Paste geometry of U14 | three paste rectangles 0.545 × 2.66, 0.6 × 1.0, 0.545 × 2.66 at x 142.2275 / 142.8 / 143.3725; vias at (142.8, 114.7) and (142.8, 116.3) clear of paste; 50 % coverage; EP pad 11 has no paste layer; DRC shows the expected `lib_footprint_mismatch` warning | CLOSED |
| F26 frag_stitch | GND pour islands with < 2 vias | none on F.Cu (4 islands), B.Cu (1), In1 (1); In2 +5V (1) | CLOSED |
| F31 jog density | segments per 10 mm; segments < 0.5 mm | camera 542 segs / 1039.9 mm = 5.21/10 mm; other nets (GND, +5V excluded) 372 / 1359.7 mm = 2.74/10 mm (hand board 2.8); segments < 0.5 mm 101 (61 camera, 40 other), with neither end at a pad or via 66 (36 camera, 30 other), 54 of them with no branch; worst camera lines TDRSTN4 8.74/10 mm, TDRSTN2 7.91, Trigger4 7.80 (kept length bumps) | CLOSED (acceptance met on non-camera nets; camera residual documented) |
| F4 fab zip | zip content vs board | zip = `fab/gerbers` (14 files), but both are the `c2bb8c1` copper, not `2e1baaf` | REGRESSION (F-1) |
| F5 signal_sim | re-run on final routing | code fix present (169 runs, no hang); inputs one copper commit stale (F-4) | CLOSED code / stale data |
| F18 Sync4 / ends.py | pad-edge lengths | Sync4 82.0379 mm, 0.17 mm from the Sync group median; Sync5 83.0424 is the 0.89 mm outlier (R6, untouched) | CLOSED |
| F27 foreign copper under SMD bodies | `repair.py` in build.sh | step runs (`REPAIR_PARTS` list), DRC clean; not re-measured geometrically this pass | NOT-VERIFIABLE here (build log shows the step) |
| R3 +12V sliver | segment at (239.808, 76.85) | no segment shorter than 0.08 mm on +12V; +12V tie ends at (239.8, 76.85) 0.425 mm piece | CLOSED |
| R7 Rev 1 GND vias | ring to own pad | (236.0, 60.935) and (241.9, 98.435) at 0.200 mm | CLOSED (documented) |

## 4. Notes on method

- Fingerprint script: `audit-tools-fixagent/fp.py` (read-only copy), first 16 hex of sha256 over
  sorted (type, net, layer, start, end, width[, drill]) with 0.1 µm rounding; it reproduces the S1
  report's `2b251adc9d235000` on the `c2bb8c1` board.
- Gerber comparison: lines sorted, `CreationDate` / `G04 Created` / `; DRILL file` lines removed,
  CR stripped; the committed In1/In2/mask/paste/silk/edge/drill files are identical to a fresh export
  under this comparison, which validates the method before it was applied to F.Cu / B.Cu.
- The sim was run on a copy of `tools/signal_sim` with the committed board placed two directories up,
  so no repository file changed. `git status` in the worktree is clean apart from this report.
