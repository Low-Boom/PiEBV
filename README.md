# PiDG

A pulse-timing box for particle image velocimetry (PIV), built around a Raspberry Pi Pico 2 W.

PIV measures how a fluid moves. Tiny particles in the flow are lit by two short flashes of light a
known time apart, and cameras record how far the particles moved in between. PiDG makes the timing
signals for that:

- It **fires two laser (or LED) drivers**, the second exactly a set delay after the first, at a set
  repetition rate.
- It **keeps up to six event cameras on one shared clock**, and marks every flash pair in each
  camera's data so the recordings line up with the flashes.
- You **control it by typing short text commands** over USB: from a terminal, a Python script or
  the included web page.

> **Status.** The current board (KiCad project `PiDG_Pico`) has not been built yet. The firmware
> compiles and its timing has been checked step by step in simulation, but nothing has run on real
> hardware. Do the [first-board checks](#first-board-checks) before connecting a laser driver or a
> camera.

**Contents:** [What it does](#what-it-does) · [Words used here](#words-used-here) ·
[Safety](#safety) · [The board](#the-board) · [Quick start](#quick-start) ·
[Connecting](#connecting) · [Command reference](#command-reference) ·
[Troubleshooting](#troubleshooting) · [Building from source](#building-from-source) ·
[Repository layout](#repository-layout)

---

## What it does

| Output | Connector | What it is for |
|---|---|---|
| **Laser 1** (CH1) | BNC J7 | Trigger for the first laser driver: a 5 V pulse (with J18 set to match the input), `WIDTH` long, `FREQ` times per second |
| **Laser 2** (CH2) | BNC J8 | Trigger for the second laser driver: the same pulse, starting exactly `DELAY` after Laser 1 |
| **Sync** | Camera ports J1–J6 | A steady clock that all six cameras keep time by (1 MHz by default, and the cameras need 1 MHz) |
| **Trigger** (the marker) | Camera ports J1–J6 | A pulse at the same instant as every Laser 1 pulse. Each camera records it as a timestamp in its data. (Jumper J10 can switch the cameras to the Laser 1 pulse itself instead.) |
| **Pixel reset** | Camera ports J1–J6 | Holds the camera sensors blank. Controlled by the J12 BNC input, and optionally by PiDG between flash pairs (`PIXGATE`) |

- Every signal to the cameras is **1.8 V**, the level they are built for. The laser outputs are
  **5 V**.
- Times are set in steps of **6.667 ns** (one tick of the Pico's 150 MHz clock). Every reply shows
  the exact value the hardware will produce, so you never have to correct for the step size.
- Both laser pulses share one `WIDTH` and one `FREQ`.
- The firmware sets **no laser-driver limits** (pulse width, duty, spacing). Set what your driver is
  rated for. It only stops the pulses from running into each other.

PiDG was designed for two **PicoLas LDP-V** laser-diode drivers (models 10-70 and 240-100) and six
**IDS uEye UE-39B0XCP-E** event cameras. Other drivers with a 5 V trigger input should work too, with
the output mode (J18/J19) set to match their input.

### Words used here

| Term | Meaning |
|---|---|
| **BNC** | The round, twist-lock connector used for coaxial cable on lab equipment. |
| **50 Ω input** | An input with a 50 Ω resistor to ground built in ("terminated"). Many laser drivers have one, including the LDP-V, and scopes can be switched to 50 Ω. |
| **High-impedance (Hi-Z) input** | An input that draws almost no current: logic inputs (TTL, 5 V CMOS) and a scope set to 1 MΩ. |
| **Output mode** | Whether a laser output is set up for a 50 Ω input or a high-impedance one (jumpers J18/J19). The wrong mode gives the wrong voltage. |
| **Jumper, shunt** | A jumper is a row of pins on the board. A shunt is the small plastic cap that connects two neighbouring pins. "J11 on 1-2" means a shunt joining pins 1 and 2 of J11. Pin 1 has a square pad. |
| **ARM / DISARM** | Commands that allow or stop the laser pulses. Cameras keep running either way. |
| **Sync slave** | A camera setting: the camera takes its clock from outside (from PiDG) instead of making its own. |
| **E-stop** | An emergency-stop switch. Here it must be *normally closed*: pressing it opens the circuit. |
| **USB-C PD charger** | A USB-C charger that can supply more than 5 V on request (laptop chargers, most phone chargers rated 30 W or more). PiDG asks it for 15 V. |
| **IDC header** | The 2×5-pin connector for a flat ribbon cable (the camera ports). |

---

## Safety

### The short version

1. **The lasers start off.** At every power-up and every reset the laser outputs are DISARMED. They
   pulse only after you send `ARM`.
2. **Typing `DISARM` stops them at once.**
3. **Three things must all be true** for the lasers to pulse. Remove any one and they stop:
   - the firmware is ARMED;
   - a shunt is on **J11 pins 1-2** (or a closed E-stop switch is wired there);
   - a 15 V USB-C charger is plugged into **J17**.
4. **Unplugging the computer does not stop the lasers.** Use J11 or J17 for that.
5. **Set each laser output's mode (J18, J19) before you connect anything to it.**
6. **One laser driver per output.** Never split an output with a BNC tee, and never join J7 and J8.
7. **Cameras:** build the harness with wires 2, 3, 4, 5 and 7 only, and set every camera to sync
   slave.

### In detail

**Starting and stopping**

- **`DISARM` always works, immediately.** The six letters D-I-S-A-R-M, in any case and anywhere in
  what you type, disarm the outputs as soon as the last letter reaches the board. You don't need to
  press Enter, as long as your terminal sends each key as you type it (all the terminals listed
  under [USB serial](#usb-serial) do). A monitor with a separate input box, such as the Arduino
  IDE's, sends nothing until you press Enter.
- **The three gates are independent.** Each one on its own holds both outputs at 0 V. The firmware
  can only see the first one, so `ARMED=1` does not by itself mean the outputs are live. The third
  gate (U18) checks that the board's 12 V laser-driver supply is between 10.6 and 13.3 V, which needs
  the 15 V charger.
- **Losing the USB link does not disarm.** If the Pico's USB cable is pulled, the PC goes to sleep
  or a script is killed while ARMED, the board keeps running from J17 and the lasers keep pulsing,
  with no way to send `DISARM`. Stop them in hardware: take the J11 shunt off 1-2, pull J16 pin 1
  low, or unplug J17.
- **Before uploading new firmware, send `DISARM`.** The upload restarts the Pico, and a restart in
  the middle of a pulse can stretch that one pulse by an estimated 70–150 ns.
- **Before using a debugger (SWD), send `DISARM` and remove the J11 shunt** (or unplug J17). A
  debugger reset can leave a laser output high for milliseconds.

**Laser outputs**

- **Match the output mode to what you connect.** J18 sets the mode for J7 (Laser 1) and J19 for J8
  (Laser 2) ([details](#jumpers)):

  | Shunt | Mode | Use it for | Into a 50 Ω input | Into a Hi-Z input |
  |---|---|---|---|---|
  | **1-2** | 50 Ω | The LDP-V, or any 50 Ω input | **about 4.8 V** (correct) | about 12 V (too high for 5 V logic) |
  | **2-3** | Hi-Z | TTL or 5 V CMOS inputs, a scope at 1 MΩ | about 2.5 V (too low to fire an LDP-V) | **about 4.8 V** (correct) |
  | none | — | nothing: always fit a shunt | about 3.5 V | about 12 V |

  Hi-Z mode is still too much for an input rated for 3.3 V only.
- **One laser driver per output — never use a BNC tee.** Each output is built to drive exactly one
  input. Simulated in 50 Ω mode, with 1–2 m of coax:
  - J7 and J8 joined into one driver: each pulse reaches only **3.4 V**, below the LDP-V's 4.5 V
    minimum, so it fires unreliably. Where the two pulses overlap (`DELAY` shorter than `WIDTH`, e.g.
    `DELAY 0`) the input sees **6.9 V**, above the LDP-V's 5.2 V damage limit.
  - One output split to two drivers: each sees **3.0 V**, too low for either.
  - The PiDG itself survives both.

  To fire **one light source with both pulses**, or **two light sources together with the same
  double pulse**, use `COMBINE 1` instead ([Combined mode](#combined-mode-combine)): each output
  then carries both pulses, still one driver per output.
- **The board itself can't be overloaded by any setting.** The outputs survive every setting the
  firmware accepts, even into a short-circuited cable. (The numbers are in
  [Hardware.md](Hardware.md#board-output-rating).)

**Cameras and jumpers**

- **Camera pins 1, 6 and 8 are not connected on the board,** so a straight-through ribbon can't
  short the camera's own supplies at the board (pin 1 is the camera's 1.8 V output, pin 8 its USB
  5 V). The remaining risk is in the harness: fit only wires 2, 3, 4, 5 and 7 (or cut 1, 6 and 8),
  and never join pin 1 or 8 to a ground wire. Pin 6 is undocumented: don't assume it is a ground.
- **Set every camera to sync slave.** PiDG drives the sync pin, so a camera set as sync master would
  fight it.
- **Never fit a shunt on J16**, and never fit one across all three pins of J10.

More detail: [Hardware.md](Hardware.md), sections Boot and arming, Laser
interlock and Connectors.

---

## The board

Orientation used below: the USB-C connector J17 is on the **top** edge, and the three BNCs stick
out of the **right** edge. The Pico plugs into two sockets left of centre, with its micro-USB at the
top edge, and the six camera ports run along the bottom. The two USB ports on the top edge are
labelled on the board: **`CONTROL / PROGRAM — PICO MICRO-USB`** (commands and firmware) and
**`POWER ONLY — USB-C PD 15 V`** (J17).

```
 top edge:  TP3   Pico micro-USB = CONTROL   J16   J17 USB-C = POWER ONLY
           +------------+--------+----------------------------------------+
           |            |  Pico  |  (J16 = ENABLE / TRIG / GND)            |
           |            |  2 W   |       J11 (laser enable)                |
           |            | in J14 |                          J18 (mode) J7 =|  Laser 1  (BNC)
           |            | / J15  |      TP4     J10 (trigger select)       |
           |            +--------+                          J19 (mode) J8 =|  Laser 2  (BNC)
           |                                                              |
           |  J1   J2   J3   J4   J5   J6   (camera ports)             J12 =|  Pixel reset (BNC)
           +--------------------------------------------------------------+
```

### Connectors

| Ref | What | Connect to | Notes |
|---|---|---|---|
| **J1–J6** | Camera ports 1–6 (2×5 IDC headers) | Each camera's 8-pin I/O cable (header pin *n* = camera pin *n*) | Pin 2, 7 ground · 3 pixel reset · 4 trigger · 5 sync · 1, 6, 8, 9, 10 not connected. All signals **1.8 V**. Pin 1 is the top-left pin. |
| **J7** | BNC, Laser 1 (CH1) | First laser driver's trigger input | Mode set by J18 |
| **J8** | BNC, Laser 2 (CH2) | Second laser driver's trigger input | Mode set by J19 |
| **J12** | BNC, pixel-reset **input** | Your reset signal, or nothing | See [J12](#j12--pixel-reset-input) below |
| **J17** | USB-C, **power only** | A USB-C PD charger that offers 15 V | No data. Commands and firmware go through the Pico's own micro-USB. |
| **J10** | Camera trigger source (jumper) | A shunt | See [Jumpers](#jumpers) |
| **J11** | Laser enable (jumper) | A shunt, or a normally-closed E-stop switch | See [Jumpers](#jumpers) |
| **J18**, **J19** | Laser output mode (jumpers; J18 = Laser 1, J19 = Laser 2) | A shunt | See [Jumpers](#jumpers) |
| **J16** | 3-pin header on the top edge, between the Pico and J17 | Probes, or a secondary laser-off input | See [J16](#j16--extra-laser-off-input-and-trigger-monitor) below. **Never fit a shunt.** |
| **TP3** | 2-pin header on the top edge | A scope | Pin 1 = the 1 MHz sync straight from the Pico (3.3 V) · pin 2 = ground |
| **TP4** | 2-pin header left of J10, marked `CH2` / `GND` | A scope only | Pin 1 = the Laser 2 pulse straight from the Pico (3.3 V; stays low while DISARMED) · pin 2 = ground. It is taken before the interlock and the output driver, so it pulses while ARMED even when J11 or the 12 V check holds J8 off. Probe it, never drive it. The matching Laser 1 point is J10 pin 1 (through 100 Ω). |

#### J12 — pixel-reset input

**Pull J12 low (to ground) to hold all six cameras in reset.** Left open, the cameras run, so an
unplugged reset cable is harmless.

- It accepts 3.3 V or 5 V logic, an open-drain (open-collector) output, or a switch to ground.
- Whatever drives it must be able to sink 1 mA.
- A 1.8 V logic high is **not** guaranteed to release the reset.
- **Don't fit a 50 Ω terminator** on J12: it would hold the cameras in reset unless your source
  actively drives J12 high.
- The Pico's optional gate ([`PIXGATE`](#pixel-reset-gate-pixgate)) works alongside it: the cameras
  are in reset whenever J12 is low **or** the gate is.

#### J16 — extra laser-off input and trigger monitor

On the top edge between the Pico and J17, pins pointing off the board. The board labels the pins
`EN` `TRIG` `GND` and adds `J16: NEVER FIT A SHUNT`, `EN IN: PULL LOW = LASERS OFF`,
`TRIG OUT: CAMERA TRIGGER (MONITOR)` and `NOT FAIL-SAFE: E-STOP ON J11`.

- **Pin 1, ENABLE IN.** Held at 5 V on the board (3.3 kΩ pull-up). Connecting it to ground (pin 3)
  turns both laser outputs off. A switch, an open-collector output or a 3.3 V or 5 V logic low all
  work (it must sink about 1.5 mA). Left open, the lasers are *enabled*, so a broken cable here
  leaves them on. Use it for a secondary inhibit, such as a door switch or a control system's logic
  line, and put the E-stop on J11.
- **Pin 2, TRIG OUT.** A copy of the camera trigger that J10 selected (3.3 V logic). Probe it; don't
  drive it.
- **Pin 3:** ground.
- **Never fit a shunt.** On 2-3 it shorts a Pico output and kills all camera triggers. On 1-2 it
  ties the laser enable to the trigger.

### Jumpers

J10 and J11 are numbered 1-2-3 from **left to right**. J18 and J19 stand upright between the large
resistors R6/R7 and the BNCs: J18's pin 1 is at the top, J19's at the bottom. Pin 1 always has the
square pad.

| Jumper | Board label | Shunt on 1-2 | Shunt on 2-3 | No shunt |
|---|---|---|---|---|
| **J11** laser enable | `ON` … `OFF` | **Lasers enabled** (the firmware must also be ARMED) | Lasers off | Lasers off (fail-safe) |
| **J10** camera trigger | `CH1 TRG MKR` | Cameras triggered by every Laser 1 pulse (only while ARMED) | **Cameras triggered by the marker** (normal) | No camera triggers |
| **J18** Laser 1 output mode | `50Ω` by pins 1-2, `HiZ` by 2-3 | **50 Ω mode** (normal, for the LDP-V) | Hi-Z mode | Wrong for everything: always fit a shunt |
| **J19** Laser 2 output mode | as J18 | as J18 | as J18 | as J18 |

**J11 — laser enable and E-stop.** Labelled `LASER INTERLOCK: ON = 1-2` and
`E-STOP: NC SWITCH ACROSS 1-2`. For an emergency-stop switch, take the shunt off and wire a
**normally-closed** switch across pins 1 and 2. Closed, the lasers are enabled (if also ARMED and
powered). Pressing the switch **or** breaking its cable opens the circuit and turns the lasers off,
so the stop is fail-safe. Don't use J16 pin 1 for the E-stop: there, a broken cable leaves the
lasers enabled.

**J10 — camera trigger source.** Labelled `CH1 TRG MKR` under the pins and
`CAMERA TRIGGER: TRG-MKR = MARKER / TRG-CH1 = LASER 1` beside them. The middle pin (`TRG`) feeds the
trigger input of all six cameras.
- `TRG` to `MKR` (2-3, normal): the marker. It rises with every Laser 1 pulse, has its own width
  (`MARKERWIDTH`, 2 µs by default) and keeps running while DISARMED.
- `TRG` to `CH1` (1-2): the Laser 1 pulse itself, so only while ARMED. The cameras need a trigger
  pulse of at least 500 ns, so this is only dependable with `WIDTH` ≥ 500 ns.
- Never join all three pins.

**J18 / J19 — laser output mode.** Labelled `LASER 1 OUT` / `LASER 2 OUT`, with `50Ω` and `HiZ`
next to the pin pairs.
- **1-2, 50 Ω mode:** about 4.8 V (4.54–5.14 V) into a 50 Ω input. Use it for the PicoLas LDP-V and
  anything else with a 50 Ω input.
- **2-3, Hi-Z mode:** about 4.8 V (4.55–5.08 V) into a high-impedance input. The output is matched
  to 50 Ω coax, so even a long cable to an unterminated input gives a clean edge with no overshoot.
  Use it for TTL or 5 V CMOS inputs, scopes at 1 MΩ and other instruments that don't terminate.
- **The wrong mode** gives the wrong voltage (see the table under [Safety](#in-detail)): an LDP-V on
  Hi-Z mode sees 2.3–2.6 V and won't fire, and a 5 V logic input on 50 Ω mode sees ~12 V, which can
  damage it. Don't use Hi-Z mode as a way to keep a laser off: J11 is the interlock.
- The two jumpers are independent, so one output can drive an LDP-V and the other a logic input. The
  firmware can't see them, and the pulse timing is the same in both modes.

### Seating the Pico

Fit a **Raspberry Pi Pico 2 W** (or a plain Pico 2, which needs the `pico2` firmware image) with
pin headers into the two sockets, J14 (left) and J15 (right). Seat it **components up, with its
micro-USB connector at the top edge**, next to the label `CONTROL / PROGRAM — PICO MICRO-USB`. Pico
pin 1 then goes into the top-left socket hole, marked `1`. **Fitted the other way round, it can be
destroyed** (the board's 5 V would land on one of its signal pins).

Fit the Pico before connecting any camera: without it, the camera sync and reset lines are
undefined.

### Power

| Plugged in | What works |
|---|---|
| **J17 (15 V charger) + Pico USB** | Everything. This is the normal set-up. |
| Pico USB only | Commands, and sync, trigger and pixel reset to the cameras. **The laser outputs stay off** (no 12 V supply for the board's output driver). |
| J17 only | The board runs, DISARMED, with sync and marker at their defaults. There is no serial link, so it can't be armed. |

**Charger:** a USB-C PD charger that offers **15 V**. In practice that means any PD charger rated
30 W or more (the USB-PD rules require chargers above 27 W to offer 15 V). With a 5 V or 9 V-only
charger the board still runs, but the laser outputs stay off.

**To restart the board,** unplug both J17 and the Pico's USB cable. Unplugging just one doesn't
restart it, and neither does closing the serial port. There is no reset button.

---

## Quick start

You need: the assembled board, a Pico 2 W, a micro-USB **data** cable (some cables only charge), a
USB-C PD charger that offers 15 V (30 W or more) with a USB-C cable, jumper shunts, and a scope
with 50 Ω inputs (or 50 Ω feed-through terminators).

1. **Build and load the firmware** (first time only):
   ```
   pio run                       # builds .pio/build/pico2w/firmware.uf2
   ```
   Do this with the Pico out of the board (or with J17 unplugged, since J17 also powers the Pico).
   Hold the **BOOTSEL** button on the Pico while plugging its USB cable into your computer. A drive
   named `RP2350` appears. Copy `firmware.uf2` onto it: the drive disappears and the Pico starts
   the firmware. (Later updates can use `pio run -t upload`; see
   [Building from source](#building-from-source).)
2. **Seat the Pico,** components up, USB toward the top edge ([details](#seating-the-pico)).
3. **Set the jumpers:** J10 on **2-3** (cameras triggered by the marker), and J18 and J19 on
   **1-2** (50 Ω outputs, for the LDP-V). Leave **J11 empty** for now, so the lasers stay off.
4. **Power up:** the charger into J17, and the Pico's micro-USB into your computer.
5. **Open a serial terminal** on the Pico's port ([how](#usb-serial)) and turn on local echo,
   because the firmware does not echo what you type. (Or use the [web GUI](#web-gui): its console
   takes the same commands.) Type `STATUS` and press Enter. You should see:
   ```
   FREQ=1000 (actual 1000.000 Hz, period 150000 cyc)
   WIDTH=100 (actual 100.000 ns, 15 cyc)
   DELAY=10000 (actual 10000.000 ns, 1500 cyc)
   MARKERWIDTH=2000 (actual 2000.000 ns, 300 cyc)
   SYNC=1000000 (actual 1000000.000 Hz, divider 75+0/256)
   COMBINE=0 (CH1 on LASER 1, CH2 on LASER 2)
   ARMED=0
   HW=OK
   ...
   ```
6. **Set your timing,** for example 15 pulse pairs per second, 100 ns wide, 10 µs apart:
   ```
   FREQ 15        ->  OK FREQ=15 (actual 15.000 Hz, period 10000000 cyc)
   WIDTH 100      ->  OK WIDTH=100 (actual 100.000 ns, 15 cyc)
   DELAY 10000    ->  OK DELAY=10000 (actual 10000.000 ns, 1500 cyc)
   ```
7. **Check the laser outputs with no laser connected.** With J18 and J19 on 1-2, connect J7 and J8
   to the scope with **50 Ω termination**. Fit J11 on **1-2**, then type `ARM`. Within one pulse
   period you should see:
   - pulses from 0 V to about 4.8 V;
   - the J8 pulse starting exactly `DELAY` after the J7 pulse.

   Type `DISARM`: both outputs must drop to 0 V.
8. **Connect the equipment.** Plug in the laser drivers (J7, J8) and the cameras (J1–J6; one camera
   first, see the [first-board checks](#first-board-checks)). Then `ARM` to run, and `DISARM` when
   you're done.

Settings are **not saved**. Every restart brings back the defaults (FREQ 1000, WIDTH 100,
DELAY 10000, MARKERWIDTH 2000, SYNC 1000000) with the lasers DISARMED.

### First-board checks

The design hasn't been proven on real hardware yet, so check every newly assembled board. The full
list, with exact test points, is under
[First-board checks in Hardware.md](Hardware.md#first-board-checks).

1. **Before the first power-up on J17,** with nothing plugged in, check with a multimeter for solder
   bridges on the fine-pitch parts (J17, U16, U17): `VBUS_PD` must not be shorted to GND, CC1
   or CC2 (at J17 and U14), +5V_PD and +5V must not be shorted to GND (at U16), and U17's input must
   not be shorted to its output. Also check that J17's four metal shell legs are soldered.
2. **Supply voltages,** with the charger on J17: `VBUS_PD` at C12 about 15 V (with the charger you
   will actually use), +12V at C17 between 11.54 and 12.05 V, and `LASER_PWR_OK` (U13 pins 1 and 8)
   about 12 V.
3. **Laser outputs,** J18/J19 on 1-2, into a 50 Ω-terminated scope with no driver connected:
   - pulses from 0 V to 4.54–5.14 V;
   - CH2 exactly `DELAY` after CH1 (`DELAY 13` should give 13.3 ns);
   - the first pulse after `ARM` is full width;
   - 0 V after `DISARM` and after a full restart; and, while ARMED and pulsing, 0 V once J17 is
     unplugged, with no stray pulse while it is plugged back in;
   - then J18/J19 on 2-3 with the scope at 1 MΩ: 0 V to 4.55–5.08 V, with no overshoot at the end of
     the longest cable you will use. Put the shunts back on the mode you need afterwards.
4. **Cameras:** with **one** camera connected, measure pixel reset, trigger and sync at the camera
   end of the harness, and confirm the camera is not driving pin 5 (it must be a sync slave). Only
   then connect all six.

---

## Connecting

### USB serial

Use the **Pico's micro-USB port**; J17 carries power only. The Pico appears as a standard USB serial
port and needs no driver on Windows 10/11, macOS or Linux.

| OS | Where to find the port |
|---|---|
| Windows | Device Manager → Ports (COM & LPT) → `USB Serial Device (COMn)` |
| macOS | `/dev/cu.usbmodem*` |
| Linux | `/dev/ttyACM*` (your user may need to be in the `dialout` group) |
| Any | `pio device list` |

The port's USB ID is `2E8A:F00F` with the `pico2w` firmware and `2E8A:000F` with the `pico2`
firmware.

**Terminal settings**

| Setting | Value |
|---|---|
| Baud rate | Anything **except 1200**, which restarts the Pico into its bootloader. 115200 is usual. |
| Line ending | CR, LF or CR+LF: all work |
| Flow control | None |
| Local echo | **On**: the firmware does not echo |
| DTR | On (the default in PuTTY, Tera Term, screen, minicom, `pio device monitor` and pyserial). With DTR off, commands still run but every reply is thrown away. |

Examples:

```
pio device monitor --echo                 # PlatformIO; add -p COM7 if needed
screen /dev/ttyACM0 115200                # Linux (macOS: /dev/cu.usbmodem*)
```

PuTTY: connection type Serial, your COM port, speed 115200; under Connection → Serial set Flow
control to None; under Terminal set Local echo to Force on.

The firmware prints a one-line greeting only if a terminal is already open in the first 1.5 s after
a restart. A terminal opened later sees nothing until you type something: try `ID?`.

### Web GUI

[`tools/pidg_gui`](tools/pidg_gui) is a browser page for the same commands. It shows every setting
with the value the hardware actually produces, and draws the timing of one pulse pair (and of three
pairs in a row) from the board's own report. It runs a small web server on your computer; the only
thing to install is pyserial:

```
python -m pip install pyserial
python tools/pidg_gui/pidg_gui.py --connect auto        # then open http://127.0.0.1:8765
```

- It opens the Pico's serial port itself, so close any other terminal first.
- Esc or the DISARM button disarms from anywhere on the page. Closing the page does not disarm.
- `--connect sim` runs it against [`tools/pidg_sim`](tools/pidg_sim) instead: the firmware's real
  command code, built for your computer, with no board needed.

See [its README](tools/pidg_gui/README.md) for the full guide.

### Scripting (Python)

[`tools/pidg_example.py`](tools/pidg_example.py) is a complete example using pyserial
(`python -m pip install pyserial`). It finds the port, reads `STATUS`, sets the timing, arms, and
always disarms at the end, however the script stops:

```
python tools/pidg_example.py --freq 15 --width 100 --delay 10000 --seconds 5
```

The core of a host script looks like this:

```python
import serial

ser = serial.Serial("COM7", 115200, timeout=1)       # DTR is on by default

def cmd(line):
    ser.write((line + "\n").encode())
    return ser.readline().decode().strip()           # one-line replies

def status():
    ser.write(b"STATUS\n")
    out = {}
    while True:
        line = ser.readline()
        if not line:
            raise TimeoutError("no STATUS reply (wrong port, or DTR off?)")
        key, _, value = line.decode().strip().partition("=")
        out[key] = value
        if key == "TX_DROPPED":                      # always the last STATUS line
            return out

try:
    assert status()["HW"] == "OK"
    for c in ("WIDTH 100", "DELAY 10000", "FREQ 15"):
        reply = cmd(c)
        if not reply.startswith("OK "):
            raise RuntimeError(reply)                # e.g. "ERR DELAY rejected: DELAY must leave ..."
    print(cmd("ARM"))                                # pulses start after <= 1 s hold-off
    ...                                              # acquire
finally:
    print(cmd("DISARM"))                             # -> "OK ARMED=0"
```

Rules for host scripts:
- **Send `ARM` after every restart.** The board always comes back DISARMED. Check `RESET=` in
  `STATUS` first: if it says `WATCHDOG`, the firmware crashed and restarted itself, so stop and ask
  the operator before arming again.
- **Read `STATUS` by key, not by line position.** New keys may be added. `TX_DROPPED` is always the
  last line.
- **Closing the port does not disarm.** Always send `DISARM` yourself.
- `HELP` output mixes LF and CR+LF line endings, so split on LF and strip any trailing CR.

### Wireless (Wi-Fi / Bluetooth)

**Not supported by the current firmware.** The board talks over USB only, and the Pico 2 W's radio
is never switched on. The Pico 2 W is fitted only because it is easier to buy than the plain Pico 2.

Wireless control is possible as a future option, as firmware-only work:
- switch on the radio;
- carry the same text commands over the wireless link;
- add a login;
- decide whether `ARM` may be sent wirelessly (`DISARM` must always stay reachable).

The [web GUI](#web-gui) would need no change: it already accepts a network address such as
`socket://pidg.local:4242` wherever it takes a serial port.

The board has solid copper under the module's antenna, which shortens the radio's range. That is
fine for the intended short range (a few metres, like Bluetooth), so no board change is needed.

---

## Command reference

### Rules

- One command per line. Upper or lower case both work; separate words with spaces or tabs.
- A name on its own **asks** for a value (`DELAY`); a name followed by a number **sets** it
  (`DELAY 5000`). There is no `NAME?` form, except `ARM?` and `ID?`.
- Numbers are plain whole numbers (0 … 4294967295): no units, decimal points, signs or hex. Times
  are in **ns** and frequencies in **Hz**.
- Backspace and DEL edit the line. Lines can be up to 95 characters.
- A successful set replies `OK NAME=value (actual …)`; a query replies `NAME=value (actual …)`;
  errors start with `ERR`.
- A rejected set changes nothing: the previous settings keep running.
- Each new value is checked **together with all the current settings**, so the order of changes
  can matter. For example, to raise `FREQ` a lot, shorten `WIDTH` first.

### Commands

| Command | Unit | Default | Allowed values | What it sets |
|---|---|---|---|---|
| `FREQ [n]` | Hz | 1000 | 1 up to where 2 × WIDTH + DELAY still fits in 1/FREQ | How many pulse pairs per second |
| `WIDTH [n]` | ns | 100 | ≥ 17 (becomes ≥ 20.000 ns), and 2 × WIDTH + DELAY ≤ 1/FREQ. No upper limit. | Length of both laser pulses |
| `DELAY [n]` | ns | 10000 | 0 up to 1/FREQ − 2 × WIDTH, so pulse pairs stay apart (with `COMBINE 1`, also more than WIDTH); the error message gives the exact limit | Time from the start of the Laser 1 pulse to the start of the Laser 2 pulse. `0` makes them start together. |
| `MARKERWIDTH [n]` | ns | 2000 | 17 up to 1/FREQ − 5 steps | Length of the camera marker pulse (it starts with every Laser 1 pulse) |
| `SYNC [n]` | Hz | 1000000 | 1145 … 75 000 000 | Camera sync clock. **Leave it at 1 MHz for the IDS/Prophesee cameras** ([why](#timing)); the web GUI keeps it fixed. |
| `COMBINE [n]` | 0 / 1 | 0 | 0 or 1; change only while DISARMED | 0: Laser 1 gets the CH1 pulse, Laser 2 the CH2 pulse. 1: **both** outputs get **both** pulses ([details](#combined-mode-combine)) |
| `PIXGATE [n]` | 0 / 1 / 2 | 0 | 0, 1 or 2 | Hold the camera pixels in reset between pulse pairs: 0 off (J12 only), 1 while ARMED, 2 always ([details](#pixel-reset-gate-pixgate)) |
| `PIXLEAD [n]` | ns | 10000 | ≥ 30 (becomes ≥ 5 steps); the window must fit in 1/FREQ | Pixels released this long before each Laser 1 pulse |
| `PIXLAG [n]` | ns | 100000 | PIXLEAD + DELAY + WIDTH + PIXLAG ≤ 1/FREQ − 3 steps | Pixels reset again this long after the last laser pulse |
| `ARM` | – | disarmed | exactly `ARM`, nothing after it | Allow the laser pulses |
| `DISARM` | – | – | – | Stop the laser pulses at once; recognised anywhere in what you type |
| `ARM?` | – | – | – | Report the arm state: `ARMED=0` or `ARMED=1` |
| `STATUS` | – | – | – | All settings, the arm state and system information |
| `ID?` | – | – | – | Firmware name and build date |
| `HELP` | – | – | – | Command summary |

A "step" is one 6.667 ns tick of the 150 MHz clock.

### Examples

```
DELAY 1003     ->  OK DELAY=1003 (actual 1000.000 ns, 150 cyc)
DELAY          ->  DELAY=1003 (actual 1000.000 ns, 150 cyc)
WIDTH 101      ->  OK WIDTH=101 (actual 100.000 ns, 15 cyc)
SYNC 2000000   ->  OK SYNC=2000000 (actual 2000000.000 Hz, divider 37+128/256, 1-cycle jitter)
ARM            ->  OK ARMED=1 (laser pulses start after a 498 us hold-off)
DISARM         ->  OK ARMED=0
ID?            ->  PiDG delay generator (Pico 2 W), firmware built Sep 24 2026 22:24:21
```

- The number after `=` is what you asked for; `actual` is what the hardware produces; `cyc` is the
  same in 6.667 ns steps ("cycles").
- The `(laser pulses start after …)` part appears only while a start delay (the hold-off, below) is
  pending; otherwise `ARM` replies just `OK ARMED=1`.
- `1-cycle jitter` on `SYNC` means the clock can't be divided down exactly: the average frequency is
  the `actual` value shown (e.g. `SYNC 1234567` → `actual 1234567.901 Hz`), and single edges can be
  up to 6.667 ns early or late. Frequencies that divide 75 MHz exactly (1 MHz, 2.5 MHz, 5 MHz, …)
  have no jitter.

### ARM and DISARM in detail

- **`ARM`** must be the word on its own: `ARM 1` gives `ERR ARM takes no argument`. `ARM` while
  already armed changes nothing.
- **The hold-off.** The reply comes at once, but the pulses start only after a wait of one full
  pulse period (the longer of the old and new periods, at most 1 s), counted from the last laser
  pulse. After a restart, pulses can't start until 1 s after it. This guarantees that two laser
  pulses are never closer together than the set period, whatever commands arrive. The marker pauses
  during the hold-off, so marker-triggered cameras miss triggers for that time. When the pulses
  start, the CH1, CH2 and marker timing restarts together, and the first pulse is full width.
  `START_PENDING_US` in `STATUS` shows the time left.
- Changing `FREQ`, `WIDTH`, `DELAY` or `MARKERWIDTH` while armed goes through the same hold-off and
  stays armed. A change that ends up at the same step counts (e.g. `WIDTH 100` → `WIDTH 101`)
  restarts nothing.
- **`DISARM`** is never refused. The outputs go low the moment the `M` arrives, the rest of that line
  is ignored, and a pending start is cancelled. It works even when the host is not reading replies,
  though a host that has stopped reading can delay it by up to about 250 ms. The letters must be on
  one line: `DIS`, Enter, `ARM`, Enter is two commands and **arms** the board.
- While DISARMED, **the sync clock and the marker keep running**, so the cameras stay synchronised.
  The laser outputs are held at 0 V.

### Combined mode (`COMBINE`)

`COMBINE 1` sends the whole double pulse (the CH1 pulse, then the CH2 pulse exactly `DELAY` later)
to **both** Laser 1 (J7) and Laser 2 (J8). Use it when one light source must make both PIV flashes,
or to fire two light sources together with the same double pulse. Each output still drives one
laser driver.

```
COMBINE 1   ->  OK COMBINE=1 (CH1 + CH2 on LASER 1 and LASER 2)
COMBINE 0   ->  OK COMBINE=0 (CH1 on LASER 1, CH2 on LASER 2)
```

- **Change it only while DISARMED.** While armed the reply is
  `ERR COMBINE rejected: DISARM first: COMBINE changes what both laser outputs carry`.
- **The pulses must stay apart:**
  - `DELAY` must be at least one step (6.667 ns) longer than `WIDTH`, e.g. `DELAY` ≥ 106.667 ns at
    `WIDTH 100`. At exactly `DELAY` = `WIDTH` the second pulse would start as the first ends, and the
    two would merge into one pulse of twice the width.
  - `DELAY` ≤ 1/FREQ − 2 × `WIDTH`, as in the normal mode, so each pair is separate from the next.
  - Each driver now gets two pulses per period: check its own spacing and duty ratings. The firmware
    does not impose any.
- The timing is exactly as precise as in the normal mode.
- The monitor points follow: TP4 and J10 pin 1 both show the double pulse, and with J10 on 1-2 the
  cameras are triggered on both pulses.

### Pixel-reset gate (`PIXGATE`)

PiDG can hold every camera's pixels in reset **between pulse pairs**, like a shutter: the pixels
are free from `PIXLEAD` before the Laser 1 pulse until `PIXLAG` after the last laser pulse, and
held in reset for the rest of each period. This cuts out background and noise events between
pairs, and every pair starts from freshly reset pixels.

```
            pair k                                        pair k+1
CH1     ____|‾|______________________________________________|‾|______
CH2     _________|‾|______________________________________________|‾|_
TDRSTN  ‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾|__________________________|‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾   (low = pixels in reset)
                   |<------>|                          |<------>|
                    PIXLAG       pixels in reset         PIXLEAD
```

(`TDRSTN` is the camera's pixel-reset pin.)

| Setting | Default | Meaning |
|---|---|---|
| `PIXGATE 0` | ✓ | Off: only J12 controls the pixel reset |
| `PIXGATE 1` | | Reset between pulse pairs **while ARMED**; off while DISARMED |
| `PIXGATE 2` | | Reset between pulse pairs **always**, even while DISARMED (for bench tests without lasers) |
| `PIXLEAD n` | 10000 ns | Pixels released this long before each Laser 1 pulse starts (at least 5 steps, 33.333 ns) |
| `PIXLAG n` | 100000 ns | Pixels reset again this long after the last laser pulse ends |

```
PIXGATE 1   ->  OK PIXGATE=1 (pixels reset between pulse pairs while ARMED)
PIXLAG 50000 -> OK PIXLAG=50000 (actual 50000.000 ns, 7500 cyc)
```

- **J12 still works.** The pixels are in reset whenever J12 is low **or** the gate is. With
  `PIXGATE 0`, J12 alone controls the reset.
- **Find PIXLEAD and PIXLAG by experiment.** How long the sensor needs to settle after a reset, and
  how long after a flash its events keep arriving, are not published. Start generous (the
  defaults), look at the event stream, then tighten. The window must fit in the period:
  `PIXLEAD + DELAY + WIDTH + PIXLAG` ≤ 1/FREQ − 3 steps; the error message gives the largest
  `PIXLAG` that fits.
- **The first pulse pair after a start has no reset before it;** every later pair does. The gate is
  timed from the same start as CH1/CH2, to the exact step.
- `STATUS` shows the result as `PIXRESET=`: reset time per period, when it starts after CH1, and how
  long the pixels are free around each pair.
- A pixel reset also puts a timestamp (trigger channel 1) into each camera's event stream, when the
  camera software's trigger channel is enabled.

### Timing

```
            |<---------------------- period = 1/FREQ ---------------------->|
CH1  (J7)  _|‾‾‾‾|______________________________________________________________|‾‾‾‾|_
             WIDTH
CH2  (J8)  ____________|‾‾‾‾|__________________________________________________________
            |<-DELAY-->|
MARKER     _|‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾|____________________________________________|‾‾‾‾‾‾‾
             MARKERWIDTH
SYNC       _|‾|_|‾|_|‾|_|‾|_|‾|_|‾|_|‾|_|‾|_|‾|_|‾|_|‾|_ ... runs all the time, 1 MHz
```

- **Rounding:** times round to the nearest 6.667 ns step, and frequencies to the nearest whole
  number of steps per period. All limits are checked on the rounded values.
- **The Laser 2 pulse starts exactly `DELAY` after Laser 1,** to the step.
- **The marker** starts at the same instant as every Laser 1 pulse and repeats at exactly the same
  rate, so it can never drift away from the pulse it marks. Each camera records it as a timestamp,
  which gives every pulse pair its own reference time. With the default 2 µs `MARKERWIDTH`, `FREQ`
  can go up to about 490 kHz; shorten `MARKERWIDTH` to go higher.
- **The sync clock** is independent of the laser timing. The IDS uEye EVS cameras (Prophesee IMX636
  sensor) need it at **1 MHz**: a camera running as sync slave counts its 1 µs event timestamps on
  this clock, and Prophesee requires Sync In to be "a 1MHz pulse train to correspond to the
  internally generated 1µs timestamp resolution". Any other frequency stretches or squeezes every
  camera's timestamps, and an IMX636 slave sends no data at all until the clock arrives. Other
  `SYNC` values are only for other equipment.
- **No laser-driver limits.** The firmware does not limit pulse width, duty or spacing: they depend
  on the driver you connect, so stay within its ratings. It only enforces what keeps the waveform
  correct:
  - **pulse pairs stay apart:** `DELAY` ≤ 1/FREQ − 2 × `WIDTH`, so the Laser 2 pulse ends at least
    one `WIDTH` before the next Laser 1 pulse (this also limits `WIDTH` to half the period);
  - **shortest pulse:** 3 steps (20.000 ns) for `WIDTH` and `MARKERWIDTH`;
  - with `COMBINE 1`, `DELAY` > `WIDTH` ([Combined mode](#combined-mode-combine)).
- **Slowest rate:** `FREQ` goes down to 1 Hz.
- **Delay through the hardware:** the board's output driver (U13) adds about 13–25 ns to both
  channels alike, so the time between the two pulses at J7/J8 is kept to within 1–2 ns. (Your laser
  drivers add their own delays.)

### Errors

| Reply | Meaning |
|---|---|
| `ERR <word> unknown command` | Not a command. Note that `FREQ?` is not valid; use `FREQ`. |
| `ERR <NAME> invalid value` | Not a plain whole number (e.g. `1.5`, `10k`, `-5`), or too large |
| `ERR <NAME> takes one value` | More than one number |
| `ERR ARM takes no argument` | Something after `ARM` |
| `ERR line too long` | More than 95 characters; the whole line is ignored |
| `ERR <NAME> rejected: value must be > 0` | FREQ or SYNC set to 0 |
| `ERR <NAME> rejected: WIDTH realizes below the 3-cycle minimum (20.000 ns)` | WIDTH ≤ 16 ns (the same for MARKERWIDTH) |
| `ERR <NAME> rejected: DELAY must leave >= WIDTH before the next pulse pair (DELAY <= 1/FREQ - 2 x WIDTH); max DELAY … ns` | DELAY too long for the period at this WIDTH |
| `ERR <NAME> rejected: WIDTH too long for the period: 2 x WIDTH must fit in 1/FREQ` | WIDTH longer than half the period |
| `ERR <NAME> rejected: COMBINE needs DELAY > WIDTH so the two pulses stay separate (min DELAY … ns)` | With `COMBINE 1`, DELAY not longer than WIDTH |
| `ERR <NAME> rejected: MARKERWIDTH must fit in the period (MARKERWIDTH <= 1/FREQ - 5 cycles); max MARKERWIDTH … ns` | MARKERWIDTH too long for the period, e.g. after raising FREQ |
| `ERR MARKERDIV removed: the marker fires with every pulse pair` | `MARKERDIV` is no longer a setting |
| `ERR <NAME> rejected: FREQ out of range` | FREQ above 300 MHz |
| `ERR <NAME> rejected: SYNC out of range (1145..75000000 Hz)` | SYNC outside its range |
| `ERR ARM …` / `ERR <NAME> rejected: pio0 unavailable` | The pulse hardware failed to start (`HW=` in STATUS) |

`<NAME>` is the setting you were changing, which is not always the one named in the reason. For
example, `FREQ 600000` with the default 2 µs `MARKERWIDTH` gives a `MARKERWIDTH` error.

### STATUS

```
FREQ=15 (actual 15.000 Hz, period 10000000 cyc)
WIDTH=100 (actual 100.000 ns, 15 cyc)
DELAY=10000 (actual 10000.000 ns, 1500 cyc)
MARKERWIDTH=2000 (actual 2000.000 ns, 300 cyc)
SYNC=1000000 (actual 1000000.000 Hz, divider 75+0/256)
COMBINE=0 (CH1 on LASER 1, CH2 on LASER 2)
PIXGATE=0 (off: pixel reset from J12 only)
PIXLEAD=10000 (actual 10000.000 ns, 1500 cyc)
PIXLAG=100000 (actual 100000.000 ns, 15000 cyc)
PIXRESET=off
ARMED=1
HW=OK
START_PENDING_US=0
CLK=150000000
RESET=POWER_ON
RESET_RAW=WD:0x0 CHIP:0x0
WDT_RESETS=0
WDT_MS=3000
TX_DROPPED=0
```

| Key | Meaning |
|---|---|
| `FREQ` … `SYNC` | Each setting as you asked for it, with the value actually produced |
| `COMBINE` | 0 = CH1 on Laser 1, CH2 on Laser 2; 1 = both pulses on both outputs |
| `PIXGATE`, `PIXLEAD`, `PIXLAG` | The pixel-reset gate settings |
| `PIXRESET` | `off`, or the gate as produced: reset time per period, its start after CH1, and how long the pixels are free around each pair |
| `ARMED` | The firmware's arm state (1/0). J11 and the 12 V supply are separate gates it can't see. |
| `HW` | `OK`, or `ERR outputs not started: …` if the pulse hardware failed to start |
| `START_PENDING_US` | Microseconds until the pulses start after an `ARM` (0 = none pending) |
| `CLK` | Processor clock in Hz |
| `RESET` | Why the board last restarted: `POWER_ON`, `WATCHDOG` (the firmware crashed and restarted itself), `SOFT`, `DEBUG`, `BROWNOUT`, `GLITCH`, `RUN_PIN` or `UNKNOWN` |
| `RESET_RAW` | Raw restart registers (for bug reports) |
| `WDT_RESETS` | Crash restarts since power-on |
| `WDT_MS` | Crash-restart timeout (3000 ms). If the firmware ever hangs, it restarts DISARMED after this long. |
| `TX_DROPPED` | Bytes of replies thrown away because the host was not reading |

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| No serial port appears | Cable in J17 (power only) instead of the Pico's micro-USB; a charge-only cable; or the Pico is in bootloader mode (a drive named `RP2350` appears instead) | Use the Pico's port with a data cable. In bootloader mode, copy `firmware.uf2` to the drive, or unplug both J17 and the Pico's USB. |
| Port opens but nothing appears | The greeting is only sent in the first 1.5 s, and the firmware does not echo | Type `ID?` or `STATUS`; turn on local echo |
| Commands work but no replies arrive | The terminal has DTR off | Turn DTR on in the terminal settings |
| The port vanishes and an `RP2350` drive appears | The port was opened at 1200 baud, which restarts the Pico into its bootloader | Use any other baud rate. Copy `firmware.uf2` to the drive, or unplug both J17 and the Pico's USB. |
| `ERR … unknown command` for everything | A typo, the `FREQ?` form, the old `6,cmd;` framing, or XON/XOFF flow control | Use bare names; set flow control to None |
| `ERR … rejected: DELAY must leave >= WIDTH …` | DELAY + 2 × WIDTH is longer than 1/FREQ | Shorten DELAY or WIDTH, or lower FREQ; the message gives the longest allowed DELAY |
| `ERR … MARKERWIDTH must fit in the period …` at high FREQ | The marker (2 µs by default) is longer than the period allows | Shorten MARKERWIDTH first; the message gives the limit |
| `ERR ARM …`, or `HW=ERR …` in STATUS | The pulse hardware did not start | Load the firmware again; if it keeps happening, report the `STATUS` output |
| `ARMED=1` but no laser pulses | J11 not on 1-2; J16 pin 1 pulled low; J17 unplugged or the charger isn't giving 15 V; or still in the hold-off (`START_PENDING_US` > 0) | Check each gate. Measure `VBUS_PD` at C12 (about 15 V) and +12V at C17 (about 11.8 V; the outputs stay off outside 10.6–13.3 V). |
| Outputs dead after a restart | The board always restarts DISARMED | Send `ARM` |
| About 12 V pulses on the scope | J18/J19 on 1-2 (50 Ω mode) into a 1 MΩ scope input | Set the scope to 50 Ω (the laser driver has its own 50 Ω), or move the shunt to 2-3 for a high-impedance load |
| About 2.5 V pulses at the laser driver | J18/J19 on 2-3 (Hi-Z mode) into the driver's 50 Ω input | Move the shunt to 1-2 |
| One output gives ~3.5 V into 50 Ω, or ~12 V open | No shunt on that output's J18/J19 | Fit the shunt: 1-2 for 50 Ω, 2-3 for Hi-Z |
| About 3 V pulses at the laser driver | Two 50 Ω loads on one output (e.g. a tee into both a 50 Ω scope input and the driver) | Watch with a high-impedance scope probe instead, or on TP4 (CH2) / J10 pin 1 (CH1, through 100 Ω) |
| Cameras get no trigger | J10 on 1-2 while DISARMED, or no shunt on J10 | J10 on 2-3 |
| Cameras don't synchronise | A camera set as sync master, or SYNC changed | Set every camera to sync slave; `SYNC 1000000` |
| All cameras stuck in pixel reset | A 50 Ω terminator on J12; the source holding it low; a 1.8 V source that can't release it | Remove the terminator; drive J12 with 3.3 V or 5 V logic, or leave it open |
| Cameras see no events around the laser pulses with `PIXGATE` on | PIXLEAD too short for the sensor to settle, or PIXLAG shorter than the sensor's event delay | Increase PIXLEAD and PIXLAG, or set `PIXGATE 0` to compare |
| `RESET=WATCHDOG` in STATUS | The firmware hung and restarted itself, DISARMED | Note what you were doing and report it; arm again deliberately |
| `TX_DROPPED` keeps rising | The host is not reading the replies | Read every reply line |
| `pio run -t upload` can't find the Pico | The automatic restart into the bootloader failed | Unplug J17, then hold BOOTSEL while plugging in the Pico's USB, and upload again or copy the UF2 |
| First build fails on Windows with git path errors | The PlatformIO folder is on a long path | Keep it at the default `%USERPROFILE%\.platformio` |

---

## Building from source

The firmware is Arduino C++ on the [arduino-pico](https://github.com/earlephilhower/arduino-pico)
core, built with [PlatformIO](https://platformio.org/) (the VS Code "PlatformIO IDE" extension, or
`python -m pip install platformio`). The exact versions of the platform, core and compiler are
fixed in `platformio.ini`.

| Command | Builds |
|---|---|
| `pio run` | `pico2w` (default): Raspberry Pi Pico 2 W |
| `pio run -e pico2` | plain Raspberry Pi Pico 2 (same pins and socket) |
| `pio run -t upload` | builds and uploads to a connected board (send `DISARM` first) |

Output files land in `.pio/build/<env>/`, including `firmware.uf2` for drag-and-drop loading. Load
the image that matches the fitted module. The first build takes longer because PlatformIO downloads
the platform and compiler.

**Pin map** (`src/board.h`): GP13 = CH1 → J7, GP12 = CH2 → J8, GP11 = marker → J10 pin 3,
GP10 = sync → cameras and TP3, GP16 = pixel-reset gate. All of them are driven by the RP2350's PIO
(a small block of timing hardware beside the processor), so the timing doesn't depend on the
software.

### Timing checks

`tools/timing_check/` checks the timing arithmetic in `src/pulse_timing.h`, step by step, against an
independent model of the PIO hardware. Run it after changing `pulse_timing.h`:

```
cd tools/timing_check
g++ -std=c++17 -O2 -Wall -Wextra -o harness harness.cpp      # harness.exe on Windows
python check_exhaustive.py
python check_random.py
python check_marker_lock.py
python check_sync.py
python check_combined.py
python check_pixgate.py
```

The expected output is listed in [its README](tools/timing_check/README.md). These checks don't
replace a scope check on the board.

---

## Repository layout

| Path | Contents |
|---|---|
| `src/` | Firmware: `main.cpp` (start-up, arming, crash watchdog), `protocol.*` (serial commands), `pulse_timing.h` (timing maths and checks), `pio_pulse.*` (PIO programs), `laser_gate.*` (laser output gate), `board.h` (pin map) |
| `platformio.ini` | Build configuration (`pico2w` and `pico2` builds) |
| `tools/pidg_example.py` | Python example script |
| `tools/pidg_gui/` | Web GUI: settings, timing chart and console in the browser |
| `tools/pidg_sim/` | Simulator: the firmware's command code built for a computer, for trying the GUI and scripts without a board |
| `tools/timing_check/` | Timing checks run on a computer |
| `PiDG_Pico.kicad_pro` / `.kicad_sch` / `.kicad_pcb` | **Current hardware:** KiCad project of the 4-layer board |
| `Hardware.md` | [Full hardware reference](Hardware.md) |
| `fab/` | Manufacturing: master parts list `fab/PiDG_Pico_BOM.csv` (with the design-constraint notes), gerbers and drill files, and `fab/jlc/` JLCPCB assembly files and [order checklist](fab/jlc/JLC_ORDER.md) |
| `libs/`, `fp-lib-table`, `sym-lib-table` | Project-local KiCad symbols and footprints |
| `tools/jlc_cpl/` | Corrects the JLC placement file to JLC's own footprints (see its README) |

## License

MIT — see [LICENSE](LICENSE).
