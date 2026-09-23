# PiDG — Hardware Reference (Pico 2 W, 4-layer)

Digital delay generator for PIV: distributes a 1 MHz sync and a camera trigger to six
cameras, and drives two 5 V laser trigger outputs with a settable inter-pulse delay.

This board is the Raspberry Pi Pico 2 W redesign of the original Teensy 4.1 design in
`../Chris Teensy Version/`. This document describes **only** the 4-layer Pico version.

**Status:** DRC 0 violations, ERC 0 violations. Not yet fabricated. Work through
[Open items](#open-items) before ordering.

---

## At a glance

| | |
|---|---|
| Board | 126 × 126 mm, 4 copper layers, 1.6 mm FR4 |
| MCU | Raspberry Pi Pico 2 W, socketed (not soldered) |
| Power | USB only, via the Pico's own connector |
| Logic rail | 3.3 V (cameras) / 5 V (lasers) |
| Design rules | 0.2 mm clearance, 0.2 mm track, 0.6/0.3 mm via, 0.25 mm copper-to-edge |
| Placeable parts | 44, plus 4 NPTH mounting holes |

Layer use:

| Layer | Purpose |
|---|---|
| F.Cu | signal + GND pour |
| In1.Cu | solid GND plane |
| In2.Cu | solid +5 V plane |
| B.Cu | signal + GND pour |

The 3.3 V rail has no plane — it is distributed as a 0.5 mm F.Cu trace.

Physical stackup (symmetric 1.6 mm, matching JLCPCB's standard 4-layer `JLC04161H-7628`):

| | Type | Thickness |
|---|---|---|
| F.Mask | solder mask | 0.010 mm |
| **F.Cu** | copper, 1 oz | 0.035 mm |
| dielectric 1 | prepreg, FR4 εr 4.5 | 0.2104 mm |
| **In1.Cu** | copper, ½ oz | 0.0152 mm |
| dielectric 2 | core, FR4 εr 4.5 | 1.065 mm |
| **In2.Cu** | copper, ½ oz | 0.0152 mm |
| dielectric 3 | prepreg, FR4 εr 4.5 | 0.2104 mm |
| **B.Cu** | copper, 1 oz | 0.035 mm |
| B.Mask | solder mask | 0.010 mm |

Total 1.586 mm of copper and dielectric, 1.606 mm over the mask — a nominal 1.6 mm board.

**Copper finish: lead-free HASL** (`HAL lead-free`) — RoHS compliant, and the cheapest
compliant option at most quick-turn fabs. It carries only a small premium over leaded HASL
and is far below ENIG, which is the usual paid upgrade.

Nothing here needs a flat surface: the finest pitch on the board is 0.95 mm (SOT-23-5), with
no BGA or fine-pitch QFN, so HASL's uneven deposit is a non-issue even at lead-free's
slightly worse flatness. It also suits the board's hand-assembly bias — every passive and SOT
uses a `_HandSolder` footprint variant, and HASL arrives pre-tinned and tolerates rework
better than OSP, whose coating degrades with repeated heat. A lead-free finish solders fine
with either leaded or lead-free solder, so it does not constrain how you assemble.

If a future revision adds a fine-pitch part, reconsider the finish at the same time.

Confirm these numbers against whatever your fabricator actually presses. Note that the gerber
job file reports the board size as 126.1 × 126.1 mm because Edge.Cuts extents include the
0.1 mm line stroke — the fabricated dimension is the centreline, **126.0 × 126.0 mm**.

---

## Socket pin mapping — read this first

The Pico plugs into two 1×20 sockets, **J14** (left row) and **J15** (right row), 17.78 mm
apart. The two rows do **not** number in the same direction:

```
J14 pad n  =  Pico physical pin n          (pads 1..20 -> pins 1..20)
J15 pad m  =  Pico physical pin (41 - m)   (pads 1..20 -> pins 40..21)
```

The Pico numbers like a DIP — down the left row from pin 1 to 20, then back **up** the right
row from 21 to 40 — so pin 40 (VBUS) sits physically opposite pin 1. Both socket footprints
on this board run pad 1 → pad 20 in the same +y direction, so the reversal lands entirely on
J15.

**Sanity check for any change here:** the Pico's ground pins pair to a constant sum
(3↔38, 8↔33, 13↔28, 18↔23, all summing to 41), so grounds land on pads 3, 8, 13 and 18 of
*both* sockets, directly opposite each other. If a proposed mapping doesn't line the grounds
up across the two rows, it is wrong.

> This is worth stating loudly because **neither ERC nor DRC can catch an error here.** The
> symbol is internally self-consistent, and U11 deliberately has no PCB footprint, so there
> is nothing for DRC to check. An earlier revision had J15 wired as `pad m = pin 20 + m`,
> which would have shorted the Pico's own 3V3_OUT to the ground plane and driven 5 V into two
> GPIOs. It was found only by checking pad nets against the physical pinout by hand.

### Connected socket pins

| Signal | Pico pin | Socket pad | Board net |
|---|---|---|---|
| GP10 | 14 | J14.14 | `PWM_1MHz` |
| GP11 | 15 | J14.15 | `PWM_Trig` |
| GP12 | 16 | J14.16 | `_PULSE_OUT_CH2` |
| GP13 | 17 | J14.17 | `_PULSE_OUT_CH1` |
| GND | 3, 8, 13, 18 | J14.3, .8, .13, .18 | `GND` |
| GND | 38, 33 (AGND), 28, 23 | J15.3, .8, .13, .18 | `GND` |
| 3V3_OUT | 36 | J15.5 | `+3V3` |
| VSYS | 39 | J15.2 | `+5V` |
| VBUS | 40 | J15.1 | `+5V` |

All eight module grounds are bonded. Every other socket pad is unconnected — and, once the
module is seated, physically inaccessible. There is no GPIO breakout header.

**The module body occupies roughly x 158–180, y 43–96 in board coordinates.** Nothing may be
placed there.

---

## Firmware pin map

`src/main.cpp` drives all four signals through PIO (pio0, state machines 0–3), so any GPIO
works — there is no PWM-slice constraint.

| Constant | GPIO | Board net | Drives |
|---|---|---|---|
| `kPinSync` | 10 | `PWM_1MHz` | U1 → U2 → Sync1‑6 |
| `kPinMarker` | 11 | `PWM_Trig` | J10.3 → (jumper) → U5 → U6 → Trigger1‑6 |
| `kPinCh2` | 12 | `_PULSE_OUT_CH2` | U8 → U13 → J8 (Laser 2) |
| `kPinCh1` | 13 | `_PULSE_OUT_CH1` | U7 → U13 → J7 (Laser 1) |

**CH1 is the higher GPIO and CH2 the lower** — the opposite order to the Teensy original
(D2 = CH1, D3 = CH2). Do not "tidy" these into ascending order.

These constants and the schematic have drifted apart once before, which made the whole board
look inert. `main.cpp` now carries this table as a comment block; keep both in step.

---

## Power

Everything is powered from the Pico's USB connector. There is no other supply input.

**+5 V** — from the Pico's VBUS (pin 40), with VSYS (pin 39) tied to the same net. This
deliberately shorts out the Pico's input Schottky, which the Pico 2 W datasheet (§3.4)
explicitly allows when USB is the only source; it recovers ~0.3 V that the laser driver
needs. Distributed on the In2.Cu plane. Consumers: U7, U8, U10, U12 (74LVC1G08), U13
(UCC27524) and the R2–R5 pull-ups. Decoupling C4, C5, C8, C9 (0.1 µF) + C10 (1 µF).

> **Constraint created by the VBUS/VSYS short:** never add an external 5 V feed to this net.
> It would back-feed the USB host with no diode in the way. If a bench-supply option is ever
> wanted, feed it through a Schottky into VSYS only, per the datasheet's ORing arrangement.

**+3.3 V** — from the Pico's 3V3_OUT (pin 36). Consumers: U1–U6, the entire camera-facing
logic bank. Decoupling C1, C2, C3, C6, C7 (0.1 µF). Worst-case board draw is ~3 mA against
the module's 300 mA guidance.

The 1.8 V rail and its LDO (U9) from the Teensy design are deleted. The cameras now see a
3.3 V swing. Nothing on this board presents 5 V to J1–J6.

---

## Signal chains

Each camera chain is two inversions deep, so it is non-inverting end to end, with one
dedicated gate per camera.

**Sync (1 MHz)**
`GP10` → U1.2 (74LVC1G04) → `SYNC_N` → U2 ×6 (SN74LVC04AD hex) → `Sync1..6` → J1–J6 pin 5

**Trigger**
`GP11` → J10.3 → *[J10 jumper]* → `PWM_TRIG_TAP` → U5.2 → `TRIG_N` → U6 ×6 → `Trigger1..6` →
J1–J6 pin 4

J10 selects the trigger source: a shunt on **2‑3** triggers the cameras from the reference
marker (normal), a shunt on **1‑2** triggers them from every laser CH1 pulse instead. J10.1
is the CH1 monitor tap.

> J10's silkscreen reads `MON / IN / OUT`, which mislabels pin 1 — it is not a monitor, it is
> the alternate trigger source. The Teensy board called it `PWM Trig. / Laser`. A shunt
> across all three pins shorts GP13 to GP11.

**Pixel reset** (no MCU involvement — pure hardware pass-through)
J12 BNC → `PIXRST_IN` (R5 3k3 pull-up to +5 V) → U12.2 → `PIXRST` → U3.2 → `PIXRST_N` →
U4 ×6 → `TDRSTN1..6` → J1–J6 pin 3

Idle high = reset de-asserted; pull the BNC low to assert. U12's other input
(`PIXRST_GATE_EN`) is hard-tied high through R4, so U12 is a buffer, not a gate — the hook
exists if gating is ever wanted. Note J12 idles at 5 V through R5; an external source must
sink ~1.5 mA to reach VIL.

**Laser outputs**
`GP13` → U7.2 → `CH1_GATED` → U13.2 (INA) → U13.7 (OUTA) → `CH1_DRIVE_RAW` → **R6 47 Ω** →
J7.1
`GP12` → U8.2 → `CH2_GATED` → U13.4 (INB) → U13.5 (OUTB) → `CH2_DRIVE_RAW` → **R7 47 Ω** →
J8.1

U13 is a TI UCC27524 dual 5 A driver, non-inverting, ENA/ENB hard-tied to +5 V. Its ~2 Ω
output plus the 47 Ω series gives a ~49 Ω source — a proper back-match to 50 Ω coax. The
Teensy drove the coax straight off a logic gate with no series element, mismatching the
source and exceeding the gate's 32 mA rating; this stage is a deliberate improvement.

U13 adds ~13–25 ns of propagation delay, common to both laser channels. Inter-pulse delay is
preserved to within the driver's channel-to-channel matching (1–2 ns). Laser-vs-camera skew
grows by that fixed, calibratable amount.

---

## Laser interlock

```
LASER_EN = AND( J11 jumper , EN tap )      -- U10, 74LVC1G08 on +5 V
J7 output = AND( LASER_EN , CH1 pulse )    -- U7
J8 output = AND( LASER_EN , CH2 pulse )    -- U8
```

| Node | Net | Notes |
|---|---|---|
| J11.1 | `LASER_EN_PU` | R2 3k3 to +5 V |
| J11.2 | `LASER_EN_JMP` | → U10.1, **R8 10k pull-down to GND** |
| J11.3 | `GND` | |
| U10.2 | `LASER_EN_TAP` | R3 3k3 to +5 V, also on J16.1 |
| U10.4 | `LASER_EN` | → U7.1, U8.1 |

**Fails safe.** R8 holds U10 pin 1 low when no jumper is fitted on J11, so the default state
is *disabled*. Fit a shunt on J11 **1‑2** to arm; **2‑3** inhibits. With the 1‑2 shunt fitted
R2 wins: 5 V × 10/(3.3+10) ≈ 3.76 V, well above the 74LVC1G08's 2.0 V VIH at VCC = 5 V.

The original Teensy design had no pull-down here and defaulted to *armed* with the header
empty. R8 is the one deliberate behavioural change to the interlock.

Disabling forces both BNC centre pins to 0 V: U10 low → U7/U8 outputs low → U13 outputs low.
The driver's ENA/ENB are tied high rather than wired to the interlock, so U13 adds no bypass
path — U10 retains sole authority.

---

## Connectors

**J1–J6 — cameras** (2×5 IDC, 2.54 mm). Identical to the Teensy design, pin for pin.

| Pin | Function |
|---|---|
| 1 | NC |
| 2, 7 | GND |
| 3 | `TDRSTNn` — pixel reset, active low |
| 4 | `Triggern` |
| 5 | `Syncn` — 1 MHz |
| 6, 8, 9, 10 | NC |

All 3.3 V. No supply rail is presented to the camera.

**BNC, 50 Ω** — J7 Laser 1 (out), J8 Laser 2 (out), J12 Pixel Reset (**in**). Shells on GND.

**Headers**

| Ref | Type | Pins |
|---|---|---|
| J10 | 1×3 vertical | 1 `_PULSE_OUT_CH1` (CH1 monitor) · 2 wiper → U5 · 3 `PWM_Trig` |
| J11 | 1×3 vertical | 1 pull-up · 2 → U10.1 · 3 GND |
| J16 | 1×3 right-angle, right edge | 1 `LASER_EN_TAP` · 2 `PWM_TRIG_TAP` · 3 GND |
| TP3 | 1×2 right-angle, top edge | 1 `PWM_1MHz` · 2 GND |
| TP4 | 1×2 vertical | 1 `_PULSE_OUT_CH2` · 2 GND |

> **J16 is probe-only — never fit a shunt.** A shunt on pins 2‑3 grounds `PWM_TRIG_TAP`,
> which via J10's selector shorts a GPIO straight to ground and silently kills all six camera
> triggers.

TP3 and TP4 are scope points with a local ground pin. External drive on the TRIG and 1 MHz
taps needs **VIH ≥ 2.0 V, VIL ≤ 0.8 V** (5 V tolerant). This threshold rose from ~1.2 V when
the logic bank moved from 1.8 V to 3.3 V — a 1.8 V or 2.5 V source that worked on the Teensy
board will now read as a permanent low.

**MH1–MH4** — M3, NPTH, mechanical only.

---

## Open items

Ordered by what would bite hardest.

1. **Measure the lasers' trigger input impedance, then confirm R6/R7.** Into a high-impedance
   input the 2.5 V launched wave doubles at the open end to a clean 5.0 V and 47 Ω is
   correct. Into a genuinely 50 Ω terminated input the divider yields only ~2.51 V, which
   clears 5 V TTL VIH by 0.5 V and fails 5 V CMOS outright. Source termination cannot deliver
   full rail amplitude into a matched load. If the input is terminated, either raise U13's
   VDD to ~10 V keeping R6/R7 near 50 Ω, or accept 2.5 V against the laser's datasheet. Do
   not silently drop R6/R7 to 0 Ω — that throws away the match. If terminated, also respec
   R6/R7 as 1206 or 250 mW (≈122 mW at 100% duty against a 125 mW 0805).
2. **Scope U13 pin 6 under load.** The UCC27524 wants VDD ≥ 4.5 V with UVLO ~4.2 V, and the
   rail is raw USB VBUS. USB 2.0 permits 4.40 V at the far end of a cable. Below UVLO both
   laser outputs go dead with no indication. Use the cable and port you will deploy with.
3. **No antenna keepout under the module.** All four copper layers run solid beneath the
   Pico, including its on-board antenna. Wi-Fi will be detuned. Harmless for the current
   USB-serial firmware, but if wireless is ever wanted the keepout must be cut on all four
   layers *before* fabrication — it cannot be fixed after.
4. **C6 and C7 are stranded.** They were re-netted from the deleted 1.8 V rail onto +3V3 but
   never moved, so they sit ~13 and ~20 mm from the nearest IC and bypass nothing in
   particular. U2, U4 and U6 — the hex inverters that actually source current into six
   ribbon cables each — have no local cap, only a shared one 8–9 mm away. Inherited from the
   Teensy layout, but it matters more at 3.3 V. Moving C6 next to U2 and C7 next to U4, and
   adding a sixth 0.1 µF at U6, costs nothing before fab.
5. **+5 V bulk is light for the new pulsed load** — C10 (1 µF) plus four 0.1 µF. Roughly
   100 mA for a ~2 µs pulse out of 1 µF is ~200 mV of droop. A 10 µF X7R beside C10 directly
   protects pulse-amplitude flatness, which is the parameter this instrument exists to
   deliver.
6. **No 50 Ω termination on the J12 pixel-reset input** — only R5's 3k3 pull-up and a CMOS
   input. Inherited from the Teensy. If the reset source is a 50 Ω driver over any
   appreciable coax this will ring, and a large enough reflection could double-trigger. A
   49.9 Ω shunt at J12 would fix it, but would fight the pull-up and force the source to hold
   the idle level.
7. **No series termination on the 18 camera lines.** At 3.3 V with ~10–15 Ω drivers into
   ~100 Ω ribbon, far-end overshoot can transiently exceed 5 V at a camera pin. Accepted —
   the cameras tolerate it. 33–47 Ω at the U2/U4/U6 outputs is the fix if that ever changes;
   terminating just the six Sync lines would cover most of it, since that is the only
   continuous 1 MHz signal.
8. **Correct J10's silkscreen** at the next revision — see the Trigger section above.

---

## Files

| Path | What |
|---|---|
| `PiDG_Pico.kicad_sch` | schematic |
| `PiDG_Pico.kicad_pcb` | board |
| `PiDG_Pico_BOM.csv` | BOM (hand-maintained; `export_bom` ignores DNP attributes) |
| `PiDG_Pico_CPL.csv` | pick-and-place, 44 parts, mounting holes excluded |
| `libs/PiDG_Local.kicad_sym` | Pico 2 W and UCC27524 symbols |
| `libs/PiDG_Local.pretty/` | `*_EdgeTrim` footprint variants (see below) |
| `libs/RPi_Pico.pretty/` | official RPi castellated module footprint (unused — board is socketed) |
| `../src/main.cpp` | firmware |

**About the `*_EdgeTrim` footprints.** J16 and TP3 overhang the board edge, so their stock
silkscreen outlines run off the board and trip `silk_edge_clearance`. The variants in
`libs/PiDG_Local.pretty/` are the stock footprints with that off-board silk clipped —
**identical part, identical pads, silkscreen only.** Order the standard parts; the CPL
carries the stock package names for exactly that reason. If you ever re-trim silk on another
overhanging connector, make a variant the same way rather than editing the board footprint in
place, or you will trade a `silk_edge_clearance` warning for a `lib_footprint_mismatch` one.

**Regenerating checks.** DRC from Pcbnew; ERC via
`kicad-cli sch erc --format json PiDG_Pico.kicad_sch`. Note that the ERC JSON reports every
coordinate and length at 1/100 of the true mm value despite declaring `"coordinate_units":
"mm"` — multiply by 100.

**Avoid "Update PCB from Schematic"** unless you disable footprint creation. U11 has no board
footprint by design, and a sync will try to place one.
