# PiEBV simulator

The firmware's command protocol, running on your computer. `piebv_sim` compiles the unmodified
`src/protocol.cpp` and `src/pulse_timing.h` against a small fake of the Arduino core (`fake/`). It
reads serial bytes on stdin and writes the board's replies on stdout. Every reply, error message
and realized value is the one the board would print.

It exists so the [web GUI](../piebv_gui) and host scripts can be developed and tried without a board:
`python tools/piebv_gui/piebv_gui.py --connect sim`.

## Building

Any C++17 compiler works (g++, clang++, MSVC or `zig c++`). From this directory:

```
g++ -std=c++17 -O2 -I fake -I ../../src -o piebv_sim piebv_sim.cpp ../../src/protocol.cpp
```

- On Windows, name the output `piebv_sim.exe`.
- With MSVC: `cl /std:c++17 /EHsc /I fake /I ..\..\src piebv_sim.cpp ..\..\src\protocol.cpp`.
- Rebuild after any change to `src/protocol.cpp`, `src/protocol.h`, `src/pulse_timing.h` or
  `src/wifi_config.h`.
- The binary is not tracked in git.

You can also run it on its own and type commands:

```
./piebv_sim
STATUS
DELAY 12000
```

`./piebv_sim --overclock` simulates a board with the clock jumper fitted: clk_sys 300 MHz (3.333 ns
steps), and `STATUS` shows `CLKMODE=OVERCLOCK`.

## What it does and does not do

| Simulated | Not simulated |
|---|---|
| Every command, reply and error, and the order-dependent accept/reject rules | Anything timed: no PIO, no pulses, no sync clock |
| Arming, with the real start hold-off: `ARM` reports it and `STATUS` counts it down | The J11 interlock, the 12 V laser-rail gate and the `HW` check; `HW` always reads `OK` |
| The realized cycles and values from `pulse_timing.h` | The reset reason and watchdog registers in `STATUS`, which are placeholders |
| The `WIFI` commands as on the board's USB port, with their checks and replies | The radio, the network link and the flash: `WIFI ON` shows a joined network with a made-up address at once, and nothing is stored (`SAVED=0` after a change) |

`piebv_sim.cpp` emulates the hooks that `src/main.cpp` installs, with the hardware calls removed:
- arming;
- the restart hold-off;
- applying a parameter set;
- `STATUS` and `ID?`;
- the Wi-Fi set-up (`net::printStatus()` in `src/net_link.cpp` is the model for the `WIFI_` and
  `NET_` lines).

**When you change those hooks in `main.cpp`, mirror the change here.** The restart decision
(`pulseLoadDiffers()`) and the hold-off time (`restartHoldUs()`) come from `pulse_timing.h`, which
both use, so those two cannot drift apart. The cycle-exact behaviour
of the pulse program is covered separately by [`tools/timing_check`](../timing_check).
