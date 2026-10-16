# HSTX bench test

`hstx_bench.cpp` is a separate firmware image for a bare Pico 2 or Pico 2 W. It is **not** the
delay generator. It measures whether the RP2350 HSTX can make the laser-pin step smaller than the
6.667 ns of the present PIO firmware:

| Mode | Step | Clocks | How the pins are driven |
|---|---|---|---|
| `COUPLED` (default) | 3.333 ns | clk_sys = clk_hstx = 150 MHz | Four PIO state machines run the PiDG pulse program. HSTX coupled mode puts one state machine on the pin in the first half of each clock cycle and another in the second half. |
| `DMA`, `HSTXCLK 150` | 3.333 ns | clk_sys = clk_hstx = 150 MHz | DMA plays a command list that holds one period of both pins. No PIO. |
| `DMA`, `HSTXCLK 300` | 1.667 ns | clk_sys 150 MHz, clk_hstx 300 MHz | The same list. Only the HSTX runs above its 150 MHz rating; the CPU, flash, buses and PIO stay at 150 MHz. |

The pattern math is in `hstx_pattern.h`. `tools/hstx_check` tests it on a host against a model of
the HSTX. This bench test finds out whether the hardware agrees with that model.

## Safety

- Use a bare Pico on the bench. Do not connect laser drivers, cameras or the PiDG board.
- The bench has no arming, no restart hold-off and no watchdog. `RUN` starts the outputs at once.
- The laser pins stay LOW from power-up (the same pre-init hook as the main firmware) until `RUN`.
  `STOP` pulls them LOW before it stops anything else.
- After the bench, flash the main firmware again (`pio run -e pico2w -t upload`).

## Build and flash

```
pio run -e hstx_bench -t upload          # Pico 2 W
pio run -e hstx_bench_pico2 -t upload    # Pico 2
```

Or copy `.pio/build/hstx_bench/firmware.uf2` to the `RP2350` drive (hold BOOTSEL while you
connect USB). Open the serial port at any baud rate, with line ending CR, LF or CR LF. Send `HELP`.

## Wiring

| Signal | GPIO | Pico pin | What it is |
|---|---|---|---|
| CH1 | GP13 | 17 | Laser 1 pin, through the HSTX (HSTX output 1) |
| CH2 | GP12 | 16 | Laser 2 pin, through the HSTX (HSTX output 0) |
| REF | GP11 | 15 | `COUPLED` mode only: a PIO pin that does not go through the HSTX |
| GND | — | 13, 18 | Ground for the probes |

The bench sets these three pins to fast slew and 8 mA drive.

Probe each pin with a short ground (a ground spring, not the long clip), or with a 450 Ω series
resistor into a 50 Ω scope input (a 10:1 divider; 6.6 mA at 3.3 V). Use the same probe type and
cable length on every channel, or measure the skew between the channels first and subtract it.

What you measure is the time between two edges of the same shape (50 % level to 50 % level), not
the edge shape. A scope of 500 MHz or more at 2.5 GS/s or more on each channel is a good choice. A
slower scope also works with averaging, but with less margin at 1.667 ns. Use the scope's
delta-time measurement with statistics (mean and standard deviation) over 1000 or more pulses.

## Commands

Times are in **steps**: 1 step = half a clk_hstx cycle (3.333 ns at 150 MHz, 1.667 ns at 300 MHz).

| Command | Effect |
|---|---|
| `RUN`, `STOP` | Start or stop the outputs. |
| `MODE COUPLED`, `MODE DMA` | Select the mode. |
| `HSTXCLK 150`, `HSTXCLK 300` | Set clk_hstx. Send `STOP` first. 300 works in `DMA` mode only. |
| `FREQ <Hz>` | Pulse-pair rate (default 1000). In `DMA` mode the period rounds to a whole number of 16-step words; `STATUS` shows the actual rate. |
| `WIDTH <steps>` | Width of both pulses (default 30). `COUPLED`: 6 or more. |
| `DELAY <steps>` | CH2 rising edge after the CH1 rising edge (default 3000). 0 is allowed. |
| `COMBINE 0`, `COMBINE 1` | 1: both pulses on both pins. Needs a gap: `DELAY` ≥ `WIDTH` + 2 (`COUPLED`) or `WIDTH` + 1 (`DMA`). |
| `REFWIDTH <cycles>` | REF width in clk_sys cycles (default 15 = 100 ns). |
| `KEEPALIVE 0`, `KEEPALIVE 1` | `COUPLED` mode: 1 (default) feeds filler words to the HSTX FIFO with DMA. |
| `SWEEP <from> <to> <ms>`, `SWEEP OFF` | While running, add 1 to `DELAY` every `<ms>` (10 to 3600000), from `<from>` to `<to>`, then start again. Each step prints the new `DELAY`. |
| `STATUS`, `HELP` | Show the settings, the actual period, the per-line plan (`COUPLED`) or the list size (`DMA`), and the FIFO counters. |

A command that changes a setting while the outputs run restarts them. A rejected value changes
nothing and shows the reason. (If the restart itself fails, the outputs stop and the old value
stays.)

In `DMA` mode a period shorter than 16 words (256 steps) goes into the list several times, so that
one pass of the list lasts at least 16 words. `STATUS` shows the number of periods per pass.

`FIFO_EMPTY_SEEN` counts the times the main loop found the HSTX FIFO empty while DMA should keep it
full. `FIFO_WOF` counts writes into a full FIFO. Both must stay 0. The main loop only takes samples:
0 does not prove that the FIFO never ran empty, but a nonzero value proves that it did.

`FIFO_KEPT_BY_RESET` counts the HSTX resets that left entries in the FIFO. The bench then drains the
FIFO before it starts, so the outputs are still correct. Write the value down: it tells whether the
production firmware needs that drain step.

## Procedure

Write down the result of each step. `STATUS` before each measurement shows what the bench made.

### 1. Smoke test

1. Send `RUN`. Trigger the scope on the CH1 rising edge.
2. Make sure that CH1 and CH2 show 100 ns pulses at 1 kHz, CH2 10 µs after CH1, and that REF shows
   a 100 ns pulse near the CH1 edge.
3. Send `STATUS`. Make sure that `FIFO_EMPTY_SEEN=0` and `FIFO_WOF=0`.

### 2. Step size and linearity, `COUPLED`

1. Send `DELAY 300` (1 µs). Measure CH1 rise to CH2 rise.
2. Send `DELAY 301`, `DELAY 302`, and so on to `DELAY 331`. Measure each one. (Or use
   `SWEEP 300 331 3000` and read the scope during each 3 s step.)
3. Plot the delta against `DELAY`. The slope must be 3.333 ns per step.
4. Compare the residuals of odd and even values. An odd `DELAY` puts the CH2 edge in the second half
   of a clock cycle. If the two halves of the cycle are not the same length, all odd values move by
   the same amount (half the difference of the two lengths). Write down that offset.
5. Do the same for `WIDTH` from 6 to 37 at `DELAY 3000`: measure the CH1 width at 50 % level.
6. Send `DELAY 0`. CH1 and CH2 now rise together: the delta is the pin-to-pin skew of the two HSTX
   outputs plus the probe skew.

### 3. HSTX path delay, `COUPLED`

REF and the four line state machines start on the same clock cycle, and REF rises on the same cycle
as the first-half line of CH1. Measure REF rise to CH1 rise. This is the extra delay of the HSTX
path against a plain PIO pin. The production firmware needs this number to keep the camera marker
(a plain PIO pin) aligned with Laser 1.

### 4. Does coupled mode need the FIFO fed?

1. Send `KEEPALIVE 0` while running. The bench restarts the outputs with no DMA.
2. If CH1 and CH2 still pulse correctly, coupled mode does not need a DMA channel. If they stop or
   show wrong levels, the production firmware must feed the FIFO as `KEEPALIVE 1` does.
3. Send `KEEPALIVE 1`.

### 5. Step size, `DMA` at 150 MHz

1. Send `STOP`, `MODE DMA`, `RUN`.
2. Repeat step 2 (`DELAY` 300 to 331, then `WIDTH` from 1). In this mode `WIDTH` can be 1 step.
3. Send `STATUS`. `FIFO_EMPTY_SEEN` and `FIFO_WOF` must be 0.
4. Send `FREQ 10000000`, `WIDTH 4`, `DELAY 15`, then `STATUS`. The period rounds to 2 words
   (32 steps = 106.667 ns, `actual 9375000.000 Hz`) and the list holds 8 periods per pass. Make
   sure that both pins pulse at that rate with the right width and delay, and that the FIFO
   counters stay 0. Then send `FREQ 1000`, `WIDTH 30`, `DELAY 300`.

### 6. Step size, `DMA` at 300 MHz

1. Send `STOP`, `HSTXCLK 300`, `RUN`. `STATUS` must show `CLK_SYS=150000000` and
   `CLK_HSTX=300000000 (... step 1.667 ns)`.
2. Repeat step 2. The slope must be 1.667 ns per step. Check odd against even values as before.
3. Measure the edge jitter (standard deviation of a delta) and compare it with step 5.
4. Leave it running for 10 minutes or more with the scope's pulse-width trigger set to catch any CH1
   or CH2 pulse more than 1 step shorter or longer than `WIDTH`. Any trigger is an error at 300 MHz.
   Then send `STATUS`: both FIFO counters must be 0.
5. Send `STOP`, `HSTXCLK 150`.

### 7. Lower rates

`FREQ 1` works in both modes. In `DMA` mode a 1 Hz period needs about 9170 list entries at 150 MHz
and 18330 at 300 MHz, of the 20480 the bench holds (`STATUS` shows the number).

## What the results decide

| Result | Meaning for the production firmware |
|---|---|
| Step 2 passes | `COUPLED` gives 3.333 ns with the existing pulse program, at the rated 150 MHz. Laser pins stay on GP12/GP13 (already HSTX pins). The four line state machines take all of pio0, so the marker and the pixel-reset gate move to pio1, started on the same cycle. |
| Step 3 | The fixed offset to add to the marker, or to correct for. |
| Step 4 fails | `COUPLED` needs one DMA channel for the filler words. |
| Steps 5–6 pass | 1.667 ns is possible in `DMA` mode, with the HSTX alone above its rating. The firmware must then build a command list for every setting, and the period is a whole number of 26.667 ns (16-step) words at 300 MHz. |
| Odd/even offset | A constant to correct, or a reason to use even steps only. |

## Not verified before the first run

The code follows the SDK register descriptions and the pico-examples HSTX code. These points have no
source that settles them; the bench measures them:

- Whether coupled mode updates the pins while the HSTX FIFO is empty (step 4).
- Whether the HSTX block reset also empties the HSTX FIFO (`FIFO_KEPT_BY_RESET`).
- The exact output timing of the `RAW` and `RAW_REPEAT` commands and the nibble order (steps 5–6;
  a wrong order shows as wrong widths or delays at once).
- HSTX operation at 300 MHz (above the 150 MHz rating).
- The HSTX path delay (step 3) and the duty error of the clock (odd/even offset).
