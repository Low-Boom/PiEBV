# PiEBV design: power

This page gives the design of the supply rails: the USB-C PD input, +5 V, +12 V and its
power-good gate, the fan supply, the +VCAM mux with its data-sheet values and load budget, +3.3 V, and the
derivation of the board output rating.
Back to: [hardware reference](../../Hardware.md) · [design notes index](../DESIGN_NOTES.md)

---

## Supply overview

Two inputs. **J17 (USB-C, power only)** is the main supply. The **Pico's own USB** carries data,
and on its own runs everything *except the laser outputs*.

```
J17 USB-C ─ U14 CH224A (asks the charger for 15 V) ─ VBUS_PD (5 V until negotiated, then 15 V)
   ├─ U15 AP63205WU buck ─ +5V_PD ─ U16 LM66100 ideal diode ─┐
   │                                                        ├─ +5V island = Pico VSYS ─ U9 (1.8 V) ─┐
   │               Pico USB VBUS ─ Pico's own Schottky (D1 on the Pico module, not the board's LED D1) ───┘
   ├─ U17 LT3065 (adj., 500 mA, 400 mA limit) ─ +12V (11.8 V) ─ U13 VDD (C9, C10, C17), U19 VDD (C21, C22)
   │    U18 TPS3700 window on +12V (10.6–13.3 V) ─ LASER_PWR_OK ─ U13 and U19 ENA/ENB  (R16 100k pull-up)
   └─ U24 CJ78M12 (12 V, 0.5 A part; C37 in, C38 out) ─ +12V_FAN ─ J23 pin 1 (cooling fan, 200 mA maximum)

     U9 ─ +1V8 ──────── U20 VIN1 ─┐
                                  U20 TPS2116 ─ +VCAM ─ U1–U6 (camera buffers), D1, R51
Pico 3V3_OUT ─ +3V3 ─┬─ U20 VIN2 ─┘   J22 open: +VCAM = +1V8.  J22 fitted: +VCAM = +3V3.
                     └─ U20 MODE, R34 and R70 (pull-ups of U20 PR1), R24, U21–U23 (activity LED monostables)
```

## VBUS_PD (the USB-C PD input)

**VBUS_PD.** U14 is a WCH **CH224A** PD sink (chapter 7 of the CH224 datasheet V2.x
covers the CH224K-to-CH224A differences). R10 =
56 kΩ on CFG1 requests **15 V** (CH224A table 5-1: 6k8 = 9 V, 24k = 12 V, 56k = 15 V, 120k = 20 V,
210k = 28 V — never leave R10 off: an open CFG1 is outside the table). CFG2/CFG3 are grounded
(WCH allows this in single-resistor mode; the CH224A's internal 7–15 kΩ pull-ups then draw well
under 1 mA), DP/DM are shorted at the chip (PD-only connection;
J17 has no D+/D− contacts, so no QC/BC1.2 request can reach the charger), and PG is unused. The VHV supply
pin (pin 1) and the VBUS sense pin (pin 8) connect **directly to VBUS_PD** by copper, as WCH's
guide (§7.2.1) requires for the CH224A. Do not fit a CH224K: its pin 1 is a 3.6 V
VDD pin and would be destroyed. VHV, VBUS, CC1 and CC2 are rated to
32 V (the CH224K's CC pins: 8 V). Until the PD contract completes VBUS_PD sits at 5 V; after
it, 15 V. The CH224A has no output switch, so everything downstream must tolerate both, and
does. Any charger rated **above 27 W** must offer 15 V under the USB-PD rules; a smaller one may
not, and the laser outputs then stay disabled (see below). C12 (10 µF) is the only large
capacitor on VBUS_PD (C11 at U14, C16 at U17 and C37 at U24 are 1 µF each), which keeps the board near the
USB-C 10 µF sink limit.

## +5 V

U15 (Diodes AP63205WU buck, fixed 5.00 V ±1 %, 3.8–32 V in) makes +5V_PD. With VBUS_PD still at
5 V it runs at 100 % duty and passes ~4.9 V. U16 (TI LM66100 ideal diode) feeds +5V_PD into the
**+5V island (In2.Cu), which is the Pico's VSYS pin** (J15.2). U16's CE is tied to its own VOUT, TI's
always-on reverse-blocking connection, so nothing can push current back into +5V_PD.

**Pico VBUS (pin 40, J15.1) is deliberately not connected.** Tying VBUS to VSYS (to save the
Schottky drop) is only safe when USB is the sole source; with J17 also feeding VSYS it would push
current back into the USB host. So the Pico's USB reaches VSYS only through the Pico's own Schottky
D1 (MBR120VLSFT1G, ~0.28 V at 0.1 A). With both inputs present, U16's ~5.0 V beats D1's ~4.7 V and
J17 carries the load, while D1 blocks any flow back into the host. With the Pico's USB alone, +5V
sits at ~4.7 V typical: U9 and the 74AHCT gates run happily (AHCT is specified from 4.5 V, so a host
whose USB sags below ~4.8 V puts them just outside their rated range), and the lasers are off
because there is no 12 V.

Loads on +5V: the Pico (VSYS), U7, U8, U10 (74AHCT1G08), **U9 (the 1.8 V regulator's input)**,
the R2/R3 pull-ups and the LED D2 (R36). Decoupling: C4, C5 (0.1 µF), C6 (1 µF, U9's input).

## +12 V (the laser driver supply)

U17 is an Analog Devices **LT3065** (adjustable linear regulator, 45 V / 500 mA, MSOP-12 with an
exposed pad), with SHDN tied to IN:

VOUT = 0.6 V × (1 + R12/R13) = 0.6 V × (1 + 100k/5.36k) = **11.8 V** (11.79 V)

The ADJ reference is 588–612 mV over line, load and temperature, so with **0.1 %** R12/R13 the rail
is **11.54–12.05 V** (see the [amplitude budget](SIGNALS.md#amplitude-budget)). R20 (750 Ω) on IMAX
sets a **400 mA ±10 %** current limit (500 × 0.6 V / R20), and C18 (22 nF) decouples IMAX as the
datasheet requires. C19 (10 nF) on BYP filters the reference and gives a soft start. The output
capacitors are C17 (10 µF X7R 1206, at U17), C9/C10 at U13 and C21/C22 at U19; the LT3065 is stable with any
ceramic of 3.3 µF or more, so no series ESR resistor is needed. The exposed pad (pin 13) is tied to GND pin 9
and has two GND vias to the planes.

**Load.** An output held high into 50 Ω draws ~96 mA, both laser outputs ~200 mA, all three outputs
(with J12) at most ~310 mA, and both laser outputs into shorted BNCs at most 358 mA, all below the
360 mA minimum limit (J12 into a short as well exceeds it; see
[Board output rating](#board-output-rating)). In Hi-Z mode an output draws less: ~60 mA
while high into an open circuit, ~100 mA into a short. U17 drops 15 − 11.8 = 3.2 V, so it
dissipates ~0.3 W at the firmware's highest sustained duty into 50 Ω (50 % per laser output), ~0.45 W
with J12 also at its 50 % limit into 50 Ω, and ~0.7 W with both laser outputs shorted at 67 %
duty (`COMBINE 1`). Thermal shutdown is the last resort. C10
(10 µF X7R 1206) is also U13's pulse reservoir: a 1 µs, ~200 mA pulse pair droops it by ~20 mV
(0.2 %) before U17's regulation catches up.

## Power-good gate (U18)

U18 is a TI **TPS3700** window comparator watching +12V (divider R21 150 kΩ / R22 1.2 kΩ /
R23 4.7 kΩ, 1 %, all JLC basic parts, decoupled by C20). Its open-drain outputs drive the enable pins ENA/ENB of
U13 and U19 as `LASER_PWR_OK` (R16 100 kΩ pull-up to +12V; the drivers' own EN pins also pull up to
VDD through ~200 kΩ each).

- OUTA pulls low below the **undervoltage** threshold: 10.6 V rising / 10.4 V falling (worst case:
  trips at 10.03–10.78 V, releases by 10.89 V).
- OUTB pulls low above the **overvoltage** threshold: 13.3 V (worst case 12.88–13.67 V).

They stay at least 0.65 V (release) and 0.82 V (overvoltage) outside the regulated 11.54–12.05 V band
so the gate never trips in normal
running. The outputs of U13 and U19 are held low:

- with J17 unplugged: +12V = 0 V, U13 is in undervoltage lockout (and U18, below its own lockout,
  holds OUTA low);
- before the PD agreement (VBUS_PD = 5 V) and with a 5 V-only charger: U17 can't regulate,
  +12V ≈ 4.7 V;
- **if the charger offers only 9 V:** +12V ≈ 8.7 V, far below the undervoltage threshold. The
  CH224A datasheet (like the CH224K's) does not say what the chip does when 15 V is unavailable, which is why the rail
  sits well above 9 V;
- when U17 can't regulate or is current limiting, e.g. on a 12 V charger setting or an overload:
  +12V below ~11 V;
- **if U17 fails short:** +12V would follow VBUS_PD to 15 V and put ~6.3 V into the LDP-V trigger
  input; the overvoltage side switches the outputs off. It is there to catch a failed regulator,
  not to police the LDP-V's 5.2 V limit, which U17's own accuracy guarantees.

U17's own PWRGD output (open drain, 90 % of nominal) can only sink 50 µA, less than the ~180 µA that
R16 and U13's internal pull-ups source, so it is left unconnected and U18 does the job.

## Fan supply (U24, J23)

J23 supplies a 2-wire 12 V DC cooling fan. The maximum fan current is 200 mA (the design limit).

**Circuit.** U24 is a **CJ78M12** linear regulator (78M12 type, 12 V, 0.5 A part, TO-252-2,
LCSC C9072). Its input is VBUS_PD. Its output is the net `+12V_FAN`. C37 (1 µF, 0805) is the
input capacitor and C38 (1 µF, 0805) is the output capacitor: they are the same part as the other
1 µF 50 V capacitors (C28323). J23 is a 1×2 vertical 2.54 mm pin header, the same part as J20 and
J22 (C32713268): pin 1 is `+12V_FAN`, pin 2 is GND. The silkscreen shows `J23  FAN 12V`,
`0.2 A MAX`, `+` beside pin 1 and `-` beside pin 2.

| VBUS_PD | `+12V_FAN` | Fan |
|---|---|---|
| 15 V (after the PD negotiation) | about 12 V | runs |
| 5 V (before the negotiation, or a charger that does not offer 15 V) | far below 12 V | does not run |

- The regulator needs about 2 V of headroom (typical 78M12 dropout, not checked against the
  CJ78M12 data sheet). 15 V gives 3 V.
- The fan is always on while 15 V is present. There is no firmware control and no tachometer
  input.
- There is no fuse. The 78M12 type has internal current limiting and thermal shutdown (not checked
  against the CJ78M12 data sheet).

**Why a separate regulator.** The fan supply does not use the +12V rail of the laser drivers
(U17), for two reasons:

- That rail has a 400 mA current limit. The worst case with both laser outputs shorted already
  takes 358 mA (see [Board output rating](#board-output-rating)).
- The noise of the fan motor would go onto the supply of the pulse drivers.

**Heat.** U24 drops about 3 V (15 V − 12 V). Its dissipation is about 3 V × the fan current:
0.6 W at 200 mA, plus the power of its own supply current. The tab of U24 is GND. It has a solid
connection to the top-layer GND pour and four GND vias.

The placement and the copper are in [Routing](LAYOUT.md#routing).

## +VCAM (the camera signal supply)

`+VCAM` powers **U1–U6, all the camera-facing logic** (decoupling C1/C2/C3, 0.1 µF, beside
U1/U3/U5). It is 1.8 V or 3.3 V:

| J22 | +VCAM | Cameras | D1 (blue, `3V3`) |
|---|---|---|---|
| **open (default)** | 1.8 V, from U9 | IDS uEye EVS (1.8 V sensor pins) | dark |
| shunt fitted | 3.3 V, from the Pico's 3V3_OUT | Prophesee EVK4, with the harness of [docs/EVK4_HARNESS.md](../EVK4_HARNESS.md) | lit |

**The 1.8 V rail** is made by **U9, an NCP718xSN180** fixed 1.8 V linear regulator fed from +5 V
(the NCP718 accepts 2.5–24 V in). Output capacitor C7 (2.2 µF), input capacitor C6 (1 µF).

**The selector is U20, a TI TPS2116 power mux** (1.6–5.5 V, SOT-583-8), not a jumper in the supply
path. VIN1 (pin 3) = +1V8, VIN2 (pin 6) = +3V3, VOUT = +VCAM (C23, 1 µF). C24 (1 µF) is the
capacitor of VIN2 (+3V3). MODE (pin 5) is tied to +3V3. With MODE high (1 V or more), the mux
passes VIN1 if its PR1 pin (pin 4) is above VREF and VIN2 if PR1 is below VREF. VREF is
0.92 / 1 / 1.08 V (minimum / typical / maximum).
PR1 is the net `VCAM_SEL`. R34 and R70 (10 kΩ each, in parallel) pull PR1 up to +3V3. One open
solder joint (R34 or R70) cannot leave PR1 floating. R70 stands directly above R34, at
(225.7, 32.9). J22 pin 2 connects to PR1 through
R35 (1 kΩ). J22 pin 1 is GND. In Rev 2 the two inputs are in this order for safety: the default
and the fault cases below give 1.8 V.

The data in this section are from the TI data sheet SLVSFG1A (January 2021, revised May 2021).
The data sheet gives:

- Pins: 1 GND, 2 and 7 VOUT, 3 VIN1, 4 PR1, 5 MODE, 6 VIN2, 8 ST.
- "Device is put into Priority mode when MODE is tied to VIN1 and manual mode when MODE is
  pulled up to an external voltage". On this board MODE is on +3V3, an external voltage.
- MODE: high at 1 V or more, low at 0.35 V or less. PR1 pin leakage: 0.1 µA maximum.
- MODE low with PR1 high is shutdown (the output is high impedance). MODE low with PR1 low
  passes the higher of VIN1 and VIN2.
- Inputs: 1.6–5.5 V. On-resistance: 41 mΩ typical / 66 mΩ maximum at 1.8 V, 40 mΩ typical /
  59 mΩ maximum at 3.3 V.
- The switch-over is break-before-make. When the output is above the new input, the new channel
  turns on only after the output has discharged to VIN + 42 mV (typical).

The states on this board:

- **J22 open:** R34 and R70 hold PR1 at 3.3 V. The mux passes VIN1: **+VCAM = 1.8 V.** No shunt
  is necessary for IDS cameras, and a lost shunt gives 1.8 V.
- **J22 fitted:** R35 and the two pull-ups put 0.55 V on PR1 (1 kΩ against 5 kΩ: 3.3 V × 1 / 6).
  This is below the 0.92 V minimum threshold. The mux passes VIN2: **+VCAM = 3.3 V.**
- **Pico not fitted:** +3V3 is 0 V, so MODE and PR1 are low. The mux passes the higher input,
  +1V8: **+VCAM = 1.8 V** (data sheet).
- **R51 (4.7 kΩ)** from +VCAM to GND discharges +VCAM when the level changes from 3.3 V to
  1.8 V. On this change the output falls through R51 and the load before the 1.8 V channel
  turns on.
- **PR1 has no capacitor.**
- **ST (pin 8)** is not connected.

**3.3 V destroys the 1.8 V pins of an IDS camera.** J22 sets the level of all six camera ports
together. Fit J22 only when no IDS camera is connected, and look at D1 before you connect a
camera: D1 lit = 3.3 V. D1 is a blue LED on +VCAM through R33 (100 Ω): a blue LED needs more than
about 2.5 V, so it is dark at 1.8 V and takes about 4 mA at 3.3 V. Do not replace it with a red,
yellow or yellow-green LED (those light at 1.8 V). Change J22 with the power off: the mux
switches break-before-make, but the cameras see the level change. Before you connect an IDS
camera, measure +VCAM at TP8 with a meter: it must be 1.8 V with J22 open
([first-board check 7](../FIRST_BOARD_CHECKS.md#first-board-checks)).

**Faults** (found by the [first-board checks](../FIRST_BOARD_CHECKS.md#first-board-checks)):
- A solder bridge from PR1 (U20 pin 4) to pin 3 (+1V8) or to pin 5 (+3V3) keeps PR1 high, so
  the output stays 1.8 V.
- With the Pico not fitted, +3V3 is 0 V. MODE and PR1 are low, and the output is 1.8 V.
- PR1 floats (level not defined) only if both R34 and R70 are missing or open. This fault can
  give the wrong level: check for it. A single open resistor leaves the 1.8 V default in place.
- The data sheet does not state the output when PR1 is high and VIN1 (+1V8) is absent while
  +3V3 is present (U9 failed). This is a bench test
  ([first-board check 7](../FIRST_BOARD_CHECKS.md#first-board-checks)).

**Load.** Six IDS cameras: CMOS inputs, no DC current. Six EVK4 cameras: each Sync and Trigger
input is an opto-coupler LED that takes 3.7–4.6 mA while the line is high (with the on-board
47 Ω resistors; `tools/signal_sim/rev2_sim.py`, case 2). The supply budget (`rev2_sim.py`, case 3) gives at most 58 mA for six cameras
while Sync and Trigger are both high, and about half of that on average. The budget calculation
does not include the 47 Ω resistors, so 58 mA is an upper limit. The Pico's 3V3_OUT pin can supply it (Raspberry Pi recommends a load below
300 mA on that pin). The on-resistance of U20 at 3.3 V is 40 mΩ typical and 59 mΩ maximum (TI data sheet).

**Why 1.8 V.** The IDS UE-39B0XCP-E documents its I/O pins as 1.8 V sensor-level signals (see
the camera table under [Connectors](../../Hardware.md#connectors)). Running this logic at 3.3 V would drive 3.3 V
into 1.8 V sensor pins on all six cameras. **Don't remove the 1.8 V rail**, even though it looks
like it powers only a few small chips.

No level translator is needed. The SN74LVC04A runs at 1.65–3.6 V and the 74LVC1G04 at
1.65–5.5 V, and both have 5.5 V-tolerant inputs at any supply, so at 1.8 V and at 3.3 V they
accept the Pico's 3.3 V GPIOs directly.

Specify the **fixed 1.8 V** part (e.g. NCP718BSN180T1G, as ordered, or NCP718ASN180T1G; ±2 % at VOUT ≥ 1.8 V). A 1.65 V or
1.7 V version eats into the camera's already modest input margin.

The series resistors in the camera lines and their simulation tables are in
[Camera line series resistors](SIGNALS.md#camera-line-series-resistors).

## +3.3 V

From the Pico's 3V3_OUT (pin 36), on the +3V3 island of In2.Cu. Loads: R24, the 10 k pull-up on
`PIXRST_GATE` (0.33 mA while the gate is low); U20 VIN2 and MODE, with C24 (1 µF) at U20, and through
U20 the camera buffers when J22 is fitted; R34 and R70 (the pull-ups of U20 PR1; they carry current only
while J22 is fitted); U21–U23 and their LEDs D4–D6
(about 2 mA for each lit LED).

**Power-up order.** Because U9 runs from +5 V, the 1.8 V rail can come up a millisecond or so before
the Pico's 3.3 V. In that moment R24 has no supply and GP16 is not yet driven, so U3's input and
TDRSTN are briefly undefined. That is harmless, because the cameras haven't started yet.

With J22 open, nothing on this board presents 5 V or 3.3 V to J1–J6. With J22 fitted, pins 3, 4
and 5 of J1–J6 are 3.3 V signals.

## Board output rating

**No firmware setting can overload the laser outputs.** R6/R7, R30 and R25–R28, R31, R32 are
**2 W 2512** resistors, and U17 is a 500 mA regulator with a 400 mA current limit. The laser outputs
carry any duty the firmware accepts (up to 50 % per output, 67 % with `COMBINE 1`):

| Situation (50 Ω mode) | Current | Dissipation |
|---|---|---|
| Output high into 50 Ω | ~96 mA per output (at most 103 mA), ~200 mA for both | at most 0.71 W in R6/R7 while high |
| Output into a shorted BNC, at the highest duty the firmware allows | at most 358 mA while high with both shorted (ROH 0 Ω, 12.05 V), just under U17's 360 mA minimum limit | at most 1.45 W |
| Output **stuck** high into a short (a fault; the firmware never holds an output high) | | 1.5–2.16 W in R6/R7: at the 2 W rating, and up to 8 % over it only if ROH is near 0 Ω (D-package ROH has no specified minimum) |

Hi-Z mode loads everything less (see [Output mode](SIGNALS.md#output-mode)).

**External Sync Out (J12) follows the camera trigger,** so its duty is the marker's, at most 50 %
(`2 × MARKERWIDTH ≤ 1/FREQ`), or with J10 on 1-2 the CH1 duty (50 %, 67 % with `COMBINE 1`, as
for the laser outputs). Into 50 Ω that is the same ~96 mA (at most 103 mA) and at most 0.71 W in R30
while high. Into a shorted BNC at those duties R30 averages at most 1.08 W (marker) or 1.45 W
(`COMBINE 1`, J10 on 1-2), the same as the laser outputs. The firmware never holds the marker high,
so 1.5–2.16 W (the stuck-high fault case of R6/R7) needs a firmware or GP11 fault as well as a
short. Still, don't short J12. All three outputs high into 50 Ω draw
at most ~310 mA, under U17's 360 mA minimum limit. Shorts on several outputs at once can exceed it:
U17 then limits, +12V sags below U18's undervoltage threshold and `LASER_PWR_OK` turns all three
drivers off, which can repeat while the short lasts.
