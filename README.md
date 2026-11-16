# PiEBV

A USB-controlled pulse-timing box for particle image velocimetry (PIV), built around a Raspberry
Pi Pico 2 W. It triggers two laser drivers and synchronizes up to six event cameras.

> **Hardware status:** Firmware timing has not yet been verified on a physical board. Complete the
> [first-board checks](docs/FIRST_BOARD_CHECKS.md#first-board-checks) before connecting a laser driver or camera.

## Quick start

With the assembled board, a Pico 2 W, a USB-C PD charger that supplies 15 V, and a micro-USB data
cable:

```
python -m pip install platformio
pio run
```

1. Follow the [first-board checks](docs/FIRST_BOARD_CHECKS.md#first-board-checks) before applying power or
   connecting equipment.
2. Flash `.pio/build/pico2w/firmware.uf2`: hold **BOOTSEL** while connecting the Pico's micro-USB
   cable, then copy the UF2 to the `RP2350` drive. Flash with the Pico out of the board or J17
   unplugged.
3. Seat the Pico components-up, USB toward the board's left edge. Set J10 to **2-3** and J18, J19
   and J21 to **1-2** for the 50 Ω scope checks; leave J11 empty until instructed to check the outputs.
4. Connect the 15 V charger to J17 and the Pico's micro-USB to the computer. Open the Pico's serial
   port, enable local echo, and send `STATUS`.
5. Follow [Hardware setup](docs/SETUP.md#hardware-setup) to check the laser outputs with a scope before
   connecting laser drivers or cameras.

**Contents:** [Quick start](#quick-start) · [Documentation](#documentation) ·
[What it does](#what-it-does) · [Safety](#safety) · [The board](#the-board) ·
[Connecting](#connecting) · [Most-used commands](#most-used-commands) ·
[Repository layout](#repository-layout)

---

## Documentation

The README gives the overview. The pages below give the detail.

| Page | What it holds | Who needs it |
|---|---|---|
| [docs/SAFETY.md](docs/SAFETY.md) | The safety rules in detail: starting and stopping, laser outputs, cameras and jumpers | Everyone, before the first `ARM` |
| [docs/SETUP.md](docs/SETUP.md) | Hardware setup step by step, first-board checks, jumpers, J12, seating the Pico, power | Anyone who sets up a board |
| [docs/CONNECTING.md](docs/CONNECTING.md) | USB serial, web GUI, Python scripting, network (Wi-Fi) | Operators and script writers |
| [docs/COMMANDS.md](docs/COMMANDS.md) | Command reference: rules, commands, timing, errors, `STATUS` | Operators and script writers |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Symptoms, likely causes and fixes | Anyone with a problem |
| [docs/FIRMWARE_BUILD.md](docs/FIRMWARE_BUILD.md) | Building from source, timing checks, signal simulation | Firmware developers |
| [Hardware.md](Hardware.md) | Hardware reference: pins, power, signal chains, connectors | Hardware developers |
| [docs/DESIGN_NOTES.md](docs/DESIGN_NOTES.md) | Design notes: index of the design pages in `docs/design/` (layout, power, signals, firmware), Rev 2 changes | Hardware developers |
| [docs/FIRST_BOARD_CHECKS.md](docs/FIRST_BOARD_CHECKS.md) | The full first-board checks, with exact test points | Anyone who tests a newly assembled board |
| [docs/MANUFACTURING.md](docs/MANUFACTURING.md) | Fabrication and assembly notes | Anyone who orders or assembles a board |
| [docs/EVK4_HARNESS.md](docs/EVK4_HARNESS.md) | The EVK4 camera harness | Users of Prophesee EVK4 cameras |
| [fab/jlc/JLC_ORDER.md](fab/jlc/JLC_ORDER.md) | The JLCPCB order checklist | Anyone who orders a board |
| [tools/rev2/README.md](tools/rev2/README.md) | The scripts that build the Rev 2 board | Hardware developers |
| [tools/signal_sim/README.md](tools/signal_sim/README.md) | The transmission-line simulation of the timing nets | Hardware developers |

---

## What it does

| Output | Connector | What it is for |
|---|---|---|
| **Laser 1** (CH1) | BNC J7 | Trigger for the first laser driver: a 5 V pulse (with J18 set to match the input), `WIDTH` long, `FREQ` times per second |
| **Laser 2** (CH2) | BNC J8 | Trigger for the second laser driver: the same pulse, starting exactly `DELAY` after Laser 1 |
| **Sync** | Camera ports J1–J6 | A steady 1 MHz clock that all six cameras keep time by |
| **Trigger** (the marker) | Camera ports J1–J6 | A pulse at the same instant as every Laser 1 pulse. Each camera records it as a timestamp in its data. (Jumper J10 can switch the cameras to the Laser 1 pulse itself instead.) |
| **Pixel reset** | Camera ports J1–J6 | Holds the camera sensors blank between flash pairs. Controlled only by PiEBV (`PIXGATE`) |
| **External Sync Out** | BNC J12 | A copy of the camera trigger (the marker, or Laser 1 with J10 on 1-2) for other equipment: a 5 V pulse, with J21 set to match the input |

- Every signal to the cameras is **1.8 V** (IDS cameras, J22 open) or **3.3 V** (Prophesee EVK4
  cameras, J22 fitted). The laser outputs and External Sync Out are **5 V**.
- The camera signal level comes from a power mux (U20). Its default input is 1.8 V: with J22 open,
  two pull-up resistors in parallel (R34 and R70) select 1.8 V. A shunt on J22 pulls the select pin low and selects
  3.3 V.
- Each camera line has a **47 Ω series resistor on the board** (R52–R69), between the buffer and
  the camera port. It terminates the camera cable at the source. The camera cables need no
  resistors.
- The camera lines of each group have **equal length** on the board, from the buffer to the series
  resistor: Sync 74.082 mm, Trigger 43.584 mm, pixel reset 51.472 mm (spread below 0.001 mm in
  each group, KiCad's length reading).
- Times are set in steps of **6.667 ns** (one tick of the Pico's 150 MHz clock), or **3.333 ns**
  with a shunt on the clock jumper J20 (a 300 MHz overclock; see [Jumpers](#jumpers)).
  Every reply shows the exact value the hardware will produce, so you never have to correct for the
  step size.
- Both laser pulses share one `WIDTH` and one `FREQ`.
- The firmware sets **no laser-driver limits** (pulse width, duty, spacing). Set what your driver is
  rated for. It only stops the pulses from running into each other.

PiEBV was designed for two **PicoLas LDP-V** laser-diode drivers (models 10-70 and 240-100) and six
**IDS uEye UE-39B0XCP-E** event cameras. Board revision 2 can also drive six **Prophesee EVK4**
cameras at 3.3 V (see the [EVK4 harness](docs/EVK4_HARNESS.md)). Other drivers with a 5 V trigger input should work too, with
the output mode (J18/J19) set to match their input.

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
4. **Unplugging the computer does not stop the lasers.** Use J11 or J17 for that. A lost network
   link does not stop them either. With Wi-Fi set up, `ARM` can also come from the network.
5. **Set each output's mode (J18, J19, J21) before you connect anything to it.**
6. **One laser driver per output.** Never split an output with a BNC tee, and never join J7 and J8.
7. **Cameras:** build the harness with wires 2, 3, 4, 5 and 7 only, and set every camera to sync
   slave.

The rules in detail are in [docs/SAFETY.md](docs/SAFETY.md).

---

## The board

The board is a **EuroCard, 160 × 100 mm**. Orientation used below: the board is landscape (160 mm
wide), seen from the top side. All connectors are on the two short edges: the Pico's micro-USB,
TP3 and, at the bottom, the USB-C connector J17 on the **left** edge, and only the three BNCs on
the **right** edge. The Pico plugs into two horizontal sockets at the top left, with its micro-USB at
the left edge, and the six camera ports run in one row along the bottom. The two USB ports are
labelled on the board: **`CONTROL / PROGRAM — PICO MICRO-USB`** (commands and firmware) and
**`POWER ONLY — USB-C PD 15 V`** (J17). The long (160 mm) edges have no parts within 2.5 mm, so the
board fits EuroCard card guides and slotted enclosures.

```
             +------------------------------------------------------------+
 Pico USB    |= Pico 2 W, in J15 (top row)                        J18 J7 =|  Laser 1 (BNC)
 = CONTROL   |  and J14 (bottom row)        J10 (trigger select)          |
             |= TP3 (1 MHz scope)  J20 (clock)                    J19 J8 =|  Laser 2 (BNC)
             |  J12 offset field            J11 (laser enable)            |
             |                                                   J21 J12 =|  External Sync Out (BNC)
 USB-C       |= J17                                                       |
 = POWER ONLY|       J1   J2   J3   J4   J5   J6   (camera ports)         |
             +------------------------------------------------------------+
```

(Not to scale. J18, J19 and J21 are the output-mode jumpers. J22, at the top centre, sets the camera signal level.
J23, the fan header, is at the bottom left, between mounting hole MH3 and camera port J1.
The status LEDs are near the top edge. Images of the board are in
[Hardware.md](Hardware.md#board-views).)

### Connectors

| Ref | What | Connect to | Notes |
|---|---|---|---|
| **J1–J6** | Camera ports 1–6 (2×5 IDC headers) | Each camera's 8-pin I/O cable (header pin *n* = camera pin *n*) | Pin 2, 7 ground · 3 pixel reset · 4 trigger · 5 sync · 1, 6, 8, 9, 10 not connected. All signals **1.8 V** (J22 open, IDS cameras) or **3.3 V** (J22 fitted, Prophesee EVK4 with the [EVK4 harness](docs/EVK4_HARNESS.md)). Each signal has a 47 Ω series resistor on the board. Pin 1 is the top-left pin. |
| **J7** | BNC, Laser 1 (CH1) | First laser driver's trigger input | Mode set by J18 |
| **J8** | BNC, Laser 2 (CH2) | Second laser driver's trigger input | Mode set by J19 |
| **J12** | BNC, External Sync Out | Equipment that must follow the camera trigger (50 Ω or Hi-Z input) | Mode set by J21. See [J12](docs/SETUP.md#j12--external-sync-out) |
| **J17** | USB-C, **power only** | A USB-C PD charger that offers 15 V | No data. Commands and firmware go through the Pico's own micro-USB. |
| **J10** | Camera trigger source (jumper) | A shunt | See [Jumpers](#jumpers) |
| **J11** | Laser enable (jumper) | A shunt, or a normally-closed E-stop switch | See [Jumpers](#jumpers) |
| **J18**, **J19**, **J21** | Output mode (jumpers; J18 = Laser 1, J19 = Laser 2, J21 = External Sync Out) | A shunt | See [Jumpers](#jumpers) |
| **J20** | Clock jumper, 2-pin header right of the Pico, below the J14 row | Nothing (150 MHz), or a shunt (300 MHz overclock) | See [Jumpers](#jumpers). Leave it open unless that Pico passed the soak test. |
| **TP3** | 2-pin header on the left edge, below the Pico | A scope | Pin 1 = the 1 MHz sync straight from the Pico (3.3 V) · pin 2 = ground |
| **J22** | Camera signal level, 2-pin header at the top centre | Nothing (1.8 V, IDS cameras), or a shunt (3.3 V, Prophesee EVK4) | See [Jumpers](#jumpers). **Never fit it with an IDS camera connected.** |
| **J23** | Fan supply, 2-pin header at the bottom left, marked `J23  FAN 12V` and `0.2 A MAX` | One 2-wire 12 V DC cooling fan of 40 mm, 200 mA maximum | Pin 1 (`+`, the top pin) = 12 V · pin 2 (`-`) = ground. The fan runs when the charger on J17 gives 15 V. There is no firmware control. The header has no key: connect the fan with the correct polarity. Do not fit a shunt on J23: it shorts the fan supply to ground. Do not connect a fan to the 12 V supply of the laser drivers. |
| **TP4–TP9** | Bare test pads at the top centre, marked `12V`, `5V`, `3V3`, `1V8`, `VCAM`, `GND` | A multimeter | Supply rails |

### Jumpers

Pin 1 always has the square pad. Change J22 with the power off.

| Jumper | Function | Positions | Default |
|---|---|---|---|
| **J10** | Camera trigger source | 1-2: every Laser 1 pulse (only while ARMED) · 2-3: the marker · none: no camera triggers | **2-3** |
| **J11** | Laser enable | 1-2: lasers enabled (the firmware must also be ARMED) · 2-3 or none: lasers off | **1-2** to run. Leave it empty until you check the outputs. |
| **J18** | Laser 1 output mode | 1-2: 50 Ω mode · 2-3: Hi-Z mode · none: wrong, always fit a shunt | **1-2** (for the LDP-V) |
| **J19** | Laser 2 output mode | as J18 | as J18 |
| **J21** | External Sync Out mode | 1-2: 50 Ω mode · 2-3: Hi-Z mode · none: wrong, always fit a shunt | **1-2** |
| **J20** | Clock jumper (2 pins) | open: 150 MHz, the rated clock · shunt: 300 MHz overclock | **open** |
| **J22** | Camera signal level (2 pins) | open: 1.8 V (IDS cameras) · shunt: 3.3 V (Prophesee EVK4) | **open** |

The board labels, the E-stop wiring and the full description of each jumper are in
[docs/SETUP.md](docs/SETUP.md#jumpers).

### Status LEDs

The LEDs near the top edge show the state of the board.

| LED | Colour | Meaning when lit |
|---|---|---|
| `12V OK` | green | The USB-C charger gave 15 V and the 12 V supply of the output drivers is good. Dark: the laser outputs and J12 cannot pulse. |
| `ARMED` | red | The lasers can fire: the firmware is ARMED, J11 is on 1-2 (or the E-stop switch is closed) and `12V OK` is lit. |
| `3V3` | blue | The camera ports are at 3.3 V (J22 fitted). Dark: 1.8 V. |
| `L1`, `L2` | red | A pulse left the Laser 1 / Laser 2 output driver. One flash for each pulse; on continuously above about 70 pulses a second. |
| `SYNC` | yellow | A pulse left the External Sync Out driver (J12). |

The LEDs are indicators only. Do not use a dark `ARMED` LED as proof that the lasers are off: an
LED can fail. To make the lasers safe, send `DISARM`, open J11 or unplug J17.

### Pico and power

Seat the Pico components up, with its micro-USB connector at the left edge. Connect a USB-C PD
charger that offers 15 V to J17. Connect the Pico's micro-USB to the computer. A 12 V cooling fan
on J23 runs when the charger gives 15 V. On a 5 V-only charger it normally does not turn. The details are in
[Seating the Pico](docs/SETUP.md#seating-the-pico) and [Power](docs/SETUP.md#power).

---

## Connecting

1. Use the Pico's micro-USB port. J17 carries power only.
2. Open the Pico's serial port. The port needs no driver.
   ```
   pio device monitor --echo                 # PlatformIO; add -p COM7 if needed
   ```
3. Turn on local echo. The firmware does not echo.
4. Do not use 1200 baud. 115200 is usual.
5. Type `STATUS` and press Enter.

Other terminals, the web GUI, Python scripting and the network (Wi-Fi) link are in [docs/CONNECTING.md](docs/CONNECTING.md).

## Most-used commands

| Command | Unit | Default | What it sets |
|---|---|---|---|
| `FREQ [n]` | Hz | 1000 | How many pulse pairs per second |
| `WIDTH [n]` | ns | 100 | Length of both laser pulses |
| `DELAY [n]` | ns | 10000 | Time from the start of the Laser 1 pulse to the start of the Laser 2 pulse. `0` makes them start together. |
| `ARM` | – | disarmed | Allow the laser pulses |
| `DISARM` | – | – | Stop the laser pulses at once; recognised anywhere in what you type |
| `ARM?` | – | – | Report the arm state: `ARMED=0` or `ARMED=1` |
| `STATUS` | – | – | All settings, the arm state and system information |
| `ID?` | – | – | Board and firmware version (the git commit it was built from) |
| `HELP` | – | – | Command summary |

A name on its own asks for a value (`DELAY`). A name followed by a number sets it (`DELAY 5000`).
All commands, limits and error replies are in [docs/COMMANDS.md](docs/COMMANDS.md). If something
does not work, see [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

---

## Repository layout

| Path | Contents |
|---|---|
| `src/` | Firmware: `main.cpp` (start-up, arming, crash watchdog), `protocol.*` (commands, on USB and on the network link), `net_link.*` (Wi-Fi and TCP link of a Pico 2 W), `wifi_config.h` (Wi-Fi set-up values and flash record), `pulse_timing.h` (timing maths and checks), `pio_pulse.*` (PIO programs), `sync_clock.*` (1 MHz SYNC clock), `clock_mode.*` (clock jumper: 150 or 300 MHz at boot), `laser_gate.*` (laser output gate), `board.h` (pin map) |
| `platformio.ini` | Build configuration (`pico2w` and `pico2` builds) |
| `tools/piebv_example.py` | Python example script |
| `tools/piebv_gui/` | Web GUI: settings, timing chart and console in the browser |
| `tools/piebv_sim/` | Simulator: the firmware's command code built for a computer, for trying the GUI and scripts without a board |
| `tools/timing_check/` | Timing checks run on a computer |
| `tools/signal_sim/` | Transmission-line simulation of the timing nets (KiCad's ngspice) |
| `PiEBV_Pico.kicad_pro` / `.kicad_sch` / `.kicad_pcb` | **Current hardware:** KiCad project of the 4-layer board |
| `Hardware.md` | [Full hardware reference](Hardware.md) |
| `fab/` | Manufacturing: master parts list `fab/PiEBV_Pico_BOM.csv` (with the design-constraint notes), gerbers and drill files, and `fab/jlc/` JLCPCB assembly files and [order checklist](fab/jlc/JLC_ORDER.md) |
| `libs/`, `fp-lib-table`, `sym-lib-table` | Project-local KiCad symbols and footprints |
| `tools/jlc_cpl/` | Corrects the JLC placement file to JLC's own footprints (see its README) |
| `tools/eurocard/` | Builds the Rev 1 EuroCard board from the 126 × 126 mm hand layout: placement, KiCadRoutingTools routing, checks (see its README) |
| `tools/rev2/` | Builds the current Rev 2 board from the Rev 1 EuroCard board: camera level select, series resistors in the camera lines, new camera routing with equal lengths, status LEDs, power islands, cooling fan supply, checks, fab export (see its README) |
| `docs/` | The documentation pages (see [Documentation](#documentation)), the [EVK4 camera harness](docs/EVK4_HARNESS.md) and the board images (`docs/img/`) |
| `docs/reports/` | Earlier design review reports |

## License

GNU General Public License, version 3 (GPL-3.0). See [LICENSE](LICENSE).
