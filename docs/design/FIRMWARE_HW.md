# PiEBV design: firmware and hardware

This page gives the firmware behaviour that the hardware depends on: the pin choice, the
derivation of the timing limits, combined mode, the pixel-reset gate, boot and arming, and the
clock jumper (300 MHz overclock).
Back to: [hardware reference](../../Hardware.md) · [design notes index](../DESIGN_NOTES.md)

---

## Firmware pin map

The firmware (`src/`) drives CH1, CH2, MARKER and PIXGATE from PIO state machines (pio0: SM0 CH1,
SM1 CH2, SM2 MARKER, SM3 PIXGATE), so any GPIO can be used for them; they are started on the same
clock cycle, so they stay exactly in step. SYNC comes from the RP2350 clock generator (clk_gpout1),
which reaches only GP13, GP15 and GP21 on the Pico header (GP23–25 are used inside the Pico 2 W);
GP13 is CH1, so SYNC is on GP15. CH1/CH2 reach their pins only while
ARMED; otherwise `src/laser_gate.cpp` holds them LOW.

| Constant | GPIO | Board net | Drives |
|---|---|---|---|
| `kPinMarker` | 11 | `PWM_Trig` | J10.3 → (jumper) → U5 → U6 → Trigger1–6, and U19 → J12 (External Sync Out) |
| `kPinCh2` | 12 | `_PULSE_OUT_CH2` | U8 → U13 → J8 (Laser 2); R18 10 k to GND |
| `kPinCh1` | 13 | `_PULSE_OUT_CH1` | U7 → U13 → J7 (Laser 1); R17 10 k to GND; R19 100 Ω → J10.1 |
| `kPinSync` | 15 (J14 pad 20) | `PWM_1MHz` | U1 → U2 → Sync1–6, and TP3. Clock generator, not PIO. |
| `kPinPixGate` | 16 (J15 pad 20) | `PIXRST_GATE` | U3.1 and U3.2 (NAND with both inputs joined: an inverter) → U4 → TDRSTN1–6; R24 10 k to +3V3. Output inverted in the GPIO block. |
| `kPinClockSel` | 10 (J14 pad 14) | `CLK_SEL` | R29 (1 kΩ) → J20.1; a shunt to J20.2 (GND) selects 300 MHz, read once at boot ([clock jumper](#clock-jumper-j20-300-mhz-overclock)). Input with the internal pull-up; no shunt reads as 150 MHz. |
| `kPinArmedLed` | 17 (J15 pad 19) | `ARMED_LED` | Q2 gate (R38 100 kΩ to GND) → D3 ([Status LEDs](SIGNALS.md#status-leds)). Plain GPIO output, high while ARMED. Status only: it gates nothing. Not connected on a Rev 1 board. |

**CH1 is the higher GPIO (GP13) and CH2 the lower (GP12).** The order is deliberate; don't "tidy"
them into ascending order.

`src/board.h` repeats this table as a comment. Keep the two in step: when the constants and the
schematic once drifted apart, the whole board looked dead.

## Timing limits

The firmware (`realizeTiming()` in `src/pulse_timing.h`) re-checks the whole set of settings on
every command, using the **realized** values (after rounding to whole PIO cycles: 6.667 ns, or
3.333 ns with the [clock jumper](#clock-jumper-j20-300-mhz-overclock)). It sets
**no laser-driver ratings**: pulse width, duty and spacing depend on the attached driver (the
PicoLas LDP-V datasheets were used only for the electrical interface), so set values within your
driver's ratings. The checks only keep the waveform correct:

- **Pulse pairs stay separate:** `DELAY ≤ 1/FREQ − 2 × WIDTH`, so CH2 ends at least one WIDTH
  before the next pair's CH1 starts. That also limits WIDTH to half the period.
- **Shortest pulse:** WIDTH and MARKERWIDTH must realize to ≥ 3 cycles (20.000 ns; 10.000 ns at
  300 MHz); 16 ns or less (at 150 MHz) is **rejected**, not rounded up. The PIO program itself needs `DELAY ≤ 1/FREQ − WIDTH − 5 cycles`,
  which only matters at 3–4-cycle widths.
- **The marker is at most 50 % duty:** `2 × MARKERWIDTH ≤ 1/FREQ`. This is the one limit set for the
  hardware, not the waveform: the marker also drives J12, and the limit keeps R30's average power
  inside its rating with J12 shorted (see [Board output rating](POWER.md#board-output-rating)). The PIO
  program also needs MARKERWIDTH ≤ 1/FREQ − 5 cycles, which is the tighter limit only for periods
  under 10 cycles.

## Combined mode (`COMBINE 1`)

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
3–3.4 V pulses in 50 Ω mode, or 6.9 V where the pulses overlap (see [Laser outputs](SIGNALS.md#laser-outputs)).

## Pixel-reset gate (`PIXGATE`)

pio0 SM3 runs the same pulse program on GP16, with the pin's output inverted in the GPIO block
(`GPIO_OVERRIDE_INVERT`), so the program's pulse becomes the pixel reset. It pulls TDRSTN low
`PIXLAG` after the last laser pulse ends (CH1 rise + DELAY + WIDTH + PIXLAG) and releases it
`PIXLEAD` before the next CH1 rise, cycle-exact and locked to CH1 (checked in
`tools/timing_check/check_pixgate.py`). `PIXGATE 1` runs it only while the laser pins carry pulses,
`PIXGATE 2` always. This gate is the only source of the camera pixel reset: the board has no
pixel-reset input, so with `PIXGATE 0` the pixels are never held in reset.

A stopped gate leaves its output latch LOW, which (inverted) leaves the pin HIGH, so DISARM, a
restart hold-off and a reset all leave the pixels free. Rules: PIXLEAD ≥ 5 cycles, and
PIXLEAD + DELAY + WIDTH + PIXLAG ≤ 1/FREQ − 3 cycles. The first pair after a start has no reset
before it. SYNC uses no state machine (it is the clock generator), and it is independent of the
laser timing.

## Timing: what you set is what you get

- **Every reply shows the realized value,** e.g. `DELAY 1003` → `OK DELAY=1003 (actual
  1000.000 ns, 150 cyc)`, and `STATUS` lists them all. The user never has to correct a setting for
  rounding or for fixed instruction overheads.
- **CH2 rises exactly DELAY after CH1,** to the nearest 6.667 ns cycle. This is exact in a
  cycle-accurate model of the PIO; see `tools/timing_check/`.
- **MARKER fires with every pulse pair** and is locked to CH1: it runs the same program at exactly
  the laser period in cycles, started on the same cycle, so it rises with every CH1 pulse and can't
  drift. Each camera timestamps the marker into its event stream, which gives every PIV pair its own
  reference time.
- **SYNC** is fixed at 1 MHz, generated by the RP2350 clock generator (clk_gpout1), whose 16.16
  divider takes clk_sys straight to the pin with 50 % duty correction. At the 150 MHz system clock
  the divider is exactly 150 (300 at 300 MHz), so SYNC is exact and jitter-free; pulse-setting
  changes do not affect it.

## Boot and arming

- **The firmware starts DISARMED.** An early start-up hook (`src/laser_gate.cpp`, `.preinit_array`
  priority 00110) drives GP12/GP13 LOW right after the chip's peripheral reset, before clock setup,
  USB, the Pico 2 W's radio-chip initialisation and `setup()`. They stay LOW until the host sends
  `ARM` (over USB, or over the network link if it is set up). SYNC and MARKER start as soon as `setup()` applies the defaults, and keep running
  while DISARMED. A second hook (`src/clock_mode.cpp`, priority 00700, after the clock setup) reads
  the [clock jumper](#clock-jumper-j20-300-mhz-overclock); the laser pins are already LOW then.
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
  count. The period is 8 s in place of 3 s while the radio chip of a Pico 2 W starts (at power-up
  if Wi-Fi is set up, and during `WIFI ON`, `OFF` and `CLEAR`, which stop the command loop for that
  call); the lasers are DISARMED then. No other command is designed to hold the firmware; to test the watchdog, write `0x80000000` (TRIGGER) to
  `WATCHDOG_CTRL` (`0x400d8000`) over SWD with the core running (a halted core pauses the
  watchdog).
- **Replies never block the firmware.** Each reply line is written whole. A link's replies wait
  for a slow host only out of a 250 ms budget, which comes back at one eighth of the time that
  passes; once it is used up, replies stop waiting until the host catches up. So a host that
  reads slowly, or not at all, delays a DISARM queued on its own link by at most about 0.3 s,
  however many commands are queued before it, and can't trip the watchdog.
  With the network link in use, a DISARM on one link can also wait for one slow command of the
  other link (about 250 ms): the main loop ends a link's turn after 5 ms. A radio chip that
  stops answering can hold the command loop for 1 s to 2 s, at most twice
  ([network limits](../CONNECTING.md#limits)).
  Replies that couldn't be sent are dropped a whole line at a time, and their bytes are counted in
  `STATUS` as `TX_DROPPED`.
- **Host scripts** must send `ARM` after every reset, and should check `RESET=` in `STATUS` first
  (require an operator action after `RESET=WATCHDOG`). Parse `STATUS` by key, not by line count.
- **Losing the USB link does not disarm.** The firmware doesn't watch the USB connection, and J17
  alone keeps the board powered, so a pulled cable, a sleeping PC or a killed host script leaves an
  ARMED board pulsing with no serial path for `DISARM`. The hardware stops are J11 (off 1-2) or
  unplugging J17.

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
  the watchdog test in [first-board check 1](../FIRST_BOARD_CHECKS.md#first-board-checks), done into a 50 Ω scope input with
  no laser driver connected.

## Clock jumper (J20): 300 MHz overclock

**J20** is a vertical 2-pin header right of the Pico's GPIO end, below the J14 row, with R29 just
right of it (silkscreen `CLOCK JUMPER`, `OPEN = 150 MHz`, `FIT = 300 MHz (OVERCLOCK)`). Pin 1
(square pad, the lower pin) is `CLK_SEL_JMP`, which reaches `CLK_SEL` = GP10 (J14 pad 14) through
**R29 (1 kΩ)**; pin 2 is GND.

- **R29 protects GP10.** Firmware older than the clock jumper (before commit 5dfedd5) drove GP10
  push-pull as the SYNC output, and any other program may drive it too. With the shunt fitted, R29
  limits that current to about 3.3 mA. The internal pull-up is tens of kΩ, so a fitted shunt still
  reads about 0.1 V, far below the 0.8 V LOW threshold.
- **No external pull-up and no capacitor on `CLK_SEL`.** The internal pull-up is enough for the
  short trace, and a capacitor would slow the rise so that an open jumper could read as fitted.
- On a bare Pico, a wire from GP10 (pin 14) to GND (pin 13) acts as a fitted shunt (add a 1 kΩ
  resistor in series for the same protection).

| Clock jumper (GP10 to GND) | clk_sys | Step | Shortest `WIDTH` / `MARKERWIDTH` |
|---|---|---|---|
| Open, no shunt (default, fail-safe) | 150 MHz, the RP2350's rated speed | 6.667 ns | 20.000 ns |
| Shunt fitted | 300 MHz, twice the rated speed | 3.333 ns | 10.000 ns |

- **Read once at boot**, by a start-up hook (`src/clock_mode.cpp`, `.preinit_array` priority 00700).
  It runs after the SDK's clock setup and before the Pico 2 W's radio-chip initialisation, USB and
  `setup()`, so everything after it sees the final clock. Moving the shunt has no effect until the
  next reset. GP10 has the internal pull-up, and the jumper pulls it to GND; a lost shunt gives the
  rated clock.
- **With the shunt fitted, the hook:**
  1. raises the core voltage from 1.10 V to 1.30 V (the highest the SDK allows without unlocking
     the limit) and waits 1 ms, as the SDK does after a voltage change;
  2. doubles the flash-interface (QMI) timing fields that count clk_sys cycles, so the flash keeps
     its 50 MHz clock, sample point and chip-select times (clock divider 3 → 6, sample delay 2 → 4
     half-cycles, deselect time 7 → 14 cycles; COOLDOWN, which only trades power for speed, stays).
     It writes them from RAM while the interface is idle;
  3. sets clk_sys to 300 MHz (pll_sys 1500 MHz / 5 / 1) through the SDK, which also moves clk_peri
     to 48 MHz (UART and SPI are unused);
  4. stops the unused HSTX clock, which would otherwise follow clk_sys to 300 MHz.

  USB, the timer and the watchdog run from their own clocks and do not change.
- **Everything timed follows the clock.** All settings realize in 3.333 ns steps, the SYNC divider is
  exactly 300 (SYNC stays an exact 1 MHz), and every reply shows the realized values. `STATUS` shows
  `CLK=300000000`, `CLKMODE=OVERCLOCK (jumper fitted)` and `VREG_MV=1300`, and the start-up line
  says `clock 300 MHz overclock`. `tools/timing_check` runs every clock-dependent check at 300 MHz too.
- **No overclock after a watchdog restart.** If the watchdog has fired since the last power-up or
  RUN reset (`WDT_RESETS` > 0), the hook keeps 150 MHz with the shunt fitted, and `STATUS` shows
  `CLKMODE=STANDARD (jumper fitted, overclock off: watchdog reset since power-up; power-cycle to
  retry)`. An unstable chip therefore can't crash in a loop at 300 MHz. To try 300 MHz again,
  power-cycle both J17 and the Pico's USB.
- **Back to 1.10 V at 150 MHz.** The voltage regulator keeps its setting through a watchdog or soft
  reset, so on every start that stays at 150 MHz the hook sets the default 1.10 V again
  (`VREG_MV=1100`).
- **300 MHz is outside the RP2350's specification.** Each chip is different, and the higher voltage
  makes the chip hotter. Once running, the watchdog catches a hang (the chip restarts DISARMED, then
  at 150 MHz). It starts only at the end of `setup()`, about 1.5 s after a reset: a chip that hangs
  before then shows no serial port and stays hung. Then remove the shunt and power-cycle. The laser
  pins are LOW from the first start-up hook on, so they stay LOW. Nothing detects a chip that keeps
  running and makes wrong timing. J11 and the 12 V power-good gate stay the hardware stops.

**Before you rely on 300 MHz with a given Pico** (again for every replacement Pico):

1. Fit the heat sink on the RP2350. Fit the shunt, power-cycle, and check `CLK=300000000` and
   `CLKMODE=OVERCLOCK …` in `STATUS`.
2. With J11 open (lasers off) and the outputs into 50 Ω scope inputs, repeat the timing points of
   [first-board check 1](../FIRST_BOARD_CHECKS.md#first-board-checks) at the finer step, e.g. `DELAY 13` → 13.333 ns and
   `WIDTH 10` → 10.000 ns.
3. Soak test: run at the highest `FREQ` and the shortest settings you will use, in the enclosure, at
   the highest room temperature you expect, for several hours (overnight is better). Use the scope's
   pulse-width trigger to catch any pulse of the wrong width. Then `STATUS` must show
   `WDT_RESETS=0` and `HW=OK`.
4. Optional: to make less heat, lower the voltage (`kOverclockVreg` in `src/clock_mode.cpp`) to the
   lowest value that still passes step 3 with margin. `VREG_MV` in `STATUS` shows the setting.
