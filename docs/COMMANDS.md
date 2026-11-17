# Command reference

This page lists all commands of the PiEBV firmware, their limits, the timing rules, the error
replies and the `STATUS` report. This page is part of the PiEBV documentation. The overview and the
list of all pages are in the [README](../README.md).

## Rules

- One command per line. Upper or lower case both work; separate words with spaces or tabs.
- A name on its own **asks** for a value (`DELAY`); a name followed by a number **sets** it
  (`DELAY 5000`). There is no `NAME?` form, except `ARM?` and `ID?`.
- `ARM`, `ARM?`, `STATUS`, `ID?` and `HELP` take nothing after them: `STATUS 1` gives
  `ERR STATUS takes no argument`.
- The same commands work on the USB port and on the [network link](CONNECTING.md#network-wi-fi).
  Only the [Wi-Fi set-up](#wi-fi-wifi) is limited to USB.
- Numbers are plain whole numbers (0 … 4294967295): no units, decimal points, signs or hex. Times
  are in **ns** and frequencies in **Hz**.
- Backspace and DEL edit the line. Lines can be up to 95 characters.
- A successful set replies `OK NAME=value (actual …)`; a query replies `NAME=value (actual …)`;
  errors start with `ERR`.
- A rejected set changes nothing: the previous settings keep running.
- Each new value is checked **together with all the current settings**, so the order of changes
  can matter. For example, to raise `FREQ` a lot, shorten `WIDTH` first.

## Commands

| Command | Unit | Default | Allowed values | What it sets |
|---|---|---|---|---|
| `FREQ [n]` | Hz | 1000 | 1 up to where 2 × WIDTH + DELAY still fits in 1/FREQ | How many pulse pairs per second |
| `WIDTH [n]` | ns | 100 | ≥ 17 (becomes ≥ 20.000 ns), and 2 × WIDTH + DELAY ≤ 1/FREQ. No upper limit. | Length of both laser pulses |
| `DELAY [n]` | ns | 10000 | 0 up to 1/FREQ − 2 × WIDTH, so pulse pairs stay apart (with `COMBINE 1`, also more than WIDTH); the error message gives the exact limit | Time from the start of the Laser 1 pulse to the start of the Laser 2 pulse. `0` makes them start together. |
| `MARKERWIDTH [n]` | ns | 2000 | 17 up to half the period (2 × MARKERWIDTH ≤ 1/FREQ) | Length of the camera marker pulse (it starts with every Laser 1 pulse) |
| `COMBINE [n]` | 0 / 1 | 0 | 0 or 1; change only while DISARMED | 0: Laser 1 gets the CH1 pulse, Laser 2 the CH2 pulse. 1: **both** outputs get **both** pulses ([details](#combined-mode-combine)) |
| `PIXGATE [n]` | 0 / 1 / 2 | 0 | 0, 1 or 2 | Hold the camera pixels in reset between pulse pairs: 0 off (no pixel reset), 1 while ARMED, 2 always ([details](#pixel-reset-gate-pixgate)) |
| `PIXLEAD [n]` | ns | 10000 | ≥ 30 (becomes ≥ 5 steps); the window must fit in 1/FREQ | Pixels released this long before each Laser 1 pulse |
| `PIXLAG [n]` | ns | 100000 | PIXLEAD + DELAY + WIDTH + PIXLAG ≤ 1/FREQ − 3 steps | Pixels reset again this long after the last laser pulse |
| `ARM` | – | disarmed | exactly `ARM`, nothing after it | Allow the laser pulses |
| `DISARM` | – | – | – | Stop the laser pulses at once; recognised anywhere in what you type |
| `ARM?` | – | – | – | Report the arm state: `ARMED=0` or `ARMED=1` |
| `STATUS` | – | – | – | All settings, the arm state and system information |
| `ID?` | – | – | – | Board and firmware version (the git commit it was built from) |
| `WIFI …` | – | off | see [Wi-Fi](#wi-fi-wifi) | The Wi-Fi state and set-up |
| `HELP` | – | – | – | Command summary |

The camera sync clock is fixed at **1 MHz** and cannot be changed: the RP2350 clock generator divides
the 150 MHz system clock by exactly 150 (300 MHz: by exactly 300). `SYNC` is not a command, and
`STATUS` does not list it.

A "step" is one 6.667 ns tick of the 150 MHz clock. With the clock jumper fitted (300 MHz) a step
is 3.333 ns, and every limit given in steps is half as long in ns. The examples in this documentation are
for 150 MHz.

## Examples

```
DELAY 1003     ->  OK DELAY=1003 (actual 1000.000 ns, 150 cyc)
DELAY          ->  DELAY=1003 (actual 1000.000 ns, 150 cyc)
WIDTH 101      ->  OK WIDTH=101 (actual 100.000 ns, 15 cyc)
ARM            ->  OK ARMED=1 (laser pulses start after a 498 us hold-off)
DISARM         ->  OK ARMED=0
ID?            ->  PiEBV delay generator (Pico 2 W), firmware 5dfedd5
```

- The `ID?` version is `git describe --always --dirty` of the git checkout the firmware was built
  in. `-dirty` means tracked files had uncommitted changes (new files that were never `git add`-ed
  do not count); `unknown` means it was built without git.

- The number after `=` is what you asked for; `actual` is what the hardware produces; `cyc` is the
  same in 6.667 ns steps ("cycles").
- The `(laser pulses start after …)` part appears only while a start delay (the hold-off, below) is
  pending; otherwise `ARM` replies just `OK ARMED=1`.

## ARM and DISARM in detail

- **`ARM`** must be the word on its own: `ARM 1` gives `ERR ARM takes no argument`. `ARM` while
  already armed changes nothing.
- **The hold-off.** The reply comes at once, but the pulses start only after a wait of one full
  pulse period (the longer of the old and new periods, at most 1 s), counted from the last laser
  pulse. After a restart, pulses can't start until 1 s after it. This guarantees that two laser
  pulses are never closer together than the set period, whatever commands arrive. The marker pauses
  during the hold-off, so marker-triggered cameras miss triggers for that time. When the pulses
  start, the CH1, CH2 and marker timing restarts together, and the first pulse is full width.
  `START_PENDING_US` in `STATUS` shows the time left.
- Changing `FREQ`, `WIDTH`, `DELAY` or `MARKERWIDTH` while armed goes through the same hold-off and
  stays armed. A change that ends up at the same step counts (e.g. `WIDTH 100` → `WIDTH 101`)
  restarts nothing.
- **`DISARM`** is never refused. The outputs go low the moment the `M` arrives, the rest of that line
  is ignored, and a pending start is cancelled. It works even when the host is not reading replies,
  though a host that reads its replies slowly, or not at all, can delay it by up to about 0.3 s
  (about 0.65 s if the hosts of both links, USB and network, are slow; these times are by
  design and were not measured on a board; a radio fault can add
  more: see [the network limits](CONNECTING.md#limits)). The letters must be on
  one line: `DIS`, Enter, `ARM`, Enter is two commands and **arms** the board.
- While DISARMED, **the sync clock and the marker keep running**, so the cameras stay synchronised.
  The laser outputs are held at 0 V.

## Wi-Fi (`WIFI`)

These commands set up the [network link](CONNECTING.md#network-wi-fi) of a Pico 2 W. `WIFI` on its
own works on both links. All the others work **only on the USB port**.

| Command | What it does |
|---|---|
| `WIFI` (or `WIFI?`) | Shows the Wi-Fi and network lines of [`STATUS`](#status) |
| `WIFI SSID <name>` | Gives the network name (1 to 32 bytes: 32 ASCII characters, fewer with letters outside ASCII; spaces inside are allowed) for the next `WIFI ON`. It also discards a passphrase given before: send `WIFI PASS` after `WIFI SSID`. |
| `WIFI PASS <passphrase>` | Gives the WPA2 passphrase (8 to 63 characters) for the next `WIFI ON`. `WIFI PASS` on its own selects an open network. The passphrase is never shown. |
| `WIFI ON` | Joins the network now and at every power-up, and stores the set-up in flash |
| `WIFI OFF` | Switches the radio off, now and at power-up. Keeps the name and the passphrase that are in use. |
| `WIFI CLEAR` | As `WIFI OFF`, and erases the name and the passphrase |

```
WIFI ON      ->  OK WIFI=ON SSID=Lab Network PASS=SET SAVED=1
WIFI OFF     ->  OK WIFI=OFF SSID=Lab Network PASS=SET SAVED=1
WIFI ON      ->  OK WIFI=ON SSID=Lab Network PASS=SET SAVED=0 (not stored: flash is written only at the 150 MHz clock; …)
```

- `WIFI ON`, `OFF` and `CLEAR` are refused while ARMED or while a laser start is pending:
  `ERR WIFI ON refused: DISARM first: …`.
- `OK WIFI=ON` means that the join started, not that it completed. Send `WIFI` to see the result.
- The reply names the set-up that is now in use: the name, and `PASS=SET` or `PASS=NONE` (never
  the passphrase). Read it: `PASS=NONE` means an open network. The name is everything between
  `SSID=` and the **last** ` PASS=` of the line (a name can itself hold such text).
- `SAVED=0 (…)` means that the set-up is in use but not in flash, with the reason.
- A name or passphrase given with `WIFI SSID` or `WIFI PASS` holds only until the next `WIFI ON`,
  `OFF` or `CLEAR`. `WIFI ON` uses it. `WIFI OFF` and `WIFI CLEAR` discard it, and so does each
  of the three when it gives an `ERR` reply, for any reason. If something was discarded, the
  `ERR` reply ends in `(what was sent with WIFI SSID / WIFI PASS is discarded)`. `WIFI_PENDING=1`
  in `WIFI` and `STATUS` shows that a name or passphrase is waiting for `WIFI ON`.
- A new name never gets the passphrase of another network: `WIFI SSID` starts the name without a
  passphrase, also when the name is the one in use. `WIFI SSID <name>`, `WIFI ON` joins an
  **open** network with that name.
- `WIFI PASS <passphrase>`, `WIFI ON` (no `WIFI SSID`) changes the passphrase of the network in
  use. `WIFI ON` alone joins the network in use again, for example after `WIFI OFF`.
- `WIFI OFF` and `WIFI CLEAR` switch the radio chip off. `WIFI ON` starts it again, which takes
  longer than the other commands (up to some seconds; not yet measured).
- `<name>` and `<passphrase>` are the rest of the line. They cannot start or end with a space,
  and cannot contain the letters `disarm` in sequence. A name must be UTF-8 text (plain ASCII is
  that) without control characters (a tab included) and without the characters that change the
  writing direction. A passphrase must be printable ASCII
  characters.
- A host on the network link can read the set-up with `WIFI` or `STATUS`, but not the passphrase.

## Combined mode (`COMBINE`)

`COMBINE 1` sends the whole double pulse (the CH1 pulse, then the CH2 pulse exactly `DELAY` later)
to **both** Laser 1 (J7) and Laser 2 (J8). Use it when one light source must make both PIV flashes,
or to fire two light sources together with the same double pulse. Each output still drives one
laser driver.

```
COMBINE 1   ->  OK COMBINE=1 (CH1 + CH2 on LASER 1 and LASER 2)
COMBINE 0   ->  OK COMBINE=0 (CH1 on LASER 1, CH2 on LASER 2)
```

- **Change it only while DISARMED.** While armed the reply is
  `ERR COMBINE rejected: DISARM first: COMBINE changes what both laser outputs carry`.
- **The pulses must stay apart:**
  - `DELAY` must be at least one step (6.667 ns) longer than `WIDTH`, e.g. `DELAY` ≥ 106.667 ns at
    `WIDTH 100`. At exactly `DELAY` = `WIDTH` the second pulse would start as the first ends, and the
    two would merge into one pulse of twice the width.
  - `DELAY` ≤ 1/FREQ − 2 × `WIDTH`, as in the normal mode, so each pair is separate from the next.
  - Each driver now gets two pulses per period: check its own spacing and duty ratings. The firmware
    does not impose any.
- The timing is exactly as precise as in the normal mode.
- The monitor point follows: J10 pin 1 shows the double pulse, and with J10 on 1-2 the cameras are
  triggered on both pulses.

## Pixel-reset gate (`PIXGATE`)

PiEBV can hold every camera's pixels in reset **between pulse pairs**, like a shutter: the pixels
are free from `PIXLEAD` before the Laser 1 pulse until `PIXLAG` after the last laser pulse, and
held in reset for the rest of each period. This cuts out background and noise events between
pairs, and every pair starts from freshly reset pixels.

```
            pair k                                        pair k+1
CH1     ____|‾|______________________________________________|‾|______
CH2     _________|‾|______________________________________________|‾|_
TDRSTN  ‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾|__________________________|‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾   (low = pixels in reset)
                   |<------>|                          |<------>|
                    PIXLAG       pixels in reset         PIXLEAD
```

(`TDRSTN` is the camera's pixel-reset pin.)

| Setting | Default | Meaning |
|---|---|---|
| `PIXGATE 0` | ✓ | Off: the pixels are never held in reset |
| `PIXGATE 1` | | Reset between pulse pairs **while ARMED**; off while DISARMED |
| `PIXGATE 2` | | Reset between pulse pairs **always**, even while DISARMED (for bench tests without lasers) |
| `PIXLEAD n` | 10000 ns | Pixels released this long before each Laser 1 pulse starts (at least 5 steps, 33.333 ns) |
| `PIXLAG n` | 100000 ns | Pixels reset again this long after the last laser pulse ends |

```
PIXGATE 1   ->  OK PIXGATE=1 (pixels reset between pulse pairs while ARMED)
PIXLAG 50000 -> OK PIXLAG=50000 (actual 50000.000 ns, 7500 cyc)
```

- **PiEBV is the only source of the pixel reset.** The board has no reset input; with `PIXGATE 0`
  the cameras run freely.
- **Find PIXLEAD and PIXLAG by experiment.** How long the sensor needs to settle after a reset, and
  how long after a flash its events keep arriving, are not published. Start generous (the
  defaults), look at the event stream, then tighten. The window must fit in the period:
  `PIXLEAD + DELAY + WIDTH + PIXLAG` ≤ 1/FREQ − 3 steps; the error message gives the largest
  `PIXLAG` that fits.
- **The first pulse pair after a start has no reset before it;** every later pair does. The gate is
  timed from the same start as CH1/CH2, to the exact step.
- `STATUS` shows the result as `PIXRESET=`: reset time per period, when it starts after CH1, and how
  long the pixels are free around each pair.
- A pixel reset also puts a timestamp (trigger channel 1) into each camera's event stream, when the
  camera software's trigger channel is enabled.

## Timing

```
            |<---------------------- period = 1/FREQ ---------------------->|
CH1  (J7)  _|‾‾‾‾|______________________________________________________________|‾‾‾‾|_
             WIDTH
CH2  (J8)  ____________|‾‾‾‾|__________________________________________________________
            |<-DELAY-->|
MARKER     _|‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾|____________________________________________|‾‾‾‾‾‾‾
             MARKERWIDTH
SYNC       _|‾|_|‾|_|‾|_|‾|_|‾|_|‾|_|‾|_|‾|_|‾|_|‾|_|‾|_ ... runs all the time, 1 MHz
```

- **Rounding:** times round to the nearest 6.667 ns step, and frequencies to the nearest whole
  number of steps per period. All limits are checked on the rounded values.
- **The Laser 2 pulse starts exactly `DELAY` after Laser 1,** to the step.
- **The marker** starts at the same instant as every Laser 1 pulse and repeats at exactly the same
  rate, so it can never drift away from the pulse it marks. Each camera records it as a timestamp,
  which gives every pulse pair its own reference time. `MARKERWIDTH` can be at most half the period, so
  with the default 2 µs `FREQ` can go up to 250 kHz; shorten `MARKERWIDTH` to go higher.
- **The sync clock** is independent of the laser timing. The IDS uEye EVS cameras (Prophesee IMX636
  sensor) need it at **1 MHz**: a camera running as sync slave counts its 1 µs event timestamps on
  this clock, and Prophesee requires Sync In to be "a 1MHz pulse train to correspond to the
  internally generated 1µs timestamp resolution". Any other frequency stretches or squeezes every
  camera's timestamps, and an IMX636 slave sends no data at all until the clock arrives. The sync
  output is fixed at 1 MHz.
- **No laser-driver limits.** The firmware does not limit pulse width or duty: they depend on the
  driver you connect, so stay within its ratings. It enforces what the pulse hardware needs, plus one
  spacing rule of its own:
  - **pulse pairs stay apart** (the firmware's own rule): `DELAY` ≤ 1/FREQ − 2 × `WIDTH`, so the
    Laser 2 pulse ends at least one `WIDTH` before the next Laser 1 pulse (this also limits `WIDTH`
    to half the period);
  - **the pulse program:** `DELAY` ≤ 1/FREQ − `WIDTH` − 5 steps. This is the tighter limit only for
    a `WIDTH` of 3 or 4 steps (20.000 or 26.667 ns); the error message names the limit that applies;
  - **shortest pulse:** 3 steps (20.000 ns) for `WIDTH` and `MARKERWIDTH`;
  - with `COMBINE 1`, `DELAY` > `WIDTH` ([Combined mode](#combined-mode-combine)).
- **Slowest rate:** `FREQ` goes down to 1 Hz.
- **Delay through the hardware:** the board's output driver (U13) adds about 17 ns (up to 27 ns) to
  both channels alike, so the time between the two pulses at J7/J8 is kept to within 1–2 ns. (Your laser
  drivers add their own delays.)

## Errors

| Reply | Meaning |
|---|---|
| `ERR <word> unknown command` | Not a command. `FREQ?` is not valid; use `FREQ`. `SYNC` is not a command: the sync clock is fixed at 1 MHz. |
| `ERR <NAME> invalid value` | Not a plain whole number (e.g. `1.5`, `10k`, `-5`), or too large |
| `ERR <NAME> takes one value` | More than one number |
| `ERR ARM takes no argument` | Something after `ARM` (the same for `ARM?`, `STATUS`, `ID?` and `HELP`) |
| `ERR line too long` | More than 95 characters; the whole line is ignored |
| `ERR WIFI refused: the Wi-Fi set-up changes only from the Pico USB port` | A `WIFI` command other than the bare `WIFI`, sent over the network link |
| `ERR WIFI <sub> refused: DISARM first: …` | `WIFI ON`, `OFF` or `CLEAR` while ARMED or while a laser start is pending |
| `ERR WIFI ON refused: the radio chip did not start` | The radio chip did not start. The radio is off. `WIFI ON` tries again. |
| `ERR WIFI ON refused: the TCP server did not start` | No memory for the network server. The radio is off. |
| `ERR WIFI unknown sub-command (SSID, PASS, ON, OFF, CLEAR; see HELP)` | A word after `WIFI` that is not a sub-command |
| `ERR WIFI <sub> takes no value` | Something after `WIFI ON`, `OFF` or `CLEAR` |
| `ERR WIFI ON no network name: send WIFI SSID <name> first` | `WIFI ON` with no name given and none in use |
| `… (what was sent with WIFI SSID / WIFI PASS is discarded)` | At the end of an `ERR WIFI ON`, `OFF` or `CLEAR` reply: a name or passphrase that was given before was discarded |
| `ERR WIFI SSID …` / `ERR WIFI PASS …` | The name or the passphrase does not have a permitted length or permitted characters |
| `ERR WIFI not available: this firmware has no Wi-Fi` | The `pico2` firmware image (plain Pico 2) |
| `ERR busy: another host is connected` | Network link only: a second connection. It is closed. |
| `ERR <NAME> rejected: value must be > 0` | FREQ set to 0 |
| `ERR <NAME> rejected: WIDTH realizes below the 3-cycle minimum (20.000 ns)` | WIDTH ≤ 16 ns (the same for MARKERWIDTH) |
| `ERR <NAME> rejected: DELAY must leave >= WIDTH before the next pulse pair (DELAY <= 1/FREQ - 2 x WIDTH); max DELAY … ns` | DELAY too long for the period at this WIDTH |
| `ERR <NAME> rejected: WIDTH too long for the period: 2 x WIDTH must fit in 1/FREQ` | WIDTH longer than half the period |
| `ERR <NAME> rejected: DELAY + WIDTH must fit in the period (DELAY <= 1/FREQ - WIDTH - 5 cycles); max DELAY … ns` | The same as the `DELAY must leave` error, for a WIDTH of 3 or 4 steps, where the pulse program's own limit is the tighter one |
| `ERR <NAME> rejected: WIDTH does not fit in the period (WIDTH <= 1/FREQ - 5 cycles)` | The period is too short for a WIDTH of 3 or 4 steps |
| `ERR <NAME> rejected: COMBINE needs DELAY > WIDTH so the two pulses stay separate (min DELAY … ns)` | With `COMBINE 1`, DELAY not longer than WIDTH |
| `ERR <NAME> rejected: MARKERWIDTH must be <= half the period (2 x MARKERWIDTH <= 1/FREQ); max MARKERWIDTH … ns` | MARKERWIDTH longer than half the period, e.g. after raising FREQ. The 50 % limit protects J12 against a shorted cable. |
| `ERR <NAME> rejected: MARKERWIDTH must fit in the period (MARKERWIDTH <= 1/FREQ - 5 cycles); max MARKERWIDTH … ns` | The same, for periods under 10 steps, where the pulse program's own limit is the tighter one |
| `ERR <NAME> rejected: FREQ out of range` | FREQ above 300 MHz |
| `ERR ARM …` / `ERR <NAME> rejected: pio0 unavailable` | The pulse hardware failed to start (`HW=` in STATUS) |
| `ERR <NAME> rejected: pulse state machines could not be loaded` | The pulse hardware did not take settings that passed every check. Should never happen: the pulse outputs stop, the lasers are DISARMED, and `ARM` is refused until a later setting loads (`HW=` in STATUS) |

`<NAME>` is the setting you were changing, which is not always the one named in the reason. For
example, `FREQ 600000` with the default 2 µs `MARKERWIDTH` gives a `MARKERWIDTH` error.

## STATUS

```
FREQ=15 (actual 15.000 Hz, period 10000000 cyc)
WIDTH=100 (actual 100.000 ns, 15 cyc)
DELAY=10000 (actual 10000.000 ns, 1500 cyc)
MARKERWIDTH=2000 (actual 2000.000 ns, 300 cyc)
COMBINE=0 (CH1 on LASER 1, CH2 on LASER 2)
PIXGATE=0 (off: no pixel reset)
PIXLEAD=10000 (actual 10000.000 ns, 1500 cyc)
PIXLAG=100000 (actual 100000.000 ns, 15000 cyc)
PIXRESET=off
ARMED=1
HW=OK
START_PENDING_US=0
CLK=150000000
CLKMODE=STANDARD
VREG_MV=1100
RESET=POWER_ON
RESET_RAW=WD:0x0 CHIP:0x0
WDT_RESETS=0
WDT_MS=3000
WIFI=CONNECTED
WIFI_SSID=Lab Network
WIFI_PASS=SET
WIFI_AT_POWER_UP=1
WIFI_SAVED=1
WIFI_MAC=28:CD:C1:00:00:01
WIFI_IP=192.168.1.37
WIFI_RSSI_DBM=-58
NET_PORT=4242
NET_CLIENT=192.168.1.20
WIFI_PENDING=0
TX_DROPPED=0
```

| Key | Meaning |
|---|---|
| `FREQ` … `MARKERWIDTH` | Each setting as you asked for it, with the value actually produced |
| `COMBINE` | 0 = CH1 on Laser 1, CH2 on Laser 2; 1 = both pulses on both outputs |
| `PIXGATE`, `PIXLEAD`, `PIXLAG` | The pixel-reset gate settings |
| `PIXRESET` | `off`, or the gate as produced: reset time per period, its start after CH1, and how long the pixels are free around each pair |
| `ARMED` | The firmware's arm state (1/0). J11 and the 12 V supply are separate gates it can't see. |
| `HW` | `OK`; `ERR outputs not started: …` if the pulse hardware failed to start; or `ERR outputs stopped: …` if it later failed to load a setting (cleared by the next setting that loads) |
| `START_PENDING_US` | Microseconds until the pulses start after an `ARM` (0 = none pending) |
| `CLK` | Processor clock in Hz: 150000000, or 300000000 with the clock jumper |
| `CLKMODE` | `STANDARD` (150 MHz); `OVERCLOCK (jumper fitted)`; or `STANDARD (jumper fitted, overclock off: …)` with the reason, e.g. a watchdog restart since power-up |
| `VREG_MV` | Core voltage setting in mV: 1100 at 150 MHz, 1300 at 300 MHz |
| `RESET` | Why the board last restarted: `POWER_ON`, `WATCHDOG` (the firmware crashed and restarted itself), `SOFT`, `DEBUG`, `BROWNOUT`, `GLITCH`, `RUN_PIN` or `UNKNOWN` |
| `RESET_RAW` | Raw restart registers (for bug reports) |
| `WDT_RESETS` | Crash restarts since power-on |
| `WDT_MS` | Crash-restart timeout (3000 ms). If the firmware ever hangs, it restarts DISARMED after this long. While the radio chip starts (at power-up with Wi-Fi set up, and during `WIFI ON`, `OFF` and `CLEAR`) the timeout is 8000 ms; `WDT_MS` does not show that. |
| `WIFI` | `OFF` (the radio chip is off); `JOINING` (not yet joined); `DHCP` (joined, no address yet); `CONNECTED`; `FAULT (the radio chip stopped answering: send WIFI ON to start it again)`: the board switched the radio chip off and leaves it off until `WIFI ON` or a power cycle; or `UNAVAILABLE` (the `pico2` image). A reason can follow in brackets, e.g. `JOINING (network not found)`, `JOINING (the network refused the passphrase)`, `JOINING (link lost)`. While `JOINING`, the board tries again at intervals of 5 s to 20 s. |
| `WIFI_SSID`, `WIFI_PASS` | The network name in use, and `SET` or `NONE` for the passphrase |
| `WIFI_AT_POWER_UP` | 1 = the board joins the network at power-up |
| `WIFI_SAVED` | 1 = the set-up in use is the one that the board loads at power-up. 0 = it is not (after `SAVED=0`): at the next power-up the board uses what its flash holds. |
| `WIFI_MAC` | The radio's hardware address. `UNKNOWN (…)` until the radio starts for the first time after power-up. |
| `WIFI_IP` | The board's address, or `NONE` |
| `WIFI_RSSI_DBM` | Received signal level in dBm, or `NONE` |
| `NET_PORT` | TCP port of the network link (4242) |
| `NET_CLIENT` | Address of the connected host, or `NONE` |
| `WIFI_PENDING` | 1 = a name or passphrase was given with `WIFI SSID` / `WIFI PASS` and is not in use yet. Not shown by the `pico2` image. |
| `TX_DROPPED` | Bytes of replies thrown away because the host on this link was not reading. Each link has its own count. |

The `pico2` image shows one line, `WIFI=UNAVAILABLE (…)`, in place of the `WIFI_` and `NET_` lines.
