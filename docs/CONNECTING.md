# Connecting

This page tells you how to connect a computer to the board: the USB serial port, the web GUI, Python
scripts, and the network (Wi-Fi) link. This page is part of the PiEBV documentation. The
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

## Network (Wi-Fi)

A Pico 2 W can also take the commands over Wi-Fi. The board joins an existing network and listens on
**TCP port 4242**. The commands and the replies are the same as on USB, `ARM` included. The radio is
off until you set it up. Bluetooth is not used.

> **Not yet tested on a board.** The network code compiles, and its command handling is tested on a
> computer. Do the [network checks](FIRST_BOARD_CHECKS.md#network-checks) before you rely on it.

**What the network must be:** an open network, or WPA2 with one passphrase for all users
(WPA2-Personal). A network that asks each user for a name and a password (WPA2-Enterprise, e.g.
eduroam) cannot be joined. The network must have a 2.4 GHz band: the Pico 2 W radio does not use
5 GHz. The address comes from DHCP.

### Set-up

Do the set-up on the **USB port**, with the lasers **DISARMED** and the clock jumper J20 open. Use
the *Network (Wi-Fi)* card of the [web GUI](../tools/piebv_gui/README.md#network-wi-fi), or these
commands in a serial terminal:

```
WIFI SSID Lab Network        ->  OK WIFI SSID=Lab Network (not in use yet: send WIFI PASS if it has a passphrase, then WIFI ON)
WIFI PASS correct horse      ->  OK WIFI PASS=SET (not in use yet: send WIFI ON)
WIFI ON                      ->  OK WIFI=ON SSID=Lab Network PASS=SET SAVED=1
WIFI                         ->  WIFI=CONNECTED … WIFI_IP=192.168.1.37 …
```

- Send `WIFI SSID` first, then `WIFI PASS`: a new name discards a passphrase given before it.
  For a network without a passphrase, send no `WIFI PASS`.
- `WIFI ON` joins the network now and at every power-up. The join takes some seconds: send `WIFI`
  until it shows `WIFI=CONNECTED`, and read the address from `WIFI_IP`.
- If `WIFI ON` (or `OFF`, or `CLEAR`) gives an `ERR` reply, the name and the passphrase that you
  sent are discarded. Send them again.
- If the network accepts only known devices, give its administrator the `WIFI_MAC` address. It is
  shown after the first `WIFI ON`.
- `WIFI OFF` switches the radio off, now and at power-up. `WIFI ON` alone then joins the same
  network again. `WIFI CLEAR` also erases the name and the passphrase.
- The name and the passphrase are stored in the Pico's flash as plain text. Anyone who holds the
  board can read them. Send `WIFI CLEAR` before you give the board away.

All `WIFI` commands and replies are in the [command reference](COMMANDS.md#wi-fi-wifi).

### Connecting

Use the address from `WIFI_IP`, or the name `piebv.local` where the computer and the network
support mDNS:

```
python tools/piebv_gui/piebv_gui.py --connect socket://192.168.1.37:4242
```

In a script, `PiEBV("socket://192.168.1.37:4242")` from `tools/piebv_gui/piebv_device.py` works as
with a serial port. For a terminal, use `nc 192.168.1.37 4242`, or PuTTY with connection type *Raw*.

- **One host at a time.** A second connection gets `ERR busy: another host is connected` and is
  closed. A host that disappears without closing frees the link after about 11 s if the connection
  was idle (longer if a reply was on its way; not measured). Until then a new connection gets
  `ERR busy`.
- USB keeps working at the same time. A reply goes only to the link that sent the command.
- The network link has no connect banner. Send `ID?` to check the link.
- Two boards on one network have the same name: use the addresses.

### Limits

- **No password and no encryption.** Every computer that can reach the board on the network can
  send `ARM`. Use a network that only the laboratory's computers can reach. The J11 interlock and
  the 12 V supply gate are not affected by the network.
- **A lost link does not disarm,** as with USB. If the network fails while ARMED, send `DISARM` over
  USB, or stop the lasers in hardware (take the J11 shunt off 1-2, or unplug J17).
- **The network link can delay a `DISARM`.** The firmware acts on `DISARM` when it reads the
  letters. None of the times below was measured on a board. The J11 interlock does not depend on
  the firmware.
  - *A host that reads replies slowly, or not at all:* the replies of a link wait for its host
    only out of a time budget of 250 ms, which comes back slowly (one eighth of the time that
    passes). When it is used up, replies are dropped (`TX_DROPPED`) until the host has caught up.
    The waits of a host that reads at 20 kB/s or faster are not counted while it has sent nothing
    more, so a script that sends a command, reads the reply and sends the next one loses no
    line, also in a tight loop. Each link gives the other link its turn after one slow command.
    In tests on a computer with slow hosts and long queues of commands, a `DISARM` acted after
    at most 0.54 s on its own link, and after at most 1.24 s when the host of the other link
    was slow also.
  - *A radio chip that stops answering:* the firmware tests the radio with one command every 2 s
    while joined, before each new join, and at once after a send that took long. While a test
    runs, and after a failed test, it hands no frame to the radio's driver. The driver holds the
    command loop for a failed test (1 s to 2 s by its time-outs). After the second failed test in
    a row the board switches the radio chip off and shows `WIFI=FAULT`; `WIFI ON` over USB starts
    the radio again. If a wait is longer than the 3 s watchdog period, the watchdog restarts the
    board, DISARMED.
  - *A bad radio link:* the radio's driver can wait about 1 s inside one send, also in the
    background. The firmware then holds further frames back until the next test of the radio.
- **Input that has arrived is run.** When a network host sends a command and then closes or
  resets the connection, the command still runs, `DISARM` included. Its reply is lost if the
  connection was reset.
- The Wi-Fi set-up changes only from USB. From the network, `WIFI SSID`, `PASS`, `ON`, `OFF` and
  `CLEAR` give `ERR WIFI refused: …`. A network host can read the set-up (`WIFI`, `STATUS`), but
  not the passphrase.
- `WIFI ON`, `OFF` and `CLEAR` are refused while ARMED. The radio start and the flash write stop
  the command loop for a time that was not yet measured. No command, `DISARM` included, is read in
  that time. The radio chip is switched off by `WIFI OFF` and `WIFI CLEAR`, and each `WIFI ON`
  that changes the network starts it from power-off.
- With the clock jumper fitted (300 MHz) the set-up is not written to flash (`SAVED=0`): it holds
  until power-off. A set-up that was stored at 150 MHz is used at 300 MHz also.
- A name or a passphrase cannot start or end with a space, and cannot contain the letters
  `disarm` in sequence (in any case): the board reads them as the `DISARM` command. A name must be
  UTF-8 text (plain ASCII is that) without control characters and writing-direction characters, at most 32 bytes long; a name in another encoding, such as
  Shift-JIS, is refused. A passphrase must be printable ASCII characters.
- A host that connects while another host has the link gets `ERR busy`. This also applies to
  your own computer after its old connection was cut without a close: the link is free again
  after about 11 s if the old connection was idle, and later if a reply was on its way.
- A reply that the network host does not take in time is dropped (`TX_DROPPED`), as on USB. At
  most about 4 kB of replies wait for the host's acknowledgement.
- A reply longer than one network packet (`HELP`), and the replies of commands that a host sends
  without waiting for the reply before, can arrive 40 ms to 200 ms late: the board sends the
  rest when the host has acknowledged the first part. (This keeps the board's network memory in
  bounds.)
- After a watchdog restart the radio stays off (`WIFI=OFF (held off after a watchdog reset …)`)
  until `WIFI ON` or a power cycle.
- The pulse timing does not depend on the network: the pulses and the sync clock come from timing
  hardware, not from software. Network traffic can only delay the reply to a command.
- The board has solid copper under the module's antenna, which shortens the radio's range. The
  range was not measured. `WIFI_RSSI_DBM` shows the signal level.
- The `pico2` firmware image (plain Pico 2) has no network link: `WIFI=UNAVAILABLE`.
