# Timing check for `src/pulse_timing.h`

Host-side verification that the firmware's timing math produces exactly the
waveforms it reports. Run it after any change to `src/pulse_timing.h` or the
laser limits.

The checks do **not** read `src/pio_pulse.cpp`: `pio_model.py` carries its own copy of
the pulse program (`PROG`, `WRAP_T`, `WRAP`). If you change the PIO program or its wrap,
mirror the change there first, or the checks will keep testing the old program.

| File | What it does |
|---|---|
| `harness.cpp` | Compiles the real `../../src/pulse_timing.h`. Reads `clk freq width delay markerdiv markerwidth [sync]` lines and prints the realized cycles, formatted values and the FIFO words the firmware would load. |
| `pio_model.py` | Independent cycle-level model of the RP2350 PIO running a copy of the pulse program (JMP X-- semantics, blocking PULL, wrap, SET timing — RP2350 datasheet ch. 11). |
| `check_exhaustive.py` | Every small configuration (period 8–47 cycles, all widths/delays): the loaded words give CH2−CH1 = DELAY, exact widths and periods from the first period on. Also prints the error the old (pre-fix) math had. |
| `check_random.py` | 3,600 random parameter sets at nine clock rates through the harness: every accept/reject decision (including the laser limits) matches an exact-rational model, every accepted set is cycle-exact in the PIO model, and every formatted ns/Hz string is correctly rounded. |
| `check_marker_lock.py` | MARKER stays on the same CH1 pulse (period = MARKERDIV × CH1 period in cycles) for frequencies whose period is not a whole number of cycles. |
| `check_sync.py` | SYNC divider (8.8 fixed point), accepted range and the reported realized frequency. |
| `check_combined.py` | `COMBINE 1`: every accept/reject decision against an exact model of the combined limits (2 pulses per output in the duty, ≥ 10 µs spacing), and CH1 + CH2 running the dual-pin program on the shared PIO pin latch give both laser pins the same double pulse, DELAY apart, cycle-exact. |

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
```

Set `PIDG_HARNESS` to use a harness binary somewhere else. Expected key lines:

| Script | Look for |
|---|---|
| `check_exhaustive.py` | `fixed exhaustive P=8..47: 11480 configs, bad = 0` (its last line shows the old math's error, for reference) |
| `check_random.py` | `accepted 663 rejected 2937 simulated 663 mismatches 0` |
| `check_marker_lock.py` | `marker phase-lock and CH2-CH1 verified for 115 configs ...` (the `rej` lines above it are expected rejections) |
| `check_sync.py` | `sync cases 3000 accepted 2031 bad 0` |
| `check_combined.py` | `combined: accepted 317 rejected 1183 simulated 317 mismatches 0` |

These checks cover the arithmetic and the program's cycle behaviour. They do not
replace a scope check on the board (see Hardware.md, Open items).
