# Timing check for `src/pulse_timing.h`

Host-side verification that the firmware's timing math produces exactly the
waveforms it reports. Run it after any change to `src/pulse_timing.h`.

The checks do **not** read `src/pio_pulse.cpp`: `pio_model.py` carries its own copy of
the pulse program (`PROG`, `WRAP_T`, `WRAP`). If you change the PIO program or its wrap,
mirror the change there first, or the checks will keep testing the old program.

| File | What it does |
|---|---|
| `harness.cpp` | Compiles the real `../../src/pulse_timing.h`. Reads `clk freq width delay markerwidth [combine [pixgate pixlead pixlag]]` lines and prints the realized cycles, formatted values and the FIFO words the firmware would load. |
| `pio_model.py` | Independent cycle-level model of the RP2350 PIO running a copy of the pulse program (JMP X-- semantics, blocking PULL, wrap, SET timing — RP2350 datasheet ch. 11). |
| `check_exhaustive.py` | Every small configuration (period 8–47 cycles, all widths/delays): the loaded words give CH2−CH1 = DELAY, exact widths and periods from the first period on. Also prints the error the old (pre-fix) math had. |
| `check_random.py` | 3,600 random parameter sets at nine clock rates through the harness: every accept/reject decision matches an exact-rational model, every accepted set is cycle-exact in the PIO model, and every formatted ns/Hz string is correctly rounded. |
| `check_marker_lock.py` | MARKER fires with every pulse pair: it rises on the same cycle as every CH1 pulse, with its own width, for frequencies whose period is not a whole number of cycles; and the fit boundary MARKERWIDTH ≤ 1/FREQ − 5 cycles. |
| `check_sync.py` | Confirms SYNC stays fixed at 1 MHz and checks its 8.8 divider and reported realized frequency across system clocks. |
| `check_combined.py` | `COMBINE 1`: every accept/reject decision against an exact model of the combined rules (DELAY ≥ WIDTH + 1 cycle and DELAY ≤ 1/FREQ − 2 × WIDTH), and CH1 + CH2 running the dual-pin program on the shared PIO pin latch give both laser pins the same double pulse, DELAY apart, cycle-exact. |
| `check_pixgate.py` | `PIXGATE 1/2`: every accept/reject decision against an exact model of the gate rules (PIXLEAD >= 5 cycles, PIXLEAD + DELAY + WIDTH + PIXLAG + 3 cycles <= 1/FREQ), and CH1, CH2 and the gate state machine enabled together in the PIO model: every period the (inverted) gate asserts the pixel reset exactly PIXLAG after the last laser pulse and releases it exactly PIXLEAD before the next CH1, with no reset before the first pair. |

## Running

Any C++17 host compiler works (g++, clang++, MSVC, or `zig c++`):

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

Set `PIDG_HARNESS` to use a harness binary somewhere else. Expected key lines:

| Script | Look for |
|---|---|
| `check_exhaustive.py` | `fixed exhaustive P=8..47: 11480 configs, bad = 0` (its last line shows the old math's error, for reference) |
| `check_random.py` | `accepted 1206 rejected 2394 simulated 1206 mismatches 0` |
| `check_marker_lock.py` | `marker rises with every CH1 and CH2-CH1 = DELAY for 140 configs; 0 rejected ...`, then `boundary MARKERWIDTH <= 1/FREQ - 5 cycles: ok` |
| `check_sync.py` | `fixed 1 MHz sync clock rates 5 bad 0` |
| `check_combined.py` | `combined: accepted 548 rejected 952 simulated 548 mismatches 0`, then `boundary DELAY=WIDTH merges, DELAY=WIDTH+1 cycle separates: ok` |
| `check_pixgate.py` | `pixgate: accepted 793 rejected 807 gated 513 simulated 513 mismatches 0`, then `boundary PIXLEAD >= 5 cycles, reset >= 3 cycles: ok` |

These checks cover the arithmetic and the program's cycle behaviour. They do not
replace a scope check on the board (see Hardware.md, First-board checks).
