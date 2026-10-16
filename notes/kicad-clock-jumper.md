# KiCad task: clock jumper (300 MHz overclock)

Notes for a later session. The firmware side is done (branch `overclock-jumper`): `src/clock_mode.*`,
`kPinClockSel = 10` in `src/board.h`, and the "Clock jumper (planned)" section in `Hardware.md`. The
board files (schematic, PCB, BOM, CPL, gerbers) are **not** changed yet. Until they are, GP10 is open,
the firmware reads it as "no shunt", and the board runs at the rated 150 MHz.

## What the firmware expects

- **Net `CLK_SEL`** on **GP10 = Pico pin 14 = J14 pad 14**. (J14 pad n = Pico pin n. Check it with
  the ground rule in `Hardware.md`, "Socket pin mapping": Pico pin 13, next to it, is GND = J14 pad 13.)
- **A 2-pin header, pin 1 = `CLK_SEL`, pin 2 = GND.** Shunt fitted = 300 MHz. Open = 150 MHz.
- The firmware enables the internal pull-up on GP10, then reads the pin twice, 100 µs and 200 µs
  later. Both reads LOW = shunt fitted. It reads once per boot (`readJumper()` in
  `src/clock_mode.cpp`).
- **Do not put a capacitor on `CLK_SEL`.** With the shunt open, the pin starts at 0 V (the pad's
  default pull-down) and charges through the pull-up. It reaches a HIGH level (about 2 V of 3.3 V)
  after about one RC time constant. With an RC of 100 µs or more, both reads could still be LOW,
  which reads as "fitted" and overclocks the chip. Without a capacitor the RC is around 1 µs or less.

## Proposed parts

| Ref | Part | Footprint | LCSC | Note |
|---|---|---|---|---|
| J20 | Pin header 1x02, 2.54 mm, vertical | `Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical` | C32713268 | Same part as TP4. J9 and J13 are also unused; J20 avoids reusing a number. |
| R29 (optional) | 10k | `Resistor_SMD:R_0805_2012Metric_Pad1.20x1.40mm_HandSolder` | C17414 | `CLK_SEL` to +3V3. Same part as R8/R9/R17/R18/R24. The internal pull-up is enough for a short trace; R29 makes the level stiffer against noise. R1, R4, R11, R14 and R15 are also unused. |
| shunt | 2.54 mm 2-pin jumper shunt | – | C100114 | Loose part, not placed. The BOM "(loose)" count goes from 4 to 5. |

## Placement and routing

- The Pico module covers about x 158–180, y 31–82 (silkscreen outline x 158.405–179.405, bottom at
  y 82.43). Nothing may be placed there, and the socket pads are out of reach once the Pico is seated.
  So J20 must sit **outside** that area.
- J14 origin (pad 1) is at (160.015, 32.385), pitch 2.54 mm downward: **pad 13 (GND) at
  (160.015, 62.865), pad 14 (GP10) at (160.015, 65.405).**
- There is room to the left of J14: the board edge is at x = 132, R18 is at (155.3, 70.485) and R17
  at (155.3, 73.025). A candidate spot for J20 is about (153, 64). Check copper, zones and the
  existing traces there first.
- Route `CLK_SEL` as a short top-layer trace from J14 pad 14 to J20 pin 1. Connect J20 pin 2 to GND
  with a via to the ground plane.
- Silkscreen at least 1.0 mm high (`Hardware.md`, Manufacturing notes), for example
  `CLK  FIT = 300 MHz (OVERCLOCK)  OPEN = 150 MHz`.

## Files to update

1. `PiDG_Pico.kicad_sch`: put a `CLK_SEL` label on U11 GP10 (pin 14) and add J20 (and R29 if
   used). Run ERC: 0 violations, as now.
2. `PiDG_Pico.kicad_pcb`: update from the schematic, then place, route and run DRC (0 violations).
3. `fab/gerbers/` and `fab/PiDG_Pico_Gerbers.zip`: plot again, with the drill files.
4. `fab/PiDG_Pico_BOM.csv`: add a J20 line (keep TP4's line as it is), add R29 to the 10k line if
   used (count 5 → 6), set the "(loose)" shunt count from 4 to 5 and add J20 to its note, and add a
   NOTE line for J20 (polarity, and "leave open unless the Pico passed the soak test").
5. `fab/jlc/PiDG_Pico_JLC_BOM.csv`: add J20 to the C32713268 line (`TP4,J20`), and R29 to the C17414
   line if used.
6. `fab/jlc/PiDG_Pico_JLC_CPL.csv`: run `tools/jlc_cpl` (`kpads.py`, then `node jlc_rot.js`), copy
   `cpl_new.csv`, and check J20 in `rot_report.txt` and in JLC's placement preview. Pin headers
   sometimes come out mirrored; see that tool's README.
7. `fab/jlc/JLC_ORDER.md`, "on delivery", step 3 (jumpers): J20 stays open (150 MHz) unless that Pico
   has passed the soak test.
8. `Hardware.md`:
   - "Connected socket pins": GP10 row, remove "planned, not yet in the KiCad files". Also update
     "Every other socket pad is unconnected".
   - "Firmware pin map": `kPinClockSel` row, remove "(planned)" and the open-pad remark.
   - Rename the heading "Clock jumper (planned): 300 MHz overclock", e.g. to
     "Clock jumper (J20): 300 MHz overclock", and remove its "Not on the board yet" paragraph.
     **Update every link to its anchor** `#clock-jumper-planned-300-mhz-overclock`: they are in
     `README.md` and `Hardware.md` (`grep -rn clock-jumper-planned`).
   - The connector list (`## Connectors`), the silkscreen note in "Manufacturing notes" (add J20 to
     "J10, J11, J16, J18 and J19 are labelled"), and first-board check 6.
9. `README.md`: add J20 to the jumper table ("Shunt fitted: 300 MHz overclock", "No shunt: 150 MHz"),
   turn the "Planned: clock jumper" paragraph into J20's description, and update the "What it does"
   bullet ("planned, not on the board yet").
10. `src/board.h`: in the `kPinClockSel` row, remove "(planned)" and the "NOT YET IN THE KICAD FILES"
    lines, and update the "GP10 ... is the planned clock jumper" line.
11. Finally, `grep -rn -i "planned\|kicad-clock-jumper" --include=*.md --include=*.h --include=*.cpp .`,
    fix every hit, then delete this file (and the `notes/` row in the README "Repository layout" if
    the folder is then empty).

## Checks on the first board

- Continuity: J20 pin 1 to Pico pin 14 (GP10), J20 pin 2 to GND, and no short between them with the
  shunt off.
- No shunt: `STATUS` shows `CLK=150000000` and `CLKMODE=STANDARD`. Shunt fitted, power-cycled:
  `CLK=300000000`, `CLKMODE=OVERCLOCK (jumper fitted)` and `VREG_MV=1300`.
- Then the soak test in `Hardware.md`, "Clock jumper".

## Design notes

- **Polarity.** A pulled-up input with the shunt to GND is the usual way, and needs no +3V3 on the
  header. Open = rated clock, so a lost shunt is safe. A short from `CLK_SEL` to GND (for example a
  solder bridge) reads as "fitted". `STATUS` and the start-up line always show the clock mode, so an
  unintended overclock is visible.
- **GP10 is not an HSTX pin** (HSTX is GP12–GP19), so this does not take a pin from the
  `hstx-bench` work.
