# Connecting

This page tells you how to connect a computer to the board: the USB serial port, the web GUI, Python
scripts, and the status of wireless control. This page is part of the PiEBV documentation. The
overview and the list of all pages are in the [README](../README.md).

## USB serial

Use the **Pico's micro-USB port**; J17 carries power only. The Pico appears as a standard USB serial
port and needs no driver on Windows 10/11, macOS or Linux.

| OS | Where to find the port |
|---|---|
| Windows | Device Manager → Ports (COM & LPT) → `USB Serial Device (COMn)` |
| macOS | `/dev/cu.usbmodem*` |
| Linux | `/dev/ttyACM*` (your user may need to be in the `dialout` group) |
| Any | `pio device list` |

The port's USB ID is `2E8A:F00F` with the `pico2w` firmware and `2E8A:000F` with the `pico2`
firmware.

**Terminal settings**

| Setting | Value |
|---|---|
| Baud rate | Anything **except 1200**, which restarts the Pico into its bootloader. 115200 is usual. |
| Line ending | CR, LF or CR+LF: all work |
| Flow control | None |
| Local echo | **On**: the firmware does not echo |
| DTR | On (the default in PuTTY, Tera Term, screen, minicom, `pio device monitor` and pyserial). With DTR off, commands still run but every reply is thrown away. |

Examples:

```
pio device monitor --echo                 # PlatformIO; add -p COM7 if needed
screen /dev/ttyACM0 115200                # Linux (macOS: /dev/cu.usbmodem*)
```

PuTTY: connection type Serial, your COM port, speed 115200; under Connection → Serial set Flow
control to None; under Terminal set Local echo to Force on.

The firmware prints a one-line greeting only if a terminal is already open in the first 1.5 s after
a restart. A terminal opened later sees nothing until you type something: try `ID?`.

## Web GUI

[`tools/piebv_gui`](../tools/piebv_gui) is a browser page for the same commands. It shows every setting
with the value the hardware actually produces, and draws the timing of one pulse pair (and of three
pairs in a row) from the board's own report. It runs a small web server on your computer; the only
thing to install is pyserial:

```
python -m pip install pyserial
python tools/piebv_gui/piebv_gui.py --connect auto        # then open http://127.0.0.1:8765
```

- It opens the Pico's serial port itself, so close any other terminal first.
- Esc or the DISARM button disarms from anywhere on the page. Closing the page does not disarm.
- `--connect sim` runs it against [`tools/piebv_sim`](../tools/piebv_sim) instead: the firmware's real
  command code, built for your computer, with no board needed.

See [its README](../tools/piebv_gui/README.md) for the full guide.

## Scripting (Python)

[`tools/piebv_example.py`](../tools/piebv_example.py) is a complete example using pyserial
(`python -m pip install pyserial`). It finds the port, reads `STATUS`, sets the timing, arms, and
always disarms at the end, however the script stops:

```
python tools/piebv_example.py --freq 15 --width 100 --delay 10000 --seconds 5
```

The core of a host script looks like this:

```python
import serial

ser = serial.Serial("COM7", 115200, timeout=1)       # DTR is on by default

def cmd(line):
    ser.write((line + "\n").encode())
    return ser.readline().decode().strip()           # one-line replies

def status():
    ser.write(b"STATUS\n")
    out = {}
    while True:
        line = ser.readline()
        if not line:
            raise TimeoutError("no STATUS reply (wrong port, or DTR off?)")
        key, _, value = line.decode().strip().partition("=")
        out[key] = value
        if key == "TX_DROPPED":                      # always the last STATUS line
            return out

try:
    assert status()["HW"] == "OK"
    for c in ("WIDTH 100", "DELAY 10000", "FREQ 15"):
        reply = cmd(c)
        if not reply.startswith("OK "):
            raise RuntimeError(reply)                # e.g. "ERR DELAY rejected: DELAY must leave ..."
    print(cmd("ARM"))                                # pulses start after <= 1 s hold-off
    ...                                              # acquire
finally:
    print(cmd("DISARM"))                             # -> "OK ARMED=0"
```

Rules for host scripts:
- **Send `ARM` after every restart.** The board always comes back DISARMED. Check `RESET=` in
  `STATUS` first: if it says `WATCHDOG`, the firmware crashed and restarted itself, so stop and ask
  the operator before arming again.
- **Read `STATUS` by key, not by line position.** New keys may be added. `TX_DROPPED` is always the
  last line.
- **Closing the port does not disarm.** Always send `DISARM` yourself.
- Every reply line ends in CR+LF, `HELP` included. (Firmware up to commit `5dfedd5` sent `HELP`'s
  inner lines with LF only, so a host that also talks to older boards should split on LF and strip
  any trailing CR.)

## Wireless (Wi-Fi / Bluetooth)

**Not supported by the current firmware.** The board talks over USB only, and the Pico 2 W's radio
is never switched on. The Pico 2 W is fitted only because it is easier to buy than the plain Pico 2.

Wireless control is possible as a future option, as firmware-only work:
- switch on the radio;
- carry the same text commands over the wireless link;
- add a login;
- decide whether `ARM` may be sent wirelessly (`DISARM` must always stay reachable).

The [web GUI](#web-gui) would need no change: it already accepts a network address such as
`socket://piebv.local:4242` wherever it takes a serial port.

The board has solid copper under the module's antenna, which shortens the radio's range. That is
fine for the intended short range (a few metres, like Bluetooth), so no board change is needed.
