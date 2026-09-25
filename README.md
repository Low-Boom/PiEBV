# PiDG

A Raspberry Pi Pico 2 W–based digital delay generator and event-camera synchroniser for
particle velocimetry. It fires two laser (or LED/LEP) drivers with a precisely set delay
between them, and keeps upto six event cameras synchronised to the same clock.

> **Status.** The current board (`Pico Version 4Layer/`) has not been fabricated yet. The
> firmware builds cleanly and its timing has been checked cycle-for-cycle in simulation, but
> nothing has run on real hardware. Do the [bench checks](#before-connecting-lasers-or-cameras)
> before connecting a laser driver or a camera.

**Contents:** [What it does](#what-it-does) ·
[Safety](#safety--read-this-first) · [The board](#the-board) · [Quick start](#quick-start) ·
[Connecting](#connecting) · [Command reference](#command-reference) ·
[Troubleshooting](#troubleshooting) · [Building from source](#building-from-source) ·
[Repository layout](#repository-layout)

---

## What it does

| Output | Where | Signal | Role |
|---|---|---|---|
| **Laser 1** (CH1) | BNC J7 | 5 V into 50 Ω | Trigger for the first laser driver (PicoLas LDP-V) |
| **Laser 2** (CH2) | BNC J8 | 5 V into 50 Ω | Trigger for the second laser driver; rises exactly `DELAY` after Laser 1 |
| **Sync** | Camera ports J1–J6, pin 5 | 1.8 V, 1 MHz by default | Common clock for all six cameras (they run as sync slaves) |
| **Trigger** | J1–J6, pin 4 | 1.8 V | Reference marker once every `MARKERDIV` pulse pairs (or every Laser 1 pulse; see [J10](#jumpers)) |
| **Pixel reset** | J1–J6, pin 3 | 1.8 V, active low | Follows the J12 BNC input; no firmware involved |

- CH1 and CH2 share one pulse `WIDTH` and one repetition rate `FREQ`.
- Every time is set in whole steps of **6.667 ns** (one cycle of the 150 MHz clock). Every reply shows the
  exact timing the hardware will produce, so you never have to correct for the step size.
- The firmware enforces the laser drivers' limits: pulse width ≤ 1000 ns and duty ≤ 0.1 %.
- Control is a plain-text command line over the Pico's USB serial port.

The target equipment is two **PicoLas LDP-V** laser-diode drivers (10-70 and 240-100) and six
**IDS uEye UE-39B0XCP-E** event cameras.

---

## Safety

- **The laser outputs start DISARMED** at every power-up and every reset. They only pulse after
  you send `ARM`.
- **`DISARM` always works, immediately.** The six letters D-I-S-A-R-M, in any case and anywhere in
  what you type, disarm the outputs as soon as the last letter reaches the board, without Enter,
  provided your terminal sends each key as you type it (every terminal listed under
  [USB serial](#usb-serial) does). A monitor with a separate input box, such as the Arduino IDE's,
  sends nothing until you press Enter.
- **Three independent gates must all be open** before J7/J8 pulse. Any one of them holds both outputs
  at 0 V:
  1. the firmware is ARMED (`ARM` command);
  2. a shunt is on **J11 pins 1-2** (the hardware interlock; no shunt or pins 2-3 = disabled);
  3. the 12 V laser-driver rail is in regulation, which needs a 15 V USB-C PD charger on **J17**.

  The firmware cannot see gates 2 and 3, so `ARMED=1` alone does not mean the outputs are live.
- **Losing the USB link does not disarm.** If the Pico's USB cable is pulled, the PC sleeps or a
  script is killed while ARMED, the board keeps running from J17 and the lasers keep pulsing, with
  no way to send `DISARM`. Stop them in hardware: move the J11 shunt off 1-2, pull J16 pin 1 low,
  or unplug J17.
- **J7 and J8 are for 50 Ω loads only.** Into 50 Ω they give 0 V / about 4.8 V (4.55–5.16 V
  worst case), which is what the LDP-V wants. Unterminated, or into a 1 MΩ scope input, they
  swing to about **12 V**.
- **One laser driver per output — never use a BNC tee.** Each output is built to drive exactly one
  50 Ω input. Simulated, with 1–2 m of coax:
  - J7 and J8 tied together into one driver: each pulse reaches only **3.4 V** (the idle output
    sinks half of it), below the LDP-V's 4.5 V minimum, so the driver fires badly. Where the pulses
    overlap (DELAY shorter than WIDTH, e.g. `DELAY 0`) both outputs push together and the input sees
    **6.9 V**, above its 5.2 V damage threshold.
  - One output split to two drivers: each sees **3.0 V**, too low for either.
  - The PiDG itself survives both (about 1 mW average in R6/R7 at the 0.1 % duty limit).

  To fire **one light source with both pulses**, or **two sources in sync with the same double
  pulse**, use `COMBINE 1` instead (see [Combined mode](#combined-mode-combine)): each output then
  carries both pulses, one driver per output.
- **Before any debugger (SWD) session: send `DISARM` and remove the J11 shunt** (or unplug J17).
  A debugger reset can leave a laser output high for milliseconds.
- **Before uploading new firmware, send `DISARM`.** The upload reboots the Pico. A reboot that lands
  in the middle of a pulse can stretch that one pulse by an estimated 70–150 ns (about 15 % at the
  1 µs maximum width).
- **Camera pins 1, 6 and 8 are not connected on the board.** Header pins 1, 6, 8, 9 and 10 of J1–J6
  are bare plated holes with no copper to anything, so a 1:1 ribbon cannot short the camera's own
  supplies (pin 1 is its 1.8 V output, pin 8 its USB 5 V) at the board. The remaining risk is in the
  harness: build it with only wires 2, 3, 4, 5 and 7 fitted (or cut 1, 6 and 8), and never tie
  pin 1 or 8 to a ground wire. Pin 6 is undocumented; do not assume it is a ground.
- **Set every camera to sync slave.** The board drives the sync pin, so a camera set as sync master
  would fight it.
- **Never fit a shunt on J16**, and never fit one across all three pins of J10.

Details are in [Hardware.md](Pico%20Version%204Layer/Hardware.md), under Boot and arming, Laser
interlock and Connectors.

---

## The board

Orientation used below: the USB-C connector J17 is on the **top** edge, and the three BNCs stick
out of the **right** edge. The Pico sits in two sockets left of centre with its micro-USB at the
top edge, and the six camera ports run along the bottom. The two USB ports on the top edge are
labelled on the silkscreen: **`CONTROL / PROGRAM — PICO MICRO-USB`** (data: serial commands and
firmware) and **`POWER ONLY — USB-C PD 15 V`** (J17).

```
 top edge:  TP3   Pico micro-USB = CONTROL          J17 USB-C = POWER ONLY
           +------------+--------+----------------------------------------+
           |            |  Pico  |                                   J16 =|  ENABLE/TRIG/GND
           |            |  2 W   |       J11 (laser enable)                |
           |            | in J14 |                                     J7 =|  Laser 1  (BNC)
           |            | / J15  |           J10 (trigger select)  TP4     |
           |            +--------+                                     J8 =|  Laser 2  (BNC)
           |                                                              |
           |  J1   J2   J3   J4   J5   J6   (camera ports)             J12 =|  Pixel reset (BNC)
           +--------------------------------------------------------------+
```

### Connectors

| Ref | What | Connect to | Signal |
|---|---|---|---|
| **J1–J6** | 2×5 IDC headers, cameras 1–6 | Camera 8-pin I/O harness (pin *n* = camera pin *n*) | 1 NC · 2 GND · 3 pixel reset (`TDRSTN`, active low) · 4 trigger · 5 sync · 6 NC · 7 GND · 8 NC · 9, 10 NC. All signals **1.8 V**. Pin 1 is the top-left pin. |
| **J7** | BNC, Laser 1 (CH1) | LDP-V trigger input (50 Ω) | 0 / ~4.8 V into 50 Ω; ~12 V open-circuit |
| **J8** | BNC, Laser 2 (CH2) | Second LDP-V | same as J7 |
| **J12** | BNC, pixel-reset **input** | Your reset source | Active LOW: pull to ground to hold all six cameras in reset. Open = cameras running. Accepts 3.3 V or 5 V logic, open-drain or a switch; the source must sink 1 mA. A 1.8 V logic high is **not** guaranteed to release reset. Do not add a 50 Ω terminator. |
| **J17** | USB-C, **power only** (silkscreen `POWER ONLY`) | USB-C PD charger that offers 15 V | No data. Programming and serial always use the Pico's own micro-USB, next to it on the top edge (`CONTROL / PROGRAM`). |
| **J10** | 1×3 trigger-source jumper | shunt | see [Jumpers](#jumpers) |
| **J11** | 1×3 laser interlock | shunt, or a normally-closed E-stop switch | see [Jumpers](#jumpers) |
| **J16** | 1×3 right-angle header, right edge | probes, or a secondary interlock | 1 `ENABLE IN` (pull LOW = lasers off) · 2 `TRIG OUT` (camera trigger, monitor only) · 3 GND. **Never fit a shunt.** |
| **TP3** | 1×2 right-angle header, top edge | scope | 1 = 1 MHz sync straight from the Pico (3.3 V) · 2 = GND |
| **TP4** | 1×2 header next to J10, `CH2` / `GND` | scope only | 1 = CH2 pulse straight from the Pico (3.3 V, idles LOW while DISARMED) · 2 = GND |

**J16 — interlock input and trigger monitor.** The silkscreen beside it reads, pin by pin,
`ENABLE IN: PULL LOW = LASERS OFF`, `TRIG OUT: CAMERA TRIGGER (MONITOR)` and `GND`, with
`J16: NEVER FIT A SHUNT` and `NOT FAIL-SAFE - PUT THE E-STOP ON J11` below.
- **Pin 1, ENABLE IN:** pulled up to 5 V on the board (3.3 kΩ). Pulling it LOW, with a switch or
  open-collector output to pin 3 or with a 3.3 V or 5 V logic low (sinking about 1.5 mA), forces
  both laser outputs off. It is *enabled when open*, so a broken cable leaves the lasers enabled:
  use it for a secondary inhibit (a door switch, a control system's logic line), and put the E-stop
  on J11.
- **Pin 2, TRIG OUT:** the camera trigger that J10 selected (the marker, or every Laser 1 pulse),
  3.3 V logic, as it enters the camera trigger buffers. It is driven by a Pico output, so probe it;
  don't drive it.
- **Pin 3:** ground.
- **Never fit a shunt:** on 2-3 it grounds a Pico output and kills all camera triggers; on 1-2 it
  ties the laser enable to the trigger.

### Jumpers

Both headers are numbered 1-2-3 from **left to right**; pin 1 has the square pad.

| Jumper | Silkscreen | Shunt on 1-2 (left pair) | Shunt on 2-3 (right pair) | No shunt |
|---|---|---|---|---|
| **J11** laser enable | `ON` … `OFF` | **Lasers enabled** (the firmware must also be ARMED) | Lasers inhibited | Lasers inhibited (fail-safe) |
| **J10** trigger source | `CH1 TRG MKR` | Cameras triggered by every Laser 1 pulse (only while ARMED) | **Cameras triggered by the reference marker** (normal) | Camera triggers held low |

**J11 — laser interlock and safety switch.** The silkscreen reads `ON` / `OFF` and
`LASER INTERLOCK: ON = 1-2`, `E-STOP: NC SWITCH ACROSS 1-2`. For a safety (E-stop) switch, remove
the shunt and wire a **normally-closed** switch across pins 1 and 2. Closed = lasers enabled
(subject to ARM and the 12 V rail); pressing the switch **or** breaking its cable opens the circuit,
and R8 then holds the interlock off, so the stop is fail-safe. Don't use J16 pin 1 as the E-stop
input: it is enabled when open, so a broken cable there would leave the lasers enabled.

**J10 — camera trigger source.** The silkscreen reads `CH1 TRG MKR` under the pins, with
`CAMERA TRIGGER: TRG-MKR = MARKER / TRG-CH1 = LASER 1` beside it. `TRG` (pin 2) feeds the trigger
input (pin 4) of all six camera ports. Shunt `TRG` to `MKR` for the reference marker (normal, runs
while disarmed), or to `CH1` for a trigger on every Laser 1 pulse (only while ARMED). Never shunt all
three pins.

**TP4 — CH2 scope point.** Labelled `CH2` / `GND` and `SCOPE ONLY`. Pin 1 is the raw Laser 2 pulse
from the Pico (GP12, 3.3 V logic, before the interlock and driver; LOW while DISARMED), pin 2 is
ground. Use it to check CH2 timing without loading J8. The matching CH1 point is J10 pin 1 (through
100 Ω). Probe only — never drive TP4.

### Seating the Pico

Fit a **Raspberry Pi Pico 2 W** (or a plain Pico 2, which needs the `pico2` firmware image) with
male headers into sockets J14 (left) and J15 (right). Seat it **component side up, with its
micro-USB connector at the top edge**, where the silkscreen reads `CONTROL / PROGRAM — PICO
MICRO-USB`. Pico pin 1 then goes into the top-left socket hole, marked `1`. Fitted the other way round,
the board's +5 V would land on one of the module's GPIO pins and could destroy it.

Fit the Pico before connecting any camera. Without it, the camera sync and reset lines float.

### Power

| Supplies connected | What works |
|---|---|
| **J17 (15 V PD charger) + Pico USB** | Everything. This is the normal set-up. |
| Pico USB only | Serial control, sync, trigger and pixel reset to the cameras. **Laser outputs stay off**, because there is no 12 V rail. |
| J17 only | The board runs, disarmed, with sync and marker at their defaults. There is no serial connection, so it cannot be armed. |

**Charger:** a USB-C PD charger that offers **15 V**. In practice that means any PD charger rated
30 W or more (the USB-PD rules require chargers above 27 W to offer 15 V). With a 5 V or 9 V-only
charger the board still runs, but the laser outputs stay disabled.

**Full power cycle:** unplug both J17 and the Pico's USB cable. Unplugging just one of them doesn't
reset the board, and neither does closing the serial port.

---

## Quick start

You need: the assembled board, a Pico 2 W, a micro-USB **data** cable, a USB-C PD charger
(≥ 30 W, offers 15 V) with a USB-C cable, jumper shunts, and a scope with 50 Ω inputs (or 50 Ω
feed-through terminators).

1. **Build and flash the firmware** (first time only):
   ```
   pio run                       # builds .pio/build/pico2w/firmware.uf2
   ```
   Do this before seating the Pico in the board (or with J17 unplugged, since J17 also powers the
   Pico). Hold the **BOOTSEL** button on the Pico while plugging its USB cable into your computer. A drive
   named `RP2350` appears. Copy `firmware.uf2` onto it; the drive disappears and the Pico starts
   the firmware. (Later updates can use `pio run -t upload`; see
   [Building from source](#building-from-source).)
2. **Seat the Pico**, component side up, USB toward the top edge ([details](#seating-the-pico)).
3. **Set the jumpers:** J10 on **2-3** (cameras triggered by the marker). Leave **J11 empty** for
   now (lasers inhibited).
4. **Power up:** the charger into J17, and the Pico's micro-USB into your computer.
5. **Open a serial terminal** on the Pico's port ([how](#usb-serial)). Turn on local echo, because
   the firmware does not echo what you type. Type `STATUS` and press Enter. You should see:
   ```
   FREQ=1000 (actual 1000.000 Hz, period 150000 cyc)
   WIDTH=100 (actual 100.000 ns, 15 cyc)
   DELAY=10000 (actual 10000.000 ns, 1500 cyc)
   MARKERDIV=100
   MARKERWIDTH=2000 (actual 2000.000 ns, 300 cyc)
   SYNC=1000000 (actual 1000000.000 Hz, divider 75+0/256)
   COMBINE=0 (CH1 on LASER 1, CH2 on LASER 2)
   ARMED=0
   HW=OK
   ...
   ```
6. **Set your timing**, for example 15 Hz pulse pairs, 100 ns wide, 10 µs apart:
   ```
   FREQ 15        ->  OK FREQ=15 (actual 15.000 Hz, period 10000000 cyc)
   WIDTH 100      ->  OK WIDTH=100 (actual 100.000 ns, 15 cyc)
   DELAY 10000    ->  OK DELAY=10000 (actual 10000.000 ns, 1500 cyc)
   ```
7. **Bench-check the laser outputs with no laser connected.** Connect J7 and J8 to the scope with
   **50 Ω termination**. Fit J11 on **1-2**, then type `ARM`. Within one pulse period you should see:
   - pulses from 0 V to about 4.8 V;
   - the J8 edge exactly `DELAY` after the J7 edge.

   Type `DISARM`: both outputs must drop to 0 V.
8. **Connect the equipment.** Plug in the laser drivers (J7, J8) and the cameras (J1–J6, one camera
   first; see [the bench checks](#before-connecting-lasers-or-cameras)). Then `ARM` to run, and
   `DISARM` when you're done.

Settings are **not saved**. Every reset or power cycle restores the defaults (FREQ 1000, WIDTH 100,
DELAY 10000, MARKERDIV 100, MARKERWIDTH 2000, SYNC 1000000) and leaves the lasers DISARMED.

### Before connecting lasers or cameras

The board is unproven, so do these checks on every newly assembled board (full list: Hardware.md,
Open items).

- **Before the first power-up on J17**, with no power applied: check that `VBUS_PD` is not shorted
  to GND, CC1 or CC2 (at J17 and U14), and that +5V_PD and +5V are not shorted to GND (at U16). J17
  (0.5 mm pitch) and U16 (0.65 mm) are where solder bridges are likely, and a VBUS-to-CC bridge
  would put up to 20 V on U14. Also check that J17's four shell legs are soldered.
- **Laser outputs,** into a 50 Ω-terminated scope with no driver connected:
  - `LASER_PWR_OK` (U13 pins 1 and 8) reads about 12 V with the charger on J17;
  - amplitude 0 V to 4.55–5.16 V;
  - CH2 exactly `DELAY` after CH1 (`DELAY 13` should give 13.3 ns);
  - the first pulse after `ARM` is full width;
  - 0 V after `DISARM` and after a full power cycle; and, while ARMED with pulses running, 0 V once
    J17 is unplugged, with no stray pulse while it is plugged back in.
- **Charger:** measure `VBUS_PD` at C12 (about 15 V) with the charger you will actually use.
- **Cameras:** with **one** camera, measure pixel reset, trigger and sync at the camera end of the
  harness, and confirm the camera is not driving pin 5 (it must be a sync slave). Only then connect
  all six.

---

## Connecting

### USB serial

Use the **Pico's micro-USB port**; J17 carries power only. The Pico shows up as a standard USB
serial port and needs no driver on Windows 10/11, macOS or Linux.

| OS | Where to find the port |
|---|---|
| Windows | Device Manager → Ports (COM & LPT) → `USB Serial Device (COMn)` |
| macOS | `/dev/cu.usbmodem*` |
| Linux | `/dev/ttyACM*` (your user may need to be in the `dialout` group) |
| Any | `pio device list` |

The port's USB ID is `2E8A:F00F` with the `pico2w` firmware and `2E8A:000F` with the `pico2` firmware.

**Terminal settings**

| Setting | Value |
|---|---|
| Baud rate | Anything **except 1200**, which reboots the Pico into its bootloader. 115200 is conventional. |
| Line ending | CR, LF or CR+LF — all work |
| Flow control | None |
| Local echo | **On**: the firmware does not echo |
| DTR | On (the default in PuTTY, Tera Term, screen, minicom, `pio device monitor` and pyserial). Without DTR, commands still run but every reply is discarded. |

Examples:

```
pio device monitor --echo                 # PlatformIO; add -p COM7 if needed
screen /dev/ttyACM0 115200                # Linux (macOS: /dev/cu.usbmodem*)
```

PuTTY: connection type Serial, your COM port, speed 115200; under Connection → Serial set Flow
control to None; under Terminal set Local echo to Force on.

The firmware prints a one-line banner only if a terminal is already open in the first 1.5 s after
reset. A terminal opened later sees nothing until you type something. Try `ID?`.

### Scripting (Python)

[`tools/pidg_example.py`](tools/pidg_example.py) is a complete example using pyserial
(`python -m pip install pyserial`). It finds the port, reads `STATUS`, sets the timing, arms, and
disarms in a `finally` block however the script ends:

```
python tools/pidg_example.py --freq 15 --width 100 --delay 10000 --seconds 5
```

The core of a host script looks like this:

```python
import serial

ser = serial.Serial("COM7", 115200, timeout=1)       # DTR is asserted by default

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
            raise RuntimeError(reply)                # e.g. "ERR FREQ rejected: laser limit: ..."
    print(cmd("ARM"))                                # pulses start after <= 1 s hold-off
    ...                                              # acquire
finally:
    print(cmd("DISARM"))                             # -> "OK ARMED=0"
```

Rules for host scripts:
- **Send `ARM` after every reset.** The board always comes back DISARMED. Check `RESET=` in `STATUS`
  first, and if it says `WATCHDOG`, stop and ask the operator before re-arming.
- **Parse `STATUS` by key, not by line position.** New keys may be added. `TX_DROPPED` is the last line.
- **Closing the port does not disarm.** Always send `DISARM` yourself.
- `HELP` output mixes LF and CR+LF line endings, so split on LF and strip any trailing CR.

### Wireless (Wi-Fi / Bluetooth)

**Not supported by the current firmware.** The board talks over USB serial only, and the Pico 2 W's
radio is never switched on. The Pico 2 W is fitted only because it is easier to buy than the plain
Pico 2.

It is possible as a future option. The Pico 2 W's radio can do both Wi-Fi and Bluetooth, and adding
either would be firmware-only work:
- bring up the radio;
- carry the same text commands over the wireless link;
- add authentication;
- decide whether `ARM` may be sent wirelessly (`DISARM` must always stay reachable).

The board has solid copper under the module's antenna, which shortens the radio's range. That is
acceptable: the aim would be short range (a few metres, Bluetooth-like), so no board change is
needed. Until then, use USB.

---

## Command reference

### Rules

- One command per line. Command names are case-insensitive, and separators are spaces or tabs.
- A bare name **queries** a value (`DELAY`); a name followed by one number **sets** it (`DELAY 5000`).
  There is no `NAME?` form, except `ARM?` and `ID?`.
- Numbers are plain decimal integers (0 … 4294967295): no units, decimal points, signs or hex. Times
  are in **ns** and frequencies in **Hz**.
- Backspace and DEL edit the line. Lines are limited to 95 characters.
- Successful sets reply `OK NAME=value (actual …)`; queries reply `NAME=value (actual …)`; errors
  start with `ERR`.
- A rejected set changes nothing: the previous settings keep running.
- Each set is checked **together with the current values of all the other settings**, so the order
  of changes can matter. For example, to go to a higher `FREQ`, shorten `WIDTH` first.

### Commands

| Command | Unit | Default | Range (150 MHz clock) | What it sets |
|---|---|---|---|---|
| `FREQ [n]` | Hz | 1000 | 1 up to the duty limit: 10 000 at WIDTH 100, 50 000 at the 20 ns minimum width | Pulse-pair repetition rate |
| `WIDTH [n]` | ns | 100 | 17 … 1003 (realizes to 20.000 … 1000.000 ns), and WIDTH × FREQ ≤ 0.1 % | Width of both CH1 and CH2 pulses |
| `DELAY [n]` | ns | 10000 | 0 up to period − WIDTH − 5 cycles (33.3 ns); the error message gives the exact maximum | CH2 rising edge after CH1 rising edge. `0` makes them coincide. |
| `MARKERDIV [n]` | count | 100 | ≥ 1, and MARKERDIV × period ≤ 2³²−1 cycles (about 28.6 s) | Marker fires once every *n* pulse pairs |
| `MARKERWIDTH [n]` | ns | 2000 | 17 up to the marker period − 5 cycles | Marker pulse width (no laser limit) |
| `SYNC [n]` | Hz | 1000000 | 1145 … 75 000 000 | Camera sync clock frequency (free-running square wave) |
| `COMBINE [n]` | 0 / 1 | 0 | 0 or 1; change only while DISARMED | 0: CH1 → Laser 1, CH2 → Laser 2. 1: **both** pulses on **both** outputs ([details](#combined-mode-combine)) |
| `ARM` | – | disarmed | exactly `ARM`, no argument | Enable the laser outputs |
| `DISARM` | – | – | – | Disable the laser outputs at once; recognised anywhere in the input |
| `ARM?` | – | – | – | Report the arm state: `ARMED=0` or `ARMED=1` |
| `STATUS` | – | – | – | All settings, the arm state and system information |
| `ID?` | – | – | – | Firmware identity and build date |
| `HELP` | – | – | – | Command summary |

### Examples

```
DELAY 1003     ->  OK DELAY=1003 (actual 1000.000 ns, 150 cyc)
DELAY          ->  DELAY=1003 (actual 1000.000 ns, 150 cyc)
WIDTH 101      ->  OK WIDTH=101 (actual 100.000 ns, 15 cyc)
MARKERDIV 50   ->  OK MARKERDIV=50
SYNC 2000000   ->  OK SYNC=2000000 (actual 2000000.000 Hz, divider 37+128/256, 1-cycle jitter)
ARM            ->  OK ARMED=1 (laser pulses start after a 498 us hold-off)
DISARM         ->  OK ARMED=0
ID?            ->  PiDG delay generator (Pico 2 W), firmware built Sep 24 2026 22:24:21
```

- The number after `=` is what you asked for; `actual` is what the hardware produces; `cyc` is the
  same in 6.667 ns cycles.
- The `(laser pulses start after …)` part appears only while a hold-off is pending; otherwise `ARM`
  replies just `OK ARMED=1`.
- `1-cycle jitter` on `SYNC` means the divider is fractional: the average frequency is the `actual`
  value shown (e.g. `SYNC 1234567` → `actual 1234567.901 Hz`), and individual edges move by up to
  6.667 ns. Frequencies that divide 75 MHz exactly (1 MHz, 2.5 MHz,
  5 MHz, …) have no jitter.

### ARM and DISARM in detail

- **ARM** must be the bare word. `ARM 1` gives `ERR ARM takes no argument`. `ARM` while already
  armed changes nothing.
- The reply comes at once, but the pulses start after a **hold-off** of one full period (the longer of
  the old and new periods), counted from when the laser outputs last pulsed: at most 1 s, and after a
  reset pulses cannot start until 1 s after it. The marker pauses during the hold-off, so
  marker-triggered cameras miss triggers for that time. The hold-off guarantees two laser pulses are never
  closer than the set period, whatever sequence of commands arrives. When the pulses start, CH1, CH2 and
  the marker start together, and the first pulse is full width. `START_PENDING_US` in `STATUS` shows the
  time remaining.
- Changing `FREQ`, `WIDTH`, `DELAY`, `MARKERDIV` or `MARKERWIDTH` while armed goes through the same
  hold-off and stays armed. A change that realizes to the same cycle counts (e.g. `WIDTH 100` →
  `WIDTH 101`) restarts nothing.
- **DISARM** is never refused. The outputs go low the moment the `M` arrives, the rest of that line
  is discarded, and a pending start is cancelled. It also works when the host is not reading replies, though a host that has
  stopped reading can delay it by up to about 250 ms.
  The letters must be on one line: `DIS`, Enter, `ARM`, Enter is two commands and **arms** the board.
- While DISARMED, **SYNC and the marker keep running**, so cameras stay synchronised. CH1/CH2 are held
  low.

### Combined mode (`COMBINE`)

`COMBINE 1` sends the whole double pulse — CH1's pulse, then CH2's pulse exactly `DELAY` later — to
**both** Laser 1 (J7) and Laser 2 (J8). Use it when one light source must produce both PIV pulses,
or to fire two sources in sync with the same double pulse. Each output still drives one laser driver.

```
COMBINE 1   ->  OK COMBINE=1 (CH1 + CH2 on LASER 1 and LASER 2)
COMBINE 0   ->  OK COMBINE=0 (CH1 on LASER 1, CH2 on LASER 2)
```

- **Change it only while DISARMED.** While armed the reply is
  `ERR COMBINE rejected: DISARM first: COMBINE changes what both laser outputs carry`.
- **The laser limits count both pulses**, because each driver now receives two per period:
  - duty: 2 × WIDTH × FREQ ≤ 0.1 % (at WIDTH 100 ns the maximum FREQ halves to 5 kHz);
  - spacing: `DELAY` ≥ 10 µs **and** period − `DELAY` ≥ 10 µs, rising edge to rising edge. That is
    the LDP-V 10-70's 100 kHz maximum repetition rate (`kLaserMinSpacingNs` in `src/pulse_timing.h`;
    the 240-100 alone would allow 500 ns). It also guarantees the two pulses never overlap.
- The timing is the same cycle-exact timing as the normal mode: the CH1 and CH2 state machines each
  drive both laser pins.
- The monitor points follow: TP4 and J10 pin 1 both show the double pulse, and with J10 on 1-2 the
  cameras are triggered on both pulses.

### Timing

```
            |<---------------------- period = 1/FREQ ---------------------->|
CH1  (J7)  _|‾‾‾‾|______________________________________________________________|‾‾‾‾|_
             WIDTH
CH2  (J8)  ____________|‾‾‾‾|__________________________________________________________
            |<-DELAY-->|
MARKER     _|‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾|____________ ... next one MARKERDIV periods later
             MARKERWIDTH
SYNC       _|‾|_|‾|_|‾|_|‾|_|‾|_|‾|_|‾|_|‾|_|‾|_|‾|_|‾|_ ... free-running, 1 MHz default
```

- **Quantization:** times round to the nearest 6.667 ns cycle; frequencies round to the nearest whole
  period in cycles. All limits are checked on the rounded (realized) values.
- **CH2 − CH1 = DELAY exactly**, to the cycle.
- **The marker** rises together with a CH1 pulse, and its period is exactly `MARKERDIV` × the CH1
  period, so it never drifts off the pulse it marks.
- **SYNC** is independent of the laser timing.
- **Laser limits** (PicoLas LDP-V 10-70, the stricter of the two drivers): realized WIDTH ≤ 1000 ns, and
  WIDTH × FREQ ≤ 0.1 %. Requests that would exceed them are rejected, not clamped, and the error tells
  you the highest FREQ allowed at the current WIDTH. To change the limits for other drivers, edit
  `kLaserMaxWidthNs` / `kLaserMaxDutyPpm` in `src/pulse_timing.h`. With `COMBINE 1` the duty counts
  both pulses and the pulses must be ≥ 10 µs apart ([Combined mode](#combined-mode-combine)).
- **Minimum width** is 3 cycles (20.000 ns) for WIDTH and MARKERWIDTH. The LDP-V 240-100's own 60 ns
  minimum is not enforced; shorter pulses simply under-drive it.
- **Low frequencies:** with MARKERDIV at 100 the lowest FREQ is 4 Hz. Lower MARKERDIV first (to ≤ 28
  for 1 Hz).
- **Hardware delays:** the laser driver stage adds about 13–25 ns, common to both channels, so the
  CH1–CH2 delay at J7/J8 is preserved to within the driver's channel-to-channel matching (1–2 ns).

### Errors

| Reply | Meaning |
|---|---|
| `ERR <word> unknown command` | Not a command. Note `FREQ?` is not valid; use `FREQ`. |
| `ERR <NAME> invalid value` | Not a plain whole number (e.g. `1.5`, `10k`, `-5`), or too large |
| `ERR <NAME> takes one value` | More than one number |
| `ERR ARM takes no argument` | Anything after `ARM` |
| `ERR line too long` | More than 95 characters; the whole line is ignored |
| `ERR <NAME> rejected: value must be > 0` | FREQ, MARKERDIV or SYNC set to 0 |
| `ERR <NAME> rejected: laser limit: realized WIDTH … ns > 1000 ns` | WIDTH over 1 µs |
| `ERR <NAME> rejected: laser limit: duty … ppm > 1000 ppm (max FREQ N Hz at this WIDTH)` | WIDTH × FREQ over 0.1 % |
| `ERR <NAME> rejected: WIDTH realizes below the 3-cycle minimum (20.000 ns)` | WIDTH ≤ 16 ns (same for MARKERWIDTH) |
| `ERR <NAME> rejected: DELAY + WIDTH does not fit in the period; max DELAY … ns` | DELAY too long for the period |
| `ERR <NAME> rejected: MARKERWIDTH does not fit in the marker period` | MARKERWIDTH too long |
| `ERR <NAME> rejected: marker period (MARKERDIV x period) is over 2^32-1 PIO cycles` | Low FREQ with a large MARKERDIV |
| `ERR <NAME> rejected: FREQ out of range` | FREQ above 300 MHz |
| `ERR <NAME> rejected: SYNC out of range (1145..75000000 Hz)` | SYNC outside its range |
| `ERR ARM …` / `ERR <NAME> rejected: pio0 unavailable` | The pulse hardware failed to start at boot (`HW=` in STATUS) |

`<NAME>` is the setting you were changing, which is not always the one named in the reason. For
example, `FREQ 1` with MARKERDIV 100 reports a marker-period error.

### STATUS

```
FREQ=15 (actual 15.000 Hz, period 10000000 cyc)
WIDTH=100 (actual 100.000 ns, 15 cyc)
DELAY=10000 (actual 10000.000 ns, 1500 cyc)
MARKERDIV=100
MARKERWIDTH=2000 (actual 2000.000 ns, 300 cyc)
SYNC=1000000 (actual 1000000.000 Hz, divider 75+0/256)
COMBINE=0 (CH1 on LASER 1, CH2 on LASER 2)
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
| `FREQ` … `SYNC` | Each setting as asked for, with its realized value |
| `COMBINE` | 0 = CH1 on Laser 1, CH2 on Laser 2; 1 = both pulses on both outputs |
| `ARMED` | Firmware arm state (1/0). J11 and the 12 V rail are separate gates. |
| `HW` | `OK`, or `ERR outputs not started: …` if the pulse hardware failed at boot |
| `START_PENDING_US` | Microseconds until pulses start after an `ARM` (0 = none pending) |
| `CLK` | System clock in Hz |
| `RESET` | Cause of the last reset: `POWER_ON`, `WATCHDOG`, `SOFT`, `DEBUG`, `BROWNOUT`, `GLITCH`, `RUN_PIN` or `UNKNOWN` |
| `RESET_RAW` | Raw reset registers (for bug reports) |
| `WDT_RESETS` | Watchdog resets since the last power-on |
| `WDT_MS` | Watchdog timeout (3000 ms). If the firmware ever hangs, it reboots DISARMED. |
| `TX_DROPPED` | Bytes of replies thrown away because the host was not reading |

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| No serial port appears | Cable in J17 (power only) instead of the Pico's micro-USB; a charge-only cable; or the Pico is in bootloader mode (a drive named `RP2350` appears instead) | Use the Pico's port with a data cable. In bootloader mode, copy `firmware.uf2` to the drive, or unplug both J17 and the Pico's USB. |
| Port opens but nothing appears | The banner is only sent in the first 1.5 s; the firmware does not echo | Type `ID?` or `STATUS`; turn on local echo |
| Commands work but no replies arrive | The terminal is not asserting DTR | Enable DTR in the terminal settings |
| The port vanishes and an `RP2350` drive appears | The port was opened at 1200 baud (reboot-to-bootloader) | Use any other baud rate. Copy `firmware.uf2` to the drive, or unplug both J17 and the Pico's USB. |
| `ERR … unknown command` for everything | A typo, the `FREQ?` form, old Teensy-style `6,cmd;` framing, or XON/XOFF flow control | Use bare names; set flow control to None |
| `ERR … rejected: laser limit: duty …` | WIDTH × FREQ over 0.1 % | Shorten WIDTH first, or use the max FREQ the message gives |
| `ERR … marker period …` at low FREQ | MARKERDIV × period too long | Lower MARKERDIV first (≤ 28 for 1 Hz) |
| `ERR ARM …`, or `HW=ERR …` in STATUS | The pulse hardware did not start | Re-flash the firmware; if it persists, report the `STATUS` output |
| `ARMED=1` but no laser pulses | J11 not on 1-2; J16 ENABLE pulled low; J17 unplugged or the charger isn't giving 15 V; still in the hold-off (`START_PENDING_US` > 0) | Check each gate. Measure `VBUS_PD` at C12 (about 15 V). |
| Outputs dead after a reset or power cycle | The board always restarts DISARMED | Send `ARM` |
| About 12 V pulses on the scope | Scope input is 1 MΩ, not 50 Ω | Use 50 Ω termination; the laser driver provides its own |
| About 3 V pulses at the laser driver | Two 50 Ω loads in parallel (e.g. a tee into both a 50 Ω scope input and the driver) | Monitor with a high-impedance probe, or on TP4 (CH2) / J10 pin 1 (CH1, through 100 Ω) |
| Cameras receive no trigger | J10 on 1-2 while DISARMED, or no J10 shunt | J10 on 2-3 |
| Cameras don't synchronise | A camera set as sync master; SYNC changed | Set every camera to sync slave; `SYNC 1000000` |
| All cameras stuck in pixel reset | A 50 Ω terminator on J12; the source holding it low; a 1.8 V source that can't release it | Remove the terminator; drive J12 with 3.3 V or 5 V logic, or leave it open |
| `RESET=WATCHDOG` in STATUS | The firmware hung and rebooted itself, DISARMED | Note what you were doing and report it; re-arm deliberately |
| `TX_DROPPED` keeps rising | The host is not reading the replies | Read every reply line |
| `pio run -t upload` can't find the Pico | Auto-reset failed | Unplug J17, then hold BOOTSEL while plugging in the Pico's USB, and upload again or copy the UF2 |
| First build fails on Windows with git path errors | The PlatformIO folder is on a long path | Keep it at the default `%USERPROFILE%\.platformio` |

Neither the board nor the Pico 2 W has a reset button. To restart, unplug both J17 and the Pico's
USB cable.

---

## Building from source

The firmware is Arduino C++ on the [arduino-pico](https://github.com/earlephilhower/arduino-pico)
core, built with [PlatformIO](https://platformio.org/) (the VS Code "PlatformIO IDE" extension, or
`python -m pip install platformio`). The platform, core and toolchain are pinned to exact versions
in `platformio.ini`.

| Command | Builds |
|---|---|
| `pio run` | `pico2w` (default): Raspberry Pi Pico 2 W |
| `pio run -e pico2` | plain Raspberry Pi Pico 2 (same pinout and socket) |
| `pio run -t upload` | builds and uploads to a connected board (send `DISARM` first) |

Output files land in `.pio/build/<env>/`, including `firmware.uf2` for drag-and-drop flashing. Flash
the image that matches the fitted module. The first build takes longer because PlatformIO downloads
the pinned platform and toolchain.

**Pin map** (`src/board.h`): GP13 = CH1 → J7, GP12 = CH2 → J8, GP11 = marker → J10 pin 3,
GP10 = sync → cameras and TP3. All four are driven by the RP2350's PIO block, so timing does not
depend on the CPU.

### Timing checks

`tools/timing_check/` verifies the timing arithmetic in `src/pulse_timing.h` cycle for cycle against an
independent model of the PIO hardware. Run it after changing `pulse_timing.h` or the laser limits:

```
cd tools/timing_check
g++ -std=c++17 -O2 -Wall -Wextra -o harness harness.cpp      # harness.exe on Windows
python check_exhaustive.py
python check_random.py
python check_marker_lock.py
python check_sync.py
python check_combined.py
```

The expected output is listed in [its README](tools/timing_check/README.md). These checks don't replace
a scope check on the board.

---

## Repository layout

| Path | Contents |
|---|---|
| `src/` | Firmware: `main.cpp` (setup, arming, watchdog), `protocol.*` (serial commands), `pulse_timing.h` (timing maths and laser limits), `pio_pulse.*` (PIO programs), `laser_gate.*` (laser output gate), `board.h` (pin map) |
| `platformio.ini` | Build configuration (pinned platform; `pico2w` and `pico2` environments) |
| `tools/pidg_example.py` | Python host example |
| `tools/timing_check/` | Host-side timing verification |
| `Pico Version 4Layer/` | **Current hardware:** KiCad project, [Hardware.md](Pico%20Version%204Layer/Hardware.md) (full hardware reference), BOM, placement file, `fab/` gerbers, drill files and JLCPCB assembly files |
| `Chris Teensy Version/` | The original Teensy 4.1 design this project is derived from |

## License

MIT — see [LICENSE](LICENSE).
