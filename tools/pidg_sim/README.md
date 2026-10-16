# PiDG simulator

The firmware's command protocol, running on your computer. `pidg_sim` compiles the unmodified
`src/protocol.cpp` and `src/pulse_timing.h` against a small fake of the Arduino core (`fake/`). It
reads serial bytes on stdin and writes the board's replies on stdout. Every reply, error message
and realized value is the one the board would print.

It exists so the [web GUI](../pidg_gui) and host scripts can be developed and tried without a board:
`python tools/pidg_gui/pidg_gui.py --connect sim`.

## Building

Any C++17 compiler works (g++, clang++, MSVC or `zig c++`). From this directory:

```
g++ -std=c++17 -O2 -I fake -I ../../src -o pidg_sim pidg_sim.cpp ../../src/protocol.cpp
```

- On Windows, name the output `pidg_sim.exe`.
- With MSVC: `cl /std:c++17 /EHsc /I fake /I ..\..\src pidg_sim.cpp ..\..\src\protocol.cpp`.
- Rebuild after any change to `src/protocol.cpp` or `src/pulse_timing.h`.
- The binary is not tracked in git.

You can also run it on its own and type commands:

```
./pidg_sim
STATUS
DELAY 12000
```

## What it does and does not do

| Simulated | Not simulated |
|---|---|
| Every command, reply and error, and the order-dependent accept/reject rules | Anything timed: no PIO, no pulses, no sync clock |
| Arming, with the real start hold-off: `ARM` reports it and `STATUS` counts it down | The J11 interlock, the 12 V laser-rail gate and the `HW` check; `HW` always reads `OK` |
| The realized cycles and values from `pulse_timing.h` | The reset reason and watchdog registers in `STATUS`, which are placeholders |

`pidg_sim.cpp` emulates the hooks that `src/main.cpp` installs, with the hardware calls removed:
- arming;
- the restart hold-off;
- applying a parameter set;
- `STATUS` and `ID?`.

**When you change those hooks in `main.cpp`, mirror the change here.** The restart decision
(`pulseLoadDiffers()`) and the hold-off time (`restartHoldUs()`) come from `pulse_timing.h`, which
both use, so those two cannot drift apart. The cycle-exact behaviour
of the pulse program is covered separately by [`tools/timing_check`](../timing_check).
