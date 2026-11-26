#!/usr/bin/env python3
"""Minimal PiEBV host example (SCPI over USB serial). Requires pyserial: python -m pip install pyserial

    python piebv_example.py                 # auto-detect the Pico, default timing
    python piebv_example.py --port COM7 --freq 15 --width 100 --delay 10000 --seconds 5
    python piebv_example.py --port socket://192.168.1.37:4242    # the network (Wi-Fi) link

What it does: open the Pico's USB serial port (or a pyserial URL), check *IDN?, read the
diagnostics, set :FREQ / :PULS:WIDT / :PULS:DOUB:DEL (each one checked with :SYST:ERR?),
arm with :OUTP ON, wait, and DISARM in a `finally` block so the lasers are disarmed
however the script ends.

Protocol notes (see src/protocol.h and docs/COMMANDS.md):
  * One program message per line (CR, LF or CRLF), up to 255 characters. Message units
    are separated by ';'. The responses of the queries of one message come on one line,
    joined by ';', and end in CRLF.
  * A setting gives no reply. An error goes to the error queue: read it with :SYST:ERR?,
    which answers <code>,"<text>" (0,"No error" when the queue is empty).
  * Times are in seconds and frequencies in hertz; a suffix (NS, US, MS, HZ, KHZ, MHZ)
    gives another unit. Queries return the REALIZED value (whole PIO cycles) in NR3
    form, e.g. 1.000000000E-07.
  * Each setting is validated together with the others that are already set (laser
    DELAY <= 1/FREQ - 2 x WIDTH so pulse pairs stay separated), so the order of changes can
    matter. A rejected change leaves the running configuration untouched, so
    set_timing() below simply retries rejected settings after the others.
  * The board boots DISARMED and after every reset; :OUTP ON must be sent again.
  * DISARM anywhere in the input disarms at once and gives no reply. Confirm with :OUTP?.
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

# name -> (SCPI header, suffix of the value): times in ns, the frequency in Hz.
SETTINGS = {"FREQ": (":FREQ", "HZ"), "WIDTH": (":PULS:WIDT", "NS"), "DELAY": (":PULS:DOUB:DEL", "NS")}


def find_port():
    for p in serial.tools.list_ports.comports():
        if p.vid == PICO_VID and p.pid in PICO_PIDS:
            return p.device
    raise SystemExit("No PiEBV found (USB VID 0x2E8A, PID 0xF00F/0x000F). Use --port.")


class PiEBV:
    def __init__(self, port, timeout=1.0):
        # Baud is ignored by USB CDC; any value except 1200 is fine. DTR must be asserted,
        # otherwise the firmware treats the host as absent and drops every reply.
        self.ser = serial.serial_for_url(port, baudrate=115200, timeout=timeout)
        if hasattr(self.ser, "dtr"):
            self.ser.dtr = True
        time.sleep(0.1)
        self.ser.reset_input_buffer()  # discard replies that a previous host left unread
        # SYST:ECHO (not SCPI) is kept per link across host connections: switch it off,
        # so that settings give no reply. *CLS empties the error queue.
        self.send(":SYST:ECHO OFF;*CLS")

    def close(self):
        self.ser.close()

    def send(self, line):
        self.ser.write((line + "\n").encode("utf-8"))
        self.ser.flush()

    def readline(self):
        raw = self.ser.readline()
        if not raw:
            raise TimeoutError("no reply from PiEBV")
        return raw.decode("utf-8", "replace").strip()

    def query(self, message):
        """Send a message of queries; return their responses (split at ';')."""
        self.send(message)
        return self.readline().split(";")  # no string response below holds a ';'

    def check(self, message):
        """Send a setting with :SYST:ERR? in the same message. Returns (ok, error entry)."""
        self.send(message + ";:SYST:ERR?")
        reply = self.readline()  # the whole line: the error text can hold a ';'
        return reply.startswith("0,"), reply

    def identify(self):
        idn = self.query("*IDN?")[0]
        if not idn.startswith("PiEBV,"):
            raise RuntimeError("not a PiEBV: " + idn)
        return idn  # PiEBV,<model>,<serial>,<firmware>

    def status(self):
        """A few read-outs, as a dict (realized values: seconds, hertz)."""
        names = ["FREQ", "WIDTH", "DELAY", "ARMED", "RESET", "WDT_RESETS"]
        values = self.query(":FREQ?;:PULS:WIDT?;:PULS:DOUB:DEL?;:OUTP?;:DIAG:RES:CAUS?;:DIAG:WATC:RES?")
        result = dict(zip(names, values))
        result["HW"] = self.query(":DIAG:HARD?")[0].strip('"')  # "OK" or why the outputs do not run
        return result

    def set(self, name, value):
        """Returns (ok, reply): reply is the error-queue entry, e.g.
        '-221,"Settings conflict;DELAY must leave ..."' or '0,"No error"'."""
        header, suffix = SETTINGS[name]
        return self.check(f"{header} {int(value)}{suffix}")

    def set_timing(self, **settings):
        """Apply several settings; retry rejected ones until a pass makes no progress."""
        pending = dict(settings)
        while pending:
            rejected = {}
            for name, value in pending.items():
                ok, reply = self.set(name, value)
                if ok:
                    header = SETTINGS[name][0]
                    print(f"{header} = {self.query(header + '?')[0]}")  # the realized value
                else:
                    rejected[name] = reply
            if len(rejected) == len(pending):
                raise RuntimeError("settings rejected: " + "; ".join(rejected.values()))
            pending = {n: settings[n] for n in rejected}

    def arm(self):
        self.send(":OUTP ON;:OUTP?;:OUTP:PEND?;:SYST:ERR?")
        armed, pending, error = self.readline().split(";", 2)  # the error text can hold a ';'
        if not error.startswith("0,") or armed != "1":
            raise RuntimeError("ARM refused: " + error)  # e.g. -240,"Hardware error;..."
        hold = float(pending)
        return "ARMED" + (f" (laser pulses start after a {hold * 1e3:.0f} ms hold-off)" if hold else "")

    def disarm(self):
        """DISARM is never refused and acts as soon as the six characters arrive. It gives
        no reply, so :OUTP? confirms it ("0" = disarmed)."""
        self.send("DISARM")
        return "OUTP? " + self.query(":OUTP?")[0]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", help="serial port (COM7, /dev/ttyACM0, /dev/cu.usbmodem1101) or a pyserial URL")
    ap.add_argument("--freq", type=int, default=1000, help="pulse-pair rate, Hz")
    ap.add_argument("--width", type=int, default=100, help="laser pulse width, ns")
    ap.add_argument("--delay", type=int, default=10000, help="CH2-after-CH1 delay, ns")
    ap.add_argument("--seconds", type=float, default=5.0, help="how long to stay armed")
    args = ap.parse_args()

    dev = PiEBV(args.port or find_port())
    try:
        print(dev.identify())
        st = dev.status()
        print(st)
        if st["HW"] != "OK":
            raise RuntimeError("hardware: " + st["HW"])
        if st["RESET"] == "WATCHDOG":  # the firmware crashed and rebooted: ask a human
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
