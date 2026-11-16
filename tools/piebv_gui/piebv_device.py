"""PiEBV device link: transports, a thread-safe protocol client and a STATUS parser.

Transports (all carry the same line protocol, src/protocol.cpp):
  * a serial port: "COM7", "/dev/ttyACM0", "/dev/cu.usbmodem1101"  (needs pyserial)
  * any pyserial URL, e.g. "socket://piebv.local:4242" -- the board's network (Wi-Fi)
    link, which serves the same protocol over TCP  (needs pyserial)
  * "sim": the PiEBV simulator (tools/piebv_sim), which runs the real protocol code on
    this computer  (no pyserial needed)

Protocol rules the client relies on (see tools/piebv_example.py for the same notes):
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
SIM_EXE = os.path.join(HERE, "..", "piebv_sim", "piebv_sim.exe" if os.name == "nt" else "piebv_sim")


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
            raise LinkError("simulator not built: %s (see tools/piebv_sim/README.md)" % exe)
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
    """[{device, description, piebv}] -- empty if pyserial is missing."""
    try:
        import serial.tools.list_ports
    except ImportError:
        return []
    out = []
    for p in serial.tools.list_ports.comports():
        piebv = p.vid == PICO_VID and p.pid in PICO_PIDS
        out.append({"device": p.device, "description": p.description or "", "piebv": bool(piebv)})
    out.sort(key=lambda d: (not d["piebv"], d["device"]))
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


# ---------------------------------------------------------------- Wi-Fi set-up values
_WIFI_LINE = re.compile(r"^\s*WIFI\??\s+(\S+)\s*(.*)$", re.I)  # sub-command, value


def wifi_check(ssid, passphrase):
    """None, or why the board cannot take this network name / passphrase (None = not
    sent). The limits are the firmware's (src/wifi_config.h, src/protocol.cpp); the link
    is ASCII, so other characters need a serial terminal."""
    for what, text, lo, hi in (("network name", ssid, 1, 32), ("passphrase", passphrase, 8, 63)):
        if text is None or (what == "passphrase" and text == ""):
            continue
        if not lo <= len(text) <= hi:
            return "the %s must have %d to %d characters" % (what, lo, hi)
        if any(not 32 <= ord(c) <= 126 for c in text):
            return "the %s can hold only printable ASCII characters here" % what
        if text != text.strip():
            return "the %s cannot start or end with a space" % what
        if "disarm" in text.lower():
            return "the %s cannot contain the letters 'disarm': the board reads them as DISARM" % what
    return None


# ---------------------------------------------------------------- client
class PiEBV:
    """Thread-safe PiEBV client. One command is in flight at a time (except DISARM)."""

    def __init__(self, target, log_size=2000):
        self.target = target
        self.link = open_transport(target)
        # Re-entrant: a sequence of commands (wifi_setup) holds it from its first command
        # to its last, so another request cannot put a command in between.
        self._cmd = threading.RLock()
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

    def _exchange(self, line, done, timeout=1.5, log=True, shown=None):
        """Send `line`, collect reply lines until done(lines) is true. Stray DISARM acks
        and boot banners are logged, not returned. log=False keeps the command and its
        reply out of the console log (the GUI's once-a-second STATUS poll). `shown` is
        the text the console log gets in place of the line (a passphrase stays out of it)."""
        with self._cmd:
            if log and shown is None:
                self._send(line)
            else:
                if log:
                    self._record(">", shown)
                self.link.write_line(line)
            got = []
            deadline = time.monotonic() + timeout
            while True:
                left = deadline - time.monotonic()
                if left <= 0:
                    # `shown`, not `line`: the message reaches the page and the log.
                    raise LinkError("no reply to %r (wrong port, or DTR off?)" % (shown or line))
                r = self.link.readline(left)
                if r is None:
                    continue
                if r == "OK ARMED=0" and not line.upper().startswith("DISARM"):
                    self._record("<", r)
                    continue  # a DISARM acknowledged while this command was in flight
                if r.startswith("PiEBV delay generator ready"):
                    self._record("<", r)
                    continue  # the board rebooted (e.g. watchdog): banner
                if log:
                    self._record("<", r)
                got.append(r)
                if done(got):
                    return got

    # ---- commands
    def identify(self):
        return self._exchange("ID?", lambda g: g[-1].startswith("PiEBV delay generator ("))[-1]

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

    def _wifi_exchange(self, line, sub, shown=None):
        """One WIFI set-up command (`sub`: SSID, PASS, ON, OFF or CLEAR) and its one
        reply line: the OK line of that sub-command, or any ERR line."""
        ok = {"SSID": "OK WIFI SSID=", "PASS": "OK WIFI PASS="}.get(sub, "OK WIFI=")

        def done(g):
            return g[-1].startswith(ok) or g[-1].startswith("ERR")

        # The radio's power-up and the flash write can take seconds (the firmware
        # allows 8 s for them).
        timeout = 12.0 if sub in ("ON", "OFF", "CLEAR") else 1.5
        return self._exchange(line, done, timeout=timeout, shown=shown)[-1]

    def wifi_setup(self, action, ssid=None, passphrase=None):
        """The board's Wi-Fi set-up (USB link only; the board refuses it over the network).
        action "on": join the network `ssid` and store the set-up. `passphrase` is its
        passphrase, or "" for an open network. None is permitted only for the network
        that the board has in use: the board then keeps its passphrase. "off": radio
        off. "clear": off, and erase the name and the passphrase.
        Returns (ok, reply lines). Raises ValueError for a value the board cannot take."""
        if action not in ("on", "off", "clear"):
            raise ValueError("unknown Wi-Fi action")
        if action == "on":
            if ssid is None:
                raise ValueError("the network name is missing")
            why = wifi_check(ssid, passphrase)
            if why:
                raise ValueError(why)
        with self._cmd:  # one sequence: no other command goes in between
            steps = []  # (line, sub-command, text for the console log or None)
            if action != "on":
                steps.append(("WIFI " + action.upper(), action.upper(), None))
            elif passphrase is None:
                # The board never tells its passphrase. WIFI ON alone joins the network
                # in use with it, but it would also take a name or passphrase that was
                # sent before and not joined (WIFI_PENDING=1), so that must not be there.
                system = self.status(log=False)["system"]
                if ssid != system.get("WIFI_SSID", ""):
                    raise ValueError("type the passphrase of this network, or choose an open network")
                if system.get("WIFI_PENDING", "0") != "0":
                    raise ValueError("the board holds a name or passphrase that was sent but not joined: "
                                     "type the passphrase of this network, or choose an open network")
                steps.append(("WIFI ON", "ON", None))
            else:
                # WIFI SSID discards a passphrase sent earlier; WIFI PASS is always sent.
                steps.append(("WIFI SSID " + ssid, "SSID", None))
                steps.append(("WIFI PASS " + passphrase if passphrase else "WIFI PASS", "PASS",
                              "WIFI PASS ********" if passphrase else None))
                steps.append(("WIFI ON", "ON", None))
            replies = []
            for line, sub, shown in steps:
                reply = self._wifi_exchange(line, sub, shown)
                replies.append(reply)
                if not reply.startswith("OK "):
                    return False, replies
            if action == "on":
                # The board names what it joined: it must be what was asked for.
                want_pass = "SET" if passphrase or passphrase is None and system.get("WIFI_PASS") == "SET" else "NONE"
                m = re.match(r"^OK WIFI=ON SSID=(.*) PASS=(SET|NONE) SAVED=", replies[-1])
                if not m or m.group(1) != ssid or m.group(2) != want_pass:
                    replies.append("ERR the board joined another set-up than the one asked for: check it and join again")
                    return False, replies
            return True, replies

    def raw(self, line, quiet=0.25, timeout=3.0):
        """Any command; returns every line until the output goes quiet. The WIFI set-up
        commands have one reply line and are waited for by it (WIFI ON, OFF and CLEAR
        for as long as the radio start takes), and a passphrase typed as WIFI PASS is
        kept out of the console log."""
        m = _WIFI_LINE.match(line)
        sub = m.group(1).upper() if m else ""
        masked = "WIFI PASS ********" if sub.startswith("PASS") and (m.group(2) or sub != "PASS") else None
        # A line that holds the letters "disarm" is answered as DISARM, and one that is
        # too long as "ERR line too long": those take the plain path below.
        if sub in ("SSID", "PASS", "ON", "OFF", "CLEAR") and "disarm" not in line.lower() and len(line) <= 95:
            return [self._wifi_exchange(line, sub, masked)]
        with self._cmd:
            if masked:
                self._record(">", masked)
                self.link.write_line(line)
            else:
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
