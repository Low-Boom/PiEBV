# PiEBV simulator

The firmware's command protocol, running on your computer. `piebv_sim` compiles the unmodified
`src/protocol.cpp` and `src/pulse_timing.h` against a small fake of the Arduino core (`fake/`). It
reads serial bytes on stdin and writes the board's replies on stdout. Every reply, error and
realized value is the one the board would give (the simulator is the USB link).

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

You can also run it on its own and type commands. It sends nothing until you send a command. A
setting gives no reply; send `:SYST:ECHO ON` to get one:

```
./piebv_sim
*IDN?
:SYST:ECHO ON
:PULS:DOUB:DEL 12 US
:FREQ?;:PULS:WIDT?;DOUB:DEL?
```

Or send the commands through a pipe:

```
printf ':PULS:DOUB:DEL 1003 NS\n:PULS:DOUB:DEL?\n' | ./piebv_sim
```

`./piebv_sim --overclock` simulates a board with the clock jumper fitted: clk_sys 300 MHz (3.333 ns
steps), and `:DIAG:CLOC:MODE?` gives `"OVERCLOCK (jumper fitted)"`.

## SCPI check (`scpi_check.py`)

`scpi_check.py` checks the SCPI protocol of the firmware in the simulator. It sends program
messages to a new simulator for each check and compares the replies with the expected texts:

- `*IDN?`, the other common commands and the status registers (`*ESR?`, `*ESE`, `*SRE`, `*STB?`,
  `*CLS`, `*RST`);
- no greeting, and no reply to a setting;
- the realized values in NR3 form, the suffixes, `DEFault`, and the steps at 150 MHz and 300 MHz;
- long and short headers, lower case, optional words and the current path;
- arming, the hold-off, `:ABORt`, and `DISARM` anywhere in the input;
- the error queue: the order, the overflow, each error number, and which errors end the rest of a
  line;
- the echo switch (`:SYST:ECHO`);
- the Wi-Fi set-up (`:SYST:COMM:WLAN`) as on the USB port, and the network queries;
- the diagnostics queries, and the length of the `:SYST:HELP:HEAD?` block.

Build the simulator first (see above), then, from this directory:

```
python scpi_check.py                 # or: python scpi_check.py <path to piebv_sim>
```

It prints `scpi_check: all checks passed`. A failed check prints its name, the reply and the
expected reply, and the exit code is 1. Run it after any change to `src/protocol.*`,
`src/pulse_timing.h` or `src/wifi_config.h`.

## What it does and does not do

| Simulated | Not simulated |
|---|---|
| Every command, reply and error, and the order-dependent accept/reject rules | Anything timed: no PIO, no pulses, no sync clock |
| Arming, with the real start hold-off: `:OUTP:PEND?` counts it down, and the echo of `:OUTP ON` gives it | The J11 interlock, the 12 V laser-rail gate and the hardware check; `:DIAG:HARD?` always gives `"OK"` |
| The realized cycles and values from `pulse_timing.h` | The reset reason and the watchdog registers (`:DIAG:RES:CAUS?` always gives `POWER_ON`), which are placeholders |
| The Wi-Fi settings (`:SYST:COMM:WLAN`) as on the USB port of the board, with their checks and errors | The radio, the network link and the flash: `:SYST:COMM:WLAN ON` shows a joined network with a made-up address at once, and nothing is stored (error 101 and `:SYST:COMM:WLAN:SAV?` = 0 after a change) |
| One link: stdin and stdout are the USB link | The network link (see [`tools/net_check`](../net_check)) |

`piebv_sim.cpp` emulates the hooks that `src/main.cpp` installs, with the hardware calls removed:
- arming;
- the restart hold-off;
- applying a parameter set;
- the read-outs for `*IDN?` and the `:DIAG` queries;
- the Wi-Fi set-up (`net::netInfo()` in `src/net_link.cpp` is the model for the `:SYST:COMM:WLAN`
  queries).

**When you change those hooks in `main.cpp`, mirror the change here.** The restart decision
(`pulseLoadDiffers()`) and the hold-off time (`restartHoldUs()`) come from `pulse_timing.h`, which
both use, so those two cannot drift apart. The cycle-exact behaviour
of the pulse program is covered separately by [`tools/timing_check`](../timing_check).
