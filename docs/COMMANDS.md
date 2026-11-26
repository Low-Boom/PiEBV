# Command reference

This page lists all commands of the PiEBV firmware: the syntax rules, the commands, the timing
rules, the status registers, the errors and the Wi-Fi set-up. This page is part of the PiEBV
documentation. The overview and the list of all pages are in the [README](../README.md).

The firmware uses SCPI commands with the IEEE 488.2 syntax. The commands of earlier firmware
(`FREQ`, `WIDTH`, `ARM`, `STATUS`, `WIFI ON` and the others) are gone. Their replacements are in
[Old commands and STATUS keys](#old-commands-and-status-keys).

**Contents:** [Rules](#rules) · [Commands](#commands) · [Examples](#examples) ·
[Arming and DISARM](#arming-and-disarm) · [Echo for terminals](#echo-for-terminals) ·
[Wi-Fi set-up](#wi-fi-set-up) · [Combined mode](#combined-mode) ·
[Pixel-reset gate](#pixel-reset-gate) · [Timing](#timing) ·
[Status registers](#status-registers) · [Errors](#errors) ·
[Old commands and STATUS keys](#old-commands-and-status-keys)

## Rules

### Program messages

- A line is one program message. End it with LF, CR or CR+LF.
- A line can have up to 255 characters. A longer line is discarded completely, and error -363
  goes into the error queue.
- Backspace and DEL erase the previous character, so you can edit a line in a raw terminal.
- One line can hold more than one command. Put `;` between them:
  `:FREQ 15;:PULS:WIDT 100 NS`.
- The same commands work on the USB port and on the [network link](CONNECTING.md#network-wi-fi).
  Only the [Wi-Fi set-up](#wi-fi-set-up) commands are limited to USB.
- Each link (USB and network) has its own error queue, status registers and echo switch. The
  settings and the arm state are the same for both links. A reply goes only to the link that
  sent the command.

### Headers

- Each command has a header, such as `:SOURce:PULSe:WIDTh`. The words of a header are joined by
  `:`.
- Each word has a long form and a short form. The short form is the part in capital letters:
  `PULSe` or `PULS`, `WIDTh` or `WIDT`. Other abbreviations are not permitted: `PUL` gives error
  -113.
- Upper case and lower case are the same: `puls:widt?` works.
- A word in square brackets is optional: `[:SOURce]:FREQuency[:CW]` accepts `:FREQ`,
  `:SOUR:FREQ`, `:FREQ:CW` and `:SOURce:FREQuency:CW`.
- A query ends in `?`, directly after the header: `:FREQ?`. A query gives a reply.
- A setting has the header, a space, then the value: `:FREQ 15`. A setting gives no reply. Use
  `:SYST:ERR?` to read the errors, or switch on the [echo](#echo-for-terminals).
- Common commands start with `*` (for example `*IDN?` and `*RST`).

### The current path

The second and later commands of a line can use the current path, as SCPI specifies:

- A header that starts with `:` starts from the root of the command tree.
- After a header such as `:PULS:WIDT`, the current path is `:PULS`. A header without a leading
  `:` then starts there: `:PULS:WIDT?;DOUB:DEL?` reads `:PULS:WIDT?` and `:PULS:DOUB:DEL?`.
- After a header that names a node which has commands below it, used in its default form (for
  example `:OUTP ON` for `:OUTP:STAT ON`), the current path is that node: `:OUTP ON;COMB?` reads
  `:OUTP:COMB?`.
- If a header is not found below the current path, the firmware tries it from the root. Thus
  `:PULS:WIDT?;FREQ?` works.
- A common command (`*...`) does not change the current path.
- `:PULS:DOUB:DEL?;WIDT?` gives error -113, because there is no `:PULS:DOUB:WIDT` and no `:WIDT`.
  Write `:PULS:DOUB:DEL?;:PULS:WIDT?`.

### Values

- **Times are in seconds and frequencies in hertz.** A number without a suffix is in these
  units: `:PULS:WIDT 100` asks for 100 s and gives error -222. Write `:PULS:WIDT 100 NS` or
  `:PULS:WIDT 1E-7`.
- A number can have a sign, a decimal point and an exponent: `0.002`, `2E-6`, `+1.5E3`.
  Hexadecimal and other bases are not accepted.
- Suffixes (upper or lower case, a space before them is optional):

  | For | Suffixes |
  |---|---|
  | Times | `S`, `MS`, `US`, `NS`, `PS` |
  | Frequencies | `HZ`, `KHZ`, `MHZ` (mega, as SCPI specifies for hertz), `MAHZ` (mega), `GHZ` |

- `DEFault` sets the default value of that setting: `:PULS:WIDT DEF`.
- `MINimum` and `MAXimum` are not supported. They give error -224.
- A frequency is rounded to a whole number of hertz, and a time to a whole number of
  nanoseconds. Then the firmware rounds the value to whole steps of the clock (see
  [Timing](#timing)).
- A time or frequency can be from 0 to 4294967295 ns (4.29 s) or Hz.
- Boolean values: `ON`, `OFF`, `1` or `0`. A number is rounded, and any value that is not 0 is
  `ON`.
- Text values (the Wi-Fi name and passphrase) must be in double quotes or single quotes:
  `"Lab Network"` or `'Lab Network'`. To put the quote character in the text, write it two
  times: `"Lab ""A"" Net"`.

### Replies

- A query returns the **realized** value: the value that the hardware makes, after the rounding
  to clock steps. It is not always the value that you sent.
- Times and frequencies come back in the SCPI NR3 form, with 10 significant digits, in seconds
  or hertz: `1.000000000E-07` is 100 ns. Whole numbers come back without a decimal point. Text
  comes back in double quotes. Fixed words (such as `ARM`, `POWER_ON` or `CONNECTED`) come back
  without quotes.
- `9.91E+37` means "no value" (SCPI "not a number").
- The replies to all queries of one line come back on one line, separated by `;`:
  `:FREQ?;:PULS:WIDT?` gives `1.000000000E+03;1.000000000E-07`.
- Each reply line ends in CR+LF.
- The firmware sends nothing that was not asked for: no greeting at start, and no reply to a
  setting (unless the [echo](#echo-for-terminals) is on).
- A rejected setting changes nothing: the previous settings keep running.
- Each new value is checked **together with all the current settings**, so the order of changes
  can matter. For example, to raise the frequency a lot, shorten the pulse width first.

## Commands

### Pulse timing

| Command | Unit | Default | What it sets or returns |
|---|---|---|---|
| `[:SOURce]:FREQuency[:CW] <f>`, `...?` | Hz | 1000 | Pulse pairs per second. The query returns the realized frequency. |
| `[:SOURce]:PULSe:PERiod?` | s | – | The realized period (1/frequency). Query only. |
| `[:SOURce]:PULSe:WIDTh <t>`, `...?` | s | 100 ns | Length of both laser pulses |
| `[:SOURce]:PULSe:DOUBle:DELay <t>`, `...?` | s | 10 µs | Time from the start of the Laser 1 pulse to the start of the Laser 2 pulse. `0` makes them start together. |
| `[:SOURce]:PULSe:DOUBle[:STATe]?` | – | 1 | Always `1`: every period has a pulse pair. Query only. |
| `[:SOURce]:MARKer:WIDTh <t>`, `...?` | s | 2 µs | Length of the camera marker pulse. It starts with every Laser 1 pulse. |
| `[:SOURce]:SYNC:FREQuency?` | Hz | 1 MHz | The camera sync clock, read from the clock generator. Query only: the sync clock is fixed. |

The limits of these values are in [Timing](#timing).

### Laser outputs

| Command | Default | What it does |
|---|---|---|
| `:OUTPut[:STATe] ON`, `OFF`, `?` | `OFF` | `ON` arms the laser outputs. `OFF` disarms them. The query returns `1` (armed) or `0`. See [Arming and DISARM](#arming-and-disarm). |
| `:ABORt` | – | Disarms, the same as `:OUTP OFF`. No query form. |
| `:OUTPut:PENDing?` | – | Time in seconds until the laser pulses start after an arming (the hold-off). `0.000000000E+00` = no start is pending. |
| `:OUTPut:COMBine ON`, `OFF`, `?` | `OFF` | `OFF`: Laser 1 gets the CH1 pulse, Laser 2 the CH2 pulse. `ON`: **both** outputs get **both** pulses. Change it only while disarmed. See [Combined mode](#combined-mode). |
| `DISARM` | – | Not SCPI. Disarms at once, anywhere in the input. See [Arming and DISARM](#arming-and-disarm). |

### Pixel-reset gate commands

| Command | Unit | Default | What it sets or returns |
|---|---|---|---|
| `:PIXel:GATE OFF`, `ARMed`, `ALWays`, `?` | – | `OFF` | Hold the camera pixels in reset between pulse pairs: `OFF` never, `ARMed` while armed, `ALWays` also while disarmed. The query returns `OFF`, `ARM` or `ALW`. |
| `:PIXel:LEAD <t>`, `...?` | s | 10 µs | The pixels are released this long before each Laser 1 pulse |
| `:PIXel:LAG <t>`, `...?` | s | 100 µs | The pixels are reset again this long after the last laser pulse |
| `:PIXel:WINDow?` | s | – | Three values: the reset time per period, the start of the reset after the Laser 1 pulse starts, and the time per period in which the pixels are free. With the gate `OFF`: `0`, `0` and the period. Query only. |

See [Pixel-reset gate](#pixel-reset-gate).

### Common commands (IEEE 488.2)

| Command | What it does |
|---|---|
| `*IDN?` | Identification: `PiEBV,<board>,<board ID>,<firmware version>`. `<board>` is `Pico 2 W` or `Pico 2`. `<board ID>` is the unique ID of the Pico's flash chip, in hexadecimal. The firmware version is `git describe --always --dirty` of the git checkout that the firmware was built in: `-dirty` means that tracked files had changes that were not committed (new files that were never added to git do not count); `unknown` means that it was built without git. |
| `*RST` | Disarms and sets all pulse settings to their defaults. It does not change the Wi-Fi set-up, the error queue, the status registers or the echo switch. |
| `*CLS` | Clears the error queue and the standard event status register of this link |
| `*ESE <n>`, `*ESE?` | The standard event status enable register (0 to 255) |
| `*ESR?` | Reads the standard event status register, then clears it |
| `*SRE <n>`, `*SRE?` | The service request enable register (0 to 255; bit 6 is always 0) |
| `*STB?` | The status byte |
| `*OPC` | Sets bit 0 (OPC) of the standard event status register |
| `*OPC?` | Returns `1` at once: each command is complete when the firmware reads the next one |
| `*WAI` | Does nothing, for the same reason |
| `*TST?` | Returns `0`. The firmware has no self-test. |

The registers are described in [Status registers](#status-registers).

### System

| Command | What it does |
|---|---|
| `:SYSTem:ERRor[:NEXT]?` | Returns the oldest entry of this link's error queue and removes it: `<code>,"<text>"`. An empty queue gives `0,"No error"`. See [Errors](#errors). |
| `:SYSTem:ERRor:COUNt?` | The number of entries in the error queue |
| `:SYSTem:VERSion?` | `1999.0`, the SCPI version |
| `:SYSTem:ECHO ON`, `OFF`, `?` | Not SCPI. A reply to each setting and error, for use in a terminal. See [Echo for terminals](#echo-for-terminals). |
| `:SYSTem:HELP:HEADers?` | The list of all headers, as a definite-length block: `#` and one digit *n*, then *n* digits that give the length, then the text. The text has one header on each line, with `/qonly/` for a query only and `/nquery/` for a command without a query form. |

### Diagnostics

All are queries only.

| Command | Returns |
|---|---|
| `:DIAGnostic:HARDware?` | `"OK"`; `"outputs not started: …"` if the pulse hardware did not start; or `"outputs stopped: …"` if it did not load a setting later (the next setting that loads clears it) |
| `:DIAGnostic:CLOCk[:FREQuency]?` | The processor clock in Hz: `150000000`, or `300000000` with the clock jumper |
| `:DIAGnostic:CLOCk:MODE?` | `"STANDARD"` (150 MHz); `"OVERCLOCK (jumper fitted)"`; or `"STANDARD (jumper fitted, overclock off: …)"` with the reason, for example a watchdog restart since power-up |
| `:DIAGnostic:VREG?` | The core voltage setting in volts: `1.100000000E+00` at 150 MHz, `1.300000000E+00` at 300 MHz |
| `:DIAGnostic:RESet:CAUSe?` | Why the board last restarted: `POWER_ON`, `WATCHDOG` (the firmware stopped and the watchdog restarted it), `SOFT`, `DEBUG`, `BROWNOUT`, `GLITCH`, `RUN_PIN` or `UNKNOWN` |
| `:DIAGnostic:RESet:RAW?` | The raw restart registers, as two decimal numbers: the watchdog reason register and the chip reset register (for bug reports) |
| `:DIAGnostic:WATChdog:RESets?` | Watchdog restarts since power-on |
| `:DIAGnostic:WATChdog:PERiod?` | The watchdog period in seconds (`3.000000000E+00`). If the firmware stops, the board restarts DISARMED after this time. While the radio chip starts (at power-up with Wi-Fi set up, and during `:SYST:COMM:WLAN ON`, `OFF` and `CLEar`) the period is 8 s; the query does not show that. |
| `:DIAGnostic:TXDRopped?` | Bytes of replies that were discarded because the host of this link did not read them. Each link has its own count. The count of the network link starts at 0 for each new host. |

### Network link (Wi-Fi)

The settings work only on the USB port, and only in the `pico2w` firmware image. The queries work
on both links and in both images. See [Wi-Fi set-up](#wi-fi-set-up).

| Command | What it does or returns |
|---|---|
| `:SYSTem:COMMunicate:WLAN[:STATe] ON`, `OFF` | `ON` joins the network now and at every power-up, and stores the set-up in flash. `OFF` switches the radio off, now and at power-up, and keeps the name and the passphrase in use. |
| `:SYSTem:COMMunicate:WLAN[:STATe]?` | `1` if the set-up in use switches the radio on (now and at power-up), else `0` |
| `:SYSTem:COMMunicate:WLAN:SSID "<name>"` | Gives the network name for the next `WLAN ON`. It also discards a passphrase given before. |
| `:SYSTem:COMMunicate:WLAN:SSID?` | The network name in use, or `""` |
| `:SYSTem:COMMunicate:WLAN:PASSword "<passphrase>"` | Gives the WPA2 passphrase for the next `WLAN ON`. `""` selects an open network. No query form: the passphrase is never shown. |
| `:SYSTem:COMMunicate:WLAN:SECurity?` | `WPA2` if the set-up in use has a passphrase, `NONE` for an open network |
| `:SYSTem:COMMunicate:WLAN:CLEar` | As `WLAN OFF`, and erases the name and the passphrase |
| `:SYSTem:COMMunicate:WLAN:LINK?` | The state of the link and a note: `<state>,"<note>"`. See the states below. |
| `:SYSTem:COMMunicate:WLAN:PENDing?` | `1` if a name or passphrase was given with `WLAN:SSID` or `WLAN:PASS` and is not in use yet, else `0` |
| `:SYSTem:COMMunicate:WLAN:SAVed?` | `1` if the set-up in use is the one that the board loads at power-up. `0` if it is not: the flash write was not done, and the next power-up uses what the flash holds. |
| `:SYSTem:COMMunicate:WLAN:MAC?` | The hardware address of the radio, for example `"28:CD:C1:00:00:01"`. `""` until the radio starts for the first time after power-up. |
| `:SYSTem:COMMunicate:WLAN:IPADdress?` | The address of the board, or `""` |
| `:SYSTem:COMMunicate:WLAN:RSSI?` | The received signal level in dBm, or `9.91E+37` (no value) |
| `:SYSTem:COMMunicate:WLAN:PORT?` | The TCP port of the network link: `4242` |
| `:SYSTem:COMMunicate:WLAN:CLIent?` | The address of the connected network host, or `""` |

States of `:SYST:COMM:WLAN:LINK?`:

| State | Meaning |
|---|---|
| `OFF` | The radio chip is off. The note can give a reason: `the stored set-up cannot be read: send it again, or :SYST:COMM:WLAN:CLE` after a power-up with a damaged record; `held off after a watchdog reset: send :SYST:COMM:WLAN ON, or power-cycle`; `the radio chip did not start`; `the TCP server did not start`. |
| `JOINING` | Not joined yet. The note can give a reason: `network not found`, `the network refused the passphrase`, `join failed`, `link lost`. The board tries again at intervals of 5 s to 20 s. |
| `DHCP` | Joined, no address yet |
| `CONNECTED` | Joined, with an address |
| `FAULT` | Note `the radio chip stopped answering: send :SYST:COMM:WLAN ON to start it again`. The board switched the radio chip off, and it stays off until `:SYST:COMM:WLAN ON` or a power cycle. |
| `UNAVAILABLE` | The `pico2` image (plain Pico 2, no radio). Note `firmware image for a Pico 2, which has no radio`. |

## Examples

In these examples, `->` shows the reply. A line without `->` gives no reply.

```
*IDN?                          ->  PiEBV,Pico 2 W,<board ID>,5dfedd5
:PULS:DOUB:DEL 1003 NS
:PULS:DOUB:DEL?                ->  1.000000000E-06
:PULS:WIDT 101NS;WIDT?         ->  1.000000000E-07
:FREQ 15;:FREQ?;:PULS:PER?     ->  1.500000000E+01;6.666666667E-02
:FREQ 7000;:FREQ?              ->  6.999860003E+03
:OUTP ON
:OUTP?;PEND?                   ->  1;9.999370000E-01
DISARM
:OUTP?                         ->  0
:FREQ 1500 KHZ
:SYST:ERR?                     ->  -221,"Settings conflict;DELAY must leave >= WIDTH before the next pulse pair (DELAY <= 1/FREQ - 2 x WIDTH); max DELAY 466.667 ns"
:SYST:ERR?                     ->  0,"No error"
```

- `1003 NS` becomes 1000.000 ns: 150 steps of 6.667 ns. `101NS` becomes 100.000 ns (15 steps).
- 7000 Hz becomes 6999.860 Hz: the period is a whole number of steps (21429).
- The time in `:OUTP:PEND?` is in seconds. It is `0` when no start is pending. The first arming
  after a start waits about 1 s (see [Arming and DISARM](#arming-and-disarm)).
- A setting that is rejected (`:FREQ 1500 KHZ` with the default delay of 10 µs) gives no reply.
  Its error goes into the error queue.

## Arming and DISARM

- **`:OUTP ON`** arms the laser outputs. `:OUTP ON` while already armed changes nothing. If the
  pulse hardware did not start, `:OUTP ON` is refused with error -240 and the reason.
- **The hold-off.** The pulses start only after a wait of one full pulse period (the longer of
  the old and new periods, at most 1 s), counted from the last laser pulse. After a restart, the
  pulses cannot start until 1 s after it. This makes sure that two laser pulses are never closer
  together than the set period, for all sequences of commands. The marker pauses during the
  hold-off, so cameras that are triggered by the marker miss triggers in that time. When the
  pulses start, the CH1, CH2 and marker timing starts again together, and the first pulse has
  its full width. `:OUTP:PEND?` gives the time that is left.
- A change of the frequency, the pulse width, the delay or the marker width while armed goes
  through the same hold-off, and the outputs stay armed. A change that gives the same step counts
  (for example `:PULS:WIDT 100 NS` to `:PULS:WIDT 101 NS`) restarts nothing.
- **`:OUTP OFF`** and **`:ABORt`** disarm. They are never refused.
- **`DISARM`** (not SCPI, a safety extension). The six letters D-I-S-A-R-M, in any case and
  anywhere in the input, disarm the outputs at once:
  - The outputs go low when the firmware reads the `M`. The firmware does not wait for the end of
    the line.
  - Nothing else on that line runs: not the part before `DISARM`, and not the part after it, up to
    the end of the line.
  - A pending start is cancelled.
  - The letters also act inside a quoted text, for example in a Wi-Fi name.
  - `DISARM` gives no reply, unless the echo is on (`OK :OUTP 0 (DISARM)`).
  - The letters must be on one line: `DIS`, Enter, `ARM`, Enter does not disarm. It gives two
    -113 errors.
- `DISARM` also works when the host does not read the replies. But a host that reads its replies
  slowly, or not at all, can delay it by up to about 0.55 s (about 1.2 s if the hosts of both
  links, USB and network, are slow). These times are from tests on a computer. They were not
  measured on a board. A radio fault can add more: see [the network limits](CONNECTING.md#limits).
- While disarmed, **the sync clock and the marker keep running**, so the cameras stay
  synchronized. The laser outputs are held at 0 V.
- `*RST` also disarms.

## Echo for terminals

`:SYST:ECHO ON` is not SCPI. It makes the firmware reply to each setting and each error, for use
in a terminal:

- A setting that is accepted replies `OK <header> <realized value>`, with a hint for people in
  brackets: `OK :PULS:DOUB:DEL 1.000000000E-06 (1000.000 ns, 150 cyc)`.
- An error replies `ERR <code>,"<text>"`: `ERR -113,"Undefined header;FOO"`.
- Queries reply as without the echo.
- The echo switch is for each link. It is off at start, and off for each new host of the network
  link. `*RST` does not change it.
- With the echo on, each error also goes into the error queue. Send `*CLS` from time to time: when
  the queue is full, the `ERR` line shows -350 in place of the error.

```
:SYST:ECHO ON              ->  OK :SYST:ECHO 1
:PULS:DOUB:DEL 1003 NS     ->  OK :PULS:DOUB:DEL 1.000000000E-06 (1000.000 ns, 150 cyc)
:PULS:WIDT 101 NS          ->  OK :PULS:WIDT 1.000000000E-07 (100.000 ns, 15 cyc)
:FREQ 15                   ->  OK :FREQ 1.500000000E+01 (15.000 Hz, period 10000000 cyc)
:OUTP:COMB ON              ->  OK :OUTP:COMB 1 (CH1 + CH2 on LASER 1 and LASER 2)
:PIX:GATE ARM              ->  OK :PIX:GATE ARM (pixels reset between pulse pairs while armed)
:OUTP ON                   ->  OK :OUTP 1 (laser pulses start after a 999871 us hold-off)
DISARM                     ->  OK :OUTP 0 (DISARM)
FOO                        ->  ERR -113,"Undefined header;FOO"
:SYST:ECHO OFF
```

- `cyc` is the realized value in clock steps ("cycles").
- The `(laser pulses start after …)` part shows only while a start (the hold-off) is pending.
  Otherwise `:OUTP ON` replies `OK :OUTP 1`.
- `:OUTP OFF` and `:ABOR` reply `OK :OUTP 0`. `*RST`, `*CLS`, `*OPC` and `*WAI` reply `OK` and
  their name.
- `:SYST:ECHO OFF` gives no reply, because the echo is off when the firmware writes it.

## Wi-Fi set-up

These commands set up the [network link](CONNECTING.md#network-wi-fi) of a Pico 2 W. The settings
work **only on the USB port**. From the network link they give error -203. The queries work on
both links. A network host can read the set-up, but not the passphrase.

```
:SYST:COMM:WLAN:SSID "Lab Network"
:SYST:COMM:WLAN:PASS "correct horse"
:SYST:COMM:WLAN:PEND?                  ->  1
:SYST:COMM:WLAN ON
:SYST:ERR?                             ->  0,"No error"
:SYST:COMM:WLAN:LINK?;IPAD?            ->  CONNECTED,"";"192.168.1.37"
```

With the echo on, the replies are:

```
:SYST:COMM:WLAN:SSID "Lab Network"  ->  OK :SYST:COMM:WLAN:SSID "Lab Network" (not in use yet: send :SYST:COMM:WLAN:PASS if it has a passphrase, then :SYST:COMM:WLAN ON)
:SYST:COMM:WLAN:PASS "correct horse" -> OK :SYST:COMM:WLAN:PASS (set; not in use yet: send :SYST:COMM:WLAN ON)
:SYST:COMM:WLAN ON                  ->  OK :SYST:COMM:WLAN 1 ("Lab Network", WPA2, stored)
:SYST:COMM:WLAN OFF                 ->  OK :SYST:COMM:WLAN 0 ("Lab Network", WPA2, stored)
:SYST:COMM:WLAN:CLE                 ->  OK :SYST:COMM:WLAN:CLE
```

**Order and staging**

- A name or passphrase given with `WLAN:SSID` or `WLAN:PASS` holds only until the next
  `WLAN ON`, `WLAN OFF` or `WLAN:CLEar`. `WLAN ON` uses it. `WLAN OFF` and `WLAN:CLEar` discard it.
  Each of the three also discards it when it is refused, for all reasons. If something was
  discarded, the error text ends in `(what was sent with WLAN:SSID / WLAN:PASS is discarded)`.
- `:SYST:COMM:WLAN:PEND?` gives `1` while a name or passphrase waits for `WLAN ON`.
- A new name never gets the passphrase of another network: `WLAN:SSID` starts the name without a
  passphrase, also when the name is the one in use. Send `WLAN:PASS` after `WLAN:SSID`.
  `WLAN:SSID "<name>"`, then `WLAN ON`, joins an **open** network with that name.
- `WLAN:PASS "<passphrase>"`, then `WLAN ON` (with no `WLAN:SSID`) changes the passphrase of the
  network in use. `WLAN ON` alone joins the network in use again, for example after `WLAN OFF`.
- `WLAN ON` with no name given and none in use gives error -221
  (`no network name: send :SYST:COMM:WLAN:SSID first`).

**Results**

- `WLAN ON` means that the join started, not that it is complete. Send
  `:SYST:COMM:WLAN:LINK?` to see the result.
- `:SYST:COMM:WLAN:SSID?` and `:SYST:COMM:WLAN:SEC?` give the set-up that is now in use. `NONE`
  means an open network.
- Error 101 (`Set-up not stored;…`) after `WLAN ON`, `OFF` or `CLEar` means that the set-up is in
  use but not in flash. The text gives the reason, for example
  `flash is written only at the 150 MHz clock; remove the clock jumper to store it` or
  `the flash write failed`. `:SYST:COMM:WLAN:SAV?` then gives `0`. With the echo on, the `OK`
  line ends in `not stored)`.

**Refusals**

- `WLAN ON`, `OFF` and `CLEar` are refused while armed or while a laser start is pending:
  error -200, `DISARM first: the radio start and the flash write stop the command loop for a
  moment`.
- `WLAN ON` gives error -200 with `the radio chip did not start` or
  `the TCP server did not start` (no memory for the network server). The radio is then off.
  `WLAN ON` tries again.
- `WLAN OFF` and `WLAN:CLEar` switch the radio chip off. `WLAN ON` starts it again. This takes
  longer than the other commands (up to some seconds; not yet measured).
- In the `pico2` image each Wi-Fi setting gives error -241.

**Text rules**

- The name is 1 to 32 bytes: 32 ASCII characters, or fewer with letters outside ASCII. It must be
  UTF-8 text (plain ASCII is UTF-8) without control characters (a tab included) and without the
  characters that change the writing direction. Spaces are part of the name, also at the start
  and at the end.
- The passphrase is 8 to 63 printable ASCII characters, or `""` for an open network.
- The name and the passphrase cannot contain the letters `disarm` in sequence, in any case: the
  firmware reads them as `DISARM` and discards the line.
- A text that is not in quotes gives error -104. A quote inside the text that is not doubled
  gives error -151. A text that does not obey the rules above gives error -222 with the reason.

## Combined mode

`:OUTP:COMB ON` sends the whole double pulse (the CH1 pulse, then the CH2 pulse exactly the delay
later) to **both** Laser 1 (J7) and Laser 2 (J8). Use it when one light source must make both
PIV flashes, or to fire two light sources together with the same double pulse. Each output
still drives one laser driver.

```
:OUTP:COMB ON;COMB?       ->  1
:OUTP:COMB OFF;COMB?      ->  0
```

- **Change it only while disarmed.** While armed, a change gives error -221 with
  `DISARM first: OUTPut:COMBine changes what both laser outputs carry`.
- **The pulses must stay apart:**
  - The delay must be at least one step (6.667 ns) longer than the pulse width, for example a
    delay of 106.667 ns or more at a width of 100 ns. At a delay equal to the width the second
    pulse would start as the first ends, and the two would become one pulse of twice the width.
  - Delay ≤ 1/frequency − 2 × width, as in the normal mode, so each pair is separate from the
    next.
  - Each driver now gets two pulses per period: check its own spacing and duty ratings. The
    firmware does not set limits for them.
- The timing is exactly as precise as in the normal mode.
- The monitor point follows: J10 pin 1 shows the double pulse, and with J10 on 1-2 the cameras are
  triggered on both pulses.

## Pixel-reset gate

PiEBV can hold the pixels of every camera in reset **between pulse pairs**, like a shutter. The
pixels are free from the lead time (`:PIX:LEAD`) before the Laser 1 pulse until the lag time
(`:PIX:LAG`) after the last laser pulse. They are held in reset for the rest of each period. This
removes background and noise events between pairs, and every pair starts from pixels that were
just reset.

```
            pair k                                        pair k+1
CH1     ____|‾|______________________________________________|‾|______
CH2     _________|‾|______________________________________________|‾|_
TDRSTN  ‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾|__________________________|‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾   (low = pixels in reset)
                   |<------>|                          |<------>|
                    PIX:LAG      pixels in reset         PIX:LEAD
```

(`TDRSTN` is the pixel-reset pin of the camera.)

| Setting | Default | Meaning |
|---|---|---|
| `:PIX:GATE OFF` | ✓ | Off: the pixels are never held in reset |
| `:PIX:GATE ARMed` | | Reset between pulse pairs **while armed**; off while disarmed |
| `:PIX:GATE ALWays` | | Reset between pulse pairs **always**, also while disarmed (for bench tests without lasers) |
| `:PIX:LEAD <t>` | 10 µs | The pixels are released this long before each Laser 1 pulse starts (at least 5 steps, 33.333 ns, while the gate is on) |
| `:PIX:LAG <t>` | 100 µs | The pixels are reset again this long after the last laser pulse ends |

```
:FREQ 2000;:PIX:GATE ALW
:PIX:WIND?                    ->  3.799000000E-04,1.101000000E-04,1.201000000E-04
:PIX:GATE ARM;GATE?           ->  ARM
:PIX:LAG 50 US;LAG?           ->  5.000000000E-05
```

- **PiEBV is the only source of the pixel reset.** The board has no reset input. With
  `:PIX:GATE OFF` the cameras run freely.
- **Find the lead and lag times by experiment.** The time that the sensor needs to settle after a
  reset, and the time for which its events keep arriving after a flash, are not published. Start
  with long times (the defaults), look at the event stream, then make them shorter. The window
  must fit in the period: lead + delay + width + lag ≤ 1/frequency − 3 steps. The error text
  gives the longest lag that fits.
- The lead time minimum (5 steps) is checked only while the gate is `ARMed` or `ALWays`.
- **The first pulse pair after a start has no reset before it.** Every later pair has one. The
  gate is timed from the same start as CH1 and CH2, to the exact step.
- `:PIX:WIND?` gives the result: the reset time per period, its start after the Laser 1 pulse
  starts, and the time per period in which the pixels are free. In the example (period 500 µs,
  default lead and lag times):
  380 µs of reset, starting 110.1 µs after CH1 (delay 10 µs + width 0.1 µs + lag 100 µs), and
  120.1 µs free.
- A pixel reset also puts a timestamp (trigger channel 1) into the event stream of each camera,
  when the trigger channel is enabled in the camera software.

## Timing

```
            |<------------------- period = 1/frequency ------------------->|
CH1  (J7)  _|‾‾‾‾|______________________________________________________________|‾‾‾‾|_
             width
CH2  (J8)  ____________|‾‾‾‾|__________________________________________________________
            |<-delay-->|
MARKER     _|‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾‾|____________________________________________|‾‾‾‾‾‾‾
             marker width
SYNC       _|‾|_|‾|_|‾|_|‾|_|‾|_|‾|_|‾|_|‾|_|‾|_|‾|_|‾|_ ... runs all the time, 1 MHz
```

A "step" is one 6.667 ns cycle of the 150 MHz clock. With the clock jumper fitted (300 MHz) a step
is 3.333 ns, and every limit given in steps is half as long in ns. The examples in this
documentation are for 150 MHz.

The error texts and the other pages of this documentation use short names for the settings:

| Name | Setting |
|---|---|
| `FREQ` | `[:SOURce]:FREQuency` |
| `WIDTH` | `[:SOURce]:PULSe:WIDTh` |
| `DELAY` | `[:SOURce]:PULSe:DOUBle:DELay` |
| `MARKERWIDTH` | `[:SOURce]:MARKer:WIDTh` |
| `COMBINE` | `:OUTPut:COMBine` |
| `PIXGATE` | `:PIXel:GATE` |
| `PIXLEAD` | `:PIXel:LEAD` |
| `PIXLAG` | `:PIXel:LAG` |

- **Rounding:** the firmware rounds a time to whole nanoseconds, then to the nearest step. It
  rounds a frequency to whole hertz, then to the nearest whole number of steps per period. All
  limits are checked on the rounded values, and the queries return them.
- **The Laser 2 pulse starts exactly DELAY after Laser 1,** to the step.
- **The marker** starts at the same time as every Laser 1 pulse and repeats at exactly the same
  rate, so it can never drift away from the pulse that it marks. Each camera records it as a
  timestamp, which gives every pulse pair its own reference time. MARKERWIDTH can be at most half
  the period, so with the default 2 µs the frequency can go up to 250 kHz. Make MARKERWIDTH
  shorter to go higher.
- **The sync clock** is fixed at **1 MHz** and cannot be changed: the RP2350 clock generator
  divides the 150 MHz system clock by exactly 150 (300 MHz: by exactly 300). `:SOUR:SYNC:FREQ?`
  reads it. It does not depend on the laser timing. The IDS uEye EVS cameras (Prophesee IMX636
  sensor) need it at **1 MHz**: a camera that runs as sync slave counts its 1 µs event
  timestamps on this clock, and Prophesee requires Sync In to be "a 1MHz pulse train to
  correspond to the internally generated 1µs timestamp resolution". Any other frequency makes
  the timestamps of every camera too long or too short, and an IMX636 slave sends no data until
  the clock arrives.
- **No laser-driver limits.** The firmware does not limit the pulse width or the duty: they
  depend on the driver that you connect, so stay within its ratings. The firmware applies what
  the pulse hardware needs, plus one spacing rule of its own:
  - **pulse pairs stay apart** (the rule of the firmware): DELAY ≤ 1/FREQ − 2 × WIDTH, so the
    Laser 2 pulse ends at least one WIDTH before the next Laser 1 pulse (this also limits WIDTH
    to half the period);
  - **the pulse program:** DELAY ≤ 1/FREQ − WIDTH − 5 steps. This is the tighter limit only for
    a WIDTH of 3 or 4 steps (20.000 or 26.667 ns). The error text names the limit that applies;
  - **shortest pulse:** 3 steps (20.000 ns) for WIDTH and MARKERWIDTH. A value of 16 ns or less
    is rejected, not made longer;
  - **marker duty:** 2 × MARKERWIDTH ≤ 1/FREQ (MARKERWIDTH ≤ 1/FREQ − 5 steps for periods under
    10 steps);
  - with `:OUTP:COMB ON`, DELAY > WIDTH ([Combined mode](#combined-mode));
  - with the pixel-reset gate on, the rules in [Pixel-reset gate](#pixel-reset-gate).
- **Slowest rate:** the frequency goes down to 1 Hz.
- **Delay through the hardware:** the output driver of the board (U13) adds about 17 ns (up to
  27 ns) to both channels alike, so the time between the two pulses at J7/J8 is kept to within
  1–2 ns. (Your laser drivers add their own delays.)

## Status registers

Each link has its own registers. They follow IEEE 488.2.

**Standard event status register** (`*ESR?` reads and clears it; `*ESE` sets its enable mask):

| Bit | Value | Name | Set when |
|---|---|---|---|
| 0 | 1 | OPC | `*OPC` was sent |
| 2 | 4 | QYE | An error -400 to -499 occurred (the firmware has no such errors now) |
| 3 | 8 | DDE | An error -300 to -399, or a positive error number (101), occurred |
| 4 | 16 | EXE | An execution error (-200 to -299) occurred |
| 5 | 32 | CME | A command error (-100 to -199) occurred |
| 7 | 128 | PON | The board started (USB link). Read it with `*ESR?` to know that the board restarted since the last read. |

**Status byte** (`*STB?`; `*SRE` sets its enable mask):

| Bit | Value | Name | Set when |
|---|---|---|---|
| 2 | 4 | EAV | The error queue of this link is not empty |
| 5 | 32 | ESB | A bit of the standard event status register is set that is also set in `*ESE` |
| 6 | 64 | MSS | A bit of the status byte is set that is also set in `*SRE` |

- The board has no service request line: read the status byte with `*STB?`.
- `*CLS` clears the error queue and the standard event status register. It does not change
  `*ESE` and `*SRE`.
- A new host of the network link starts with a clear error queue, all registers at 0 and the echo
  off.

```
*ESR?            ->  128
*ESE 32;*SRE 32
FOO
*STB?            ->  100
```

(`*STB?` gives 100 = 4 + 32 + 64: an error is in the queue, the CME bit is set and enabled in
`*ESE`, and the ESB bit is enabled in `*SRE`.)

## Errors

An error does not give a reply (unless the echo is on). It goes into the error queue of the link
that sent the command, and sets a bit of the standard event status register. Read the queue with
`:SYST:ERR?`, one entry at a time, oldest first:

```
FOO
:FREQ 0
:SYST:ERR:COUN?;:SYST:ERR?;:SYST:ERR?;:SYST:ERR?
    ->  2;-113,"Undefined header;FOO";-221,"Settings conflict;value must be > 0";0,"No error"
```

- The text is the SCPI error text, then `;` and the detail. A double quote in the detail becomes
  a single quote.
- The queue holds 8 entries. When it is full, the newest entry becomes `-350,"Queue overflow"`,
  and later errors are lost until you read the queue or send `*CLS`.
- An error in the structure of a command ends the rest of the line: errors -102, -103 and -113,
  error -151 for a missing closing quote, and error -108 for more than four values. The commands
  before it ran.
- All other errors end only their own command. The next command of the line runs. For example,
  `:FREQ 0;:FREQ?` gives the frequency, and error -221 goes into the queue.
- After a restart, a problem of the pulse hardware is in the error queue of the USB link as error
  -240. `:DIAG:HARD?` gives the same reason.

| Code | Text | When |
|---|---|---|
| 0 | `No error` | The queue is empty |
| -102 | `Syntax error` | A header that does not start with a letter, or no space between the header and its value (`:FREQ=5`) |
| -103 | `Invalid separator` | A value is missing before or after `,` (`:FREQ 5,`) |
| -104 | `Data type error` | A number is needed, but the value is a word (`:PULS:WIDT abc`); a text is needed, but the value is not in quotes |
| -108 | `Parameter not allowed` | Too many values, or a value after a query (`:FREQ? 5`) |
| -109 | `Missing parameter` | A setting without its value (`:FREQ`) |
| -113 | `Undefined header` | Not a command (the detail gives the header); a query of a command that has no query form (`:ABOR?`); a setting of a query only (`:PULS:PER 1`) |
| -121 | `Invalid character in number` | Characters after a number that are not a suffix (`:FREQ 1 2`) |
| -131 | `Invalid suffix` | A suffix of the wrong unit or an unknown suffix (`:PULS:WIDT 10K`, `:PULS:WIDT 5 HZ`) |
| -138 | `Suffix not allowed` | A suffix on a value that has no unit (`*ESE 5 HZ`) |
| -151 | `Invalid string data` | A text without its closing quote, or with a quote inside that is not doubled |
| -200 | `Execution error` | A Wi-Fi `WLAN ON`, `OFF` or `CLEar` that was refused (see [Wi-Fi set-up](#wi-fi-set-up)); `*RST` when the defaults did not load |
| -203 | `Command protected` | A Wi-Fi setting sent over the network link |
| -221 | `Settings conflict` | A setting that does not fit together with the other settings (the reasons are below); `:OUTP:COMB` changed while armed; `WLAN ON` without a network name |
| -222 | `Data out of range` | A negative time; a time longer than 4.29 s or a frequency above 4.29 GHz; a number too large; `*ESE` or `*SRE` outside 0 to 255; a Wi-Fi name or passphrase that does not obey the [text rules](#wi-fi-set-up) |
| -224 | `Illegal parameter value` | `MIN` or `MAX`; a boolean that is not `ON`, `OFF` or a number; a pixel gate that is not `OFF`, `ARMed` or `ALWays` |
| -240 | `Hardware error` | `:OUTP ON` refused because the pulse hardware did not start or did not load a setting; a problem of the pulse hardware at start (USB link) |
| -241 | `Hardware missing` | A Wi-Fi setting in the `pico2` image (no radio) |
| -350 | `Queue overflow` | The error queue was full |
| -363 | `Input buffer overrun` | A line longer than 255 characters. The whole line is discarded. |
| 101 | `Set-up not stored` | Not an error: the new Wi-Fi set-up is in use, but it is not in flash. The detail gives the reason. |

**Reasons of error -221 for the pulse settings.** The detail names the limit with the short
names of [Timing](#timing). The setting that you changed is not always the one named in the
reason: for example, `:PULS:DOUB:DEL 1 US;:FREQ 600 KHZ` with the default 2 µs marker width
gives a `MARKERWIDTH` reason for the `:FREQ` setting.

| Detail | Meaning |
|---|---|
| `value must be > 0` | A frequency of 0 Hz (also after the rounding to whole hertz, for example 0.4 Hz) |
| `WIDTH realizes below the 3-cycle minimum (20.000 ns)` | WIDTH of 16 ns or less (the same text with `MARKERWIDTH` for the marker width) |
| `DELAY must leave >= WIDTH before the next pulse pair (DELAY <= 1/FREQ - 2 x WIDTH); max DELAY … ns` | DELAY too long for the period at this WIDTH |
| `WIDTH too long for the period: 2 x WIDTH must fit in 1/FREQ` | WIDTH longer than half the period |
| `DELAY + WIDTH must fit in the period (DELAY <= 1/FREQ - WIDTH - 5 cycles); max DELAY … ns` | The same as the `DELAY must leave` reason, for a WIDTH of 3 or 4 steps, where the limit of the pulse program is the tighter one |
| `WIDTH does not fit in the period (WIDTH <= 1/FREQ - 5 cycles)` | The period is too short for a WIDTH of 3 or 4 steps |
| `COMBINE needs DELAY > WIDTH so the two pulses stay separate (min DELAY … ns)` | In combined mode, DELAY not longer than WIDTH |
| `DISARM first: OUTPut:COMBine changes what both laser outputs carry` | `:OUTP:COMB` changed while armed |
| `MARKERWIDTH must be <= half the period (2 x MARKERWIDTH <= 1/FREQ); max MARKERWIDTH … ns` | MARKERWIDTH longer than half the period, for example after a higher frequency. The 50 % limit protects J12 against a shorted cable. |
| `MARKERWIDTH must fit in the period (MARKERWIDTH <= 1/FREQ - 5 cycles); max MARKERWIDTH … ns` | The same, for periods under 10 steps, where the limit of the pulse program is the tighter one |
| `PIXLEAD realizes below the 5-cycle minimum (33.333 ns)` | With the pixel-reset gate on, PIXLEAD too short |
| `PIXLEAD + DELAY + WIDTH + PIXLAG must leave >= 3 cycles of pixel reset in 1/FREQ; max PIXLAG … ns` | With the pixel-reset gate on, the window does not fit in the period |
| `PIXLEAD + DELAY + WIDTH leave no time to reset the pixels in 1/FREQ: lower PIXLEAD or FREQ` | The same, when no PIXLAG fits |
| `FREQ out of range` | The frequency is so high that the period rounds to 0 steps (above 300 MHz at the 150 MHz clock) |
| `pio0 unavailable` | The pulse hardware did not start (`:DIAG:HARD?`) |
| `pulse state machines could not be loaded` | The pulse hardware did not take settings that passed every check. This should never occur: the pulse outputs stop, the lasers are disarmed, and `:OUTP ON` is refused until a later setting loads (`:DIAG:HARD?`) |

**Other texts**

- `ERR busy: another host is connected` is not SCPI. A second network connection gets this line,
  and the board closes the connection. See [Network (Wi-Fi)](CONNECTING.md#network-wi-fi).

## Old commands and STATUS keys

The text commands of earlier firmware are gone. They give error -113. Use these commands:

| Old command | New command |
|---|---|
| `FREQ 15` | `:FREQ 15` (hertz, as before) |
| `WIDTH 100` | `:PULS:WIDT 100 NS` (a number without a suffix is in seconds) |
| `DELAY 10000` | `:PULS:DOUB:DEL 10000 NS` or `:PULS:DOUB:DEL 10 US` |
| `MARKERWIDTH 2000` | `:MARK:WIDT 2000 NS` |
| `COMBINE 0` / `1` | `:OUTP:COMB OFF` / `ON` |
| `PIXGATE 0` / `1` / `2` | `:PIX:GATE OFF` / `ARMed` / `ALWays` |
| `PIXLEAD n`, `PIXLAG n` | `:PIX:LEAD n NS`, `:PIX:LAG n NS` |
| `FREQ`, `WIDTH`, … (on its own: ask for the value) | `:FREQ?`, `:PULS:WIDT?`, … |
| `ARM` | `:OUTP ON` |
| `DISARM` | `DISARM` (no change), or `:OUTP OFF`, or `:ABOR` |
| `ARM?` | `:OUTP?` |
| `ID?` | `*IDN?` |
| `HELP` | `:SYST:HELP:HEAD?` |
| `STATUS` | The queries in the table below |
| `WIFI` | `:SYST:COMM:WLAN:LINK?` and the other `:SYST:COMM:WLAN` queries |
| `WIFI SSID Lab Network` | `:SYST:COMM:WLAN:SSID "Lab Network"` |
| `WIFI PASS correct horse` | `:SYST:COMM:WLAN:PASS "correct horse"` |
| `WIFI PASS` (on its own: open network) | `:SYST:COMM:WLAN:PASS ""` |
| `WIFI ON`, `WIFI OFF` | `:SYST:COMM:WLAN ON`, `:SYST:COMM:WLAN OFF` |
| `WIFI CLEAR` | `:SYST:COMM:WLAN:CLE` |

The old replies (`OK DELAY=1003 (actual …)`, `ARMED=0`, `ERR …`) are gone: settings give no reply,
and errors go into the [error queue](#errors). The old start-up greeting is gone too.

| Old `STATUS` key | New query | Note |
|---|---|---|
| `FREQ` | `:FREQ?` | Realized value only |
| `WIDTH` | `:PULS:WIDT?` | In seconds |
| `DELAY` | `:PULS:DOUB:DEL?` | In seconds |
| `MARKERWIDTH` | `:MARK:WIDT?` | In seconds |
| `COMBINE` | `:OUTP:COMB?` | |
| `PIXGATE` | `:PIX:GATE?` | `OFF`, `ARM` or `ALW` |
| `PIXLEAD`, `PIXLAG` | `:PIX:LEAD?`, `:PIX:LAG?` | In seconds |
| `PIXRESET` | `:PIX:WIND?` | Three values in seconds |
| `ARMED` | `:OUTP?` | |
| `HW` | `:DIAG:HARD?` | `"OK"` or the reason |
| `START_PENDING_US` | `:OUTP:PEND?` | In seconds |
| `CLK` | `:DIAG:CLOC?` | |
| `CLKMODE` | `:DIAG:CLOC:MODE?` | In quotes |
| `VREG_MV` | `:DIAG:VREG?` | In volts |
| `RESET` | `:DIAG:RES:CAUS?` | |
| `RESET_RAW` | `:DIAG:RES:RAW?` | Two decimal numbers |
| `WDT_RESETS` | `:DIAG:WATC:RES?` | |
| `WDT_MS` | `:DIAG:WATC:PER?` | In seconds |
| `WIFI` | `:SYST:COMM:WLAN:LINK?` | `<state>,"<note>"` |
| `WIFI_SSID` | `:SYST:COMM:WLAN:SSID?` | |
| `WIFI_PASS` | `:SYST:COMM:WLAN:SEC?` | `WPA2` or `NONE` |
| `WIFI_AT_POWER_UP` | `:SYST:COMM:WLAN?` | |
| `WIFI_SAVED` | `:SYST:COMM:WLAN:SAV?` | |
| `WIFI_MAC` | `:SYST:COMM:WLAN:MAC?` | `""` until known |
| `WIFI_IP` | `:SYST:COMM:WLAN:IPAD?` | `""` for no address |
| `WIFI_RSSI_DBM` | `:SYST:COMM:WLAN:RSSI?` | `9.91E+37` for no value |
| `NET_PORT` | `:SYST:COMM:WLAN:PORT?` | |
| `NET_CLIENT` | `:SYST:COMM:WLAN:CLI?` | `""` for no host |
| `WIFI_PENDING` | `:SYST:COMM:WLAN:PEND?` | |
| `TX_DROPPED` | `:DIAG:TXDR?` | |

One line can read many values: `:FREQ?;:PULS:WIDT?;DOUB:DEL?;:OUTP?;:DIAG:HARD?`.
