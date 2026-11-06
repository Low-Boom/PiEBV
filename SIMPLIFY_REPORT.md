# Simplify report: R9 / J10 routing and driver trace widths (branch `fix/simplify-r9j10`, base 6944e93)

Scope: Task A, re-evaluate the routing of `CH1_J10`, `PWM_TRIG_TAP`, `PWM_Trig`, `PIXRST_GATE` and `GND`
in x 184–216, y 44–80 mm. Task B, verify the driver trace widths (no edits). All work is in the worktree
`PiDG-wt/fix-simplify`. Local commits only. KRT came from `PiDG-wt/_krt` (read-only).
Scratch files are outside the worktree, in `PiDG-wt/_simp`.

Tools: KiCad 10.0.6 python and kicad-cli; `fp.py` (copper fingerprint, from `audit-tools-fixagent`),
`netdiff.py`, `netgap.py`, `regiongap.py` (new, committed), `kilen.py`-style KiCad length reading for any
net, `frag_stitch.py` on copies.

Baseline: the first build of 6944e93 gave `fcc9f88c90995994` (1022 segments, 2490.8 mm, 194 vias, 0
duplicates). This is the same as the committed board. It is kept as `_simp/base-simplify.kicad_pcb`.

Note on the build command: the brief's `KRT_DIR` (`.../_krt/krc_src/...`) does not exist. The real path
is `.../_krt/krt_src/KiCadRoutingTools`. With the brief's path the build stops at step 2 (`cd: No such
file or directory`). All builds below use `krt_src`.

## 1. Result

| Net | Verdict | Copper change |
|---|---|---|
| `PIXRST_GATE` | **RESHAPE**: router jog removed | B.Cu 5 → 3 segments, length +0.0000 mm, vias unchanged |
| `PWM_TRIG_TAP` | KEEP: every bend is necessary (crossing with `PIXRST_GATE`, R9.1 connection) | none |
| `CH1_J10` | KEEP: via needed to cross the CH1 pulse lane; the brief's via-in-pad candidate is not allowed | none |
| `PWM_Trig` | KEEP: one 45° run + one horizontal (minimal) | none |
| `GND` (6 taps in region) | KEEP: real plane taps (see 2.5) | none |

Board: 1022 → **1020** segments, 2490.8 mm (unchanged), **194 → 194** vias, fingerprint
`fcc9f88c90995994` → **`2b251adc9d235000`**.

The brief's ground truth did not match the board in four places. The decisions above use the
real geometry:

1. The long `PWM_TRIG_TAP` run (210.2, 57.2) → (235.3, 82.3) is on **B.Cu**, not F.Cu, on the line
   y = x − 153.0 (not − 153.2). Hardware.md also gives `PWM_TRIG_TAP` 70.2 mm on B.Cu.
2. The F.Cu "stub" (209.0, 56.0) → (210.1, 57.1) is **R9.1's only connection** to the net. R9 is a front
   SMD part. If you remove the stub, R9 is disconnected.
3. The three GND taps in the brief, (207.5, 59.2)→(208.8, 57.9) and (202.0, 47.5)→(202.0, 49.5)→(203.0, 50.5),
   **do not exist** on the board. The real GND copper in the region is in 2.5.
4. `PIXRST_GATE` and `PWM_TRIG_TAP` must cross. That changes the analysis of items 1 and 3 (see 2.2).

## 2. Per-segment verdicts (base board, all tracks 0.3 mm unless stated)

Clearance numbers: edge to edge, same copper layer (tracks, vias, exact pad outlines; zone fills not
counted). The board rule is 0.20 mm.

### 2.1 `PIXRST_GATE` (RESHAPE, `simplify.py`)

| Segment (base) | Layer | Verdict | Reason |
|---|---|---|---|
| (193.6, 41.0) → (205.0, 52.4) | F.Cu | KEEP | One 45° run to the via. It must change to B.Cu before the CH1 pulse lane (F.Cu, y 53.8); the via ring is 0.95 mm from the lane |
| via (205.0, 52.4) | — | KEEP | Crossing of the lane (above), and the crossing point with `PWM_TRIG_TAP` (2.2) |
| (205.0, 52.4) → (208.2, 55.6) | B.Cu | RESHAPE | Extended on the same 45° line to (209.1, 56.5) |
| (208.2, 55.6) → (208.2, 57.9) | B.Cu | REMOVE | Router jog. The vertical at x 208.2 cannot continue: the `LASER_EN_TAP` via (208.0, 68.5) is in its path |
| (208.2, 57.9) → (210.0, 59.7) | B.Cu | REMOVE | Router jog to x 210 |
| (210.0, 59.7) → (210.0, 77.8) | B.Cu | RESHAPE | One vertical at x 209.1, (209.1, 56.5) → (209.1, 76.9). At x 210 it was 0.230 mm from the +5V tap via (210.68, 67.05) |
| (210.0, 77.8) → (218.3, 86.1) | B.Cu | RESHAPE | Same 45° line, start moved to (209.1, 76.9). The end (218.3, 86.1) and all copper outside the region are unchanged |
| via (218.3, 86.1) and on | — | KEEP | Outside the region |

The new shape is 45°, vertical, 45°. Both 45° legs stay on their old lines. So the total 45° run (13.3
mm in x) and the total vertical run (20.4 mm) do not change, and the length does not change. X 209.1 is
the 0.1 mm grid position (208.6–209.6) with the largest smallest gap of the new copper. It is between
the two vias that set the limits: the `PWM_TRIG_TAP` via (210.2, 57.2) and the `LASER_EN_TAP` via
(208.0, 68.5), 0.650 mm to each.

`simplify.py` guards (all passed): the old run must have exactly the expected 6 vertices (otherwise
the run is left as it is); octilinear; no segment < 0.3 mm (new: 5.798 / 20.400 / 13.011 mm); no turn
> 90° (turns: 45°, 45°); length change ≤ 0.001 mm (+0.0000); to every other net not below min(old
window gap, 0.45 mm) and not below the net's smallest gap before (0.208 mm); own copper > 2 mm along
≥ 0.45 mm.

Clearance check of the new copper (B.Cu): `LASER_EN_TAP` 1.550 → 0.650; `PWM_TRIG_TAP` 1.044 → 0.650
(window; 0.894 → 0.650 with the via included); +5V (region) 0.230 → 1.130; `PWM_Trig` (J10.3 pad)
1.489 → 1.489; GND 0.879 → 0.879; Sync6 2.033 and TDRSTN6 4.600 unchanged (outer diagonal).

### 2.2 `PWM_TRIG_TAP` (KEEP)

| Segment | Layer | Verdict | Reason |
|---|---|---|---|
| (202.5, 56.0) → (202.5, 52.2) | B.Cu | KEEP | Leaves J10.2 up, left of the GND frag via (203.65, 52.70) and the `PIXRST_GATE` via (205.0, 52.4) |
| (202.5, 52.2) → (204.6, 50.1) | B.Cu | KEEP | Goes over the `PIXRST_GATE` via (0.894 mm) |
| (204.6, 50.1) → (210.2, 55.7) | B.Cu | KEEP | Comes down right of `PIXRST_GATE`, parallel to its 45° leg (1.04 mm) |
| (210.2, 55.7) → (210.2, 57.1) | B.Cu | KEEP | Steps from the line y = x − 154.5 (clear of the `PIXRST_GATE` via) onto the long run's line y = x − 153.0 at the via |
| via (210.2, 57.2) | — | KEEP | R9.1 is a front SMD pad; this via is its only connection. The J10.2 → U5 path stays on B.Cu through it (the via is a branch to R9, not a plane jump on the path) |
| (209.0, 56.0) → (210.1, 57.1) | F.Cu | KEEP | R9.1 pad to the via (1.556 mm, one 45° run) |
| (210.2, 57.2) → (235.3, 82.3) | B.Cu | KEEP | Long run to U5 / U19; leaves the region |

Why the up-and-over is necessary: `PIXRST_GATE` comes from the upper left on F.Cu, changes to B.Cu at
(205.0, 52.4) and continues down to (218.3, 86.1). `PWM_TRIG_TAP` must go from J10.2 (left of that
path) to R9 and the long run (right of it). So the two nets must cross. Below the lane both are on
B.Cu (F.Cu has the lane and the J10 pin row). Above the lane `PIXRST_GATE` is on F.Cu. So the
crossing can only be where `PWM_TRIG_TAP` passes on B.Cu above the `PIXRST_GATE` via. The same path
must then come down again to R9 (y 56–57). The up-then-down is that crossing, not a router zig-zag.
Alternatives checked:
- **The brief's candidate** (B.Cu (202.5, 56) → (205.85, 52.65), via, F.Cu to (235.3, 82.3)). The B.Cu
  leg crosses the `PIXRST_GATE` B.Cu leg at (205.55, 52.95): short circuit. The F.Cu leg would cross the
  F.Cu `_PULSE_OUT_CH1` lane at about (207.0, 53.8): short circuit. It is also not on a 45° line (dx 29.45,
  dy 29.65). Rejected.
- **J10.2 to R9.1 on F.Cu**, between the J10 pin row and the lane. There is 1.2 mm between the pad
  edge (y 55.15) and the lane edge (53.95). This puts a 0.3 mm track at most 0.45 mm from the CH1 laser
  pulse lane, along about 6 mm. The lane's documented smallest gap is 0.538 mm (all nets except
  `CH1_J10`), and Hardware.md keeps the lanes clear of other signals. This adds coupling onto a timed
  lane. Rejected.
- **Same topology, lower apex.** The lowest apex that clears the GND frag via and the `PIXRST_GATE` via
  (0.2 mm) is y 50.96 (now 50.1). It saves 1.7 mm, has the same 4 segments and 0.2 mm gaps. This is not
  a simplification. Rejected.

The B.Cu and F.Cu ends at (210.2, 57.1) / (210.1, 57.1) are 0.10 / 0.14 mm from the via centre
(inside the ring). Joining them to the centre would add 0.100 mm to the J10 → U5 path (rule:
±0.05 mm). They are left as they are.

### 2.3 `CH1_J10` (KEEP)

| Segment | Layer | Verdict | Reason |
|---|---|---|---|
| (192.0, 52.0) → (192.9, 52.9) | F.Cu | KEEP | R19.2 pad to the via. The brief's candidate via at (192.0, 52.0) is the **centre of the R19.2 pad**: a via in a pad, which the router rules forbid ("no via-in-pad") |
| via (192.9, 52.9) | — | KEEP | R19.2 is above the lane (y 53.8, F.Cu), J10.1 below it, so the net must cross the lane on B.Cu. The via ring is 0.450 mm from the lane, the value Hardware.md documents |
| (192.9, 52.9) → (196.0, 56.0) | B.Cu | KEEP | 45° to the J10 pin row |
| (196.0, 56.0) → (200.0, 56.0) | B.Cu | KEEP | Into J10.1. Two segments is the minimum for dx 7.1 / dy 3.1 on a 0/45/90 grid |

Other via sites: directly below the pad, (192.0, 53.0), the ring would be 0.35 mm from the lane (now
0.45 mm), a lane-gap regression. The present site is the 45° site next to the pad.

### 2.4 `PWM_Trig` (KEEP)

| Segment | Layer | Verdict | Reason |
|---|---|---|---|
| (205.1, 56.0) → (201.7, 59.4) | F.Cu | KEEP | 45° out of J10.3, below J10.2 / J10.1 (0.810 mm to J10.2) |
| (201.7, 59.4) → (184.3, 59.4) | F.Cu | KEEP | Straight horizontal |

Two segments, no via in the region. A vertical-then-horizontal shape would also be two segments but
longer.

### 2.5 `GND` copper in the region (KEEP)

The real GND copper: 6 plane taps (0.4 mm F.Cu, pad → via): R17.2 → (193.15, 46.0), R18.2 →
(196.15, 66.5), R8.2 → (201.15, 73.0), U10.3 → (205.32, 68.95), R9.2 → (212.15, 56.0), C6.2 →
(214.5, 76.525). There are also two stitch / frag vias: (187.5, 57.5) and (203.65, 52.70). `frag_stitch.py`
added the second one for the B.Cu neck between `PWM_TRIG_TAP` and `PIXRST_GATE`. All taps run outward
from the part body, as `taps.py` places them. They are not router artefacts: KEEP.

Each tap is stored as **two collinear segments**, for example (211.0, 56.0)→(211.6, 56.0) and
(212.15, 56.0)→(211.6, 56.0). Cause: in `routed.kicad_pcb` the router adds a 0.55 mm piece from the via
to the pad edge on top of the tap. `tjoin.py` then splits the tap at that piece's end, and "piece already
present, not added" (35 on this board) leaves the two halves. The copper is the same as one segment. The
cause is board-wide (all taps), so a region-only fix would be inconsistent. Not changed. Finding F1
below.

### 2.6 Other findings in the region (not in scope, report only)

- **F1 (cosmetic, board-wide):** split plane taps, see 2.5. A fix would be a collinear-merge pass for
  GND / +5V tap pairs in `tidy.py`. It has no copper effect, so the gerbers would not change.
- **F2 `LASER_EN_TAP` at U10:** R3.2 (201, 68) to U10.2 (206.65, 68) runs F.Cu → via (202.5, 68.0) →
  B.Cu → via (208.0, 68.5) → F.Cu. The two vias are a real crossing: `LASER_EN_JMP` leaves U10.1, the
  pin above U10.2, down-left to J11.2 and crosses the straight F.Cu line at y 68. The end via sits
  diagonally off U10.2, with 0.71 / 0.85 mm 45° doglegs on B.Cu / F.Cu. A via at (208.0, 68.0) would
  remove both doglegs. Not changed: not a scope net. If it is done, the `PIXRST_GATE` vertical (x 209.1)
  would then be 0.65 mm from that via. Check this first.
- **F3 `PWM_Trig` outside the region:** J14.15 (TH) → B.Cu 9.6 mm → via (176.4, 56.3) → F.Cu. This is
  at x < 184, outside the region. Not examined further.

## 3. Electrical length per scope net

KiCad 10's own length (DRC length rule that every net fails, vias over their layers, the same reading
as `kilen.py`), and the centre-line sum of all segments (`netdiff.py`):

| Net | KiCad before | KiCad after | Centre-line before | after | Change |
|---|---|---|---|---|---|
| `CH1_J10` | 11.2431 | 11.2431 | — | — | 0 (unchanged) |
| `PWM_TRIG_TAP` | 76.6309 | 76.6309 | — | — | 0 (unchanged) |
| `PWM_Trig` | 42.5970 | 42.5970 | — | — | 0 (unchanged) |
| `PIXRST_GATE` | 87.0799 | 87.0799 | 83.790 | 83.790 | **0.0000 mm** (B.Cu 39.209 → 39.209) |

No length bump was needed. No exception to the ±0.05 mm rule is claimed.

## 4. Region gap battery (`regiongap.py`, x 184–216, y 44–80, same layer, edge to edge, mm)

Tracks are clipped to the box; vias and pads count if their centre is in it. Pairs with a gap < 3 mm:

| Net | Other | Before | After | Layer |
|---|---|---|---|---|
| CH1_J10 | PWM_TRIG_TAP | 0.840 | 0.840 | F.Cu |
| CH1_J10 | PWM_Trig | 2.254 | 2.254 | F.Cu |
| CH1_J10 | _PULSE_OUT_CH1 | 0.450 | 0.450 | F.Cu |
| PWM_TRIG_TAP | GND | 0.324 | 0.324 | F.Cu |
| PWM_TRIG_TAP | PIXRST_GATE | 0.894 | **0.650** | B.Cu |
| PWM_TRIG_TAP | PWM_Trig | 0.810 | 0.810 | F.Cu |
| PWM_TRIG_TAP | _PULSE_OUT_CH1 | 1.200 | 1.200 | F.Cu |
| PWM_Trig | GND | 1.450 | 1.450 | F.Cu |
| PWM_Trig | PIXRST_GATE | 1.489 | 1.489 | B.Cu |
| PWM_Trig | _PULSE_OUT_CH1 | 1.200 | 1.200 | F.Cu |
| PIXRST_GATE | +5V | **0.230** | **1.130** | B.Cu |
| PIXRST_GATE | GND | 0.719 | 0.719 | F.Cu |
| PIXRST_GATE | LASER_EN_TAP | 1.550 | **0.650** | B.Cu |
| PIXRST_GATE | _PULSE_OUT_CH1 | 0.950 | 0.950 | F.Cu |
| GND | +5V / CLK_SEL_JMP / LASER_EN / LASER_EN_JMP / LASER_EN_PU / LASER_EN_TAP | 0.900 / 0.840 / 1.140 / 0.444 / 2.950 / 0.264 | same | F.Cu |
| GND | PIXRST_GATE / PWM_TRIG_TAP / PWM_Trig / VBUS_PD / _PULSE_OUT_CH1 / _PULSE_OUT_CH2 | 0.719 / 0.324 / 1.450 / 1.660 / 0.646 / 0.800 | same | F.Cu |
| **min per net** | CH1_J10 / PWM_TRIG_TAP / PWM_Trig / PIXRST_GATE / GND | 0.450 / 0.324 / 0.810 / **0.230** / 0.264 | 0.450 / 0.324 / 0.810 / **0.650** / 0.264 | |

How to read this: no net's smallest gap in the region goes down, and the region's smallest gap does
not go down. `PIXRST_GATE`'s smallest gap goes from 0.230 to 0.650 mm. Two pairs do go down, both to
0.650 mm (`PIXRST_GATE`–`PWM_TRIG_TAP`, `PIXRST_GATE`–`LASER_EN_TAP`), each at one via, not along
a parallel run. A strict rule of "no pair may go down" cannot be met by any single vertical: the
vertical must pass between the two vias, which are 2.2 mm apart. 0.650 mm is the best split of that
space, above the board's 0.45 mm signal floor and well above the 0.20 mm rule.

Board-wide (`netgap.py`, with pads): `PIXRST_GATE` to all other nets 0.208 → 0.208 mm. This is the +5V
via (213.32, 82.05) on the unchanged outer diagonal, outside the region. Lanes to all other nets
0.220 → 0.220 (U7.2 pad); lanes to `PIXRST_GATE` 0.950 → 0.950; `PWM_1MHz` to `PIXRST_GATE` 14.970 →
14.970.

Pour check: `frag_stitch.py` run on copies of the base and of the final board gives the same output
(2 B.Cu neck sites, both outside the region, and the known "no site" F.Cu neck). The change makes no
new GND pour island or neck.

## 5. Camera lines (before / after: identical)

`work/len2.txt` (KiCad reading after the last camera step) is the same in the base build and in builds
1 and 2, byte for byte. `simplify.py` runs after it. `netdiff.py` shows 0 segment / 0.000 mm change on
all 18 lines.

| Group | Lengths (mm) | Spread |
|---|---|---|
| Sync1–6 | 81.8656 / 82.5781 / 81.9748 / 82.0379 / 83.0424 / 82.2750 | 1.1768 |
| Trigger1–6 | 42.5632 / 43.3233 / 42.7163 / 43.5978 / 42.8968 / 42.7807 | 1.0346 |
| TDRSTN1–6 | 52.0103 / 52.1670 / 52.5191 / 53.0545 / 52.1323 / 51.6878 | 1.3667 |

`meander_check`: ok.

## 6. Task B: driver trace widths (verification only, no edits)

Measured on the board (pcbnew), all on F.Cu, no vias:

| Net | Pads | Width | Length | Current case (max) | IPC-2221 capacity, ΔT 10 °C | Margin: spec / short / ceiling | ΔT at spec / short |
|---|---|---|---|---|---|---|---|
| `CH1_DRIVE_RAW` | U13.7 – R6.1 | 0.30 mm | 7.525 mm | 102.7 mA spec; 179.0 mA short; 440 mA ceiling | 999 mA | 9.73× / 5.58× / 2.27× | 0.057 / 0.20 °C |
| `CH1_DRIVE` | R6.2 – J18.1, R25.1 | 0.30 mm | 25.057 mm | same | 999 mA | same | same |
| `CH1_OUT` | J18.2, R25.2 – J7.1 | 0.30 mm | 11.900 mm | same | 999 mA | same | same |
| `CH2_DRIVE_RAW` | U13.5 – R7.1 | 0.30 mm | 8.934 mm | same | 999 mA | same | same |
| `CH2_DRIVE` | R7.2 – J19.1, R26.1 | 0.30 mm | 24.113 mm | same | 999 mA | same | same |
| `CH2_OUT` | J19.2, R26.2 – J8.1 | 0.30 mm | 11.900 mm | same | 999 mA | same | same |
| `EXT_SYNC_DRIVE_RAW` | U19.7 – R30.1 | 0.30 mm | 7.525 mm | same | 999 mA | same | same |
| `EXT_SYNC_DRIVE` | R30.2 – J21.1, R31.1 | 0.30 mm | 19.704 mm | same | 999 mA | same | same |
| `PWM_1MHz` | J14.20 – U1.2, TP3.1 | **0.50 mm** (as expected) | 83.663 mm (B.Cu 79.6) | logic, ≤ 12 mA (GPIO drive) | 1447 mA | > 100× | ≈ 0 |
| `_PULSE_OUT_CH1` | J14.17 – U7.2, R17.1, R19.1 | **0.30 mm** (as expected) | 63.549 mm | logic, ≤ 12 mA | 999 mA | > 80× | ≈ 0 |
| `_PULSE_OUT_CH2` | J14.16 – U8.2, R18.1 | **0.30 mm** (as expected) | 79.267 mm | logic, ≤ 12 mA | 999 mA | > 80× | ≈ 0 |

All eight driver nets are 0.30 mm, the expected width. No driver trace is thinner than expected, so
nothing is flagged. **No width change is necessary. No width was changed** (`netdiff.py`: 0 change on
every net except `PIXRST_GATE`).

Arithmetic (`_simp/ipc.py`):

- Copper: 1 oz outer (stackup F.Cu / B.Cu `thickness 0.035`; Hardware.md stackup table; JLC order "1 oz
  outer") = 35 µm = 1.378 mil.
- Cross-section: 0.3 mm = 11.811 mil → A = 11.811 × 1.378 = **16.275 mil²**; 0.5 mm → **27.125 mil²**.
- IPC-2221 external: I = 0.048 · ΔT^0.44 · A^0.725. At ΔT 10 °C: 10^0.44 = 2.754.
  0.3 mm: 0.048 × 2.754 × 16.275^0.725 (= 7.557) = **0.999 A**. 0.5 mm: 0.048 × 2.754 × 10.945 = **1.447 A**.
- Spec current, 50 Ω mode, high corner (Hardware.md amplitude budget: 12.05 V, R6 67.32 Ω, ROH 0 Ω):
  12.05 × 50 / 117.32 = 5.136 V → 5.136 / 50 = **102.7 mA**. Low corner: 11.54 / (50 + 68.68 + 8.5) =
  90.7 mA (4.54 V).
- Short at the BNC (50 Ω mode, fault): only R6 / R7 / R30 limit it. 12.05 / 67.32 = **179.0 mA**
  (Hardware.md "Board output rating": at most 358 mA with both laser outputs shorted = 2 × 179).
  The brief's 11.8 / 68.68 = 171.8 mA mixes a typical rail with a low-corner resistor. It is not the
  maximum.
- Ceiling: U17 (LT3065) current limit 400 mA **±10 %** (R20 = 750 Ω; Hardware.md "+12 V"), so at most
  **440 mA** in any one trace. Only a short directly on a `*_DRIVE_RAW` net (before the 68 Ω resistor)
  can draw this. The brief's 2.5× used 400 mA; at 440 mA the margin is **2.27×**.
- Rise at a given current: ΔT = (I / (0.048 · A^0.725))^(1/0.44). 0.3 mm: 102.7 mA → **0.057 °C**;
  179.0 mA → 0.20 °C; 440 mA → 1.55 °C.
- In Hi-Z mode every case is lower (≤ ~63 mA in R27 / R28 / R32, about 60 mA supply current per
  output; Hardware.md "Output mode").
- IR drop: 1.72e-8 Ω·m / (0.3 mm × 35 µm) = 1.638 mΩ/mm. The sum of the three nets per channel (an
  upper bound on the current path): CH1 44.48 mm → 72.9 mΩ → **7.5 mV** at 102.7 mA (13.0 mV at
  179 mA); CH2 44.95 mm → 7.6 mV; EXT_SYNC 39.13 mm → 6.6 mV. 73 mΩ in series with the ~118 Ω divider
  is 0.06 % of the level, against the 1 % tolerance of R6 (±0.68 Ω). The effect is very small.
- The brief's "0.254 mm → ~169 mA @ 10 °C" check value is wrong: the same formula gives 0.885 A for
  10 mil / 1 oz / external / ΔT 10 °C (A = 13.78 mil²). The 999 mA and 1447 mA results do not depend on
  that line.

## 7. Gates and final state

| # | Gate | Result |
|---|---|---|
| 1 | Build exit 0 | builds 0 (base), 1 (S1 working tree), 2 (committed c2bb8c1): exit 0, about 120 s each |
| 2 | DRC | 0 non-warning violations, 0 unconnected, 1 warning: U14 `lib_footprint_mismatch` (F21) |
| 3 | viaguard | placed 19 / tapped 64 / cam_l 79 / routed 107 / st_in 111 / st_out 178: file = KRT on all 6 |
| 4 | gaps.py | 25 lines, MH 0; 3 runs on the final board: one md5; equal to the base build's `gaps.txt` |
| 5 | netdiff base → final | only `PIXRST_GATE`: 19 → 17 segments, +0.000 mm; every other net 0 / 0.000 |
| 6 | Vias | 194 → 194 |
| 7 | Camera lengths | `len2.txt` identical; meander_check ok |
| 8 | Fingerprint | build 1 and build 2 (from the committed tree) both **`2b251adc9d235000`**: 1020 segs, 2490.8 mm (B.Cu 1014.7, F.Cu 1476.1), 194 vias, 0 dups. Root `PiDG_Pico.kicad_pcb` = the same |
| 9 | Fab | gerbers + drill re-exported with `kicad-cli pcb export gerbers --board-plot-params` and `export drill --format excellon --excellon-separate-th --generate-map --map-format pdf`. This command first gave all 14 committed text files from the HEAD board unchanged, apart from timestamps. Zip: 14 files, same member order, sha256 `b5ebb067e8ce552545a102ee6151c83f6fe7708767859bba2815b562592dccd5` |

On the gerber diff: B.Cu changes (the re-shape). In1 / In2 change only in line order (sorted
content equal). F.Cu changes in 13 lines of GND pour polygon start points, all outside the region. A
second build with the same fingerprint gives the same kind of difference (HEAD vs. the base rebuild: 44
lines). The zone fill is not bit-stable between builds, but the copper is the same.

Documents: Hardware.md "Routing" has a new bullet **R9 / J10 area** (the re-shape and why the other
shapes are necessary); totals 1022 → 1020 segments; non-camera density 2.75 → 2.74 per 10 mm (374 →
372 segments over 1359.7 mm). README: `simplify.py` step, `regiongap.py` / `netdiff.py` checks.
`tools/signal_sim` does not model `PIXRST_GATE`, and no simulated net changed, so no simulation was
run again.

## 8. Commits (fix/simplify-r9j10, on 6944e93)

- c2bb8c1 EuroCard S1: PIXRST_GATE B.Cu jog at R9/J10 re-shaped (simplify.py). Also includes
  `regiongap.py`, `netdiff.py`, `gapcheck.py`, the root board, gerbers and zip.
- (this report) EuroCard S1: SIMPLIFY_REPORT.md

Only one net was reshaped, so there is one reshape commit.

## 9. Recommendation

The R9 / J10 area had one unnecessary router jog (`PIXRST_GATE`). It is removed with the length and
vias unchanged. The other shapes there come from one necessary crossing and from the CH1 pulse lane.
To make `PWM_TRIG_TAP` straight, you would have to move the `PIXRST_GATE` crossing, and every such
move found puts copper closer to the lane or crosses copper. Before release, look at the area in the
KiCad GUI (B.Cu, x 202–212, y 50–78). Finding F2 (`LASER_EN_TAP` doglegs at U10) is the next
candidate of the same kind, if `LASER_EN_TAP` is put in scope.
