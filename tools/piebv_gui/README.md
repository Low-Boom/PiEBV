# PiEBV web GUI

A small local web server that drives the PiEBV over USB serial or over its network link. The browser page does everything
the serial commands do, and draws the timing of one PIV pulse pair above the settings.

- **Everything shown comes from the board.** The chart, the edge table and every "actual …" line
  come from the board's own `STATUS` reply, so they show what the hardware actually produces after
  rounding, not the values you typed.
- **It uses the ordinary firmware.** The page sends the same commands you would type
  (`FREQ 15`, `DELAY 10000`, …), so no firmware change is needed.
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
| Header | Device list, with PiEBV boards marked; **↻** rescans. **Connect**/**Disconnect**. The board's identity and, under it, a system line: clock, why it last restarted, crash restarts (watchdog), the watchdog timeout and reply bytes dropped. A crash restart or dropped replies is flagged ⚠. Then the theme button, the **ARMED** indicator and **DISARM**. |
| Arming | A short strip above the charts: **ARM** and **DISARM**, with the firmware's arming state, start hold-off and `HW` status. |
| Timing chart | One pulse pair, with Laser 1, Laser 2, marker and pixel reset on a common time axis. (The sync clock runs continuously, so it is not drawn.) Time 0 is the CH1 rising edge. **Pulses** zooms to the two laser pulses. **Pulses + reset window** also shows the `PIXLEAD`/`PIXLAG` window. Hover for the level of every signal at that instant. |
| Sequence chart | Three consecutive pairs, with the marker and the pixel-reset gate between pairs. |
| Edge table | Every edge's realized time after CH1, in ns and in PIO cycles (6.667 ns at 150 MHz, 3.333 ns at 300 MHz with the clock jumper). |
| Timing settings | `FREQ`, `WIDTH`, `DELAY` (Δt), `COMBINE`, and the camera marker's `MARKERWIDTH`, with one **Apply**. The 1 MHz camera sync clock is fixed by the firmware and is not an adjustable setting; `STATUS` reports its realized value. |
| Pixel-reset gate | `PIXGATE`, `PIXLEAD`, `PIXLAG`. Hidden if the firmware predates the gate. |
| Network (Wi-Fi) | The board's Wi-Fi link: its state, address, signal level, MAC address and connected host, and the set-up (network name, passphrase, **Join and store**, **Switch off**, **Erase set-up**). See [Network (Wi-Fi)](#network-wi-fi). Hidden if the firmware predates the link. |
| Console | Full width at the bottom, and resizable by dragging its bottom edge. Shows every command and reply on the link. You can type any firmware command here, exactly as in a serial terminal. The camera sync clock is fixed at 1 MHz, not a command. The page's own once-a-second `STATUS` poll is kept out of the console. |

**Entering values**
- Type into a field and press **Enter** (that field only) or **Apply** (the whole card).
- Units are optional:

  | Kind | Plain number | With units |
  |---|---|---|
  | Times | ns | `10us`, `2.5 ms`, `100ns` |
  | Frequencies | Hz | `20k`, `1 MHz` |

- A field you have changed but not applied is outlined until you apply it.
- **Rejected settings.** If the board rejects a value, its own `ERR …` message appears under the
  field, and the old value stays in force.
- **Applying several changes at once.** When a card holds changes that depend on each other (for
  example raising `DELAY` and lowering `FREQ` together), Apply retries in another order, so a
  valid combination is accepted whichever order it was typed in.

**Arming**
- **ARM needs two clicks within 3 s**, and the button reads *Click again to ARM* between them.
- **DISARM is one click, or Esc anywhere on the page**, even while typing in a field.

## Safety

- **Closing the page, disconnecting or stopping the server does not disarm.** Only DISARM does,
  from the page or from any other host. This matches the firmware, where closing the serial port
  does not disarm either. Your hardware interlock on J11 is the safety layer.
- **DISARM is never queued.** It is written to the board at once, even while another command is
  waiting for its reply. The firmware acts on the six letters `DISARM` as soon as they arrive.
- **`ARMED` does not mean the outputs are live.** The indicator shows the firmware's arming state.
  The firmware cannot see the J11 interlock or the 12 V laser-rail power gate.
- **Serve to this computer only unless you trust the network.** The server has no login, so
  anyone who can reach the page can ARM the lasers. It listens on `127.0.0.1` by default.
  `--host 0.0.0.0` exposes it to the network and prints a warning.
- **Commands typed in the console are sent as they are.** That includes `ARM`, with no second
  click, just as in a serial terminal.

## Simulator

`--connect sim` (or *Simulator* in the device list) runs [`tools/piebv_sim`](../piebv_sim). It
compiles the firmware's real `src/protocol.cpp` and `src/pulse_timing.h` for this computer, so
every reply, error message and realized value is the one the board would print. Build it once
(see its README). The option appears in the device list only when the simulator binary exists.

## Network (Wi-Fi)

The device layer accepts any [pyserial URL](https://pyserial.readthedocs.io/en/latest/url_handlers.html),
and the firmware serves the same line protocol on TCP port 4242 when its Wi-Fi link is set up:

```
python tools/piebv_gui/piebv_gui.py --connect socket://192.168.1.37:4242
```

or type the URL into *Other port or URL…* in the device list. Use the address that `WIFI` shows
(`WIFI_IP`), or `piebv.local` where mDNS works.

**Set-up in the page.** Connect the page to the board's **USB serial port**, with the lasers
DISARMED. In the *Network (Wi-Fi)* card:

1. Type the network name and the passphrase. For a network without a passphrase, tick *Open
   network*.
2. Click **Join and store**. The page sends `WIFI SSID`, `WIFI PASS` and `WIFI ON`.
3. Wait until *State* shows `CONNECTED`. *Address* then shows the URL to connect to.

- An empty passphrase field keeps the passphrase that the board already has.
- **Switch off** sends `WIFI OFF`. **Erase set-up** sends `WIFI CLEAR`.
- The board's reply is shown under the buttons. `SAVED=0` means that the set-up is in use but not
  stored (see [the limits](../../docs/CONNECTING.md#limits)).
- The passphrase is shown as `********` in the console. The page does not keep it, and the board
  does not send it back.
- The buttons are disabled while ARMED, and while the page is connected over the network: the
  board changes its Wi-Fi set-up only over USB and only while DISARMED.
- The name and the passphrase can hold printable ASCII characters only in the page. They cannot
  start or end with a space, and cannot contain the letters `disarm` in sequence.
- The same set-up is possible with the `WIFI` commands in the console or a serial terminal: see
  [Network (Wi-Fi)](../../docs/CONNECTING.md#network-wi-fi).
- The board takes one network host at a time. Close other connections first.
- The link has no password and no encryption, and a lost link does not disarm.
- Tested: pyserial's `socket://` handler with the simulator through a TCP bridge. Not yet tested:
  the link to a board.

## Files

| File | Contents |
|---|---|
| `piebv_gui.py` | Web server: static files plus the JSON API below. Start here. |
| `piebv_device.py` | Device link: serial/URL and simulator transports, a thread-safe protocol client (`PiEBV`) and the `STATUS` parser. Usable on its own from Python. |
| `static/index.html`, `static/style.css`, `static/app.js` | The page. No build step and no external libraries; it works offline. |

JSON API (same origin, used by the page):

| Route | Does |
|---|---|
| `GET /api/state` | Connection state and the parsed `STATUS` |
| `GET /api/ports` | Serial ports (PiEBV boards flagged) and whether the simulator is built |
| `GET /api/log?since=N` | Console entries after sequence number `N` |
| `POST /api/connect` `{"target": "COM7"}` | Connect (`sim`, a port or a URL) |
| `POST /api/disconnect` | Close the link (does not disarm) |
| `POST /api/apply` `{"settings": {"FREQ": 15, "DELAY": 10000}}` | Set adjustable values; returns each reply |
| `POST /api/arm`, `POST /api/disarm` | Arm / disarm |
| `POST /api/command` `{"line": "HELP"}` | Any one command; returns every reply line |
| `POST /api/wifi` `{"action": "on", "ssid": "Lab Network", "passphrase": "…"}` | Wi-Fi set-up. `action` is `on`, `off` or `clear`. For `on`, leave out `passphrase` to keep the board's one, or send `""` for an open network. Returns each reply. |
