# PiEBV web GUI

A small local web server that drives the PiEBV over USB serial or over its network link. The browser page does everything
the serial commands do, and draws the timing of one PIV pulse pair above the settings.

- **Everything shown comes from the board.** The chart, the edge table and every "realized …" line
  come from the board's replies to its SCPI queries (`:FREQ?`, `:PULS:WIDT?`, …). These replies
  give the realized values (whole PIO cycles), so the page shows what the hardware produces after
  rounding, not the values you typed.
- **It uses the ordinary firmware.** The page sends the same SCPI commands that you can type
  (`:FREQ 15HZ`, `:PULS:DOUB:DEL 10000NS`, …), so no firmware change is necessary. The command
  list is in [docs/COMMANDS.md](../../docs/COMMANDS.md).
- **One server, many tabs.** The server owns the serial port, and any number of browser tabs can
  share it.

## Running

Needs Python 3.8 or newer. For a real board you also need pyserial:

```
python -m pip install pyserial
```

Then, from the repository root:

```
python tools/piebv_gui/piebv_gui.py --connect auto      # finds the PiEBV on USB, opens http://127.0.0.1:8765
python tools/piebv_gui/piebv_gui.py                     # choose the port on the page instead
python tools/piebv_gui/piebv_gui.py --connect COM7      # or /dev/ttyACM0, /dev/cu.usbmodem1101
python tools/piebv_gui/piebv_gui.py --connect sim       # no hardware: the simulator (see below)
```

| Option | Meaning |
|---|---|
| `--connect TARGET` | Connect at start-up. `TARGET` is one of: a serial port; `auto` (the first USB device with the Pico's ID `2E8A`); `sim`; or a [pyserial URL](#network-wi-fi). Without it, pick the device on the page. |
| `--http-port N` | Web server port (default 8765). |
| `--host ADDR` | Interface to serve on. Default `127.0.0.1`: this computer only. See [Safety](#safety). |
| `--no-browser` | Don't open a browser window. |

**Only one program can have the serial port open at a time.** Close PuTTY, `pio device monitor`
and similar tools before connecting. The GUI opens the port at 115200 baud and asserts DTR. It
never uses 1200 baud, which would reboot the Pico into its bootloader.

## The page

| Part | What it does |
|---|---|
| Header | Device list, with PiEBV boards marked; **↻** rescans. **Connect**/**Disconnect**. The board's identity (from `*IDN?`) and, under it, a system line: clock, why it last restarted, crash restarts (watchdog), the watchdog timeout and reply bytes dropped (from the `:DIAG:` queries). A crash restart or dropped replies is flagged ⚠. A board restart that the GUI sees is flagged too: see [Board restarts](#board-restarts). Then the theme button, the **ARMED** indicator and **DISARM**. |
| Arming | A short strip above the charts: **ARM** and **DISARM**, with the firmware's arming state (`:OUTP?`), the start hold-off (`:OUTP:PEND?`), the hardware status (`:DIAG:HARD?`) and the camera sync clock (`:SOUR:SYNC:FREQ?`). |
| Timing chart | One pulse pair, with Laser 1, Laser 2, marker and pixel reset on a common time axis. (The sync clock runs continuously, so it is not drawn.) Time 0 is the CH1 rising edge. **Pulses** zooms to the two laser pulses. **Pulses + reset window** also shows the window of `:PIX:LEAD` and `:PIX:LAG`. Hover for the level of every signal at that instant. |
| Sequence chart | Three consecutive pairs, with the marker and the pixel-reset gate between pairs. |
| Edge table | Every edge's realized time after CH1, in ns and in PIO cycles (6.667 ns at 150 MHz, 3.333 ns at 300 MHz with the clock jumper). |
| Timing settings | Pair rate (`:FREQ`), pulse width (`:PULS:WIDT`), Δt (`:PULS:DOUB:DEL`), outputs split or combined (`:OUTP:COMB`), and the camera marker width (`:MARK:WIDT`), with one **Apply**. The 1 MHz camera sync clock is fixed by the firmware and is not an adjustable setting. |
| Pixel-reset gate | Gate (`:PIX:GATE OFF`, `ARM` or `ALW`), release before CH1 (`:PIX:LEAD`), reset after the last pulse (`:PIX:LAG`), and the reset window that the board calculates (`:PIX:WIND?`). |
| Network (Wi-Fi) | The board's Wi-Fi link: its state, address, signal level, MAC address and connected host, and the set-up (network name, passphrase, **Join and store**, **Switch off**, **Erase set-up**). See [Network (Wi-Fi)](#network-wi-fi). For a firmware image without a radio (Pico 2), the card shows the state `UNAVAILABLE` only. |
| Console | Full width at the bottom, and resizable by dragging its bottom edge. Shows every command and reply on the link, and the entries of the board's error queue. You can type any SCPI command here: see [Console](#console). The page's own once-a-second status poll is kept out of the console. |

### Board restarts

A board that restarts (power loss, watchdog, reset button, firmware upload) is DISARMED and
has the default settings again. The GUI finds such a restart, also when the link was lost
and connected again:

- With each status poll, the GUI reads `:DIAG:UPT?`, the time since the board started.
- It compares the value with the last value from the same board (the same `*IDN?` reply) plus
  the time between the two reads. A value more than 2 s too small is a restart.
- The GUI then writes a line that starts with `!` in the console, and the system line shows
  **⚠ board restarted (seen at <time>, reset cause <cause>)** until the GUI disconnects from
  that board.

Limits:
- The GUI keeps the last values in memory only. After a restart of the GUI itself, it cannot
  see a board restart that occurred before.
- A firmware upload with a different version changes the `*IDN?` reply, so the GUI sees a
  different board, and does not report the restart.
- Because of the 2 s slack, a second restart is not seen if it occurs less than 2 s after
  the board started.

**Entering values**
- Type into a field and press **Enter** (that field only) or **Apply** (the whole card).
- Units are optional:

  | Kind | Plain number | With units |
  |---|---|---|
  | Times | ns | `10us`, `2.5 ms`, `100ns` |
  | Frequencies | Hz | `20k`, `1 MHz` |

- The page rounds the value to whole ns or Hz and sends it with a unit suffix, for example
  `:PULS:WIDT 27NS` or `:FREQ 400HZ`.
- The field then shows the realized value: the board rounds to whole PIO cycles. For example,
  `27ns` becomes 26.667 ns (4 cycles of 6.667 ns).
- A field you have changed but not applied is outlined until you apply it.
- **Rejected settings.** The page sends each setting with `:SYST:ERR?` in the same message, for
  example `:PULS:WIDT 27NS;:SYST:ERR?`. If the board rejects the value, the error text appears
  under the field, for example *Settings conflict: DELAY + WIDTH must fit in the period … (error
  -221)*. The old value stays in force.
- **Applying several changes at once.** When a card holds changes that depend on each other (for
  example a longer Δt and a lower pair rate together), Apply retries in another order, so a
  valid combination is accepted whichever order it was typed in.

**Arming**
- **ARM needs two clicks within 3 s**, and the button reads *Click again to ARM* between them.
  The page then sends `:OUTP ON;:SYST:ERR?;:OUTP?;:OUTP:PEND?` and shows the result.
- **DISARM is one click, or Esc anywhere on the page**, even while typing in a field. The page
  sends `DISARM` and then reads `:OUTP?` to make sure that the outputs are disarmed.

## Console

- Type one SCPI program message and press **Enter**. The page sends it as you typed it. Examples:

  | Line | Reply in the console |
  |---|---|
  | `*IDN?` | `PiEBV,<model>,<serial>,<firmware>` |
  | `:PULS:WIDT 200NS` | Nothing: a setting gives no reply. |
  | `:PULS:WIDT?;DOUB:DEL?;:FREQ?` | `2.000000000E-07;1.000000000E-05;1.000000000E+03` (one line) |
  | `FOO` | `-113,"Undefined header;FOO"` (an entry of the error queue, in red) |

- After each line, the page reads the board's error queue (`:SYST:ERR?`) until it is empty, and
  shows each entry under the line. It does not show these `:SYST:ERR?` reads.
- The page waits for the replies with a sync message (`*OPC?`). A setting thus gives no time-out.
  For a line with `WLAN`, the page waits up to 12 s, because the radio start can take some
  seconds.
- Times are in seconds and frequencies in hertz. Use a suffix for other units: `100NS`, `10US`,
  `2KHZ`.
- The page keeps `:SYST:ECHO` off on its link. It sends `:SYST:ECHO OFF` when it connects and
  after each console line that has `ECHO` in it.
- A line can have up to 255 bytes. The page refuses a longer line, and a line with control
  characters.
- A line that sets a passphrase (a header word `PASS` or `PASSWORD`, any case and any form) is
  shown with `********` from that word to the end of the line. This applies to the console, to
  the log at `/api/log`, to the board's error texts for that line, and to a line that the GUI
  server refuses.

## Safety

- **Closing the page, disconnecting or stopping the server does not disarm.** Only DISARM does,
  from the page or from any other host. This matches the firmware, where closing the serial port
  does not disarm either. Your hardware interlock on J11 is the safety layer.
- **DISARM is never queued.** It is written to the board at once, even while another command is
  waiting for its reply. The firmware acts on the six letters `DISARM` as soon as they arrive,
  anywhere in the input. It gives no reply: the page reads `:OUTP?` after it.
- **An ARM that waited does not go out after a DISARM.** An ARM can wait for the link behind a
  slow command (for example a Wi-Fi start). If a DISARM is sent during that wait, the page does
  not send the ARM. The console shows *ARM not sent: a DISARM came after it*. The same rule
  applies to a console line that has `OUTP` in it.
- **`ARMED` (`:OUTP?` 1) does not mean the outputs are live.** The indicator shows the firmware's arming state.
  The firmware cannot see the J11 interlock or the 12 V laser-rail power gate.
- **Serve to this computer only unless you trust the network.** The server has no login, so
  anyone who can reach the page can ARM the lasers. It listens on `127.0.0.1` by default.
  `--host 0.0.0.0` exposes it to the network and prints a warning.
- **Commands typed in the console are sent as they are.** That includes `:OUTP ON`, with no
  second click, just as in a serial terminal.

## Simulator

`--connect sim` (or *Simulator* in the device list) runs [`tools/piebv_sim`](../piebv_sim). It
compiles the firmware's real `src/protocol.cpp` and `src/pulse_timing.h` for this computer, so
every reply, error message and realized value is the one the board would print. Build it once
(see its README). The option appears in the device list only when the simulator binary exists.
`--connect sim:PATH` starts another program that speaks the protocol on its standard input and
output, for example a test wrapper around the simulator.

## Network (Wi-Fi)

The device layer accepts any [pyserial URL](https://pyserial.readthedocs.io/en/latest/url_handlers.html),
and the firmware serves the same SCPI protocol on TCP port 4242 when its Wi-Fi link is set up:

```
python tools/piebv_gui/piebv_gui.py --connect socket://192.168.1.37:4242
```

or type the URL into *Other port or URL…* in the device list. Use the address that the card
shows (`:SYST:COMM:WLAN:IPAD?`), or `piebv.local` where mDNS works.

**Set-up in the page.** Connect the page to the board's **USB serial port**, with the lasers
DISARMED. In the *Network (Wi-Fi)* card:

1. Type the network name and the passphrase. For a network without a passphrase, tick *Open
   network*.
2. Click **Join and store**. The page sends `:SYST:COMM:WLAN:SSID "<name>"`,
   `:SYST:COMM:WLAN:PASS "<passphrase>"` (`""` for an open network) and `:SYST:COMM:WLAN ON`.
   It reads the error queue after each step and stops at the first error.
3. Wait until *State* shows `CONNECTED`. *Address* then shows the URL to connect to.

- For the network that the board has in use, an empty passphrase field keeps its passphrase
  (the placeholder shows *unchanged*). The page then sends only `:SYST:COMM:WLAN ON`. For any
  other name, type the passphrase or tick *Open network*: a passphrase is never carried over to
  another network. The same applies when the board holds a name or passphrase that was sent but
  not joined (`:SYST:COMM:WLAN:PEND?` gives 1, for example after a command in the console).
- After the join, the page reads `:SYST:COMM:WLAN:SSID?;SEC?`. The name and the security
  (`WPA2` or `NONE`) must be what you asked for.
- If the board refuses the join, the fields keep what you typed. Click **Join and store** again.
- **Switch off** sends `:SYST:COMM:WLAN OFF`. **Erase set-up** sends `:SYST:COMM:WLAN:CLE`.
- The result is shown under the buttons. Error 101 *Set-up not stored* is a warning: the set-up
  is in use but not stored (see [the limits](../../docs/CONNECTING.md#limits)). The page then
  shows *In use, but not stored* and the reason.
- The passphrase is shown as `********` in the console, also when you type a
  `:SYST:COMM:WLAN:PASS` command there. The page clears the field after a join and when the link
  closes. The board does not send it back.
- The buttons and the Enter key do nothing while ARMED, and while the page is connected over the
  network (a `socket://` address): the board changes its Wi-Fi set-up only over USB (over the
  network it gives error -203 *Command protected*) and only while DISARMED.
- While the board starts its radio (some seconds), the page shows no new state. **DISARM** is
  still written to the board at once.
- The name and the passphrase can hold printable ASCII characters only in the page. They cannot
  start or end with a space, and cannot contain the letters `disarm` in sequence.
- The same set-up is possible with the `:SYST:COMM:WLAN` commands in the console or a serial
  terminal: see
  [Network (Wi-Fi)](../../docs/CONNECTING.md#network-wi-fi).
- The board takes one network host at a time. Close other connections first.
- The link has no password and no encryption, and a lost link does not disarm.
- Tested: pyserial's `socket://` handler with the simulator through a TCP bridge. Not yet tested:
  the link to a board.

## Files

| File | Contents |
|---|---|
| `piebv_gui.py` | Web server: static files plus the JSON API below. Start here. |
| `piebv_device.py` | Device link: serial/URL and simulator transports, a thread-safe SCPI client (`PiEBV`) and the status read-out. Usable on its own from Python. |
| `static/index.html`, `static/style.css`, `static/app.js` | The page. No build step and no external libraries; it works offline. |

JSON API (same origin, used by the page):

| Route | Does |
|---|---|
| `GET /api/state` | Connection state, the identity (`*IDN?`) and the status: the settings with their realized values, and the system and Wi-Fi state |
| `GET /api/ports` | Serial ports (PiEBV boards flagged) and whether the simulator is built |
| `GET /api/log?since=N` | Console entries after sequence number `N`. `dir` is `>` (sent) or `<` (received, or an error-queue entry). |
| `POST /api/connect` `{"target": "COM7"}` | Connect (`sim`, a port or a URL) |
| `POST /api/disconnect` | Close the link (does not disarm) |
| `POST /api/apply` `{"settings": {"FREQ": 15, "DELAY": 10000}}` | Set adjustable values: `FREQ` in Hz; `WIDTH`, `DELAY`, `MARKERWIDTH`, `PIXLEAD`, `PIXLAG` in ns; `COMBINE` 0 or 1; `PIXGATE` 0, 1 or 2 (`OFF`, `ARM`, `ALW`). Returns the error-queue entry for each setting (`0,"No error"` = accepted). |
| `POST /api/arm`, `POST /api/disarm` | Arm / disarm |
| `POST /api/command` `{"line": "*IDN?"}` | Any one program message; returns every reply line and then the error-queue entries |
| `POST /api/wifi` `{"action": "on", "ssid": "Lab Network", "passphrase": "…"}` | Wi-Fi set-up. `action` is `on`, `off` or `clear`. For `on`, leave out `passphrase` to keep the board's one, or send `""` for an open network. Returns `ok`, `warning` (in use, but not stored) and the result text. |
