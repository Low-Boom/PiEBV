#!/usr/bin/env python3
"""Minimal PiDG host example (USB serial). Requires pyserial: python -m pip install pyserial

    python pidg_example.py                 # auto-detect the Pico, default timing
    python pidg_example.py --port COM7 --freq 15 --width 100 --delay 10000 --seconds 5

What it does: open the Pico's USB serial port, check ID?, read STATUS into a dict,
set FREQ / WIDTH / DELAY (every reply must start with "OK"), ARM, wait, and DISARM in a
`finally` block so the lasers are disarmed however the script ends.

Protocol notes (see src/protocol.h and src/protocol.cpp):
  * One command per line; CR, LF or CRLF all end a line. Replies end in CRLF.
  * Values are plain decimal integers: FREQ in Hz, WIDTH/DELAY/MARKERWIDTH in ns.
  * Each setting is validated together with the others that are already set (laser
    width/duty limits, DELAY + WIDTH must fit in the period), so the order of changes can
    matter. A rejected change leaves the running configuration untouched, so
    set_timing() below simply retries rejected settings after the others.
  * The board boots DISARMED and after every reset; ARM must be sent again.
  * Never open the port at 1200 baud: that reboots the Pico into BOOTSEL (upload) mode.
  * Closing the port or ending this script does NOT disarm by itself; only DISARM does.
"""
import argparse
import sys
import time

import serial
import serial.tools.list_ports

PICO_VID = 0x2E8A
PICO_PIDS = {0xF00F: "Pico 2 W", 0x000F: "Pico 2"}  # USB IDs of the firmware's serial port


def find_port():
    for p in serial.tools.list_ports.comports():
        if p.vid == PICO_VID and p.pid in PICO_PIDS:
            return p.device
    raise SystemExit("No PiDG found (USB VID 0x2E8A, PID 0xF00F/0x000F). Use --port.")


class PiDG:
    def __init__(self, port, timeout=1.0):
        # Baud is ignored by USB CDC; any value except 1200 is fine. DTR must be asserted,
        # otherwise the firmware treats the host as absent and drops every reply.
        self.ser = serial.Serial(port, 115200, timeout=timeout)
        self.ser.dtr = True
        time.sleep(0.1)
        self.ser.reset_input_buffer()  # discard a boot banner, if one is pending

    def close(self):
        self.ser.close()

    def send(self, line):
        self.ser.write((line + "\n").encode("ascii"))
        self.ser.flush()

    def readline(self):
        raw = self.ser.readline()
        if not raw:
            raise TimeoutError("no reply from PiDG")
        return raw.decode("ascii", "replace").strip()

    def query(self, cmd):
        """Send a command that answers with exactly one line; return that line."""
        self.send(cmd)
        return self.readline()

    def identify(self):
        self.send("ID?")
        while True:  # skip anything left over, e.g. the boot banner
            line = self.readline()
            if line.startswith("PiDG delay generator ("):
                return line

    def status(self):
        """STATUS prints KEY=value lines; the last one is TX_DROPPED=. Parse by key."""
        self.send("STATUS")
        result = {}
        while True:
            line = self.readline()
            key, sep, value = line.partition("=")
            if sep:
                result[key] = value
            if key == "TX_DROPPED":
                return result

    def set(self, name, value):
        """Returns (ok, reply). OK replies look like 'OK DELAY=1003 (actual 1000.000 ns, 150 cyc)'."""
        reply = self.query(f"{name} {int(value)}")
        return reply.startswith(f"OK {name}="), reply

    def set_timing(self, **settings):
        """Apply several settings; retry rejected ones until a pass makes no progress."""
        pending = dict(settings)
        while pending:
            rejected = {}
            for name, value in pending.items():
                ok, reply = self.set(name, value)
                if ok:
                    print(reply)
                else:
                    rejected[name] = reply  # e.g. "ERR FREQ rejected: laser limit: ..."
            if len(rejected) == len(pending):
                raise RuntimeError("settings rejected: " + "; ".join(rejected.values()))
            pending = {n: settings[n] for n in rejected}

    def arm(self):
        reply = self.query("ARM")
        if not reply.startswith("OK ARMED=1"):
            raise RuntimeError(reply)  # e.g. "ERR ARM refused: pulse outputs not running"
        return reply  # may add "(laser pulses start after a N us hold-off)"

    def disarm(self):
        """DISARM is never refused and acts as soon as the six characters arrive."""
        self.send("DISARM")
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            try:
                if self.readline() == "OK ARMED=0":
                    break
            except TimeoutError:
                break
        return self.query("ARM?")  # "ARMED=0" when disarmed


def value_of(status, key):
    """'1000 (actual 1000.000 Hz, period 150000 cyc)' -> '1000'."""
    return status.get(key, "").split(" ", 1)[0]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", help="serial port, e.g. COM7, /dev/ttyACM0, /dev/cu.usbmodem1101")
    ap.add_argument("--freq", type=int, default=1000, help="pulse-pair rate, Hz")
    ap.add_argument("--width", type=int, default=100, help="laser pulse width, ns")
    ap.add_argument("--delay", type=int, default=10000, help="CH2-after-CH1 delay, ns")
    ap.add_argument("--seconds", type=float, default=5.0, help="how long to stay armed")
    args = ap.parse_args()

    dev = PiDG(args.port or find_port())
    try:
        print(dev.identify())
        st = dev.status()
        print({k: value_of(st, k) for k in ("FREQ", "WIDTH", "DELAY", "ARMED", "RESET")})
        if st.get("HW") != "OK":
            raise RuntimeError("HW=" + st.get("HW", "?"))
        if st.get("RESET") == "WATCHDOG":  # the firmware crashed and rebooted: ask a human
            if input("Board was reset by its watchdog. Type ARM to arm anyway: ").strip() != "ARM":
                return 1

        dev.set_timing(WIDTH=args.width, DELAY=args.delay, FREQ=args.freq)
        print(dev.arm())
        time.sleep(args.seconds)  # acquire here
        return 0
    finally:
        try:
            print(dev.disarm())
        except (serial.SerialException, OSError, TimeoutError) as e:
            print(f"WARNING: could not confirm DISARM ({e}). Check the board!", file=sys.stderr)
        dev.close()


if __name__ == "__main__":
    sys.exit(main())
