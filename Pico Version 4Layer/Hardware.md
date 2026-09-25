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
| Power | **USB-C PD input (J17, 15 V)** for the laser driver and the whole board; the Pico's own USB still powers the logic when J17 is unplugged |
| Rails | **1.8 V** (camera I/O) · 3.3 V (MCU, pixel-reset input) · 5 V (logic, Pico VSYS) · **12 V** (11.9 V, laser driver U13, from J17 only) |
| Design rules | 0.2 mm clearance, 0.2 mm track, 0.6/0.3 mm via, 0.25 mm copper-to-edge |
| Placeable parts | 75, plus 4 NPTH mounting holes |

Layer use:

| Layer | Purpose |
|---|---|
| F.Cu | signal + GND pour |
| In1.Cu | solid GND plane |
| In2.Cu | solid +5 V plane |
| B.Cu | signal + GND pour |

The 1.8 V camera rail has no plane — it is distributed as a 0.5 mm F.Cu trunk. The 3.3 V
rail is a single 0.3 mm B.Cu run from J15 to the pixel-reset input stage.

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

The finest pitch on the board is J17's USB-C receptacle and U17 (LT3065, DFN-10 with an exposed
pad), both 0.5 mm, and U16 (SC-70-6, 0.65 mm). There is no BGA. Quick-turn fabs routinely assemble USB-C
receptacles on lead-free HASL, but the finish is uneven enough that J17 is worth inspecting for
bridges; see Open item 1 for the continuity check before first power-up. Most passives and
SOT-23s use `_HandSolder` footprint variants (U16, U17, L1 and U14's exposed pad are the exceptions),
and HASL arrives pre-tinned and tolerates rework better than OSP, whose coating degrades with
repeated heat. A lead-free finish solders fine
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
| VBUS | 40 | J15.1 | **not connected** (see Power) |

All eight module grounds are bonded. Every other socket pad is unconnected — and, once the
module is seated, physically inaccessible. There is no GPIO breakout header.

**The module body occupies roughly x 158–180, y 31–82 in board coordinates**, with its micro-USB at
the top board edge (the sockets start at y = 32.385; they were moved 13.97 mm up on 2026-09-25 so
the control port can be reached through the enclosure wall). Nothing may be placed there. The
silkscreen labels the two top-edge ports `CONTROL / PROGRAM — PICO MICRO-USB` and
`POWER ONLY — USB-C PD 15 V` (J17).

---

## Firmware pin map

The firmware (`../src/`) drives all four signals from pio0 state machines (SM0 CH1, SM1 CH2,
SM2 MARKER, SM3 SYNC), so any GPIO works — there is no PWM-slice constraint. CH1/CH2 reach
their pads only while ARMED; otherwise `src/laser_gate.cpp` drives them LOW.

| Constant | GPIO | Board net | Drives |
|---|---|---|---|
| `kPinSync` | 10 | `PWM_1MHz` | U1 → U2 → Sync1‑6 |
| `kPinMarker` | 11 | `PWM_Trig` | J10.3 → (jumper) → U5 → U6 → Trigger1‑6 |
| `kPinCh2` | 12 | `_PULSE_OUT_CH2` | U8 → U13 → J8 (Laser 2); R18 10 k to GND |
| `kPinCh1` | 13 | `_PULSE_OUT_CH1` | U7 → U13 → J7 (Laser 1); R17 10 k to GND; R19 100 Ω → J10.1 |

**CH1 is the higher GPIO and CH2 the lower** — the opposite order to the Teensy original
(D2 = CH1, D3 = CH2). Do not "tidy" these into ascending order.

These constants and the schematic have drifted apart once before, which made the whole board
look inert. `src/board.h` now carries this table as a comment block; keep both in step.

### Timing limits

The firmware (`realizeTiming()` in `src/pulse_timing.h`) re-validates the whole parameter set
on every command, on the **realized** values (after rounding to whole 6.667 ns PIO cycles). It
imposes **no laser-driver ratings** — pulse width, duty and pulse spacing depend on the attached
driver (the PicoLas LDP-V datasheets were only the reference for the electrical interface), so set
values within your driver's ratings. The checks are the ones that keep the waveform correct:

- **Pulse pairs stay separated:** `DELAY ≤ 1/FREQ − 2 × WIDTH`, so CH2 ends at least one WIDTH
  before the next pair's CH1 rises. That also caps WIDTH at half the period.
- **Minimum width:** WIDTH and MARKERWIDTH realize to ≥ 3 cycles (≤ 16 ns is **rejected**, not
  clamped; the shortest pulse is 20.000 ns). The program itself needs `DELAY ≤ 1/FREQ − WIDTH − 5
  cycles`, which binds only at 3–4-cycle widths.
- The marker period (MARKERDIV × period ≤ 2³² − 1 cycles) and the SYNC divider range.

**Board output rating: nothing to observe.** R6/R7 are **2 W 2512** resistors and U17 is a 500 mA
regulator with a 400 mA current limit, so the outputs carry any duty the firmware accepts (up to
50 % per output, 67 % with `COMBINE 1`). An output held high into 50 Ω draws ~98 mA and dissipates
0.66 W in its resistor; both outputs together draw ~200 mA. Even an output held high into a
shorted BNC dissipates at most 1.9 W, and both shorted together draw ~340 mA, under U17's
360 mA minimum limit.

**Combined mode (`COMBINE 1`).** Both pulses of every pair go to **both** laser outputs, for one
light source producing both PIV pulses, or two sources fired in sync with the same double pulse.
The CH1 and CH2 state machines then each run a dual-pin copy of the pulse program (`SET PINS, 3`
on GP12–GP13; identical cycle timing), and the shared PIO output latch makes each laser pin carry
CH1's pulse and then CH2's, exactly DELAY later (checked cycle-exact in
`tools/timing_check/check_combined.py`). Each driver then sees two pulses per period (check its
ratings; the firmware imposes none). The only extra rule is that the pulses stay separate on the
shared pins, `DELAY ≥ WIDTH + 1 PIO cycle` (6.667 ns). At `DELAY = WIDTH`, CH2 rises on the cycle
CH1 falls, the higher-numbered state machine wins the latch, and the two pulses fuse into one of
2 × WIDTH. COMBINE can only be changed while DISARMED. **Do not
use a BNC tee instead**: tying J7 and J8 together, or splitting one output to two drivers, gives
3–3.4 V pulses, or 6.9 V where the pulses overlap (see Laser outputs).

### Timing: what you set is what you get

- **Every reply shows the realized value**, e.g. `DELAY 1003` → `OK DELAY=1003 (actual
  1000.000 ns, 150 cyc)`. `STATUS` lists all of them. The user never has to correct a setting
  for quantization or for fixed instruction overheads.
- **CH2 rises exactly DELAY after CH1** (to the nearest 6.667 ns cycle). Firmware before
  this revision loaded CH2 two cycles short, so it fired 13.33 ns early — a 1.3 % velocity error
  at 1 µs separation. The fix is exact in a cycle-accurate model of the PIO; see
  `../tools/timing_check/`.
- **MARKER is phase-locked to CH1**: its period is exactly MARKERDIV × the laser period in
  cycles. Before, the two periods were rounded separately, via a period truncated to whole
  nanoseconds, so MARKER drifted off the pulse it marks — e.g. by 5 cycles per marker period
  at 3 kHz with MARKERDIV 100.
- **SYNC** is realized with the PIO's 8.8 fixed-point clock divider. The default 1 MHz is
  exact (divider 75). Other values are reported with their actual average frequency; a
  fractional divider adds 1-cycle (6.667 ns) edge jitter, which the reply notes.

### Boot and arming

- **The firmware boots DISARMED.** A pre-init hook (`src/laser_gate.cpp`, `.preinit_array`
  priority 00110) drives GP12/GP13 LOW from SIO right after the SDK's peripheral reset, before
  clock setup, USB, the Pico 2 W's CYW43 init and `setup()`. They stay LOW until the host sends
  `ARM` over the Pico's USB serial port. SYNC and MARKER start as soon as `setup()` applies the
  defaults and keep running while DISARMED.
- **`ARM`** (exactly that word, no argument) restarts CH1, CH2 and MARKER together, so the
  first laser pulse is full width and in phase. It replies at once; the pulses begin after a
  **restart hold-off** of one pulse period (the longer of the old and new periods, ≤ 1 s),
  measured from when the laser pads last carried pulses. Pulse-setting changes while armed go
  through the same restart. The hold-off keeps the laser pulse spacing ≥ the set period under
  any command sequence, so a host looping ARM/DISARM cannot fire faster than FREQ. MARKER pauses
  during it.
- **`DISARM` can never be refused and takes effect at once.** The six characters `DISARM`
  (any case) anywhere in the input disarm immediately — mid-line, inside an over-long line,
  after backspace edits — and cancel a pending start. Lines may end with CR, LF or CRLF, so
  PuTTY, Tera Term, screen and minicom all work.
- **J7/J8 pulse only when all three are true:** firmware ARMED, J11 on 1‑2 (hardware
  interlock), and `LASER_PWR_OK` (12 V rail in regulation).
- **Watchdog.** A 3 s hardware watchdog, fed only from the main loop, reboots the chip if the
  firmware hangs; it comes back DISARMED and `STATUS` shows `RESET=WATCHDOG` (and a
  `WDT_RESETS` count). There is no command that hangs the firmware; to test the watchdog, write
  `0x80000000` (TRIGGER) to `WATCHDOG_CTRL` (`0x400d8000`) over SWD with the core running (a
  halted core pauses the watchdog). Replies are written a whole line at a time within a 250 ms
  budget, and once a host stops reading, later replies stop waiting until it drains again — so a
  host that stops reading delays a queued DISARM by at most about 250 ms in total and cannot trip
  the watchdog. Replies that could not be sent are dropped a whole line at a time, and their
  bytes are counted in `STATUS` as `TX_DROPPED`.
- **Host scripts** must now send `ARM` after every reset, and should check `RESET=` in
  `STATUS` before doing so (require an operator action after `RESET=WATCHDOG`). `STATUS` has
  more lines than before; parse it by key, not by line count.
- **Losing the USB link does not disarm.** The firmware does not watch the USB connection, and J17
  alone keeps the board powered, so a pulled cable, a sleeping PC or a killed host script leaves an
  ARMED board pulsing with no serial path left for `DISARM`. The hardware stops are J11 (off 1‑2),
  J16.1 pulled low, or unplugging J17.

**Residual hazards the firmware cannot remove** (both need a reset to land during a laser
pulse, so the chance per event is at most the duty):

- *A reset mid-pulse* (watchdog, or `pio run -t upload`'s 1200-baud reboot) releases
  the pad rather than driving it LOW; R17/R18 plus the pad pull-down discharge the node in an
  estimated 70–150 ns, so that one pulse can end up to that much past WIDTH.
  Measure it (scope GP13 while forcing a watchdog reset). If it matters, fit R17/R18 = 2.2 k
  (τ ≈ 30 ns; 1.5 mA while high, well inside the GPIO's drive).
- *A debugger warm reset (SYSRESETREQ)* leaves PIO running while the bootrom latches the pads,
  so a pad caught HIGH can stay HIGH until the pre-init hook runs — milliseconds. **Before any
  SWD session or debugger reset: DISARM and open J11 (or unplug J17).** The one deliberate
  exception is the bench test of Open item 1, done into a 50 Ω scope input with no laser driver
  connected.

---

## Power

Two inputs. **J17 (USB-C, power only)** is the main supply; the **Pico's own USB** carries data
and can run everything *except the laser outputs* on its own.

```
J17 USB-C ─ U14 CH224K (asks the charger for 15 V) ─ VBUS_PD (5 V until negotiated, then 15 V)
   ├─ U15 AP63205WU buck ─ +5V_PD ─ U16 LM66100 ideal diode ─┐
   │                                                        ├─ +5V plane = Pico VSYS
   │               Pico USB VBUS ─ Pico's own Schottky D1 ───┘
   └─ U17 LT3065 (adj., 500 mA, 400 mA limit) ─ +12V (11.9 V) ─ U13 VDD (C9, C10, C17)
        U18 TPS3700 window on +12V (11.0–13.1 V) ─ LASER_PWR_OK ─ U13 ENA/ENB  (R16 100k pull-up)
```

**VBUS_PD.** U14 is a WCH CH224K PD sink. R10 = 56 kΩ on CFG1 requests **15 V** (CH224K table:
6k8 = 9 V, 24k = 12 V, 56k = 15 V, open = 20 V — never leave R10 off). CFG2/CFG3 are grounded,
DP/DM are shorted at the chip (the datasheet's way of disabling the QC/BC1.2 protocols), and PG
is unused. VDD is fed through R11 = 1 kΩ (1206, 0.14 W at 15 V) and the VBUS sense pin through
R15 = 10 kΩ, both per the datasheet. Until the PD contract completes VBUS_PD sits at 5 V; after
it, 15 V. The CH224K has no output switch, so everything downstream must tolerate both, and
does. Any charger rated **above 27 W** must offer 15 V under the USB-PD rules; a smaller one may
not, and the laser outputs then stay disabled (see below). C12 (10 µF) is the only large
capacitor on VBUS_PD, which keeps the board near the USB-C 10 µF sink limit.

**+5 V.** U15 (Diodes AP63205WU, fixed 5.00 V ±1 %, 3.8–32 V in) makes +5V_PD. With VBUS_PD
still at 5 V it runs in 100 % duty dropout and passes ~4.9 V. U16 (TI LM66100) ORs +5V_PD
into the **+5V plane, which is the Pico's VSYS pin** (J15.2). U16's CE is tied to its own
VOUT — TI's always-on reverse-blocking connection — so +5V_PD is never back-driven.

**Pico VBUS (pin 40, J15.1) is deliberately not connected.** Previous revisions tied VBUS to
VSYS to recover the Schottky drop, which was only legal while USB was the sole source. With J17
feeding VSYS, that tie would back-feed the USB host. Now the Pico's USB reaches VSYS only through
its own Schottky D1 (MBR120VLSFT1G, ~0.28 V at 0.1 A). With both inputs present, U16's ~5.0 V
beats D1's ~4.7 V and J17 carries the load, while D1 blocks any flow back into the host. With
the Pico USB alone, +5V sits at ~4.7 V typical: U9 and the 74AHCT gates run happily (AHCT is
specified from 4.5 V, so a host that sags below ~4.8 V puts them just outside their rated
range), and the lasers are off because there is no 12 V.

Consumers on +5V: the Pico (VSYS), U7, U8, U10 (74AHCT1G08), **U9 (the 1.8 V LDO's input)**,
and the R2/R3 pull-ups. Decoupling C4, C5 (0.1 µF), C6 (1 µF, U9's input).

**+12 V — the laser driver rail.** U17 is an Analog Devices **LT3065** (adjustable, 45 V / 500 mA,
DFN-10 with an exposed pad) with SHDN tied to IN:
VOUT = 0.6 V × (1 + R12/R13) = 0.6 V × (1 + 101k/5.36k) = **11.9 V**. The ADJ reference is
588–612 mV over line, load and temperature, so with **0.1 %** R12/R13 the rail is **11.65–12.17 V**
(see the laser amplitude budget under Signal chains). R20 (750 Ω) on IMAX sets a **400 mA ±10 %**
current limit (500 × 0.6 V / R20), and C18 (22 nF) decouples IMAX as the datasheet requires. C19
(10 nF) on BYP filters the reference and soft-starts it. The output capacitors are C17 (10 µF X7R
1206, at U17) and C9/C10 at U13. The LT3065 is stable on any ceramic of 3.3 µF or more, so the
series ESR resistor the LP2951 needed (R14) is gone. The exposed pad is tied to GND pin 7 and has
two GND vias to the planes.

Load: an output held high into 50 Ω draws ~98 mA, both outputs ~200 mA, and both outputs into
shorted BNCs ~340 mA, all below the 360 mA minimum limit. U17 drops 15 − 11.9 = 3.1 V, so it
dissipates ~0.3 W at the firmware's highest sustained duty into 50 Ω (50 % per output), and
~0.7 W with both outputs shorted at 67 % duty (`COMBINE 1`). Thermal shutdown is the last resort.
C10 (10 µF X7R 1206) is also U13's pulse reservoir: a 1 µs, ~200 mA pulse pair droops it by
~20 mV (0.2 %), before U17's loop catches up.

**Power-good gate (U18).** U18 is a TI **TPS3700** window comparator on +12V (divider R21 1 MΩ /
R22 6.04 kΩ / R23 31.6 kΩ, 1 %, decoupled by C20). Its open-drain outputs drive U13's ENA/ENB as
`LASER_PWR_OK` (R16 100 kΩ pull-up to +12V; U13's own EN pins also pull up to VDD through
~200 kΩ). OUTA pulls low below the **undervoltage** threshold, 11.0 V rising / 10.9 V falling
(worst case: trips at 10.5–11.2 V, releases by 11.35 V). OUTB pulls low above the **overvoltage**
threshold, 13.1 V (worst case 12.75–13.5 V). Both stay at least 0.3 V outside the regulated
11.65–12.17 V band, so the gate never trips in normal running. U13's outputs are held low:

* with J17 unplugged — +12V = 0 V, U13 in UVLO (and U18 below its own UVLO holds OUTA low);
* before the PD contract (VBUS_PD = 5 V) and with a 5 V-only charger — U17 in dropout, +12V ≈ 4.7 V;
* **if the charger only offers 9 V** — +12V ≈ 8.7 V, far below the undervoltage threshold. The
  CH224K datasheet does not say what it does when 15 V is unavailable, which is why the rail sits
  well above 9 V;
* in dropout or current limit, e.g. on a 12 V PDO or under an overload — +12V below ~11 V;
* **if U17 fails short** — +12V would follow VBUS_PD to 15 V and put ~6.3 V into the LDP-V
  trigger input; the overvoltage side switches the outputs off. It is there to catch a failed
  regulator, not to police the 5.2 V limit, which U17's own accuracy guarantees.

U17's PWRGD output (open drain, 90 % of nominal) can only sink 50 µA, less than the ~180 µA that
R16 and U13's internal pull-ups source, so it is left unconnected and U18 does the job.

**+1.8 V — the camera I/O rail.** Generated by **U9, an NCP718xSN180** fixed 1.8 V LDO,
fed from +5 V (NCP718 accepts 2.5–24 V in; the 3.2 V of headroom costs ~16 mW at the few mA
drawn). Consumers: **U1–U6, the entire camera-facing logic bank**. Output capacitor C7
(2.2 µF), input capacitor C6 (1 µF), plus C1/C2/C3 (0.1 µF) local to U1/U3/U5.

> **Why 1.8 V.** The IDS UE-39B0XCP-E documents its I/O pins as 1.8 V sensor-level signals
> (see the camera table under Connectors). An earlier revision of this board deleted the 1.8 V
> rail as "vestigial" and ran the bank at 3.3 V, which would have driven 3.3 V into 1.8 V
> sensor pins on all six cameras. It was restored before fabrication. Do not remove it again.
>
> The 74LVC parts need no level translator: SN74LVC04A runs 1.65–3.6 V and 74LVC1G04 runs
> 1.65–5.5 V, and both have 5.5 V-tolerant inputs independent of VCC, so at 1.8 V they accept
> the Pico's 3.3 V GPIO and U12's 3.3 V output directly. At 1.8 V the drivers' 60–113 Ω
> output impedance also series-matches the ribbon, so **do not add series resistors** to the
> camera lines — they would over-damp the edge.
>
> Specify the **fixed 1.8 V** part (e.g. NCP718ASN180T1G, ±2 % at VOUT ≥ 1.8 V). A 1.65 V or
> 1.7 V option erodes the camera's already-modest VIH margin.

**+3.3 V** — from the Pico's 3V3_OUT (pin 36). Consumers: U12 (the pixel-reset Schmitt
input) and its R5 pull-up only, decoupled by C8 (0.1 µF). Draw is under 1 mA.

Power-up order: because U9 is fed from +5 V, the 1.8 V rail can rise a millisecond or so
before the Pico's 3.3 V. During that window U12 is unpowered and its output is high-impedance
(LVC partial-power-down), so `PIXRST` floats and TDRSTN is briefly undefined. Harmless — the
cameras have not enumerated yet — but it is why TDRSTN is not defined for the first moment
after USB power is applied.

Nothing on this board presents 5 V — or 3.3 V — to J1–J6.

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
marker (normal), a shunt on **1‑2** triggers them from every laser CH1 pulse instead — which
exist only while the firmware is ARMED; with the lasers disarmed, 1‑2 gives the cameras no
trigger (use 2‑3, or ARM with J11 on 2‑3, for camera-only work). J10.1 reaches `_PULSE_OUT_CH1`
through **R19 (100 Ω)**; like TP4 it idles LOW while DISARMED. Without R19, the 1‑2 shunt would
hang the whole ~150 mm `PWM_TRIG_TAP` net (U5, R9, the J16.2 run) directly on the CH1 GPIO, and
a transmission-line simulation put CH1 0.4–1.7 ns behind CH2 at U7/U8 — a jumper-dependent
error in the laser inter-pulse delay. R19 cuts that to under ~0.2 ns and costs the camera
trigger 1.5–2 ns of edge, which does not matter there. **With no shunt fitted, R9 (10 k) pulls `PWM_TRIG_TAP` low**, so all
six camera trigger lines idle low rather than following a floating input on ~145 mm of trace
(the node also runs up to J16.2). 10 k rather than a weaker pull holds U5's 1.8 V input at
≤ 0.05 V even at worst-case input leakage, and loads the selected GPIO by only 330 µA.

> J10's silkscreen reads **`CH1 / TRG / MKR`** (pins 1/2/3): shunt TRG to CH1 for a camera
> trigger on every laser CH1 pulse, or TRG to MKR for the reference marker. (Earlier layouts
> read `MON / IN / OUT`, which mislabelled pin 1.) Never fit a shunt across all three pins —
> that ties GP13 (through R19) to GP11. J11 is marked **ON** (pins 1‑2, lasers enabled) and
> **OFF** (pins 2‑3).

**Pixel reset** (no MCU involvement — pure hardware pass-through)
J12 BNC → `PIXRST_IN` (R5 3k3 pull-up to **+3V3**) → U12.2 (**74LVC1G17** Schmitt buffer,
VCC 3.3 V) → `PIXRST` → U3.2 (74LVC1G04, 1.8 V) → `PIXRST_N` → U4 ×6 (1.8 V) → `TDRSTN1..6`
→ J1–J6 pin 3

**Active LOW at the BNC: pull J12 low to reset.** One buffer and two inversions, so TDRSTN
follows J12 directly, and TDRSTN is active low at the camera (`0 = pixels in reset`). An open
BNC idles at 3.3 V through R5 and leaves the cameras running, so an unplugged reset cable
fails safe.

U12 is a Schmitt trigger chosen for this input specifically. At VCC = 3.3 V it switches low
below **0.89 V** and high above **~1.92–2.1 V**, with **0.5–0.8 V of hysteresis**, and its
input tolerates 5.5 V regardless of VCC. That gives:

| J12 driven by | Result |
|---|---|
| Nothing (open) | idles 3.28 V → cameras **active** |
| 3.3 V or 5 V CMOS, high | **active** (≥1.4 V margin) |
| 5 V TTL, high (VOH min 2.4 V) | **active** (~0.3–0.5 V margin) |
| any logic low ≤ 0.8 V, open-drain, relay, switch to GND | **reset** |
| **1.8 V logic, high** | **not guaranteed** — 1.8 V sits inside the hysteresis band |

A source must sink **1.0 mA** to assert reset. A 5 V source back-feeds 0.5 mA into +3V3 through
R5, which the Pico's own load absorbs.

The previous revision used a 74LVC1G08 powered from +5 V here. At VCC = 5 V an LVC input needs
**0.7 × VCC = 3.5 V** to read high, so a 3.3 V source could not reliably release reset, and
there was no hysteresis on a bare BNC input. Its second input, `PIXRST_GATE_EN`, was only ever
tied high through R4 and was never connected to anything; R4 and that net were removed with it.

**Laser outputs**
`GP13` → U7.2 → `CH1_GATED` → U13.2 (INA) → U13.7 (OUTA) → `CH1_DRIVE_RAW` → **R6 68 Ω, 2 W** →
J7.1
`GP12` → U8.2 → `CH2_GATED` → U13.4 (INB) → U13.5 (OUTB) → `CH2_DRIVE_RAW` → **R7 68 Ω, 2 W** →
J8.1

U7 and U8 are **74AHCT1G08** gates on +5 V. AHCT has TTL input thresholds (high above
2.0 V), so the Pico's 3.3 V pulses drive them with ~1.3 V of margin. An LVC gate here would
need 0.7 × VCC = 3.5 V to read high, which a 3.3 V GPIO cannot guarantee.

U13 is a TI UCC27524 dual 5 A driver, non-inverting, on **VDD = +12V** with ENA/ENB on
`LASER_PWR_OK` (see Power). Its local bypass **C9 (0.1 µF, 50 V)** sits directly beside VDD
(pin 6) with its own GND via, and GND (pin 3) drops straight to the In1 plane through a via under
the package — a board loop of roughly 1.5–2 nH, against the 7–13 nH of the earlier layout, which
fed VDD only from C10 via 15 mm of trace and two vias. That keeps the ~100 mA, few-ns output
edges from bouncing VDD into the pulse top. C10 (10 µF) remains the bulk reservoir. U13's inputs are TTL-compatible independent of VDD (high above
1.8–2.3 V, 1 V hysteresis), so the 5 V AHCT gates drive it unchanged. Output pull-up is
**2.5 / 5 / 7.5 Ω** (min/typ/max, PMOS only — which is what holds a steady load high during a
pulse); pull-down 0.15–1 Ω, so the low level into 50 Ω is well under the 0.2 V limit.

**Amplitude budget.** The target loads are PicoLas LDP-V 10-70 and LDP-V 240-100 drivers, whose
trigger inputs are **50 Ω terminated** and need **4.5–5.2 V high, ≤ 0.2 V low**. Delivered
level = VDD × 50 / (50 + R6 + ROH):

| Corner | VDD | R6 (68 Ω ±1 %) | ROH | Into 50 Ω |
|---|---|---|---|---|
| Low | 11.65 V (ADJ 588 mV, divider −0.2 %) | 68.68 Ω | 7.5 Ω | **4.61 V** |
| Typical | 11.91 V | 68 Ω | 5 Ω | 4.84 V |
| High | 12.17 V (ADJ 612 mV, divider +0.2 %) | 67.32 Ω | 2.5 Ω | **5.08 V** |

Every corner passes, with ~2.5 % margin at both ends. The budget assumes a 50 Ω termination at
the driver; a load 1 % high adds ~0.6 %. The trace drop from U17 to U13 is a few mV. With 1 %
divider resistors the corners would sit only ~0.7 % inside the window, which is why R12/R13 are
0.1 %.

> **The laser BNCs are for 50 Ω loads only.** Open-circuit, or into a high-impedance scope
> input, the output rises to ~12 V (the source is ~73 Ω). **One driver per output — no BNC
> tees.** A transmission-line simulation (scratch `tee_sim.py`, typ. corners) gives: J7 and J8
> tied into one 50 Ω input → 3.4 V per pulse (the idle channel's 68 Ω sinks half), and 6.9 V where
> the pulses overlap (DELAY < WIDTH), above the LDP-V's 5.2 V damage limit; one output teed to two
> drivers → 3.0 V each. The PiDG itself survives either (see the board output rating under Timing limits). PicoLas's acceptance test applies:
> a scope with **50 Ω input termination** must read 0 to ~4.9 V. The LDP-V absolute maximum on
> its trigger input is 15 V, so an unterminated reflection cannot exceed it.

U13 adds ~13–25 ns of propagation delay, common to both laser channels. Inter-pulse delay is
preserved to within the driver's channel-to-channel matching (1–2 ns). Laser-vs-camera skew
grows by that fixed, calibratable amount.

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

**Fails safe.** R8 holds U10 pin 1 low when no jumper is fitted on J11, so the default state
is *disabled*. Fit a shunt on J11 **1‑2** to enable the hardware interlock (the firmware must
also be ARMED — see Boot and arming); **2‑3** inhibits. With the 1‑2 shunt fitted
R2 wins: 5 V × 10/(3.3+10) ≈ **3.76 V**, against U10's (74AHCT1G08) **VIH of 2.0 V** — about
**1.76 V of margin**. (With the 74LVC1G08 used previously, VIH at VCC = 5 V was
0.7 × VCC = 3.5 V and the margin only ~260 mV.) AHCT also means an external interlock signal on
J16.1 can be 3.3 V logic.

**Safety (E-stop) switch: wire it across J11 1‑2.** Replace the shunt with a *normally-closed*
switch between J11.1 and J11.2. Closed, it acts like the shunt; pressing it or breaking its cable
opens the circuit and R8 pulls U10.1 low, so the stop fails safe. J16.1 is the wrong place for an
E-stop: it is enabled when open. The silkscreen beside J11 reads `LASER INTERLOCK: ON = 1-2` and
`E-STOP: NC SWITCH ACROSS 1-2`.

The original Teensy design had no pull-down here and defaulted to *armed* with the header
empty. R8 is the one deliberate behavioural change to the interlock.

The firmware's ARM state acts upstream of U7/U8 (DISARMED holds their pulse inputs LOW), so the
three gates — firmware ARM, the J11/U10 interlock and U13's power-good enable — are in series.

Disabling forces both BNC centre pins to 0 V: U10 low → U7/U8 outputs low → U13 outputs low.
U13's ENA/ENB carry only the **power-good** gate (`LASER_PWR_OK`, see Power), not the user
interlock. The two act in series, and either one alone forces the outputs low; neither can
enable a laser the other has disabled. U10 retains sole authority over the user interlock.

**Pico removed, J17 powered.** J17 can power the board with no module fitted, which the old
USB-only design could not. U7/U8's pulse inputs would then float, and an armed interlock would
pass whatever they picked up. **R17/R18 (10 kΩ)** hold `_PULSE_OUT_CH1`/`_PULSE_OUT_CH2` low at
the socket (J14.17/.16), so the laser outputs stay at 0 V. With the Pico fitted they cost
0.33 mA per GPIO while high. The camera lines are not guarded the same way: with no module,
`PWM_1MHz` floats and U12 is unpowered (no +3V3), so Sync and TDRSTN at the cameras are
undefined. That is a nuisance, not a hazard — fit the Pico before connecting cameras.

---

## Connectors

**J1–J6 — cameras** (2×5 IDC, 2.54 mm). Identical to the Teensy design, pin for pin, and
mapped 1:1 onto the 8-pin I/O connector of the **IDS uEye UE-39B0XCP-E** (IDS part 1011378)
for pins 1–8:

| Pin | Board | Camera (IDS datasheet, verbatim) |
|---|---|---|
| 1 | NC | Voltage output 1.8 V, max. 50 mA |
| 2 | GND | Ground (GND) |
| 3 | `TDRSTNn` — pixel reset, active low | TDRSTN (sensor), 1.8 V |
| 4 | `Triggern` | Trigger input (sensor), 1.8 V |
| 5 | `Syncn` — 1 MHz | SYNC (sensor), 1.8 V |
| 6 | NC | – |
| 7 | GND | Ground (GND) |
| 8 | NC | USB Power: 5 V, max. 400 mA |
| 9, 10 | NC | (no counterpart) |

Source: IDS UE-39B0XCP-E-GL datasheet, rev 2026-01-09. **All three signals are 1.8 V**, driven
by U2/U4/U6 on the 1.8 V rail. Delivered levels: VOH ≥ 1.5 V and VOL ≤ 0.2 V at light load over
temperature, against a 1.8 V CMOS receiver's typical VIH of ~1.17–1.26 V and VIL of ~0.63 V.
IDS does not publish the camera's own thresholds or input pull, so confirm on the bench.

> **Pins 1, 6 and 8 are unconnected on the board** (so are 9 and 10): bare plated holes with no
> copper to any net, so the board can never short the camera's own supplies — pin 8 is its USB 5 V
> and pin 1 its 1.8 V output. The only remaining risk is a harness that ties pin 1 or 8 to a ground
> wire; build it with only wires 2, 3, 4, 5 and 7. Pin 6 is undocumented; do not assume it is a
> ground.
>
> **Configure every camera as a sync *slave*.** The IMX636's SYNC pad is bidirectional (it
> drives when the sensor is master), and the board drives pin 5 push-pull. A camera left in
> master mode would contend with U2.

**BNC, 50 Ω** — J7 Laser 1 (out), J8 Laser 2 (out), J12 Pixel Reset (**in**, active low,
3.3 V/5 V/open-drain compatible — see Signal chains). Shells on GND. J7/J8 expect a 50 Ω load
(see Laser outputs).

**J17 — USB-C power input** (HRO TYPE-C-31-M-12, top edge, face flush with the board edge).
Power only: VBUS, CC1/CC2 to U14, GND and shell to GND; D+/D−/SBU are not connected. Use a USB-PD
charger that offers 15 V — in practice any PD charger rated 30 W or more. Programming and serial
still go through the Pico's own USB port.

**Headers**

| Ref | Type | Pins |
|---|---|---|
| J10 | 1×3 vertical | 1 `_PULSE_OUT_CH1` (CH1 monitor) · 2 wiper → U5 · 3 `PWM_Trig` |
| J11 | 1×3 vertical | 1 pull-up · 2 → U10.1 · 3 GND |
| J16 | 1×3 right-angle, right edge | 1 `LASER_EN_TAP` · 2 `PWM_TRIG_TAP` · 3 GND |
| TP3 | 1×2 right-angle, top edge | 1 `PWM_1MHz` · 2 GND |
| TP4 | 1×2 vertical | 1 `_PULSE_OUT_CH2` · 2 GND |

> **J16.1 (ENABLE) doubles as an external interlock input:** pull it LOW (switch or
> open-collector to J16.3, or 3.3 V/5 V logic) to inhibit both lasers. It is *enabled when
> open* (R3 pulls it up), so a broken interlock cable leaves the lasers enabled — J11 remains the
> fail-safe interlock.
>
> The silkscreen beside J16 spells this out pin by pin: `ENABLE IN: PULL LOW = LASERS OFF`,
> `TRIG OUT: CAMERA TRIGGER (MONITOR)`, `GND`, then `J16: NEVER FIT A SHUNT` and
> `NOT FAIL-SAFE - PUT THE E-STOP ON J11`. J16's and TP3's pins both overhang their edges by 2.1 mm.
>
> **Never fit a shunt on J16.** A shunt on pins 2‑3 grounds `PWM_TRIG_TAP`,
> which via J10's selector shorts a GPIO straight to ground and silently kills all six camera
> triggers.

TP3 and TP4 are scope points with a local ground pin (TP4, like J10.1, idles LOW while the
firmware is DISARMED). TP4 is labelled `CH2` / `GND` / `SCOPE ONLY`. J10 stands on its own about 9 mm east of TP4 (so the two
headers cannot be read as one row) and carries `CAMERA TRIGGER: TRG-MKR = MARKER / TRG-CH1 = LASER 1`
to the right of its `CH1 TRG MKR` pin labels. The TRIG and 1 MHz taps feed U5 and U1,
which run from the 1.8 V rail: external drive there needs **VIH ≥ 1.17 V, VIL ≤ 0.63 V**, and
the inputs are 5.5 V-tolerant. Note that both taps are normally driven by a Pico GPIO, so an
external source would fight it — treat them as monitor points.

**MH1–MH4** — M3, NPTH, mechanical only.

---

## Open items

Ordered by what would bite hardest.

1. **Bench-verify the laser outputs before connecting a laser driver.** With J17 on a 15 V PD
   charger, check +12V at C17 (11.65–12.17 V, typically 11.9 V) and that `LASER_PWR_OK` (U13 pins 1/8) is
   high (~12 V). Fit J11 on 1‑2 and send `ARM`,
   then scope J7 and J8 through a **50 Ω-terminated** input:
   - amplitude 0 V to 4.61–5.08 V (typically ~4.84 V) — the budget rests on datasheet corners
     for U17's reference and U13's ROH, so a measurement closes it;
   - CH2 rising edge exactly DELAY after CH1 (e.g. `DELAY 10000` → 10.000 µs, `DELAY 13` →
     13.3 ns), and MARKER staying on the same CH1 pulse for minutes at `FREQ 3000`;
   - the first pulse after `ARM` full width, and no two CH1 pulses closer than 1/FREQ while a
     host loops `ARM`/`DISARM` as fast as it can;
   - J7/J8 at 0 V after `DISARM`, after a reset (a power cycle of both J17 and the Pico USB —
     neither the board nor the Pico 2 W has a reset button — and a watchdog timeout forced
     over SWD as described under Boot and arming), and — while ARMED with pulses running — with
     J17 unplugged and during plug-in;
   - MARKER staying on the same CH1 pulse at a FREQ whose period is not a whole number of
     cycles, e.g. `FREQ 7000`.
2. **Check the charger's PD behaviour.** The CH224K datasheet does not say what it does when
   the charger lacks the requested 15 V. The board is safe either way — U18 keeps the lasers
   disabled below ~11 V — but a small charger may leave them disabled. Measure VBUS_PD (C12)
   with the charger you will deploy.
3. **Bench-confirm the camera I/O before plugging in six cameras.** IDS documents the pins as
   1.8 V but publishes no VIH/VIL, input pull or absolute maximum. With one camera, measure
   TDRSTN, Trigger and Sync at the camera end of the harness, and confirm pin 5 is not being
   driven by the camera (i.e. that it is configured as a sync slave).
4. **No 50 Ω termination on the J12 pixel-reset input** — only R5's 3k3 pull-up and U12's
   CMOS input. U12's 0.5–0.8 V of hysteresis now absorbs moderate ringing from an unterminated
   coax run. Do *not* add a 49.9 Ω shunt as-is: against R5 it would hold J12 at ~50 mV, i.e.
   keep all six cameras permanently in reset unless the source actively drives high.
5. **Before the first USB-C PD power-up, check the fine-pitch parts for solder bridges.** J17's
   and U17's pads are 0.5 mm pitch and U16's 0.65 mm, on lead-free HASL. With no power applied, check that
   VBUS_PD is not shorted to GND, CC1 or CC2 (J17, and U14 pins), and that +5V_PD and +5V are not
   shorted to GND (U16). A VBUS-to-CC bridge would put up to 20 V on U14. Check U17's IN (pins 1-3) against OUT
   (pins 9-10) too: a bridge there would put 15 V on +12V (U18 would then hold the outputs off). Also confirm that J17's
   four shell legs are soldered (they are through-hole with no paste layer).

**Not an open item: Wi-Fi / Bluetooth.** The firmware does not use the radio; the Pico 2 W is
fitted only because it is easier to buy than the plain Pico 2. All four copper layers run solid
under the module, including its antenna, which shortens the radio's range. That is acceptable
even for a future wireless firmware: the aim would be short, Bluetooth-like range (a few metres),
so no antenna keepout is needed.

---

## Manufacturing notes

Layout decisions made in the final DFM / assembly / signal-integrity review (2026-09-25):

- **No vias inside SMD pads,** apart from the two thermal vias in each of U14's and U17's exposed GND
  pads, which is normal practice. Every other via drill is at least 0.2 mm from any SMD pad edge, so the standard
  **tented** via option is correct; filled-and-capped via-in-pad (a paid option on 4-layer boards)
  is not needed. On the JLC order form choose *Tented*, not *Plugged*.
- **No controlled impedance is needed.** The longest critical run (J7/J8 drive, ~32 mm, Z0 ≈ 55 Ω)
  is electrically short against the driver's edges. Order *Impedance control: No*.
- **Copper keep-outs:** zone copper stays 0.5 mm from the board edge on all four layers, and a
  3 mm-radius rule area keeps all copper (including the In2 +5 V plane) away from each M3 hole, so
  a metal screw or standoff cannot touch a plane in the hole wall.
- **GND stitching:** 47 stitching vias along the board edges and in the south-east quadrant, plus
  local vias at the decoupling capacitors and IC ground pins that previously reached the planes
  only through thermal spokes.
- **Silkscreen** shows the Pico outline, the `CONTROL / PROGRAM` and `POWER ONLY` port labels, and a pin-1 mark (a module fitted the other way round would put the
  board's +5 V on one of its GPIO pins), and J10/J11 are labelled as described under
  Signal chains. All board text is at least 1.0 mm high.

**JLCPCB order:** the board is set up for full assembly by JLCPCB, with every SMD and
through-hole part fitted, so nothing needs soldering on delivery. `fab/jlc/JLC_ORDER.md` is the
checklist: order-form settings, remarks to paste, the parts that need Global Sourcing (U14 CH224K
and U9 NCP718 were out of stock on 2026-09-25), rotations to
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
| `PiDG_Pico_BOM.csv` | BOM (hand-maintained; `export_bom` ignores DNP attributes) |
| `PiDG_Pico_CPL.csv` | pick-and-place, all 75 placed parts (KiCad columns), mounting holes excluded |
| `fab/jlc/PiDG_Pico_JLC_BOM.csv`, `fab/jlc/PiDG_Pico_JLC_CPL.csv`, `fab/jlc/JLC_ORDER.md` | JLCPCB full-assembly upload files (all 75 parts, LCSC numbers) and the order checklist |
| `fab/gerbers/`, `fab/PiDG_Pico_Gerbers.zip` | gerbers, Excellon drill (PTH/NPTH) and job file, from the board's stored plot settings |
| `libs/PiDG_Local.kicad_sym` | Pico 2 W, UCC27524, LT3065 and TPS3700 symbols |
| `libs/PiDG_Local.pretty/` | `*_EdgeTrim` footprint variants (see below) |
| `libs/RPi_Pico.pretty/` | official RPi castellated module footprint (unused — board is socketed) |
| `../src/` | firmware: `board.h` (pin map), `pulse_timing.h` (timing math and checks), `pio_pulse.*` (PIO programs), `laser_gate.*` (CH1/CH2 gate, pre-init hook), `protocol.*` (serial commands), `main.cpp` (arming, hold-off, watchdog) |
| `../platformio.ini` | build config: platform pinned to an exact commit; envs `pico2w` (default) and `pico2` |
| `../tools/timing_check/` | host check of `pulse_timing.h` against a cycle-level PIO model (see its README) |

**About the `*_EdgeTrim` footprints.** J16 and TP3 overhang the board edge, and J17's face is flush with it, so their stock
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

Current state: DRC 0 violations, 0 unconnected items; ERC 0 violations. A
`kicad-cli pcb drc --schematic-parity` run additionally reports ~185 parity *warnings*, none
electrical: board net names lack the `/` root-sheet prefix the schematic generates for local
labels (`TDRSTN1` vs `/TDRSTN1` — connectivity identical), unused J14/J15 socket pads carry no
net rather than `unconnected-(…)`, `Datasheet`/`Description` field text differs, and
MH1–4 exist only on the board by design (U11 is marked not-on-board in the schematic). A pad-by-pad net comparison with the prefix stripped
matches exactly.

**Take care with "Update PCB from Schematic".** U11 is now marked *not on board* and *not in
BOM*, so a sync should no longer try to place a Pico footprint, but the net-name prefix
differences above make a sync noisy; review its change list before accepting it.
