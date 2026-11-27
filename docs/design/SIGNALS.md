# PiEBV design: signals

This page gives the analysis of the signal chains: the camera chains and the Sync routing, the
trigger source and the CH1/CH2 skew, the pixel reset, the laser outputs with the amplitude budget
and the output mode, External Sync Out timing, the camera line series resistors, the laser
interlock and the status LED circuits.
Back to: [hardware reference](../../Hardware.md) · [design notes index](../DESIGN_NOTES.md)

---

## Camera signal chains

Each camera signal passes through two inversions, so it arrives the right way up, with one
dedicated gate per camera.

**Sync (1 MHz)**
`GP15` (clk_gpout1) → U1.2 (74LVC1G04) → `SYNC_N` → U2 ×6 (SN74LVC04AD hex) → `Sync1..6` → R52–R57 (47 Ω) → `Sync1_C..6_C` → J1–J6 pin 5
(U1 and U2 on `+VCAM`)
(TP3 taps `PWM_1MHz`). On the board, `PWM_1MHz` is 83.7 mm of 0.5 mm track, nearly all on B.Cu,
with 1 via. `PWM_1MHz` and `SYNC_N` stay at least 21.70 mm from the laser pulse lanes. Gaps of
`PWM_1MHz` (edge to edge on one layer, tracks and vias; `tools/eurocard/netgap.py`): 1.90 mm to
`SYNC_N`, which carries the same 1 MHz sync; 0.232 mm to a GND via
on In2.Cu at (194.84, 87.25), 0.888 mm to a +VCAM track (the buffer supply copper), 2.03 mm to a +5V via. Counting pads too:
0.28 mm to U1's unused pin 1 (next to its input, pin 2), 0.872 mm to C1.1 (+VCAM), 1.58 mm from
the J14.20 pad to a `PWM_Trig` track and 2.20 mm to J20.1 (`CLK_SEL_JMP`). The gaps from
`PWM_1MHz` to the camera lines were not measured again after the new camera routing.

**Trigger**
`GP11` → J10.3 → *[J10 jumper]* → `PWM_TRIG_TAP` → U5.2 → `TRIG_N` → U6 ×6 → `Trigger1..6` →
R58–R63 (47 Ω) → `Trigger1_C..6_C` → J1–J6 pin 4. `PWM_TRIG_TAP` also drives U19.2, the [External Sync Out](#external-sync-out-j12)
channel to J12.

## Trigger source (J10)

J10's silkscreen reads **`CH1 / TRG / MKR`** (pins 1/2/3).

- **2-3 (TRG to MKR, normal):** the cameras are triggered by the marker, which rises with CH1 and
  has its own `MARKERWIDTH`.
- **1-2 (TRG to CH1):** the cameras are triggered by every laser CH1 pulse. Prophesee specifies a
  500 ns minimum trigger pulse, so this is only dependable with `WIDTH` ≥ 500 ns. CH1 pulses exist
  only while ARMED, so with the lasers disarmed 1-2 gives the cameras no trigger (use 2-3, or arm
  with J11 on 2-3, for camera-only work).
- **Never fit a shunt across all three pins:** that ties GP13 (through R19) to GP11.

J10.1 reaches `_PULSE_OUT_CH1` through **R19 (100 Ω)**; it idles LOW while DISARMED. R19
is there for the laser timing. Without it, the 1-2 shunt would hang the whole `PWM_TRIG_TAP` net
(U5, R9, U19 and 73.2 mm of trace) directly on the CH1 GPIO. The transmission-line simulation
in `tools/signal_sim` (169 ngspice runs on the final routing; typical corner, 4 mA GPIO in the
table) puts CH1 behind CH2 at U7/U8
by the values below. On the 126 mm layout (unequal laser pulse lanes) the 2-3 row was 0.22 / 0.25 ns
and the 1-2 row 0.38 / 0.42 ns; the equal-length lanes remove most of that.

| J10 | With R19 (100 Ω) | Without R19 |
|---|---|---|
| 2-3 or open | 0.001 / 0.007 ns (rise / fall), up to 0.025 ns | 0.016 / 0.013 ns, up to 0.037 ns |
| 1-2 | 0.20 / 0.21 ns, up to 1.26 ns at the GPIO and threshold corners | 0.57 / 0.71 ns, up to 2.01 ns |

With J10 on 2-3, the small remaining skew comes from the R17 and R19 stubs on `_PULSE_OUT_CH1`
(`_PULSE_OUT_CH2` has only R18). With J10 on 1-2, CH1 is later because the J10/R19 branch loads
`_PULSE_OUT_CH1`.

So with J10 on 1-2 the laser delay error depends on the jumper even with R19. R19 cuts it by about
65–70 % at the typical corner and by about 37 % at the worst corner. With J10 on 1-2, at J7/J8 it
is 0.18–0.31 ns with R19 and 0.51–1.49 ns without, before U13's own channel matching (1 ns typical,
2 ns maximum), which is larger. R19 costs the camera trigger and
J12 0.75–1.65 ns of edge, which doesn't matter there. Keep R19.

**With no shunt fitted, R9 (10 k) pulls `PWM_TRIG_TAP` low,** so all six camera triggers and J12
idle low instead of following a floating input on 73.2 mm of trace. 10 k, rather than a weaker
pull-down, holds U5's 1.8 V input at ≤ 0.05 V even at worst-case input leakage, and loads the
selected GPIO by only 330 µA.

## Pixel reset (Pico only)

`GP16` → `PIXRST_GATE` → U3.1 and U3.2 (**74LVC1G00** NAND, on `+VCAM`, both inputs joined) →
`PIXRST_N` → U4 ×6 (`+VCAM`) → `TDRSTN1..6` → R64–R69 (47 Ω) → `TDRSTN1_C..6_C` → J1–J6 pin 3. R24 (10 k) pulls `PIXRST_GATE` up to +3V3.

**The Pico is the only source.** With both inputs on `PIXRST_GATE`, U3 is an inverter, so after U4
the cameras get TDRSTN = `PIXRST_GATE` (active low at the camera: `0 = pixels in reset`). The gate
idles high (R24 before the firmware runs, then the firmware drives it high while `:PIX:GATE` is `OFF`), so
the cameras run unless the firmware asserts the reset. GP16 drives U3 directly at 3.3 V; U3's inputs
are 5.5 V-tolerant at any supply (VIH 1.17 V at 1.8 V, 2.0 V at 3.3 V). The firmware side is under
[Pixel-reset gate](FIRMWARE_HW.md#pixel-reset-gate-pixgate).

## Laser outputs

```
GP13 → U7.2 → CH1_GATED → U13.2 (INA) → U13.7 (OUTA) → CH1_DRIVE_RAW → R6 68 Ω 2 W → CH1_DRIVE → output mode (J18, R25, R27) → CH1_OUT → J7.1
GP12 → U8.2 → CH2_GATED → U13.4 (INB) → U13.5 (OUTB) → CH2_DRIVE_RAW → R7 68 Ω 2 W → CH2_DRIVE → output mode (J19, R26, R28) → CH2_OUT → J8.1
```

**U7 and U8** are **74AHCT1G08** AND gates on +5 V (the interlock gates; see
[Laser interlock](#laser-interlock)). AHCT has TTL input thresholds (high above 2.0 V), so the
Pico's 3.3 V pulses drive them with ~1.3 V of margin. An LVC gate here would need
0.7 × VCC = 3.5 V to read high, which a 3.3 V GPIO can't guarantee.

**U13** is a TI UCC27524 dual 5 A gate driver, non-inverting, on **VDD = +12V**, with ENA/ENB on
`LASER_PWR_OK` (see [Power-good gate](POWER.md#power-good-gate-u18)). Its inputs are TTL-compatible at any
VDD (high above 1.8–2.3 V, 1 V of hysteresis), so the 5 V AHCT gates drive it directly. Output
pull-up resistance (ROH, the PMOS side that holds a steady load high during a pulse) is **5 Ω typical,
8.5 Ω maximum** for this SOIC-8 (D) package, with no minimum given (TI SLUSFA9; the 2.5 / 5 / 7.5 Ω
often quoted is the DSD package's figure). The budget below takes 0–8.5 Ω; pull-down (ROL) is 0.6 Ω typical, 1.1 Ω maximum (D package), so the low level into 50 Ω is well under the LDP-V's
0.2 V limit.

Its local bypass capacitor **C9 (0.1 µF, 50 V)** sits right beside VDD (pin 6) with its own GND
via, and GND (pin 3) drops straight to the In1 ground plane through a via under the package. That
keeps the supply loop to roughly 1.5–2 nH, so the ~100 mA, few-ns output edges don't bounce VDD into
the top of the pulse. C10 (10 µF) is the bulk reservoir.

U13 adds 17 ns typical, 27 ns maximum of delay (TI SLUSFA9, D package; no minimum is given. The
older die gives 6 / 13 / 23 ns. JLC's listing quotes older-die input thresholds, so the die on the
reel is not known). The delay is the same on both laser channels to within its channel-to-channel
matching (1–2 ns), so the delay between the lasers is preserved. The laser-to-camera timing shifts
by that fixed, calibratable amount.

### Amplitude budget

For 50 Ω mode (J18/J19 on 1-2). The target loads are PicoLas LDP-V 10-70 and LDP-V 240-100
drivers, whose trigger inputs are **50 Ω terminated** and need **4.5–5.2 V high, ≤ 0.2 V low**.
U13's output, R6/R7 and the 50 Ω input form a voltage divider, so the level delivered is
VDD × 50 / (50 + R6 + ROH), where ROH is U13's output resistance:

| Corner | VDD | R6 (68 Ω ±1 %) | ROH | Into 50 Ω |
|---|---|---|---|---|
| Low | 11.54 V (ADJ 588 mV, divider −0.2 %) | 68.68 Ω | 8.5 Ω | **4.54 V** |
| Typical | 11.79 V | 68 Ω | 5 Ω | 4.79 V |
| High | 12.05 V (ADJ 612 mV, divider +0.2 %) | 67.32 Ω | 0 Ω | **5.14 V** |

Every corner passes, with ~0.8 % margin at the low end and ~1.2 % at the high end. Rev 2: each output
also drives its activity-LED sense divider (14.7 kΩ, 0.8 mA while high), which lowers the level by
1.6 mV (typical) to 2.4 mV (low corner): 4.534 V at the low corner, 0.76 % above 4.5 V
(`tools/signal_sim/results_rev2.md`, case 4). R12 = 100k
(11.8 V) centres the window for this ROH range: The UCC27524 DSD package (ROH 2.5–7.5 Ω) would give
~2.5 % at both ends, but its minimum pulse width (25 ns max) and channel matching (4 ns max) break
the 20 ns WIDTH and the 1–2 ns matching, so the D package stays. Its current die (SLUSFA9) needs an
input pulse of 10 ns typical, 15 ns maximum. The older D-package die needed 15 / 25 ns, and the die
on the reel is not known (see above): check that a 20 ns WIDTH reaches J7/J8 at full height on the
first board ([first-board check 1](../FIRST_BOARD_CHECKS.md#first-board-checks)); TI only guarantees an output above 1.5 V
into 1.8 nF at the minimum pulse. With the clock jumper (300 MHz) the shortest WIDTH, 10 ns, is
below the maximum of either die (15 / 25 ns), so it can be lost or shortened; use WIDTH ≥ 20 ns (≥ 30 ns for an older die) at the outputs. The same
applies to MARKERWIDTH at J12, through U19. The budget assumes a 50 Ω termination at the
driver; a load 1 % high adds ~0.6 %. The trace drop from U17 to U13 was a few mV on the 126 mm
layout (not re-calculated for the EuroCard routing). With 1 % divider
resistors the corners would sit only ~0.7 % inside the window, which is why R12/R13 are 0.1 %.

### Output mode

J18 sets the mode for J7, J19 for J8 and J21 for J12 ([External Sync Out](#external-sync-out-j12),
same circuit with R30/R31/R32). Between R6/R7 and each BNC:

```
CHn_DRIVE ──┬── R25/R26 47 Ω 2 W ──┬── CHn_OUT ── BNC centre pin
            │                      │
        jumper pin 1          jumper pin 2        jumper pin 3 ── CHn_TERM ── R27/R28 82 Ω 2 W ── GND
```

- **Shunt on 1-2 (50 Ω mode)** shorts out the 47 Ω, so the output is exactly the circuit budgeted
  above: a ~73 Ω source.
- **Shunt on 2-3 (Hi-Z mode)** leaves the 47 Ω in series and adds the 82 Ω resistor to ground. The
  output is then a source of VDD × Rp / (R6 + ROH + Rx + Rp) behind (R6 + ROH + Rx) ∥ Rp, where Rx is
  the 47 Ω and Rp the 82 Ω. Over every corner of VDD, ROH and the 1 % resistors:

  | | Low | Typical | High |
  |---|---|---|---|
  | Open circuit | 4.55 V | 4.79 V | 5.08 V |
  | Into 10 kΩ | 4.53 V | 4.76 V | 5.05 V |
  | Source impedance | 47.4 Ω | 48.7 Ω | 49.8 Ω |
  | Into 50 Ω (wrong mode for an LDP-V) | 2.29 V | 2.43 V | 2.59 V |

  **Why both resistors.** With the source 0.4–5.2 % below the coax's 50 Ω, the first edge reaching an
  unterminated input is 1.00–1.03 × the final level, whatever the cable length. With a scope's
  1 MΩ ∥ 15 pF at the end of the cable, the simulation gives 1.4–4.1 % overshoot (5.28 V peak at the
  high corner) and −0.21 V undershoot, settled within 2 % after 13 ns (1 m) or 33 ns (3 m). That is
  the J12 circuit; J7/J8 are the same circuit. At the 47.4 Ω source corner, not simulated, the
  overshoot could reach ~4.7 %, with the peak still ~5.25 V. A simpler version, just a 51 Ω resistor
  to ground with no series resistor, would be a ~30 Ω source and overshoot by ~25 %, to about 6 V, on any cable longer than the edge.
- **No shunt:** the 47 Ω in series and no resistor to ground, so ~12 V open circuit and
  3.35–3.66 V into 50 Ω. Always fit a shunt.
- **Dissipation in Hi-Z mode** (all 2 W 2512 parts): R27/R28 at most 0.31 W while high; R25/R26 at
  most 0.18 W while high into an open circuit, 0.32 W into 50 Ω, and 0.52 W stuck high into a
  short. The supply current while high is ~60 mA per output, against ~96 mA in 50 Ω mode.
- **Layout.** The 47 Ω resistor sits in line on the BNC centre-pin row, with jumper pin 2 on the same
  trace; pin 1 loops back over the resistor to `CHn_DRIVE`, and the 82 Ω resistor and its GND via
  sit beside the jumper. In Hi-Z mode that loop is an unterminated stub of ~14 mm, far too short to
  matter at these edge rates. From the 47 Ω resistor onward the two channels are mirror images about
  the line between the J7 and J8 centre pins. R6 and R7 are not symmetric about that line, so CH1's
  trace from R6 takes larger 45° corners to make up the difference: U13 to the 47 Ω resistor is
  19.593 mm on both channels, and so is every path on to the BNCs, in both modes. The silkscreen
  reads `LASER n OUT`, with `50Ω` and `HiZ` beside the pin pairs. In the EuroCard re-layout the
  whole output block (U7, U8, U13, J7, J8, J12, U19, J18, J19, J21 and their resistors and
  capacitors) moved as one rigid block (moved, not turned), with its hand-routed copper unchanged,
  so these lengths are unchanged (U13 output to 47 Ω resistor 19.59 mm, 47 Ω resistor to BNC
  11.90 mm, on both channels).

> **Match the output mode to the load.** In 50 Ω mode an open-circuit or high-impedance load sees
> ~12 V; use Hi-Z mode for those.
>
> **One driver per output, no BNC tees.** A transmission-line simulation (typical corners, 50 Ω
> mode) gives: J7 and J8 joined into one 50 Ω input → 3.4 V per pulse (the idle channel's 68 Ω sinks
> half), and 6.9 V where the pulses overlap (DELAY < WIDTH), above the LDP-V's 5.2 V damage limit;
> one output teed to two drivers → 3.0 V each. The PiEBV itself survives either (see
> [Board output rating](POWER.md#board-output-rating)).
>
> PicoLas's acceptance test applies: a scope with **50 Ω input termination** must read 0 to
> ~4.9 V. The LDP-V's absolute maximum on its trigger input is 15 V, so an unterminated reflection
> can't exceed it.

## External Sync Out (J12)

```
PWM_TRIG_TAP → U19.2 (INA) → U19.7 (OUTA) → EXT_SYNC_DRIVE_RAW → R30 68 Ω 2 W → EXT_SYNC_DRIVE → output mode (J21, R31, R32) → EXT_SYNC_OUT → J12.1
```

J12 gives other equipment a copy of the camera trigger: the marker with J10 on 2-3, every CH1 laser
pulse with J10 on 1-2 (see [Trigger source](#trigger-source-j10)). It is high while the cameras'
trigger lines are high, and low while `PWM_TRIG_TAP` is low, including with no shunt on J10.

- **Same circuit as a laser output.** U19 is a second UCC27524 on +12V; only channel A is used
  (INB tied to GND, OUTB open). R30 (68 Ω), R31 (47 Ω), R32 (82 Ω) and J21 are the values of R6,
  R25, R27 and J18, so the [amplitude budget](#amplitude-budget) and the
  [output-mode table](#output-mode) apply unchanged: J21 on 1-2 gives 4.53–5.14 V into 50 Ω, J21
  on 2-3 gives 4.55–5.08 V open circuit from a 47–50 Ω source. Ship with J21 on 1-2.
- **Power.** U19's ENA/ENB are on `LASER_PWR_OK` and its VDD on +12V, so J12 is live only with a
  15 V PD charger on J17; on the Pico's USB alone it stays at 0 V. C21 (0.1 µF) sits beside U19 pin 6
  with its own GND via, and C22 (10 µF) is its reservoir, as C9/C10 are for U13.
- **Not gated by the laser interlock.** Arming and J11 act only on the laser pulses (U7/U8). With
  J10 on 2-3, J12 keeps pulsing while the lasers are disarmed, as the camera triggers do.
- **Timing: measure the offset to the cameras on each board.** J12 follows GP11 through U19, and
  the camera trigger lines through U5 and U6, so the two are offset by a fixed delay that the
  datasheets don't pin down. From the GP11 edge, simulated in `tools/signal_sim` (4 mA default
  drive, J10 on 2-3, J21 on 1-2, J12 into 50 Ω; min / typ / max over the datasheet corners;
  re-run on the final EuroCard routing):

  | Path | Rising edge | Falling edge |
  |---|---|---|
  | GP11 → J12 (U19 + R30/J21 + ~4 ns of GP11 edge to U19's threshold) | 10.3 / 21.5 / 33.7 ns | 9.7 / 20.9 / 32.2 ns |
  | GP11 → Trigger1–6 at J1–J6 pin 4 (U5 + U6, mean of the six) | 6.9 / 11.0 / 19.4 ns | 7.4 / 11.4 / 19.9 ns |
  | **J12 minus camera trigger** | **−8.5 / +10.5 / +26.3 ns** | **−9.4 / +9.5 / +24.1 ns** |

  The offset limits are not the difference of the rows above: both paths share the GP11 corner, and
  the extremes pair a fast U19 with slow U5/U6 or the reverse. The range is wide because U19
  (6–27 ns; TI gives no minimum, 6 ns is the older die's) and U5 + U6 (4–15.5 ns) spread
  independently. The typical value uses U19's 17 ns, which TI specifies at TJ = 125 °C; TI's 25 °C
  curves read 16–16.5 ns rising and 18–19 ns falling, so the typical offset may be about 1 ns less
  on the rising edge and up to 2 ns more on the falling edge. With an older-die U19 (13 ns typical)
  the typical offset is +6.6 ns rising, +5.4 ns falling. If the GP11 pad sits at its datasheet
  VOH/VOL limit, J12 can reach 38.6 ns (39 ns on the 126 mm layout, where the offset then spanned
  −10.9 to +31 ns; that span was not re-computed). On one board the offset is fixed: measured once ([first-board check 4](../FIRST_BOARD_CHECKS.md#first-board-checks)),
  it holds to about 0.5 ns, plus 1–2 ns over temperature (estimates). It depends on the jumpers:
  J10 on 1-2 adds about +0.83 ns (rising edge; −0.20 ns falling), and J21 in Hi-Z mode about
  +0.65 ns rising / +0.63 ns falling, so measure each
  setting you use. The six trigger lines are length-matched from U6's outputs to the series
  resistors R58–R63 (43.584 mm each, then 9.77 mm from each resistor to its header pin; the
  `TRIG_N` fan-out to U6's inputs is not matched) and arrive within
  0.04–0.06 ns of each other in the simulation (up to 0.3 ns on the 126 mm layout).

- **Duty and loads.** J12 is high at most 50 % of the time, the firmware's MARKERWIDTH limit (67 %
  with J10 on 1-2 and `:OUTP:COMB ON`; see [Board output rating](POWER.md#board-output-rating)); don't short it. One load per output, no BNC tee,
  as for the laser outputs.
- **Layout.** J21, R31 and R32 copy the Laser 1 block 40 mm lower, on J12's centre-pin row, and
  U19, C21, C22 and R30 copy U13's layout. These parts are in the rigid output block (see the
  laser [Output mode](#output-mode) layout). The +12V and `LASER_PWR_OK` runs to U19 are autorouted
  (`LASER_PWR_OK` has 88.2 mm of track on B.Cu). The silkscreen reads `EXT SYNC OUT`, with `50Ω` and
  `HiZ` beside J21. The `J12-TRIG OFFSET (MEASURED)` field (boxes for RISE and FALL in ns, and the
  J10/J21 setting) is in the left area of the board, below TP3 (no longer below J12). It takes the
  hand-written result of [first-board check 4](../FIRST_BOARD_CHECKS.md#first-board-checks).

---

## Camera line series resistors

**Series resistors in the camera lines (Rev 2).** Each camera line has a 47 Ω resistor (1 %,
0805, LCSC C17714) on the board, between the buffer output and the camera header pin:

| Resistors | Lines | From | To |
|---|---|---|---|
| R52–R57 | `Sync1`–`Sync6` | U2 | J1–J6 pin 5 |
| R58–R63 | `Trigger1`–`Trigger6` | U6 | J1–J6 pin 4 |
| R64–R69 | `TDRSTN1`–`TDRSTN6` | U4 | J1–J6 pin 3 |

The net on the buffer side keeps its name (`Sync1` … `TDRSTN6`). The net on the header side is
`Sync1_C` … `TDRSTN6_C`. The resistor is the source termination of the camera cable. The cable
is a line of about 105 Ω. The buffer output resistance is lower, so an edge with no termination
overshoots at the camera. One value (47 Ω) is used for IDS and EVK4 cameras. Simulation
(`rev2_sim.py`, case 2; `tools/signal_sim/results_rev2.md`), at the camera end of the cable:

| Camera, +VCAM | Series resistor | Steady high level | Peak | After a falling edge | Lowest level after a rising edge |
|---|---|---|---|---|---|
| IDS, 1.8 V | none (Rev 1) | – | 3.02 V | −1.22 V | – |
| IDS, 1.8 V | 47 Ω | – | 2.18 V | −0.34 V | – |
| EVK4, 3.3 V | none | 2.98–3.32 V | 5.58 V | −2.94 V | 2.20 V |
| EVK4, 3.3 V | 47 Ω | 2.83–3.11 V (2.5 V needed) | 3.78 V | −0.88 V | 2.69 V |

With 47 Ω the edge at an IDS camera is at most 0.3 ns later. The EVK4 input current is
3.7–4.6 mA (2.7 mA needed). A wrong J22 setting (3.3 V into an IDS camera) gives 3.20–3.40 V
steady and 4.43 V peak at the 1.8 V pin. The
fast and typical output resistances of the buffers are estimates, not data-sheet values: measure the overshoot
at the camera end ([first-board check 3](../FIRST_BOARD_CHECKS.md#first-board-checks)).

The table above is for one line (`Trigger3`). `rev2_sim.py` also runs all 18 camera lines, each
with its own routed copper, its resistor and its stub to the header pin
(`results_rev2.md`, "All camera lines"). Conditions: fast corner, 2 m cable.

| Camera, +VCAM | Lines | Steady high level | Highest peak | Lowest level after a falling edge | Rise to +VCAM / 2 | Lowest level after a rising edge |
|---|---|---|---|---|---|---|
| IDS, 1.8 V | `Sync1`–`Sync6` | 1.84 V | 2.16 V | −0.33 V | 11.02–11.09 ns | – |
| IDS, 1.8 V | `Trigger1`–`Trigger6` | 1.84 V | 2.17 V | −0.33 V | 10.88–10.91 ns | – |
| IDS, 1.8 V | `TDRSTN1`–`TDRSTN6` | 1.84 V | 2.16 V | −0.32 V | 10.89–10.94 ns | – |
| EVK4, 3.3 V | `Sync1`–`Sync6` | 3.11 V | 3.82 V | −0.92 V | 11.10–11.17 ns | 2.96 V |
| EVK4, 3.3 V | `Trigger1`–`Trigger6` | 3.11 V | 3.77 V | −0.88 V | 10.97–11.00 ns | 2.96 V |

The EVK4 has no pixel-reset input, so `TDRSTN` is run for IDS only. The rise time includes the
board line and the 2 m cable.

**Levels at an IDS camera.** The signals are driven by U2/U4/U6 on `+VCAM`, each through its 47 Ω series resistor (R52–R69). Delivered levels: VOH ≥ 1.5 V and VOL ≤ 0.2 V at light load over temperature, against a 1.8 V CMOS input's typical VIH of ~1.17–1.26 V and VIL of ~0.63 V. IDS doesn't publish the camera's own thresholds or input pull, so confirm on the bench.

---

## Laser interlock

```
LASER_EN = AND( J11 jumper , EN tap )      -- U10, 74AHCT1G08 on +5 V
J7 output = AND( LASER_EN , CH1 pulse )    -- U7
J8 output = AND( LASER_EN , CH2 pulse )    -- U8
```

| Node | Net | Notes |
|---|---|---|
| J11.1 | `LASER_EN_PU` | R2 3k3 to +5 V |
| J11.2 | `LASER_EN_JMP` | → U10.1, **R8 10k pull-down to GND** |
| J11.3 | `GND` | |
| U10.2 | `LASER_EN_TAP` | R3 3k3 to +5 V (held high: J11 is the only user interlock) |
| U10.4 | `LASER_EN` | → U7.1, U8.1 |

**Fails safe.** R8 holds U10 pin 1 low when J11 has no shunt, so the default is *disabled*. A shunt
on J11 **1-2** enables the hardware interlock (the firmware must also be ARMED; see
[Boot and arming](FIRMWARE_HW.md#boot-and-arming)); **2-3** disables it. With the 1-2 shunt fitted, R2 wins:
5 V × 10/(3.3+10) ≈ **3.76 V**, against U10's **VIH of 2.0 V**, about **1.76 V of margin**. U10's
other input (`LASER_EN_TAP`) is held high by R3;

**E-stop switch: wire it across J11 1-2.** Replace the shunt with a *normally-closed* switch between
J11.1 and J11.2. Closed, it acts like the shunt; pressing it or breaking its cable opens the circuit
and R8 pulls U10.1 low, so the stop fails safe. The silkscreen beside J11 reads `LASER INTERLOCK: ON = 1-2` and
`E-STOP: NC SWITCH ACROSS 1-2`, and the pins are marked **ON** (1-2, lasers enabled) and **OFF**
(2-3).

Without R8 the interlock would be *enabled* with the header empty; R8 makes an empty J11 fail safe.

**Three gates in series.** The firmware's arm state acts before U7/U8 (DISARMED holds their pulse
inputs LOW), the J11/U10 interlock acts at U7/U8, and the power-good gate (`LASER_PWR_OK`, see
[Power-good gate](POWER.md#power-good-gate-u18)) acts on U13's ENA/ENB (and on U19's, for J12). Any one of them alone forces both
BNC centre pins to 0 V, and none can enable a laser that another has disabled. U10 alone carries the
user interlock; U13's enables carry only the power-good gate.

**Pico removed, J17 powered.** J17 can power the board with no module fitted. U7/U8's pulse inputs
would then float, and an enabled interlock would pass whatever they picked up, so **R17/R18
(10 kΩ)** hold `_PULSE_OUT_CH1`/`_PULSE_OUT_CH2` low at the socket (J14.17/.16) and the laser
outputs stay at 0 V. With the Pico fitted they cost 0.33 mA per GPIO while high. The camera lines
are not all guarded the same way: R9 holds `PWM_TRIG_TAP` low, so the camera triggers and J12 stay
low, but `PWM_1MHz` floats and R24 has no supply (+3V3 comes from the Pico), so Sync and TDRSTN at
the cameras are undefined. That is a nuisance, not a hazard: fit the Pico before connecting cameras.

---

## Status LEDs

Six LEDs on the top side, each with its name on the silkscreen. D2–D6 are in a row 4.8 mm below
the top edge (y = 34.8). D1 stands vertical at (235.5, 35.7).

| LED | Silkscreen | Colour | Lit when | Circuit |
|---|---|---|---|---|
| D2 | `12V OK` | green | the +12V rail is in its window (10.6–13.3 V): the USB-C charger gave 15 V and U17 regulates | +5V → R36 (1 kΩ) → D2 → Q1. Q1 (2N7002) conducts while `LASER_PWR_OK` is high. |
| D3 | `ARMED` | red | the firmware is ARMED **and** J11 is closed **and** the +12V rail is good | `LASER_EN` → R37 (1 kΩ) → D3 → Q2 → Q1. Q2 conducts while GP17 (`ARMED_LED`) is high; R38 (100 kΩ) holds its gate low during a reset and with no Pico fitted. |
| D1 | `3V3` | blue | the camera I/O level is 3.3 V (J22 fitted) | `+VCAM` → R33 (100 Ω) → D1. See [+VCAM](POWER.md#vcam-the-camera-signal-supply). |
| D4 | `L1` | red | a pulse leaves the Laser 1 driver (U13, to J7) | U21 (pulse stretcher) on `CH1_DRIVE_RAW` |
| D5 | `L2` | red | a pulse leaves the Laser 2 driver (U13, to J8) | U22 on `CH2_DRIVE_RAW` |
| D6 | `SYNC` | yellow | a pulse leaves the External Sync Out driver (U19, to J12) | U23 on `EXT_SYNC_DRIVE_RAW` |

**D3 `ARMED` shows that all three laser gates are open.** Its current path is in series with the
three conditions: it comes from `LASER_EN` (the output of U10: high only with J11 on 1-2), goes
through Q2 (on only while the firmware drives GP17 high, which it does while ARMED), and returns
through Q1 (on only while `LASER_PWR_OK` is high). So D3 dark with the firmware ARMED means that
J11 is open or the 12 V rail is not good. The LED is an indicator, not a safety device: a failed
LED is dark with the lasers live. `LASER_EN` supplies about 3 mA to D3; U10 (74AHCT1G08, 8 mA
rated) still delivers a valid high level to U7 and U8.

**D4–D6 show real pulses at the driver outputs,** after the firmware gate, the J11 interlock and
the power-good gate. Each LED has a retriggerable monostable (U21–U23, SN74LVC1G123 on +3V3) that
stretches each pulse to about 15 ms (R = 150 kΩ, C = 0.1 µF; nominal, not a timing reference).
One pulse gives one flash; above about 70 pulses a second the LED is on continuously. D6 follows
the camera trigger (the marker, or CH1 with J10 on 1-2), and is dark without the USB-C charger
because U19 is then disabled.

The trigger input of each monostable is a compensated divider on the 12 V driver output:
10 kΩ with 12 pF (C0G) to the pin, 4.7 kΩ with 22 pF (C0G) to GND (R39/C31/R40/C32 for Laser 1,
R43/C33/R44/C34 for Laser 2, R47/C35/R48/C36 for External Sync Out). The settled level at the pin
is 3.18–3.76 V and the highest peak is 4.14 V
(threshold 2.0 V, input rated to 5.5 V). The capacitors keep the divider ratio for fast
edges near the ratio for DC, so the track to U23 (about 56 mm: 49.0 mm on B.Cu and 6.9 mm on
F.Cu) does not slow the edge: a 10 ns pulse holds the pin
above 2.0 V for 8.7 ns or more, and the monostable needs 3 ns (`rev2_sim.py`, case 4). Keep the
ratio C_top / C_bot near R_bot / R_top if you change a value; the input and track add 6–10 pF
to C_bot. The divider takes 0.8 mA from the driver and lowers the output level by 2.4 mV at most
(see [Amplitude budget](#amplitude-budget)).

The dividers are beside R6 (Laser 1), below R7 (Laser 2) and above R30 (External Sync Out). The
sense tracks of Laser 2 and External Sync Out go to U22 and U23 on B.Cu.

**In an enclosure** the LEDs point up from the board. For a view from outside, use a window in
the lid or light pipes above the row.
