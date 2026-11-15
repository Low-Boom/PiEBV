# Hardware setup

This page tells you how to set up the board: the step-by-step procedure, the first-board checks, the
jumpers, the External Sync Out connector J12, how to seat the Pico, and the power supply. This page
is part of the PiEBV documentation. The overview and the list of all pages are in the
[README](../README.md).

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
   [Building from source](FIRMWARE_BUILD.md#building-from-source).)
2. **Seat the Pico,** components up, USB toward the left edge ([details](#seating-the-pico)).
3. **Set the jumpers:** J10 on **2-3** (cameras triggered by the marker), and J18 and J19 on
   **1-2** (50 Ω outputs, for the LDP-V). Leave **J11 empty** for now, so the lasers stay off, and
   **J20 empty** (the rated 150 MHz clock).
4. **Power up:** the charger into J17, and the Pico's micro-USB into your computer.
5. **Open a serial terminal** on the Pico's port ([how](CONNECTING.md#usb-serial)) and turn on local echo,
   because the firmware does not echo what you type. (Or use the [web GUI](CONNECTING.md#web-gui): its console
   takes the same commands.) Type `STATUS` and press Enter. You should see:
   ```
   FREQ=1000 (actual 1000.000 Hz, period 150000 cyc)
   WIDTH=100 (actual 100.000 ns, 15 cyc)
   DELAY=10000 (actual 10000.000 ns, 1500 cyc)
   MARKERWIDTH=2000 (actual 2000.000 ns, 300 cyc)
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
DELAY 10000 and MARKERWIDTH 2000); the 1 MHz sync clock is fixed. The lasers start DISARMED.

## First-board checks

The design hasn't been proven on real hardware yet, so check every newly assembled board. The full
list, with exact test points, is under
[First-board checks](FIRST_BOARD_CHECKS.md#first-board-checks).

1. **Before the first power-up on J17,** with nothing plugged in, check with a multimeter for solder
   bridges on the fine-pitch parts (J17, U16, U17, and U20 with its 0.5 mm pitch): `VBUS_PD` must not be shorted to GND, CC1
   or CC2 (at J17 and U14), +5V_PD and +5V must not be shorted to GND (at U16), and U17's input must
   not be shorted to its output. Also check that J17's four metal shell legs are soldered.
2. **Supply voltages,** with the charger on J17: `VBUS_PD` at C12 about 15 V (with the charger you
   will actually use), +12V at C17 between 11.54 and 12.05 V, and `LASER_PWR_OK` (U13 pins 1 and 8)
   about 12 V.
   - **Fan start-up,** if you use a fan on J23: confirm that the selected fan starts at the lowest
     and the highest input (about 14.2 V and 15.75 V), cold and warm. If it does not start, use a
     fan with a lower rated current.
3. **Laser outputs,** J18/J19 on 1-2, into a 50 Ω-terminated scope with no driver connected:
   - pulses from 0 V to 4.53–5.14 V;
   - CH2 exactly `DELAY` after CH1 (`DELAY 13` should give 13.3 ns);
   - the first pulse after `ARM` is full width;
   - 0 V after `DISARM` and after a full restart; and, while ARMED and pulsing, 0 V once J17 is
     unplugged, with no stray pulse while it is plugged back in;
   - then J18/J19 on 2-3 with the scope at 1 MΩ: 0 V to 4.55–5.08 V, with at most ~5 % overshoot at
     the end of the longest cable you will use. Put the shunts back on the mode you need afterwards.
   - **External Sync Out (J12),** J21 on 1-2, same 50 Ω scope: a 0 V to 4.53–5.14 V pulse of
     `MARKERWIDTH` with every period, also while DISARMED (J10 on 2-3); J21 on 2-3 at 1 MΩ:
     4.55–5.08 V.
4. **Camera signal level, before any camera is connected:** with J22 open, measure the test pad
   `VCAM` (TP8) with a meter. It must be 1.76–1.84 V and the blue `3V3` LED dark. With a shunt on
   J22 it must be about 3.3 V and the LED lit. Take the shunt off again for IDS cameras. Do not
   connect an IDS camera if the pad is not at 1.8 V with J22 open.
5. **Status LEDs:** `12V OK` lit with the 15 V charger; `ARMED` lit only when ARMED with J11 on 1-2
   and `12V OK` lit; `L1`, `L2` and `SYNC` flash with the pulses.
6. **Cameras:** with **one** camera connected, measure pixel reset, trigger and sync at the camera
   end of the harness, and confirm the camera is not driving pin 5 (it must be a sync slave). The
   series resistors are on the board (R52–R69), so this check is a measurement only. Only
   then connect all six.

## Jumpers

J10 and J11 are numbered 1-2-3 from **left to right**. J18, J19 and J21 stand upright between the
large resistors and the BNCs: J18's and J21's pin 1 is at the top, J19's at the bottom. Pin 1 always
has the square pad.

| Jumper | Board label | Shunt on 1-2 | Shunt on 2-3 | No shunt |
|---|---|---|---|---|
| **J11** laser enable | `ON` … `OFF` | **Lasers enabled** (the firmware must also be ARMED) | Lasers off | Lasers off (fail-safe) |
| **J10** camera trigger | `CH1 TRG MKR` | Cameras triggered by every Laser 1 pulse (only while ARMED) | **Cameras triggered by the marker** (normal) | No camera triggers |
| **J18** Laser 1 output mode | `50Ω` by pins 1-2, `HiZ` by 2-3 | **50 Ω mode** (normal, for the LDP-V) | Hi-Z mode | Wrong for everything: always fit a shunt |
| **J19** Laser 2 output mode | as J18 | as J18 | as J18 | as J18 |
| **J21** External Sync Out mode | as J18 | **50 Ω mode** (normal) | Hi-Z mode | as J18 |
| **J20** clock jumper (2 pins) | `CLOCK JUMPER` · `OPEN = 150 MHz` · `FIT = 300 MHz (OVERCLOCK)` | Shunt fitted: 300 MHz overclock (soak-test the Pico first) | – | **150 MHz, the rated clock** (normal) |
| **J22** camera signal level (2 pins) | `CAMERA I/O LEVEL (J22)` · `OPEN = 1V8  IDS` · `SHUNT = 3V3  EVK4` | Shunt fitted: **3.3 V** on all six camera ports (Prophesee EVK4). The blue LED `3V3` is lit. | – | **1.8 V** (IDS cameras; normal) |

**J11 — laser enable and E-stop.** Labelled `LASER INTERLOCK: ON = 1-2` and
`E-STOP: NC SWITCH ACROSS 1-2`. For an emergency-stop switch, take the shunt off and wire a
**normally-closed** switch across pins 1 and 2. Closed, the lasers are enabled (if also ARMED and
powered). Pressing the switch **or** breaking its cable opens the circuit and turns the lasers off,
so the stop is fail-safe.

**J22 — camera signal level.** J22 sets the level of the Sync, Trigger and pixel-reset lines on
**all six** camera ports. Open, the level is 1.8 V, which the IDS cameras need. With a shunt, the
level is 3.3 V, which the Prophesee EVK4 needs. **3.3 V can destroy the 1.8 V inputs of an IDS
camera:** fit the shunt only when no IDS camera is connected, and do not use IDS and EVK4 cameras
together. The blue LED marked `3V3` next to J22 is lit when the level is 3.3 V: look at it before
you connect a camera. Before you connect an IDS camera, also measure the test pad `VCAM` (TP8)
with a meter: it must be 1.8 V with J22 open. Change J22 with the power off. An EVK4 camera needs the
[EVK4 harness](EVK4_HARNESS.md); it has no pixel-reset input, so `PIXGATE` has no effect on it.
The harness has no resistors: the series resistors are on the board.

**J10 — camera trigger source.** Labelled `CH1 TRG MKR` under the pins and
`CAMERA TRIGGER: TRG-MKR = MARKER / TRG-CH1 = LASER 1` beside them. The middle pin (`TRG`) feeds the
trigger input of all six cameras and External Sync Out (J12).
- `TRG` to `MKR` (2-3, normal): the marker. It rises with every Laser 1 pulse, has its own width
  (`MARKERWIDTH`, 2 µs by default) and keeps running while DISARMED.
- `TRG` to `CH1` (1-2): the Laser 1 pulse itself, so only while ARMED. The cameras need a trigger
  pulse of at least 500 ns, so this is only dependable with `WIDTH` ≥ 500 ns.
- Never join all three pins.

**J18 / J19 — laser output mode.** Labelled `LASER 1 OUT` / `LASER 2 OUT`, with `50Ω` and `HiZ`
next to the pin pairs.
- **1-2, 50 Ω mode:** about 4.8 V (4.53–5.14 V) into a 50 Ω input. Use it for the PicoLas LDP-V and
  anything else with a 50 Ω input.
- **2-3, Hi-Z mode:** about 4.8 V (4.55–5.08 V) into a high-impedance input. The output is matched
  to 50 Ω coax, so even a long cable to an unterminated input gives a clean edge (at most ~5 %
  overshoot into a scope's 1 MΩ ∥ 15 pF).
  Use it for TTL or 5 V CMOS inputs, scopes at 1 MΩ and other instruments that don't terminate.
- **The wrong mode** gives the wrong voltage (see the table under [Safety](SAFETY.md#in-detail)): an LDP-V on
  Hi-Z mode sees 2.3–2.6 V and won't fire, and a 5 V logic input on 50 Ω mode sees ~12 V, which can
  damage it. Don't use Hi-Z mode as a way to keep a laser off: J11 is the interlock.
- The two jumpers are independent, so one output can drive an LDP-V and the other a logic input. The
  firmware can't see them, and the pulse timing is the same in both modes.

**J20 — clock jumper (300 MHz overclock).** A 2-pin header right of the Pico, below the J14 row.
Pin 1 (square pad, the lower pin) goes to GP10 through R29 (1 kΩ, which protects GP10 if a
program drives it), pin 2 is GND. A shunt on J20, read at every start (power-up or reset),
runs the Pico at 300 MHz instead of 150 MHz, so every time setting has 3.333 ns steps instead of
6.667 ns. That is twice the chip's rated speed: soak-test each Pico first, as described in
[Hardware.md](../Hardware.md#clock-jumper-j20-300-mhz-overclock). No shunt (the default) is the
rated 150 MHz. After any watchdog restart the Pico stays at 150 MHz until it is power-cycled.
`STATUS` shows the clock in `CLK` and `CLKMODE`.

## J12 — External Sync Out

**A copy of the camera trigger, for other equipment.** J12 pulses whenever the cameras' trigger
lines do: with every marker (J10 on 2-3, also while DISARMED), or with every Laser 1 pulse (J10 on
1-2, only while ARMED). It is built like a laser output, so the levels are the same:

- **J21 on 1-2 (50 Ω mode):** about 4.8 V (4.53–5.14 V) into a 50 Ω input.
- **J21 on 2-3 (Hi-Z mode):** about 4.8 V (4.55–5.08 V) into a high-impedance input, from a ~50 Ω
  source, so long cables don't overshoot.
- It needs the 15 V charger on J17; on the Pico's USB alone J12 stays at 0 V.
- J12 and the cameras' trigger are offset by a fixed delay: J12 passes a 12 V driver, the camera
  trigger lines pass the camera buffers. It is typically about +10 ns (J12 later), but anywhere from
  −9 to +26 ns from part to part. **Measure it once on each board** and write it in the `J12-TRIG OFFSET (MEASURED)` field on the silkscreen (left area, below TP3), if your
  instrument must line up with the cameras to better than ~30 ns ([First-board checks](FIRST_BOARD_CHECKS.md#first-board-checks)).
- One device per output, no BNC tee, and don't short it (see [Safety](SAFETY.md#safety)).

The board has no pixel-reset input any more: PiEBV alone controls the camera pixel reset
([`PIXGATE`](COMMANDS.md#pixel-reset-gate-pixgate)).

## Seating the Pico

Fit a **Raspberry Pi Pico 2 W** (or a plain Pico 2, which needs the `pico2` firmware image) with
pin headers into the two horizontal sockets, J15 (top row) and J14 (bottom row). Seat it
**components up, with its micro-USB connector at the left edge**, next to the label
`CONTROL / PROGRAM — PICO MICRO-USB`. Pico pin 1 then goes into pad 1 of J14: the left end of the
bottom row, at the pin-1 mark. **Fitted the other way round, it can be
destroyed** (the board's 5 V would land on one of its signal pins).

Fit the Pico before connecting any camera: without it, the camera sync and reset lines are
undefined.

## Power

| Plugged in | What works |
|---|---|
| **J17 (15 V charger) + Pico USB** | Everything. This is the normal set-up. |
| Pico USB only | Commands, and sync, trigger and pixel reset to the cameras. **The laser outputs stay off** (no 12 V supply for the board's output driver); the `12V OK`, `ARMED`, `L1`, `L2` and `SYNC` LEDs stay dark. |
| J17 only | The board runs, DISARMED, with the fixed 1 MHz sync clock and marker running. There is no serial link, so it can't be armed. |

**Charger:** a USB-C PD charger that offers **15 V**. In practice that means any PD charger rated
30 W or more. With a 5 V or 9 V-only charger the board still runs, but the laser outputs stay off.

**Cooling fan:** J23 (marked `J23  FAN 12V`, `0.2 A MAX`) supplies a 2-wire 12 V DC fan, 200 mA
maximum. Pin 1 (`+`) is 12 V and pin 2 (`-`) is ground. The fan runs when the charger on J17 gives
15 V. The firmware does not control the fan.

- On a 5 V-only charger the fan gets about 3 V and normally does not turn. On a 9 V or 12 V
  charger setting it gets about 7 V or 10 V and turns slowly.
- J23 is the same 2-pin header type as the jumpers J20 and J22. It has no key.
- **Do not fit a shunt on J23.** A shunt shorts the fan supply to ground.
- Connect the fan with the correct polarity (`+` = pin 1).
- A fan near the 200 mA limit can need more current to start than it draws when it runs. If the
  fan does not start, use a fan with a lower rated current
  (see [Fan supply](design/POWER.md#fan-supply-u24-j23)).

**To restart the board,** unplug both J17 and the Pico's USB cable. Unplugging just one doesn't
restart it, and neither does closing the serial port.
