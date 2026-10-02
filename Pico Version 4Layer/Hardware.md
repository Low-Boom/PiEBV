# PiDG hardware reference (Pico 2 W, 4-layer board)

This is the design reference for the PiDG board: what each part of the circuit does, why it was
built that way, and what to check on the first boards. It is for anyone building, checking or
changing the hardware. To *use* the board, see the [top-level README](../README.md).

The board is a Raspberry Pi Pico 2 W redesign of the original Teensy 4.1 design in
`../Chris Teensy Version/`. This document covers **only** the 4-layer Pico version.

**Status:** passes KiCad's design-rule check (DRC) and electrical-rule check (ERC) with 0
violations. Not yet built: work through the [first-board checks](#first-board-checks) on the first
boards.

**Contents:** [How the board works](#how-the-board-works) · [At a glance](#at-a-glance) ·
[Socket pin mapping](#socket-pin-mapping--read-this-first) · [Firmware pin map](#firmware-pin-map) ·
[Power](#power) · [Signal chains](#signal-chains) · [Laser interlock](#laser-interlock) ·
[Connectors](#connectors) · [First-board checks](#first-board-checks) ·
[Manufacturing notes](#manufacturing-notes) · [Files](#files)

---

## How the board works

```
 USB-C charger ──► J17 ──► power section ──┬─► +5 V  (logic, Pico) ◄── also from the Pico's USB
   (15 V)                                   ├─► +1.8 V (camera signals)
                                            └─► +12 V (laser driver), checked by a voltage window (U18)
                                                (+3.3 V comes from the Pico itself)

 PC ──USB──► Pico 2 W ──┬─ CH1, CH2 ──► interlock ──► 12 V driver ──► output resistors ──► J7, J8
                        │             (ARM, J11)      (U13, on only    and mode jumpers      Laser 1, 2
                        │             (J16 pin 1)      if 12 V is OK)  (R6/R7, J18/J19)
                        ├─ marker ────► J10 selector ──► 1.8 V buffers ──► camera trigger (J1–J6)
                        ├─ 1 MHz sync ───────────────► 1.8 V buffers ──► camera sync    (J1–J6)
                        └─ pixel gate ──┐
       J12 BNC (reset input) ───────────┴─► combine ──► 1.8 V buffers ──► camera pixel reset
```

- **The Pico makes all the timing.** Its PIO blocks (small timing engines beside the processor)
  produce the two laser pulses, the camera marker, the 1 MHz sync clock and the pixel-reset gate,
  all from one 150 MHz clock.
- **The laser path** has three gates in series: the firmware's ARM state, the hardware interlock
  (J11, with J16 pin 1 as an extra off input) and a 12 V power-good check (U18) that switches the
  driver chip on. The driver chip (U13) swings its output to 12 V; resistors after it bring that
  down to about 5 V at the laser driver's input. Jumpers J18/J19 match each output to a 50 Ω or a
  high-impedance load: the wrong setting gives the wrong voltage.
- **The camera path** converts every signal to 1.8 V, the level the cameras use, and each camera
  cable has its own driver gate.
- **Power** comes from a USB-C charger on J17, which the board asks for 15 V. The Pico's own USB can
  run everything except the laser outputs.

### Reading this document

- **Reference designators** (U13, R6, J7 …) are the part labels on the board and in the schematic.
  Pin numbers are written `U13.7` (U13, pin 7).
- **Net names** (the names of connections in the schematic) are in `code`, e.g. `CH1_DRIVE`.
- **Rail:** a supply voltage shared across the board (+5V, +12V …).
- **Pull-up / pull-down:** a resistor that holds a line high or low when nothing else drives it.
- **Open-drain:** an output that can only pull low; a pull-up provides the high level.
- **VIH / VIL:** the voltage an input needs to read high / low. **VOH / VOL:** what an output
  delivers when high / low. "Margin" is how far the level an output delivers is beyond what the
  input needs (e.g. 3.76 V delivered against a VIH of 2.0 V is 1.76 V of margin).
- **Schmitt trigger:** an input with two thresholds (hysteresis), so a slow or noisy edge switches
  once instead of chattering.
- **LDO, buck:** two kinds of voltage regulator: a linear one (simple, quiet, burns the excess as
  heat) and a switching one (efficient).
- **Shunt** means the plastic jumper cap. The resistors to ground in the output-mode circuit are
  called resistors to ground, not shunts.

---

## At a glance

| | |
|---|---|
| Board | 126 × 126 mm, 4 copper layers, 1.6 mm FR4 |
| Processor | Raspberry Pi Pico 2 W, in sockets (not soldered) |
| Power | **USB-C PD input (J17, 15 V)** for the laser driver and the whole board; the Pico's own USB still powers the logic when J17 is unplugged |
| Rails | **1.8 V** (camera signals) · 3.3 V (Pico, pixel-reset input) · 5 V (logic, Pico VSYS) · **12 V** (11.9 V, laser driver U13, from J17 only) |
| Design rules | 0.2 mm clearance, 0.2 mm track, 0.6/0.3 mm via, 0.25 mm copper-to-edge |
| Parts | 82 placed parts, plus 4 unplated mounting holes |

**Layers**

| Layer | Use |
|---|---|
| F.Cu (top) | signals + ground fill |
| In1.Cu | solid ground plane |
| In2.Cu | solid +5 V plane |
| B.Cu (bottom) | signals + ground fill |

The 1.8 V camera rail has no plane: it runs as a 0.5 mm top-layer trunk. The 3.3 V rail is a single
0.3 mm bottom-layer run from J15 to the pixel-reset input.

**Stackup** (symmetric 1.6 mm, matching JLCPCB's standard 4-layer `JLC04161H-7628`):

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

Total 1.586 mm of copper and dielectric, 1.606 mm with the mask: a nominal 1.6 mm board. Confirm
these numbers against what your fabricator actually presses.

**Finish: lead-free HASL** (`HAL lead-free`). It is RoHS compliant and the cheapest compliant finish
at most quick-turn fabs, only slightly dearer than leaded HASL and far cheaper than ENIG. It arrives
pre-tinned, tolerates rework better than OSP (whose coating degrades with repeated heating), and
solders with either leaded or lead-free solder.

The finest pitches are J17's USB-C receptacle and U17 (LT3065, DFN-10 with an exposed pad), both
0.5 mm, and U16 (SC-70-6, 0.65 mm). There is no BGA. Fabs routinely assemble USB-C receptacles on
lead-free HASL, but the surface is uneven enough that J17 is worth inspecting for solder bridges
(see [first-board check 5](#first-board-checks)). Most passives and SOT-23s use `_HandSolder`
footprints (U16, U17, L1 and U14's exposed pad are the exceptions). If a future revision adds a
finer-pitch part, reconsider the finish.

**Board size:** the gerber job file reports 126.1 × 126.1 mm because the outline's extents include
its 0.1 mm line width. The fabricated board is **126.0 × 126.0 mm**.

---

## Socket pin mapping — read this first

The Pico plugs into two 1×20 sockets, **J14** (left row) and **J15** (right row), 17.78 mm apart.
The two rows do **not** number in the same direction:

```
J14 pad n  =  Pico pin n          (pads 1..20 -> pins 1..20)
J15 pad m  =  Pico pin (41 - m)   (pads 1..20 -> pins 40..21)
```

The Pico numbers its pins like a chip: down the left row from 1 to 20, then back **up** the right
row from 21 to 40, so pin 40 (VBUS) sits opposite pin 1. Both socket footprints on the board number
their pads 1 → 20 in the same direction, so the reversal lands entirely on J15.

**Sanity check for any change here:** the Pico's ground pins pair up to a constant sum (3↔38, 8↔33,
13↔28, 18↔23, each summing to 41), so grounds land on pads 3, 8, 13 and 18 of *both* sockets,
directly opposite each other. A mapping that doesn't line the grounds up across the two rows is
wrong.

> **Neither ERC nor DRC can catch a mistake here.** The Pico symbol is self-consistent, and U11 (the
> Pico) deliberately has no PCB footprint, so DRC has nothing to compare. An earlier draft wired J15
> as `pad m = pin 20 + m`, which would have shorted the Pico's 3.3 V output to ground and driven 5 V
> into two GPIOs. It was found only by checking every pad against the Pico's pinout by hand. Do the
> same after any change.

### Connected socket pins

| Signal | Pico pin | Socket pad | Board net |
|---|---|---|---|
| GP10 | 14 | J14.14 | `PWM_1MHz` |
| GP11 | 15 | J14.15 | `PWM_Trig` |
| GP12 | 16 | J14.16 | `_PULSE_OUT_CH2` |
| GP13 | 17 | J14.17 | `_PULSE_OUT_CH1` |
| GP16 | 21 | J15.20 | `PIXRST_GATE` |
| GND | 3, 8, 13, 18 | J14.3, .8, .13, .18 | `GND` |
| GND | 38, 33 (AGND), 28, 23 | J15.3, .8, .13, .18 | `GND` |
| 3V3_OUT | 36 | J15.5 | `+3V3` |
| VSYS | 39 | J15.2 | `+5V` |
| VBUS | 40 | J15.1 | **not connected** (see [Power](#power)) |

All eight module grounds are connected. Every other socket pad is unconnected and, once the module
is seated, out of reach. There is no GPIO breakout header.

**Keep-out:** the module body covers roughly x 158–180, y 31–82 in board coordinates, with its
micro-USB at the top board edge (the sockets start at y = 32.385, so the port can be reached through
an enclosure wall). Nothing may be placed there. The silkscreen labels the two top-edge ports
`CONTROL / PROGRAM — PICO MICRO-USB` and `POWER ONLY — USB-C PD 15 V` (J17).

---

## Firmware pin map

The firmware (`../src/`) drives all five signals from PIO state machines (pio0: SM0 CH1, SM1 CH2,
SM2 MARKER, SM3 PIXGATE; pio1: SM0 SYNC), so any GPIO can be used. CH1, CH2, MARKER and PIXGATE are
started on the same clock cycle, so they stay exactly in step. CH1/CH2 reach their pins only while
ARMED; otherwise `src/laser_gate.cpp` holds them LOW.

| Constant | GPIO | Board net | Drives |
|---|---|---|---|
| `kPinSync` | 10 | `PWM_1MHz` | U1 → U2 → Sync1–6 |
| `kPinMarker` | 11 | `PWM_Trig` | J10.3 → (jumper) → U5 → U6 → Trigger1–6 |
| `kPinCh2` | 12 | `_PULSE_OUT_CH2` | U8 → U13 → J8 (Laser 2); R18 10 k to GND |
| `kPinCh1` | 13 | `_PULSE_OUT_CH1` | U7 → U13 → J7 (Laser 1); R17 10 k to GND; R19 100 Ω → J10.1 |
| `kPinPixGate` | 16 (J15 pad 20) | `PIXRST_GATE` | U3.1 (NAND with the J12 input) → U4 → TDRSTN1–6; R24 10 k to +3V3. Output inverted in the GPIO block. |

**CH1 is the higher GPIO and CH2 the lower**, the opposite of the Teensy original (D2 = CH1,
D3 = CH2). Don't "tidy" them into ascending order.

`src/board.h` repeats this table as a comment. Keep the two in step: when the constants and the
schematic once drifted apart, the whole board looked dead.

### Timing limits

The firmware (`realizeTiming()` in `src/pulse_timing.h`) re-checks the whole set of settings on
every command, using the **realized** values (after rounding to whole 6.667 ns PIO cycles). It sets
**no laser-driver ratings**: pulse width, duty and spacing depend on the attached driver (the
PicoLas LDP-V datasheets were used only for the electrical interface), so set values within your
driver's ratings. The checks only keep the waveform correct:

- **Pulse pairs stay separate:** `DELAY ≤ 1/FREQ − 2 × WIDTH`, so CH2 ends at least one WIDTH
  before the next pair's CH1 starts. That also limits WIDTH to half the period.
- **Shortest pulse:** WIDTH and MARKERWIDTH must realize to ≥ 3 cycles (20.000 ns); 16 ns or less
  is **rejected**, not rounded up. The PIO program itself needs `DELAY ≤ 1/FREQ − WIDTH − 5 cycles`,
  which only matters at 3–4-cycle widths.
- **The marker fits in the period** (MARKERWIDTH ≤ 1/FREQ − 5 cycles), and SYNC stays within the
  divider's range.

### Board output rating

**There is nothing to observe: no firmware setting can overload the outputs.** R6/R7 and R25–R28
are **2 W 2512** resistors, and U17 is a 500 mA regulator with a 400 mA current limit. The outputs
carry any duty the firmware accepts (up to 50 % per output, 67 % with `COMBINE 1`):

| Situation (50 Ω mode) | Current | Dissipation |
|---|---|---|
| Output high into 50 Ω | ~98 mA per output, ~200 mA for both | 0.66 W in R6/R7 while high |
| Output into a shorted BNC, at the highest duty the firmware allows | ~340 mA while high with both shorted, under U17's 360 mA minimum limit | at most 1.4 W |
| Output **stuck** high into a short (a fault; the firmware never holds an output high) | | 1.6–2.05 W in R6/R7, at the edge of their rating |

Hi-Z mode loads everything less (see [Output mode](#output-mode)).

### Combined mode (`COMBINE 1`)

Both pulses of every pair go to **both** laser outputs, for one light source making both PIV pulses
or two sources fired together with the same double pulse. The CH1 and CH2 state machines then each
run a two-pin copy of the pulse program (`SET PINS, 3` on GP12–GP13, identical cycle timing). The
PIO's shared output latch makes each laser pin carry CH1's pulse and then CH2's, exactly DELAY later
(checked cycle by cycle in `tools/timing_check/check_combined.py`). Each driver then sees two pulses
per period, so check its ratings; the firmware imposes none.

The one extra rule is that the pulses stay separate on the shared pins: `DELAY ≥ WIDTH + 1 PIO
cycle` (6.667 ns). At `DELAY = WIDTH`, CH2 rises on the cycle CH1 falls, the higher-numbered state
machine wins the latch, and the two pulses merge into one of 2 × WIDTH. COMBINE can only be changed
while DISARMED.

**Don't use a BNC tee instead.** Joining J7 and J8, or splitting one output to two drivers, gives
3–3.4 V pulses in 50 Ω mode, or 6.9 V where the pulses overlap (see [Laser outputs](#laser-outputs)).

### Pixel-reset gate (`PIXGATE`)

pio0 SM3 runs the same pulse program on GP16, with the pin's output inverted in the GPIO block
(`GPIO_OVERRIDE_INVERT`), so the program's pulse becomes the pixel reset. It pulls TDRSTN low
`PIXLAG` after the last laser pulse ends (CH1 rise + DELAY + WIDTH + PIXLAG) and releases it
`PIXLEAD` before the next CH1 rise, cycle-exact and locked to CH1 (checked in
`tools/timing_check/check_pixgate.py`). `PIXGATE 1` runs it only while the laser pins carry pulses,
`PIXGATE 2` always.

A stopped gate leaves its output latch LOW, which (inverted) leaves the pin HIGH, so DISARM, a
restart hold-off and a reset all leave the pixels free. Rules: PIXLEAD ≥ 5 cycles, and
PIXLEAD + DELAY + WIDTH + PIXLAG ≤ 1/FREQ − 3 cycles. The first pair after a start has no reset
before it. SYNC runs on pio1 so the gate can have SM3; SYNC is independent of the laser timing.

### Timing: what you set is what you get

- **Every reply shows the realized value,** e.g. `DELAY 1003` → `OK DELAY=1003 (actual
  1000.000 ns, 150 cyc)`, and `STATUS` lists them all. The user never has to correct a setting for
  rounding or for fixed instruction overheads.
- **CH2 rises exactly DELAY after CH1,** to the nearest 6.667 ns cycle. This is exact in a
  cycle-accurate model of the PIO; see `../tools/timing_check/`.
- **MARKER fires with every pulse pair** and is locked to CH1: it runs the same program at exactly
  the laser period in cycles, started on the same cycle, so it rises with every CH1 pulse and can't
  drift. Each camera timestamps the marker into its event stream, which gives every PIV pair its own
  reference time.
- **SYNC** comes from the PIO's 8.8 fixed-point clock divider. The default 1 MHz is exact (divider
  75). Other values are reported with their actual average frequency; a fractional divider adds
  1 cycle (6.667 ns) of edge jitter, which the reply notes.

### Boot and arming

- **The firmware starts DISARMED.** An early start-up hook (`src/laser_gate.cpp`, `.preinit_array`
  priority 00110) drives GP12/GP13 LOW right after the chip's peripheral reset, before clock setup,
  USB, the Pico 2 W's radio-chip initialisation and `setup()`. They stay LOW until the host sends
  `ARM` over USB. SYNC and MARKER start as soon as `setup()` applies the defaults, and keep running
  while DISARMED.
- **`ARM`** (exactly that word, no argument) restarts CH1, CH2 and MARKER together, so the first
  laser pulse is full width and in step. It replies at once; the pulses begin after a **restart
  hold-off** of one pulse period (the longer of the old and new periods, ≤ 1 s), counted from when
  the laser pins last carried pulses. Changing pulse settings while armed goes through the same
  restart. The hold-off keeps the laser pulse spacing ≥ the set period under any sequence of
  commands, so a host looping ARM/DISARM can't fire faster than FREQ. MARKER pauses during it.
- **`DISARM` can never be refused and acts at once.** The six characters `DISARM` (any case)
  anywhere in the input disarm immediately (mid-line, inside an over-long line, after backspace
  edits) and cancel a pending start. Lines may end with CR, LF or CRLF, so PuTTY, Tera Term, screen
  and minicom all work.
- **J7/J8 pulse only when all three are true:** firmware ARMED, J11 on 1-2 (hardware interlock), and
  `LASER_PWR_OK` (12 V rail in its window).
- **Watchdog.** A 3 s hardware watchdog, fed only from the main loop, restarts the chip if the
  firmware hangs. It comes back DISARMED, and `STATUS` shows `RESET=WATCHDOG` and a `WDT_RESETS`
  count. No command can hang the firmware; to test the watchdog, write `0x80000000` (TRIGGER) to
  `WATCHDOG_CTRL` (`0x400d8000`) over SWD with the core running (a halted core pauses the
  watchdog).
- **Replies never block the firmware.** Each reply line is written whole within a 250 ms budget, and
  once a host stops reading, later replies stop waiting until it catches up. So a host that stops
  reading delays a queued DISARM by at most about 250 ms in total and can't trip the watchdog.
  Replies that couldn't be sent are dropped a whole line at a time, and their bytes are counted in
  `STATUS` as `TX_DROPPED`.
- **Host scripts** must send `ARM` after every reset, and should check `RESET=` in `STATUS` first
  (require an operator action after `RESET=WATCHDOG`). Parse `STATUS` by key, not by line count.
- **Losing the USB link does not disarm.** The firmware doesn't watch the USB connection, and J17
  alone keeps the board powered, so a pulled cable, a sleeping PC or a killed host script leaves an
  ARMED board pulsing with no serial path for `DISARM`. The hardware stops are J11 (off 1-2), J16.1
  pulled low, or unplugging J17.

**Remaining hazards the firmware can't remove.** Both need a reset to land during a laser pulse, so
the chance per reset is at most the duty.

- *A reset mid-pulse* (watchdog, or the 1200-baud restart that `pio run -t upload` uses) releases
  the pin instead of driving it LOW. R17/R18 and the pin's own pull-down then discharge it in an
  estimated 70–150 ns, so that one pulse can end up to that much later than WIDTH. Measure it (scope
  GP13 while forcing a watchdog reset). If it matters, fit R17/R18 = 2.2 k (τ ≈ 30 ns; 1.5 mA while
  high, well within the GPIO's drive).
- *A debugger warm reset (SYSRESETREQ)* leaves the PIO running while the boot ROM latches the pins,
  so a pin caught HIGH can stay HIGH until the start-up hook runs: milliseconds. **Before any SWD
  session or debugger reset: DISARM and open J11 (or unplug J17).** The one deliberate exception is
  the watchdog test in [first-board check 1](#first-board-checks), done into a 50 Ω scope input with
  no laser driver connected.

---

## Power

Two inputs. **J17 (USB-C, power only)** is the main supply. The **Pico's own USB** carries data,
and on its own runs everything *except the laser outputs*.

```
J17 USB-C ─ U14 CH224A (asks the charger for 15 V) ─ VBUS_PD (5 V until negotiated, then 15 V)
   ├─ U15 AP63205WU buck ─ +5V_PD ─ U16 LM66100 ideal diode ─┐
   │                                                        ├─ +5V plane = Pico VSYS
   │               Pico USB VBUS ─ Pico's own Schottky D1 ───┘
   └─ U17 LT3065 (adj., 500 mA, 400 mA limit) ─ +12V (11.9 V) ─ U13 VDD (C9, C10, C17)
        U18 TPS3700 window on +12V (11.0–13.1 V) ─ LASER_PWR_OK ─ U13 ENA/ENB  (R16 100k pull-up)
```

**VBUS_PD.** U14 is a WCH **CH224A** PD sink, the pin-compatible successor of the CH224K (the
CH224K is discontinued; chapter 7 of the CH224 datasheet V2.x is WCH's migration guide). R10 =
56 kΩ on CFG1 requests **15 V** (CH224A table 5-1: 6k8 = 9 V, 24k = 12 V, 56k = 15 V, 120k = 20 V,
210k = 28 V — never leave R10 off: an open CFG1 is outside the table). CFG2/CFG3 are grounded
(WCH allows this in single-resistor mode; the CH224A's internal 7–15 kΩ pull-ups then draw well
under 1 mA), DP/DM are shorted at the chip (carried over from the CH224K's PD-only connection; J17's
D+/D− are open, so no QC/BC1.2 request can reach the charger), and PG is unused. The VHV supply
pin (pin 1) and the VBUS sense pin (pin 8) connect straight to VBUS_PD through **R11 = R15 = 0 Ω**,
as WCH's guide (§7.2.1) requires for the CH224A; the CH224K needed 1 kΩ and 10 kΩ on the same pads.
Do not fit those values with a CH224A (1 kΩ drops VHV below its 3.3 V minimum before the contract),
and do not fit a CH224K with 0 Ω (its pin 1 is a 3.6 V VDD pin). VHV, VBUS, CC1 and CC2 are rated to
32 V (the CH224K's CC pins: 8 V). Until the PD contract completes VBUS_PD sits at 5 V; after
it, 15 V. The CH224A has no output switch, so everything downstream must tolerate both, and
does. Any charger rated **above 27 W** must offer 15 V under the USB-PD rules; a smaller one may
not, and the laser outputs then stay disabled (see below). C12 (10 µF) is the only large
capacitor on VBUS_PD (C11 at U14 and C16 at U17 are 1 µF each), which keeps the board near the
USB-C 10 µF sink limit.
### +5 V

U15 (Diodes AP63205WU buck, fixed 5.00 V ±1 %, 3.8–32 V in) makes +5V_PD. With VBUS_PD still at
5 V it runs at 100 % duty and passes ~4.9 V. U16 (TI LM66100 ideal diode) feeds +5V_PD into the
**+5V plane, which is the Pico's VSYS pin** (J15.2). U16's CE is tied to its own VOUT, TI's
always-on reverse-blocking connection, so nothing can push current back into +5V_PD.

**Pico VBUS (pin 40, J15.1) is deliberately not connected.** Tying VBUS to VSYS (to save the
Schottky drop) is only safe when USB is the sole source; with J17 also feeding VSYS it would push
current back into the USB host. So the Pico's USB reaches VSYS only through the Pico's own Schottky
D1 (MBR120VLSFT1G, ~0.28 V at 0.1 A). With both inputs present, U16's ~5.0 V beats D1's ~4.7 V and
J17 carries the load, while D1 blocks any flow back into the host. With the Pico's USB alone, +5V
sits at ~4.7 V typical: U9 and the 74AHCT gates run happily (AHCT is specified from 4.5 V, so a host
whose USB sags below ~4.8 V puts them just outside their rated range), and the lasers are off
because there is no 12 V.

Loads on +5V: the Pico (VSYS), U7, U8, U10 (74AHCT1G08), **U9 (the 1.8 V regulator's input)**, and
the R2/R3 pull-ups. Decoupling: C4, C5 (0.1 µF), C6 (1 µF, U9's input).

### +12 V (the laser driver supply)

* with J17 unplugged — +12V = 0 V, U13 in UVLO (and U18 below its own UVLO holds OUTA low);
* before the PD contract (VBUS_PD = 5 V) and with a 5 V-only charger — U17 in dropout, +12V ≈ 4.7 V;
* **if the charger only offers 9 V** — +12V ≈ 8.7 V, far below the undervoltage threshold. The
  CH224A datasheet (like the CH224K's) does not say what it does when 15 V is unavailable, which is
  why the rail sits well above 9 V;
* in dropout or current limit, e.g. on a 12 V PDO or under an overload — +12V below ~11 V;
* **if U17 fails short** — +12V would follow VBUS_PD to 15 V and put ~6.3 V into the LDP-V
  trigger input; the overvoltage side switches the outputs off. It is there to catch a failed
  regulator, not to police the 5.2 V limit, which U17's own accuracy guarantees.

U17 is an Analog Devices **LT3065** (adjustable linear regulator, 45 V / 500 mA, DFN-10 with an
exposed pad), with SHDN tied to IN:

VOUT = 0.6 V × (1 + R12/R13) = 0.6 V × (1 + 101k/5.36k) = **11.9 V**

The ADJ reference is 588–612 mV over line, load and temperature, so with **0.1 %** R12/R13 the rail
is **11.65–12.17 V** (see the [amplitude budget](#amplitude-budget)). R20 (750 Ω) on IMAX
sets a **400 mA ±10 %** current limit (500 × 0.6 V / R20), and C18 (22 nF) decouples IMAX as the
datasheet requires. C19 (10 nF) on BYP filters the reference and gives a soft start. The output
capacitors are C17 (10 µF X7R 1206, at U17) and C9/C10 at U13; the LT3065 is stable with any
ceramic of 3.3 µF or more, so no series ESR resistor is needed. The exposed pad is tied to GND pin 7
and has two GND vias to the planes.

**Load.** An output held high into 50 Ω draws ~98 mA, both outputs ~200 mA, and both outputs into
shorted BNCs ~340 mA, all below the 360 mA minimum limit. In Hi-Z mode an output draws less: ~60 mA
while high into an open circuit, ~100 mA into a short. U17 drops 15 − 11.9 = 3.1 V, so it
dissipates ~0.3 W at the firmware's highest sustained duty into 50 Ω (50 % per output), and ~0.7 W
with both outputs shorted at 67 % duty (`COMBINE 1`). Thermal shutdown is the last resort. C10
(10 µF X7R 1206) is also U13's pulse reservoir: a 1 µs, ~200 mA pulse pair droops it by ~20 mV
(0.2 %) before U17's regulation catches up.

### Power-good gate (U18)

U18 is a TI **TPS3700** window comparator watching +12V (divider R21 1 MΩ / R22 6.04 kΩ /
R23 31.6 kΩ, 1 %, decoupled by C20). Its open-drain outputs drive U13's enable pins ENA/ENB as
`LASER_PWR_OK` (R16 100 kΩ pull-up to +12V; U13's own EN pins also pull up to VDD through ~200 kΩ).

- OUTA pulls low below the **undervoltage** threshold: 11.0 V rising / 10.9 V falling (worst case:
  trips at 10.5–11.2 V, releases by 11.35 V).
- OUTB pulls low above the **overvoltage** threshold: 13.1 V (worst case 12.75–13.5 V).

Both stay at least 0.3 V outside the regulated 11.65–12.17 V band, so the gate never trips in normal
running. U13's outputs are held low:

- with J17 unplugged: +12V = 0 V, U13 is in undervoltage lockout (and U18, below its own lockout,
  holds OUTA low);
- before the PD agreement (VBUS_PD = 5 V) and with a 5 V-only charger: U17 can't regulate,
  +12V ≈ 4.7 V;
- **if the charger offers only 9 V:** +12V ≈ 8.7 V, far below the undervoltage threshold. The
  CH224K datasheet doesn't say what the chip does when 15 V is unavailable, which is why the rail
  sits well above 9 V;
- when U17 can't regulate or is current limiting, e.g. on a 12 V charger setting or an overload:
  +12V below ~11 V;
- **if U17 fails short:** +12V would follow VBUS_PD to 15 V and put ~6.3 V into the LDP-V trigger
  input; the overvoltage side switches the outputs off. It is there to catch a failed regulator,
  not to police the LDP-V's 5.2 V limit, which U17's own accuracy guarantees.

U17's own PWRGD output (open drain, 90 % of nominal) can only sink 50 µA, less than the ~180 µA that
R16 and U13's internal pull-ups source, so it is left unconnected and U18 does the job.

### +1.8 V (the camera signal supply)

Made by **U9, an NCP718xSN180** fixed 1.8 V linear regulator fed from +5 V (the NCP718 accepts
2.5–24 V in; the 3.2 V of headroom costs ~16 mW at the few mA drawn). It powers **U1–U6, all the
camera-facing logic**. Output capacitor C7 (2.2 µF), input capacitor C6 (1 µF), plus C1/C2/C3
(0.1 µF) beside U1/U3/U5.

> **Why 1.8 V.** The IDS UE-39B0XCP-E documents its I/O pins as 1.8 V sensor-level signals (see
> the camera table under [Connectors](#connectors)). Running this logic at 3.3 V would drive 3.3 V
> into 1.8 V sensor pins on all six cameras. **Don't remove the 1.8 V rail**, even though it looks
> like it powers only a few small chips.
>
> No level translator is needed. The SN74LVC04A runs at 1.65–3.6 V and the 74LVC1G04 at
> 1.65–5.5 V, and both have 5.5 V-tolerant inputs at any supply, so at 1.8 V they accept the Pico's
> 3.3 V GPIO and U12's 3.3 V output directly. At 1.8 V the drivers' 60–113 Ω output impedance also
> matches the ribbon cable, so **don't add series resistors** to the camera lines: they would slow
> the edges.
>
> Specify the **fixed 1.8 V** part (e.g. NCP718ASN180T1G, ±2 % at VOUT ≥ 1.8 V). A 1.65 V or
> 1.7 V version eats into the camera's already modest input margin.

### +3.3 V

From the Pico's 3V3_OUT (pin 36). It powers only U12 (the pixel-reset Schmitt input) and its R5
pull-up, decoupled by C8 (0.1 µF). Draw is under 1 mA.

**Power-up order.** Because U9 runs from +5 V, the 1.8 V rail can come up a millisecond or so before
the Pico's 3.3 V. In that moment U12 is unpowered and its output floats (LVC parts go
high-impedance when unpowered), so `PIXRST` and TDRSTN are briefly undefined. That is harmless,
because the cameras haven't started yet.

Nothing on this board presents 5 V or 3.3 V to J1–J6.

---

## Signal chains

Each camera signal passes through two inversions, so it arrives the right way up, with one
dedicated gate per camera.

**Sync (1 MHz)**
`GP10` → U1.2 (74LVC1G04) → `SYNC_N` → U2 ×6 (SN74LVC04AD hex) → `Sync1..6` → J1–J6 pin 5

**Trigger**
`GP11` → J10.3 → *[J10 jumper]* → `PWM_TRIG_TAP` → U5.2 → `TRIG_N` → U6 ×6 → `Trigger1..6` →
J1–J6 pin 4

### Trigger source (J10)

J10's silkscreen reads **`CH1 / TRG / MKR`** (pins 1/2/3).

- **2-3 (TRG to MKR, normal):** the cameras are triggered by the marker, which rises with CH1 and
  has its own `MARKERWIDTH`.
- **1-2 (TRG to CH1):** the cameras are triggered by every laser CH1 pulse. Prophesee specifies a
  500 ns minimum trigger pulse, so this is only dependable with `WIDTH` ≥ 500 ns. CH1 pulses exist
  only while ARMED, so with the lasers disarmed 1-2 gives the cameras no trigger (use 2-3, or ARM
  with J11 on 2-3, for camera-only work).
- **Never fit a shunt across all three pins:** that ties GP13 (through R19) to GP11.

J10.1 reaches `_PULSE_OUT_CH1` through **R19 (100 Ω)**; like TP4 it idles LOW while DISARMED. R19
is there for the laser timing. Without it, the 1-2 shunt would hang the whole ~120 mm
`PWM_TRIG_TAP` net (U5, R9, the run to J16.2) directly on the CH1 GPIO, and a transmission-line
simulation put CH1 0.4–1.7 ns behind CH2 at U7/U8: a laser delay error that depended on the jumper.
R19 cuts that to under ~0.2 ns, and costs the camera trigger 1.5–2 ns of edge, which doesn't matter
there.

**With no shunt fitted, R9 (10 k) pulls `PWM_TRIG_TAP` low,** so all six camera triggers idle low
instead of following a floating input on ~145 mm of trace (the net also runs up to J16.2). 10 k,
rather than a weaker pull-down, holds U5's 1.8 V input at ≤ 0.05 V even at worst-case input leakage,
and loads the selected GPIO by only 330 µA.

### Pixel reset (J12, optionally gated by the Pico)

J12 BNC → `PIXRST_IN` (R5 3k3 pull-up to **+3V3**) → U12.2 (**74LVC1G17** Schmitt buffer, VCC
3.3 V) → `PIXRST` → U3.2 (**74LVC1G00** NAND, 1.8 V) → `PIXRST_N` → U4 ×6 (1.8 V) → `TDRSTN1..6` →
J1–J6 pin 3. U3.1 is `PIXRST_GATE`: Pico GP16 (J15 pad 20), with R24 10 k pull-up to +3V3.

**Active LOW at the BNC: pull J12 low to reset.** Through one buffer and two inversions, TDRSTN
follows J12 directly, and TDRSTN is active low at the camera (`0 = pixels in reset`). An open BNC
idles at 3.3 V through R5 and leaves the cameras running, so an unplugged reset cable is harmless.

**The Pico gate.** U3 is a NAND, so after U4 the cameras get TDRSTN = J12 **AND** `PIXRST_GATE`:
the pixels are held in reset whenever J12 is low **or** GP16 is low. The gate idles high (R24
before the firmware runs, then the firmware drives it high while `PIXGATE` is 0), so with the gate
off J12 works on its own. GP16 drives U3 directly at 3.3 V; U3's inputs are 5.5 V-tolerant at
VCC = 1.8 V (VIH 1.17 V). The firmware side is under
[Pixel-reset gate](#pixel-reset-gate-pixgate).

**Why a Schmitt buffer at 3.3 V.** U12 must accept 3.3 V and 5 V sources on a bare BNC. At
VCC = 3.3 V it switches low below **0.89 V** and high above **~1.92–2.1 V**, with **0.5–0.8 V of
hysteresis**, and its input tolerates 5.5 V at any supply. (An ordinary LVC gate on 5 V would need
0.7 × VCC = 3.5 V to read high, which a 3.3 V source can't guarantee, and would have no hysteresis.)

| J12 driven by | Result |
|---|---|
| Nothing (open) | idles at 3.28 V → cameras **running** |
| 3.3 V or 5 V CMOS, high | **running** (≥ 1.4 V margin) |
| 5 V TTL, high (VOH min 2.4 V) | **running** (~0.3–0.5 V margin) |
| any logic low ≤ 0.8 V, open-drain, relay, switch to GND | **reset** |
| **1.8 V logic, high** | **not guaranteed**: 1.8 V sits inside the hysteresis band |

A source must sink **1.0 mA** to assert reset. A 5 V source pushes 0.5 mA back into +3V3 through
R5, which the Pico's own load absorbs.

### Laser outputs

```
GP13 → U7.2 → CH1_GATED → U13.2 (INA) → U13.7 (OUTA) → CH1_DRIVE_RAW → R6 68 Ω 2 W → CH1_DRIVE → output mode (J18, R25, R27) → CH1_OUT → J7.1
GP12 → U8.2 → CH2_GATED → U13.4 (INB) → U13.5 (OUTB) → CH2_DRIVE_RAW → R7 68 Ω 2 W → CH2_DRIVE → output mode (J19, R26, R28) → CH2_OUT → J8.1
```

**U7 and U8** are **74AHCT1G08** AND gates on +5 V (the interlock gates; see
[Laser interlock](#laser-interlock)). AHCT has TTL input thresholds (high above 2.0 V), so the
Pico's 3.3 V pulses drive them with ~1.3 V of margin. An LVC gate here would need
0.7 × VCC = 3.5 V to read high, which a 3.3 V GPIO can't guarantee.

**U13** is a TI UCC27524 dual 5 A gate driver, non-inverting, on **VDD = +12V**, with ENA/ENB on
`LASER_PWR_OK` (see [Power-good gate](#power-good-gate-u18)). Its inputs are TTL-compatible at any
VDD (high above 1.8–2.3 V, 1 V of hysteresis), so the 5 V AHCT gates drive it directly. Output
pull-up resistance is **2.5 / 5 / 7.5 Ω** (min/typ/max; it is the PMOS side that holds a steady load
high during a pulse); pull-down is 0.15–1 Ω, so the low level into 50 Ω is well under the LDP-V's
0.2 V limit.

Its local bypass capacitor **C9 (0.1 µF, 50 V)** sits right beside VDD (pin 6) with its own GND
via, and GND (pin 3) drops straight to the In1 ground plane through a via under the package. That
keeps the supply loop to roughly 1.5–2 nH, so the ~100 mA, few-ns output edges don't bounce VDD into
the top of the pulse. C10 (10 µF) is the bulk reservoir.

U13 adds ~13–25 ns of delay, the same on both laser channels to within its channel-to-channel
matching (1–2 ns), so the delay between the lasers is preserved. The laser-to-camera timing shifts
by that fixed, calibratable amount.

#### Amplitude budget

For 50 Ω mode (J18/J19 on 1-2). The target loads are PicoLas LDP-V 10-70 and LDP-V 240-100
drivers, whose trigger inputs are **50 Ω terminated** and need **4.5–5.2 V high, ≤ 0.2 V low**.
U13's output, R6/R7 and the 50 Ω input form a voltage divider, so the level delivered is
VDD × 50 / (50 + R6 + ROH), where ROH is U13's output resistance:

| Corner | VDD | R6 (68 Ω ±1 %) | ROH | Into 50 Ω |
|---|---|---|---|---|
| Low | 11.65 V (ADJ 588 mV, divider −0.2 %) | 68.68 Ω | 7.5 Ω | **4.61 V** |
| Typical | 11.91 V | 68 Ω | 5 Ω | 4.84 V |
| High | 12.17 V (ADJ 612 mV, divider +0.2 %) | 67.32 Ω | 2.5 Ω | **5.08 V** |

Every corner passes, with ~2.5 % margin at both ends. The budget assumes a 50 Ω termination at the
driver; a load 1 % high adds ~0.6 %. The trace drop from U17 to U13 is a few mV. With 1 % divider
resistors the corners would sit only ~0.7 % inside the window, which is why R12/R13 are 0.1 %.

#### Output mode

J18 sets the mode for J7 and J19 for J8. Between R6/R7 and each BNC:

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
  | Open circuit | 4.62 V | 4.84 V | 5.06 V |
  | Into 10 kΩ | 4.60 V | 4.81 V | 5.04 V |
  | Source impedance | 47.8 Ω | 48.7 Ω | 49.6 Ω |
  | Into 50 Ω (wrong mode for an LDP-V) | 2.33 V | 2.45 V | 2.57 V |

  **Why both resistors.** With the source 0.8–4.4 % below the coax's 50 Ω, the first edge reaching an
  unterminated input is 1.00–1.02 × the final level (at most ~5.14 V): no overshoot, whatever the
  cable length. A simpler version, just a 51 Ω resistor to ground with no series resistor, would be
  a ~30 Ω source and overshoot by ~25 %, to about 6 V, on any cable longer than the edge.
- **No shunt:** the 47 Ω in series and no resistor to ground, so ~12 V open circuit and
  3.35–3.66 V into 50 Ω. Always fit a shunt.
- **Dissipation in Hi-Z mode** (all 2 W 2512 parts): R27/R28 at most 0.31 W while high; R25/R26 at
  most 0.18 W while high into an open circuit, 0.32 W into 50 Ω, and 0.51 W stuck high into a
  short. The supply current while high is ~60 mA per output, against ~98 mA in 50 Ω mode.
- **Layout.** The 47 Ω resistor sits in line on the BNC centre-pin row, with jumper pin 2 on the same
  trace; pin 1 loops back over the resistor to `CHn_DRIVE`, and the 82 Ω resistor and its GND via
  sit beside the jumper. In Hi-Z mode that loop is an unterminated stub of ~14 mm, far too short to
  matter at these edge rates. From the 47 Ω resistor onward the two channels are mirror images about
  the line between the J7 and J8 centre pins. R6 and R7 are not symmetric about that line, so CH1's
  trace from R6 takes larger 45° corners to make up the difference: U13 to the 47 Ω resistor is
  19.593 mm on both channels, and so is every path on to the BNCs, in both modes. The silkscreen
  reads `LASER n OUT`, with `50Ω` and `HiZ` beside the pin pairs.

> **Match the output mode to the load.** In 50 Ω mode an open-circuit or high-impedance load sees
> ~12 V; use Hi-Z mode for those.
>
> **One driver per output, no BNC tees.** A transmission-line simulation (typical corners, 50 Ω
> mode) gives: J7 and J8 joined into one 50 Ω input → 3.4 V per pulse (the idle channel's 68 Ω sinks
> half), and 6.9 V where the pulses overlap (DELAY < WIDTH), above the LDP-V's 5.2 V damage limit;
> one output teed to two drivers → 3.0 V each. The PiDG itself survives either (see
> [Board output rating](#board-output-rating)).
>
> PicoLas's acceptance test applies: a scope with **50 Ω input termination** must read 0 to
> ~4.9 V. The LDP-V's absolute maximum on its trigger input is 15 V, so an unterminated reflection
> can't exceed it.

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
| U10.2 | `LASER_EN_TAP` | R3 3k3 to +5 V, also on J16.1 |
| U10.4 | `LASER_EN` | → U7.1, U8.1 |

**Fails safe.** R8 holds U10 pin 1 low when J11 has no shunt, so the default is *disabled*. A shunt
on J11 **1-2** enables the hardware interlock (the firmware must also be ARMED; see
[Boot and arming](#boot-and-arming)); **2-3** disables it. With the 1-2 shunt fitted, R2 wins:
5 V × 10/(3.3+10) ≈ **3.76 V**, against U10's **VIH of 2.0 V**, about **1.76 V of margin**. Because
U10 is AHCT, an external interlock signal on J16.1 can be 3.3 V logic.

**E-stop switch: wire it across J11 1-2.** Replace the shunt with a *normally-closed* switch between
J11.1 and J11.2. Closed, it acts like the shunt; pressing it or breaking its cable opens the circuit
and R8 pulls U10.1 low, so the stop fails safe. J16.1 is the wrong place for an E-stop, because it
is enabled when open. The silkscreen beside J11 reads `LASER INTERLOCK: ON = 1-2` and
`E-STOP: NC SWITCH ACROSS 1-2`, and the pins are marked **ON** (1-2, lasers enabled) and **OFF**
(2-3).

The original Teensy design had no pull-down here and was *enabled* with the header empty. R8 is the
one deliberate change to the interlock's behaviour.

**Three gates in series.** The firmware's ARM state acts before U7/U8 (DISARMED holds their pulse
inputs LOW), the J11/U10 interlock acts at U7/U8, and the power-good gate (`LASER_PWR_OK`, see
[Power-good gate](#power-good-gate-u18)) acts on U13's ENA/ENB. Any one of them alone forces both
BNC centre pins to 0 V, and none can enable a laser that another has disabled. U10 alone carries the
user interlock; U13's enables carry only the power-good gate.

**Pico removed, J17 powered.** J17 can power the board with no module fitted. U7/U8's pulse inputs
would then float, and an enabled interlock would pass whatever they picked up, so **R17/R18
(10 kΩ)** hold `_PULSE_OUT_CH1`/`_PULSE_OUT_CH2` low at the socket (J14.17/.16) and the laser
outputs stay at 0 V. With the Pico fitted they cost 0.33 mA per GPIO while high. The camera lines
are not guarded the same way: with no module, `PWM_1MHz` floats and U12 is unpowered (no +3V3), so
Sync and TDRSTN at the cameras are undefined. That is a nuisance, not a hazard: fit the Pico before
connecting cameras.

---

## Connectors

### J1–J6: cameras

2×5 IDC headers, 2.54 mm. Identical to the Teensy design, pin for pin, and mapped 1:1 onto the 8-pin
I/O connector of the **IDS uEye UE-39B0XCP-E** (IDS part 1011378) for pins 1–8:

| Pin | Board | Camera (IDS datasheet, verbatim) |
|---|---|---|
| 1 | NC | Voltage output 1.8 V, max. 50 mA |
| 2 | GND | Ground (GND) |
| 3 | `TDRSTNn`: pixel reset, active low | TDRSTN (sensor), 1.8 V |
| 4 | `Triggern` | Trigger input (sensor), 1.8 V |
| 5 | `Syncn`: 1 MHz | SYNC (sensor), 1.8 V |
| 6 | NC | – |
| 7 | GND | Ground (GND) |
| 8 | NC | USB Power: 5 V, max. 400 mA |
| 9, 10 | NC | (no counterpart) |

Source: IDS UE-39B0XCP-E-GL datasheet, rev 2026-01-09. **All three signals are 1.8 V,** driven by
U2/U4/U6 on the 1.8 V rail. Delivered levels: VOH ≥ 1.5 V and VOL ≤ 0.2 V at light load over
temperature, against a 1.8 V CMOS input's typical VIH of ~1.17–1.26 V and VIL of ~0.63 V. IDS
doesn't publish the camera's own thresholds or input pull, so confirm on the bench.

> **Pins 1, 6 and 8 are unconnected on the board** (so are 9 and 10): bare plated holes with no
> copper to any net, so the board can never short the camera's own supplies (pin 8 is its USB 5 V
> and pin 1 its 1.8 V output). The only remaining risk is a harness that joins pin 1 or 8 to a
> ground wire: build it with only wires 2, 3, 4, 5 and 7. Pin 6 is undocumented; don't assume it is
> a ground.
>
> **Set every camera as a sync *slave*.** The IMX636's SYNC pin is bidirectional (it drives when
> the sensor is master), and the board drives pin 5 push-pull. A camera left in master mode would
> fight U2.

### BNCs (50 Ω)

J7 Laser 1 (out), J8 Laser 2 (out), J12 Pixel reset (**in**, active low, 3.3 V/5 V/open-drain
compatible; see [Pixel reset](#pixel-reset-j12-optionally-gated-by-the-pico)). Shells on GND.
J7/J8 drive a 50 Ω or a high-impedance load, set per channel by J18/J19 (see
[Output mode](#output-mode)).

### J17: USB-C power input

HRO TYPE-C-31-M-12, on the top edge with its face flush with the board edge. Power only: VBUS,
CC1/CC2 to U14, GND and shell to GND; D+/D−/SBU are not connected. Use a USB-PD charger that offers
15 V, in practice any PD charger rated 30 W or more. Programming and serial go through the Pico's own
USB port.

### Headers

| Ref | Type | Pins |
|---|---|---|
| J10 | 1×3 vertical | 1 `_PULSE_OUT_CH1` (CH1 monitor) · 2 middle → U5 · 3 `PWM_Trig` |
| J11 | 1×3 vertical | 1 pull-up · 2 → U10.1 · 3 GND |
| J18 | 1×3 vertical, Laser 1 output mode (pin 1 at the top) | 1 `CH1_DRIVE` · 2 `CH1_OUT` (J7) · 3 `CH1_TERM` → R27 |
| J19 | 1×3 vertical, Laser 2 output mode (mirrored: pin 1 at the bottom) | 1 `CH2_DRIVE` · 2 `CH2_OUT` (J8) · 3 `CH2_TERM` → R28 |
| J16 | 1×3 right-angle, top edge between the Pico and J17 | 1 `LASER_EN_TAP` · 2 `PWM_TRIG_TAP` · 3 GND |
| TP3 | 1×2 right-angle, top edge | 1 `PWM_1MHz` · 2 GND |
| TP4 | 1×2 vertical | 1 `_PULSE_OUT_CH2` · 2 GND |

**J16.1 (ENABLE) doubles as an external interlock input:** pull it LOW (a switch or open-collector
to J16.3, or 3.3 V/5 V logic) to turn off both lasers. It is *enabled when open* (R3 pulls it up),
so a broken cable leaves the lasers enabled; J11 remains the fail-safe interlock. **Never fit a
shunt on J16:** on pins 2-3 it grounds `PWM_TRIG_TAP`, which through J10 shorts a GPIO to ground
and silently kills all six camera triggers.

The silkscreen spells this out: `EN` / `TRIG` / `GND` under the pins, then `J16: NEVER FIT A
SHUNT`, `EN IN: PULL LOW = LASERS OFF`, `TRIG OUT: CAMERA TRIGGER (MONITOR)` and
`NOT FAIL-SAFE: E-STOP ON J11`. J16 and TP3 both sit on the top edge (TP3 left of the Pico, J16
between the Pico and J17), and their pins overhang it by the same 2.1 mm.

**TP3 and TP4** are scope points with their own ground pin. TP4 (like J10.1) idles LOW while the
firmware is DISARMED, and is labelled `CH2` / `GND` / `SCOPE ONLY`. J10 stands about 9 mm east of
TP4, so the two headers can't be mistaken for one row, and carries
`CAMERA TRIGGER: TRG-MKR = MARKER / TRG-CH1 = LASER 1` to the right of its `CH1 TRG MKR` pin labels.

The TRIG and 1 MHz taps (J16.2, TP3.1) feed U5 and U1, which run from the 1.8 V rail: an external
signal there needs **VIH ≥ 1.17 V, VIL ≤ 0.63 V**, and the inputs are 5.5 V-tolerant. But both
taps are normally driven by a Pico GPIO, so an external source would fight it. Treat them as monitor
points.

### MH1–MH4

M3, unplated, mechanical only.

---

## First-board checks

Ordered by what would bite hardest.

1. **Bench-verify the laser outputs before connecting a laser driver.** With J17 on a 15 V PD
   charger, check +12V at C17 (11.65–12.17 V, typically 11.9 V) and that `LASER_PWR_OK` (U13 pins
   1/8) is high (~12 V). Fit J11 on 1-2 and J18/J19 on 1-2 (50 Ω mode), send `ARM`, then scope J7
   and J8 through a **50 Ω-terminated** input:
   - amplitude 0 V to 4.61–5.08 V (typically ~4.84 V); the budget rests on datasheet corners for
     U17's reference and U13's output resistance, so a measurement closes it;
   - CH2 rising exactly DELAY after CH1 (e.g. `DELAY 10000` → 10.000 µs, `DELAY 13` → 13.3 ns),
     and MARKER rising with every CH1 pulse for minutes at `FREQ 3000`;
   - MARKER rising with every CH1 pulse at a FREQ whose period is not a whole number of cycles,
     e.g. `FREQ 7000`;
   - the first pulse after `ARM` full width, and no two CH1 pulses closer than 1/FREQ while a host
     loops `ARM`/`DISARM` as fast as it can;
   - J7/J8 at 0 V after `DISARM`; after a reset (a power cycle of both J17 and the Pico USB, since
     neither the board nor the Pico 2 W has a reset button, and a watchdog timeout forced over SWD
     as described under [Boot and arming](#boot-and-arming)); and, while ARMED with pulses running,
     with J17 unplugged and while it is plugged back in;
   - Hi-Z mode: J18/J19 on 2-3 and the scope at 1 MΩ, 0 V to 4.62–5.06 V, with no overshoot at the
     far end of a 2 m cable (the source is ~49 Ω).
2. **Check the charger's PD behaviour.** The CH224A datasheet does not say what it does when the
   charger lacks the requested 15 V. The board is safe either way (U18 keeps the lasers disabled
   below ~11 V), but a small charger may leave them disabled. Measure VBUS_PD (C12) with the charger
   you will deploy. This also confirms that the CH224A completes the PD contract with DP/DM shorted
   at the chip (a connection carried over from the CH224K; WCH documents it only for the CH224K).
   If it does not, VBUS_PD stays at 5 V: lasers off, logic still running.
3. **Bench-confirm the camera I/O before plugging in six cameras.** IDS documents the pins as 1.8 V
   but publishes no VIH/VIL, input pull or absolute maximum. With one camera, measure TDRSTN,
   Trigger and Sync at the camera end of the harness, and confirm pin 5 is not being driven by the
   camera (i.e. that it is configured as a sync slave).
4. **No 50 Ω termination on the J12 pixel-reset input** — only R5's 3k3 pull-up and U12's CMOS
   input. U12's 0.5–0.8 V of hysteresis absorbs moderate ringing from an unterminated coax run. Do
   *not* add a 49.9 Ω resistor to ground as-is: against R5 it would hold J12 at ~50 mV, keeping all
   six cameras in reset unless the source actively drives high.
5. **Before the first USB-C PD power-up, check the fine-pitch parts for solder bridges.** J17's and
   U17's pads are 0.5 mm pitch and U16's 0.65 mm, on lead-free HASL. With no power applied, check
   that VBUS_PD is not shorted to GND, CC1 or CC2 (at J17 and U14 pins), and that +5V_PD and +5V are
   not shorted to GND (at U16). U14's CC pins are rated to 32 V, but a VBUS-to-CC bridge would put
   VBUS_PD on the cable's CC line. U14 pins 1 (VHV) and 8 (VBUS) sit directly on VBUS_PD through
   the 0 Ω R11/R15, so also check U14 pin 1 against pin 2 (GND) and pin 8 against pin 9 (CFG1, rated
   only 3.8 V). Check U17's IN (pins 1-3) against OUT (pins 9-10) too: a bridge there would put 15 V
   on +12V (U18 would then hold the outputs off). Also confirm that J17's four shell legs are
   soldered (they are through-hole with no paste).

**Not an open item: Wi-Fi / Bluetooth.** The firmware doesn't use the radio; the Pico 2 W is fitted
only because it is easier to buy than the plain Pico 2. All four copper layers run solid under the
module, including its antenna, which shortens the radio's range. That is acceptable even for a
future wireless firmware, which would aim for short, Bluetooth-like range (a few metres), so no
antenna keep-out is needed.

---

## Manufacturing notes

- **No vias inside SMD pads,** apart from the two thermal vias in each of U14's and U17's exposed
  GND pads, which is normal practice. Every other via drill is at least 0.2 mm from any SMD pad
  edge, so the standard **tented** via option is correct, and filled-and-capped via-in-pad (a paid
  option on 4-layer boards) is not needed. On the JLC order form choose *Tented*, not *Plugged*.
- **No controlled impedance is needed.** The longest critical run (U13 to J7/J8 through the
  output-mode block, ~50 mm, Z0 ≈ 55 Ω) is electrically short compared with the driver's edges.
  Order *Impedance control: No*.
- **Copper keep-outs:** zone copper stays 0.5 mm from the board edge on all four layers, and a
  3 mm-radius keep-out keeps all copper (including the In2 +5 V plane) away from each M3 hole, so a
  metal screw or standoff can't touch a plane in the hole wall.
- **Ground stitching:** 47 stitching vias along the board edges and in the south-east quadrant,
  plus local vias at the decoupling capacitors and IC ground pins.
- **Silkscreen** shows the Pico outline, the `CONTROL / PROGRAM` and `POWER ONLY` port labels, and a
  pin-1 mark (a module fitted the other way round would put the board's +5 V on one of its GPIO
  pins). J10, J11, J16, J18 and J19 are labelled as described above. All board text is at least
  1.0 mm high.

**JLCPCB order:** the board is set up for full assembly by JLCPCB, with every SMD and
through-hole part fitted, so nothing needs soldering on delivery. `fab/jlc/JLC_ORDER.md` is the
checklist: order-form settings, remarks to paste, the parts that need Global Sourcing (U9 NCP718
was out of stock on 2026-09-25 and 2026-10-02; U14 changed from the discontinued CH224K to the
in-stock CH224A on 2026-10-02), rotations to
check in the placement preview, the cost estimate, what to do on delivery (plug in a Pico 2 WH,
flash the firmware, fit J10, wire the E-stop to J11), and enclosure notes. The JLC BOM carries an
LCSC number on every line; through-hole parts sit in the placement file at their pad centre,
because their footprint origins are on pin 1. The back silkscreen carries JLC's `JLCJLCJLCJLC`
order-number placeholder.

---

## Files

| Path | What |
|---|---|
| `PiDG_Pico.kicad_sch` | schematic |
| `PiDG_Pico.kicad_pcb` | board |
| `PiDG_Pico_BOM.csv` | parts list (hand-maintained; KiCad's `export_bom` ignores DNP attributes) |
| `PiDG_Pico_CPL.csv` | placement file, all 82 placed parts (KiCad columns), mounting holes excluded |
| `fab/jlc/PiDG_Pico_JLC_BOM.csv`, `fab/jlc/PiDG_Pico_JLC_CPL.csv`, `fab/jlc/JLC_ORDER.md` | JLCPCB full-assembly upload files (all 82 parts, LCSC numbers) and the order checklist |
| `fab/gerbers/`, `fab/PiDG_Pico_Gerbers.zip` | gerbers, Excellon drill files (plated and unplated) and job file, from the board's stored plot settings |
| `libs/PiDG_Local.kicad_sym` | Pico 2 W, UCC27524, LT3065 and TPS3700 symbols |
| `libs/PiDG_Local.pretty/` | `*_EdgeTrim` footprint variants (see below) |
| `libs/RPi_Pico.pretty/` | official RPi castellated-module footprint (unused: the board uses sockets) |
| `../src/` | firmware: `board.h` (pin map), `pulse_timing.h` (timing maths and checks), `pio_pulse.*` (PIO programs), `laser_gate.*` (CH1/CH2 gate, start-up hook), `protocol.*` (serial commands), `main.cpp` (arming, hold-off, watchdog) |
| `../platformio.ini` | build configuration: platform pinned to an exact commit; `pico2w` (default) and `pico2` builds |
| `../tools/timing_check/` | checks `pulse_timing.h` against a cycle-level PIO model (see its README) |

**The `*_EdgeTrim` footprints.** J16 and TP3 overhang the board edge, and J17's face is flush with
it, so their stock silkscreen outlines run off the board and trip `silk_edge_clearance`. The variants
in `libs/PiDG_Local.pretty/` are the stock footprints with that off-board silkscreen clipped:
**identical part, identical pads, silkscreen only.** Order the standard parts; the placement file
carries the stock package names for that reason. To trim the silkscreen on another overhanging
connector, make a variant the same way rather than editing the footprint on the board, or you will
trade a `silk_edge_clearance` warning for a `lib_footprint_mismatch` one.

**Re-running the checks.** DRC from Pcbnew, or
`kicad-cli pcb drc --schematic-parity --refill-zones PiDG_Pico.kicad_pcb`; ERC with
`kicad-cli sch erc --format json PiDG_Pico.kicad_sch`. The ERC JSON reports every coordinate and
length at 1/100 of the true mm value despite declaring `"coordinate_units": "mm"`: multiply by 100.

**Current state:** DRC 0 violations, 0 unconnected items; ERC 0 violations. The schematic-parity
check also reports 199 *warnings*, none of them electrical:
- 166 net-name mismatches: board net names lack the `/` root-sheet prefix the schematic gives local
  labels (`TDRSTN1` vs `/TDRSTN1`, same connections), and unused J14/J15 socket pads carry no net
  instead of `unconnected-(…)`;
- 29 field mismatches: `Datasheet`/`Description` text differs between schematic and board;
- 4 extra footprints: MH1–MH4 exist only on the board, by design (U11, the Pico, is marked
  not-on-board in the schematic).

A pad-by-pad net comparison with the prefix stripped matches exactly.

**Take care with "Update PCB from Schematic".** U11 is marked *not on board* and *not in BOM*, so a
sync won't try to place a Pico footprint, but the net-name differences above make it noisy. Review
its change list before accepting it.
