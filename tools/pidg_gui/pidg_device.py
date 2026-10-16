"""PiDG device link: transports, a thread-safe protocol client and a STATUS parser.

Transports (all carry the same line protocol, src/protocol.cpp):
  * a serial port: "COM7", "/dev/ttyACM0", "/dev/cu.usbmodem1101"  (needs pyserial)
  * any pyserial URL, e.g. "socket://pidg.local:4242" -- the planned Wi-Fi link, once
    the firmware serves the same protocol over TCP  (needs pyserial)
  * "sim": the PiDG simulator (tools/pidg_sim), which runs the real protocol code on
    this computer  (no pyserial needed)

Protocol rules the client relies on (see tools/pidg_example.py for the same notes):
  * one command per line; replies end in CRLF (older firmware: HELP's inner lines in LF only);
  * a DTR-asserted host is required, and the port must never be opened at 1200 baud
    (that reboots the Pico into BOOTSEL mode);
  * DISARM acts as soon as its six letters arrive, anywhere in the input, and answers
    "OK ARMED=0" -- so disarm() writes immediately, without waiting for a command in
    flight, and every reader treats a stray "OK ARMED=0" as unsolicited.
"""
import os
import re
import subprocess
import threading
import time
from collections import deque

PICO_VID = 0x2E8A
PICO_PIDS = {0xF00F: "Pico 2 W", 0x000F: "Pico 2"}
HERE = os.path.dirname(os.path.abspath(__file__))
SIM_EXE = os.path.join(HERE, "..", "pidg_sim", "pidg_sim.exe" if os.name == "nt" else "pidg_sim")


class LinkError(Exception):
    pass


# ---------------------------------------------------------------- transports
class _LineTransport:
    """Byte stream -> lines, fed by a reader thread; readline() waits with a timeout."""

    def __init__(self):
        self._buf = bytearray()
        self._cv = threading.Condition()
        self._wlock = threading.Lock()
        self._closed = False
        self.error = None

    def _feed(self, data):
        with self._cv:
            self._buf += data
            self._cv.notify_all()

    def _fail(self, exc):
        with self._cv:
            self.error = exc
            self._closed = True
            self._cv.notify_all()

    def readline(self, timeout):
        """One line without its terminator, or None on timeout."""
        deadline = time.monotonic() + timeout
        with self._cv:
            while True:
                nl = self._buf.find(b"\n")
                if nl >= 0:
                    line = bytes(self._buf[:nl])
                    del self._buf[:nl + 1]
                    return line.decode("ascii", "replace").rstrip("\r")
                if self._closed:
                    raise LinkError("link closed" + (": %s" % self.error if self.error else ""))
                left = deadline - time.monotonic()
                if left <= 0:
                    return None
                self._cv.wait(left)

    def write_line(self, text):
        with self._wlock:
            self._write((text + "\n").encode("ascii"))

    @property
    def closed(self):
        return self._closed


class SerialTransport(_LineTransport):
    def __init__(self, target):
        super().__init__()
        try:
            import serial  # noqa: F401  (pyserial)
        except ImportError:
            raise LinkError("pyserial is not installed: python -m pip install pyserial")
        import serial
        # Baud is ignored by USB CDC; anything except 1200 is safe (1200 = reboot to BOOTSEL).
        self.ser = serial.serial_for_url(target, baudrate=115200, timeout=0.05)
        if hasattr(self.ser, "dtr"):
            try:
                self.ser.dtr = True  # the firmware drops replies to a host without DTR
            except Exception:
                pass
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def _reader(self):
        try:
            while not self._closed:
                data = self.ser.read(max(1, getattr(self.ser, "in_waiting", 0) or 1))
                if data:
                    self._feed(data)
        except Exception as exc:  # unplugged, port closed
            self._fail(exc)

    def _write(self, data):
        self.ser.write(data)
        self.ser.flush()

    def close(self):
        self._closed = True
        try:
            self.ser.close()
        except Exception:
            pass


class SimTransport(_LineTransport):
    def __init__(self, exe=SIM_EXE):
        super().__init__()
        exe = os.path.normpath(exe)
        if not os.path.exists(exe):
            raise LinkError("simulator not built: %s (see tools/pidg_sim/README.md)" % exe)
        self.proc = subprocess.Popen([exe], stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0)
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def _reader(self):
        try:
            while True:
                data = self.proc.stdout.read(4096)  # unbuffered pipe: returns as soon as any bytes arrive
                if not data:
                    raise LinkError("simulator exited")
                self._feed(data)
        except Exception as exc:
            self._fail(exc)

    def _write(self, data):
        self.proc.stdin.write(data)
        self.proc.stdin.flush()

    def close(self):
        self._closed = True
        try:
            self.proc.stdin.close()
            self.proc.terminate()
        except Exception:
            pass


def list_ports():
    """[{device, description, pidg}] -- empty if pyserial is missing."""
    try:
        import serial.tools.list_ports
    except ImportError:
        return []
    out = []
    for p in serial.tools.list_ports.comports():
        pidg = p.vid == PICO_VID and p.pid in PICO_PIDS
        out.append({"device": p.device, "description": p.description or "", "pidg": bool(pidg)})
    out.sort(key=lambda d: (not d["pidg"], d["device"]))
    return out


def open_transport(target):
    if target == "sim" or target.startswith("sim:"):
        return SimTransport(target[4:] if target.startswith("sim:") and len(target) > 4 else SIM_EXE)
    return SerialTransport(target)


# ---------------------------------------------------------------- STATUS parsing
_NUM = r"-?\d+(?:\.\d+)?"


def parse_value(key, rest):
    """'1000 (actual 1000.000 Hz, period 150000 cyc)' -> dict with value / actual / cycles."""
    d = {"text": rest}
    m = re.match(r"^(-?\d+)(?: \((.*)\))?$", rest)
    if not m:
        return d
    d["value"] = int(m.group(1))
    detail = m.group(2) or ""
    d["detail"] = detail
    if (mm := re.match(r"actual (%s) ns, (\d+) cyc" % _NUM, detail)):
        d.update(unit="ns", actual=float(mm.group(1)), cycles=int(mm.group(2)))
    elif (mm := re.match(r"actual (%s) Hz, period (\d+) cyc" % _NUM, detail)):
        d.update(unit="Hz", actual=float(mm.group(1)), cycles=int(mm.group(2)))
    elif (mm := re.match(r"actual (%s) Hz, divider (\d+)\+(\d+)/(\d+)" % _NUM, detail)):  # I+F/65536 (I+F/256 before)
        d.update(unit="Hz", actual=float(mm.group(1)), divider=int(mm.group(2)) + int(mm.group(3)) / int(mm.group(4)),
                 jitter="jitter" in detail)
    elif detail:
        d["mode"] = detail
    return d


def parse_status(lines):
    """STATUS lines -> {'fields': {...settable, in order}, 'system': {...}, 'pixreset': {...}|None}."""
    fields, system, order = {}, {}, []
    pixreset = None
    seen_armed = False
    for line in lines:
        key, sep, rest = line.partition("=")
        if not sep or not re.match(r"^[A-Z0-9_]+$", key):
            continue
        if key == "ARMED":
            seen_armed = True
            system["ARMED"] = rest.strip() == "1"
        elif key == "PIXRESET":
            if rest.strip() == "off":
                pixreset = {"on": False}
            else:
                m = re.match(r"(%s) ns per period, from CH1 \+ (%s) ns; pixels free (%s) ns" % (_NUM, _NUM, _NUM), rest)
                pixreset = {"on": True, "text": rest}
                if m:
                    pixreset.update(reset_ns=float(m.group(1)), start_ns=float(m.group(2)), free_ns=float(m.group(3)))
        elif not seen_armed:
            fields[key] = parse_value(key, rest)
            order.append(key)
        else:
            system[key] = rest
    return {"fields": fields, "order": order, "system": system, "pixreset": pixreset}


# ---------------------------------------------------------------- client
class PiDG:
    """Thread-safe PiDG client. One command is in flight at a time (except DISARM)."""

    def __init__(self, target, log_size=2000):
        self.target = target
        self.link = open_transport(target)
        self._cmd = threading.Lock()
        self._log = deque(maxlen=log_size)
        self._log_seq = 0
        self._log_lock = threading.Lock()
        self.identity = None
        time.sleep(0.15)
        self._drain(0.2)  # boot banner, if one is pending
        self.identity = self.identify()

    # ---- log (the GUI console)
    def _record(self, direction, text):
        with self._log_lock:
            self._log_seq += 1
            self._log.append((self._log_seq, time.time(), direction, text))

    def log_since(self, seq):
        with self._log_lock:
            return [{"seq": s, "t": t, "dir": d, "text": x} for s, t, d, x in self._log if s > seq], self._log_seq

    # ---- low level
    def _send(self, line):
        self._record(">", line)
        self.link.write_line(line)

    def _drain(self, quiet):
        """Collect lines until `quiet` seconds pass with none (unsolicited output)."""
        while True:
            line = self.link.readline(quiet)
            if line is None:
                return
            self._record("<", line)

    def _exchange(self, line, done, timeout=1.5, log=True):
        """Send `line`, collect reply lines until done(lines) is true. Stray DISARM acks
        and boot banners are logged, not returned. log=False keeps the command and its
        reply out of the console log (the GUI's once-a-second STATUS poll)."""
        with self._cmd:
            if log:
                self._send(line)
            else:
                self.link.write_line(line)
            got = []
            deadline = time.monotonic() + timeout
            while True:
                left = deadline - time.monotonic()
                if left <= 0:
                    raise LinkError("no reply to %r (wrong port, or DTR off?)" % line)
                r = self.link.readline(left)
                if r is None:
                    continue
                if r == "OK ARMED=0" and not line.upper().startswith("DISARM"):
                    self._record("<", r)
                    continue  # a DISARM acknowledged while this command was in flight
                if r.startswith("PiDG delay generator ready"):
                    self._record("<", r)
                    continue  # the board rebooted (e.g. watchdog): banner
                if log:
                    self._record("<", r)
                got.append(r)
                if done(got):
                    return got

    # ---- commands
    def identify(self):
        return self._exchange("ID?", lambda g: g[-1].startswith("PiDG delay generator ("))[-1]

    def status_lines(self, log=True):
        return self._exchange("STATUS", lambda g: g[-1].startswith("TX_DROPPED="), log=log)

    def status(self, log=True):
        return parse_status(self.status_lines(log))

    def set(self, name, value):
        name = name.upper()

        def done(g):
            return g[-1].startswith("OK %s=" % name) or g[-1].startswith("ERR %s" % name)

        reply = self._exchange("%s %d" % (name, int(value)), done)[-1]
        return reply.startswith("OK "), reply

    def apply(self, settings):
        """Apply several settings; rejected ones are retried after the others, until a
        pass makes no progress (each change is validated against the running set)."""
        results, pending = [], dict(settings)
        while pending:
            rejected = {}
            for name, value in pending.items():
                ok, reply = self.set(name, value)
                (results.append((name, True, reply)) if ok else rejected.__setitem__(name, reply))
            if len(rejected) == len(pending):
                results += [(n, False, r) for n, r in rejected.items()]
                break
            pending = {n: settings[n] for n in rejected}
        return results

    def arm(self):
        reply = self._exchange("ARM", lambda g: g[-1].startswith("OK ARMED=") or g[-1].startswith("ERR ARM"))[-1]
        return reply.startswith("OK ARMED=1"), reply

    def disarm(self):
        """Written at once, even while another command is waiting for its reply."""
        self._send("DISARM")
        # Confirm through the normal path (queued behind any command in flight).
        reply = self._exchange("ARM?", lambda g: g[-1].startswith("ARMED="))[-1]
        return reply == "ARMED=0", reply

    def raw(self, line, quiet=0.25, timeout=3.0):
        """Any command; returns every line until the output goes quiet."""
        with self._cmd:
            self._send(line)
            got, deadline = [], time.monotonic() + timeout
            first = self.link.readline(1.5)
            if first is None:
                return got
            self._record("<", first)
            got.append(first)
            while time.monotonic() < deadline:
                r = self.link.readline(quiet)
                if r is None:
                    break
                self._record("<", r)
                got.append(r)
            return got

    def close(self):
        self.link.close()
