# Building from source

This page tells you how to build the firmware and how to run the timing checks and the signal
simulation. This page is part of the PiEBV documentation. The overview and the list of all pages are
in the [README](../README.md).

The firmware is Arduino C++ on the [arduino-pico](https://github.com/earlephilhower/arduino-pico)
core, built with [PlatformIO](https://platformio.org/) (the VS Code "PlatformIO IDE" extension, or
`python -m pip install platformio`). The exact versions of the platform, core and compiler are
fixed in `platformio.ini`.

| Command | Builds |
|---|---|
| `pio run` | `pico2w` (default): Raspberry Pi Pico 2 W |
| `pio run -e pico2` | plain Raspberry Pi Pico 2 (same pins and socket; no network link) |
| `pio run -t upload` | builds and uploads to a connected board (send `DISARM` first) |

Output files land in `.pio/build/<env>/`, including `firmware.uf2` for drag-and-drop loading. Load
the image that matches the fitted module. The first build takes longer because PlatformIO downloads
the platform and compiler.

**Pin map** (`src/board.h`): GP13 = CH1 → J7, GP12 = CH2 → J8, GP11 = marker → J10 pin 3,
GP15 = sync → cameras and TP3, GP16 = pixel-reset gate. The laser, marker and gate outputs are
driven by the RP2350's PIO (a small block of timing hardware beside the processor), and the sync
clock by its clock generator, so none of the timing depends on the software.

## Timing checks

`tools/timing_check/` checks the timing arithmetic in `src/pulse_timing.h`, step by step, against an
independent model of the PIO hardware. Run it after changing `pulse_timing.h`:

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

The expected output is listed in [its README](../tools/timing_check/README.md). These checks don't
replace a scope check on the board.

## Network check

`tools/net_check/` runs the firmware's TCP link (`src/tcp_link.cpp`) and command protocol on a
computer, against a model of lwIP. It checks what happens to commands and replies when a host
closes or resets the connection, when a second host connects and when lwIP has no memory. Run it
after changing `src/tcp_link.*` or `src/protocol.*`:

```
cd tools/net_check
g++ -std=c++17 -O1 -g -Wall -Wextra -fsanitize=address,undefined -DPIEBV_NET_CHECK \
    -I fake -I ../piebv_sim/fake -I ../../src -o net_check \
    net_check.cpp ../../src/tcp_link.cpp ../../src/protocol.cpp
./net_check
```

It prints `net_check: all checks passed`. It does not replace the
[network checks](FIRST_BOARD_CHECKS.md#network-checks) on a board: see [its README](../tools/net_check/README.md).

## Signal simulation

`tools/signal_sim/` is a transmission-line simulation of the trigger, laser and External Sync Out
nets, built from the routed board and datasheet values, run through the ngspice in KiCad 10. It
gives the CH1-to-CH2 skew for each J10 setting, J12's delay and its offset to the camera triggers,
and the output levels. `rev2_sim.py` adds the Rev 2 cases: the camera lines at 1.8 V and 3.3 V, the
camera cable with IDS and EVK4 inputs and the on-board 47 Ω series resistors, the supply budget of the camera buffers, the activity-LED
sense dividers and the gaps between the power islands. Run both after changing the routing or a
part in these chains; see [its README](../tools/signal_sim/README.md). It runs with KiCad's ngspice
on Windows and with libngspice on Linux.
