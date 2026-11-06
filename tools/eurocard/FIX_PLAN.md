# EuroCard review fix plan (from REVIEW.md, base commit 8408895)

Execution by Claude Opus 5.5 sub-agents (Claude Code 2.1.310, `--model
claude-opus-5-5`, effort high; final adversarial audit at xhigh), isolated
git worktrees, dual adversarial review at the end. Local commit only — push
is user-managed.

## Fixed environment

- One shared KiCadRoutingTools clone at commit 8759686 and its venv (see
  `tools/eurocard/README.md`, Setup), outside the worktrees:
  - `KRT_DIR=<path to the KiCadRoutingTools clone>`
  - `KRT_PY=<path to that venv's python.exe>`
  - Build: `KRT_DIR=... KRT_PY=... bash tools/eurocard/build.sh` (about 2.5 min)
- Verified fix code: a read-only copy next to the worktrees, `_verified-fixes/`
  (`verify-fix-<F>/` per finding, `simfix/` F5 patch + val126, `review-routing/`
  camera-first prototype incl. frag_stitch.py); session scratch, not in the repository.
- Worktrees: one git worktree per phase branch (`fix/p1-placement`, `fix/p1-sim`,
  `fix/p1-docs`, `fix/p1-postroute`, `fix/p2-routing`, `fix/p3-postroute`), created as
  each phase starts.

## Verification gates (board changes)

1. DRC: 0 violations, 0 unconnected (`work/final/drc.json`)
2. CPL cross-check vs `tools/jlc_cpl`: 84 rows, 0 position/rotation discrepancies
3. Pad-net parity vs ref `3883378`: 88 footprints, 0 inner tracks, 0 locked
4. KiCad-measured camera lengths (after the fixes and the audit fixes: Sync 81.87–83.04,
   Trigger 42.56–43.60, TDRSTN 51.69–53.05 mm; spreads 1.18 / 1.04 / 1.37 mm)
5. Fab outputs regenerated (gerbers, drill, CPL) before any zip

## Phase 1 — parallel (4 agents, effort high)

### A `fix/p1-placement` — placement + carry changes, one rebuild
F1 (C12 into CARRY_GND), F6 (VBUS A9–B9 join + locked lane + J17 keep-out +
stub removal), F7 (U9/C7/C6 above buffer row + silk), F8 (R18 (194.0,66.5) +
R18 branch drawn in lane), F10 (pin-1 mark (132.385,56.6)), F11
(taps SAME_PAD=0.25 + own-pad-by-shape), F12 (MH y 36/124 + gaps.py check),
F13 (TP3 (141.0,67.0)), F15 (C17/C20 poses), F16 (C14/C15/U16 row by L1.2),
F20 (silk labels U3/U15/U10/TP3), F21 (U14 paste "H"), F24 (BNC position fix
only if a verified variant exists in `_verified-fixes/verify-fix-F24/`).
Port each change from its verified variant; full rebuild; gates 1–4.

### B `fix/p1-sim` — signal_sim fix (no board change)
Port `simfix/fix.patch` (Dijkstra hand-check 4, branch-point vias, option-d
assert) into `tools/signal_sim/`; README paragraph. Re-extract geometry.json
from the committed board, run full sim (~100 s): no hang, 169 runs, voltage
levels clean. Validate against `simfix/val126` (max delta ≤ 0.0025 ns on the
126 mm geometry).

### C `fix/p1-docs` — geometry-independent docs (no build)
F19 (fan-out match starts at buffer output), F22 (0.65 mm-pitch hot-plate
paste), F25 (camera ribbon + J11 E-stop wire exits), F29 (J17 0.27 mm gap,
U18 not `_HandSolder`), F30 (README board diagram J11 position), F24 fallback
spacer note if agent A does not take the position fix.

### D `fix/p1-postroute` — new post-route scripts (test on 8408895 fixture)
ends.py (F18: trim track ends to pad edge as KiCad measures), frag_stitch.py
(F26: vias on single-via islands/necks; start from review-routing prototype),
repair (F27: PIXRST_GATE between C2 pads, +12V under R30, +5V_PD at U15 pin 1
corner), tidy.py (F28: remove stitch bridges + slivers < 0.08 mm only),
straighten (F31b: merge collinear, replace jogs with straight runs where
clearance allows). Each script: DRC clean after, measured before/after
evidence, netlist diff where applicable. No build.sh integration yet; deliver
scripts + TEST_REPORT.md.

## Phase 2 — camera-first routing (after A; effort high)

`fix/p2-routing` (worktree of A's final commit). build.sh: route the 18
camera nets first in their own route.py pass with real meander arm spacing
(≥ 0.3 mm gap), lock them, then route the rest (F2, F3, per the
review-routing prototype). Higher `--turn-cost` for non-camera style (F31a).
Gates 1–4 + arm-gap measurement + jog-density measurement.

## Phase 3 — post-route application (after Phase 2; effort high)

`fix/p3-postroute` (worktree of Phase 2's final commit). Wire D's scripts
into build.sh (ends → frag_stitch → repair → tidy → straighten → DRC),
rebuild, gates 1–5 + F31 acceptance (non-camera nets ≈ 2.8 segments/10 mm,
no < 0.5 mm segment except pads/vias) + F18 (Sync4 within 0.05 mm) +
F26/F27/F28 measured acceptance.

## Phase 4 — integration, sim, docs, fab

Merge Phase 3 into `eurocard` (local commit). Re-extract geometry from the
final board, run final signal_sim (F5), update Hardware.md tables (F14) with
measured values, rebuild `fab/PiEBV_Pico_Gerbers.zip` from `fab/gerbers` (F4,
14 files, no drill-map PDFs). Full verification suite.

## Phase 5 — dual adversarial review

- Local (Hermes): diff 8408895 → final for every changed file; re-verify all
  gates independently (fresh DRC, CPL, parity, lengths, jog density, island
  scan, under-part copper scan); check sim results against geometry
  timestamps; check every REVIEW.md finding is closed with evidence.
- Sub-agent (effort xhigh): independent audit of the same diff + outputs,
  adversarial stance (assume the fix is wrong until proven).
- Findings from either side are fixed, re-verified, then the work is
  reported. Push only on explicit user instruction.

## Audit fixes (branch `fix/audit-findings`)

The dual audit of 801ae47 found 23 items; the fix report with before/after
measurements is `tools/eurocard/work/audit/FIX_AUDIT_REPORT.md` (build output
folder, not committed). Decisions recorded here:

- **F9 (return path of B.Cu lines): no extra GND return vias.** The review's
  option, `route_planes.py --add-gnd-vias --gnd-via-distance 1.5` in the
  stitching step, adds 50 GND vias beside the signal vias on the current
  routing and changes no track (tested on the build's `st_in`, scratch only).
  REVIEW.md leaves it as "decide before use", and the fix check rated the
  finding low severity (1.8 V LVC lines, 1–3 ns edges; the B.Cu GND pour gives
  about 18.9 pF/cm² to the +5 V plane). The conservative choice keeps the
  verified copper; Hardware.md (Routing, "Reference planes") records the B.Cu
  lengths, the return path and the option. Add it if EMI measurements call
  for it, then run all gates again.
- **U1 (camera-line "ducking" near J1–J6):** level 1 of the fix ladder, a
  deterministic clean-up (`camclean.py`, length kept; `kilen.py` +
  `camclean.py --trim` for KiCad's length reading). Router re-route (level 2)
  was not needed.
- **Separation values:** measured with `netgap.py` and checked with KiCad DRC
  rules; several values in the audit's own table were wrong (its script
  missed parallel runs and pads). Hardware.md gives the measured values.
