"""PiEBV device link: transports, a thread-safe SCPI client and the status read-out.

Transports (all carry the same SCPI protocol, src/protocol.cpp):
  * a serial port: "COM7", "/dev/ttyACM0", "/dev/cu.usbmodem1101"  (needs pyserial)
  * any pyserial URL, e.g. "socket://piebv.local:4242" -- the board's network (Wi-Fi)
    link, which serves the same protocol over TCP  (needs pyserial)
  * "sim": the PiEBV simulator (tools/piebv_sim), which runs the real protocol code on
    this computer  (no pyserial needed); "sim:<path>" runs another executable that
    speaks the protocol on stdin/stdout

Protocol rules the client relies on (src/protocol.h; tools/piebv_example.py has the same notes):
  * one program message per line, up to 255 characters; message units are separated by
    ';'. The responses of the queries of one message come on ONE line, joined by ';',
    and end in CR LF. A setting gives no reply.
  * errors go to a per-link error queue, read with :SYST:ERR? -> <code>,"<text>"
    (0,"No error" when empty). A command error (-1xx, e.g. an unknown header) ends the
    whole message, so a message can give no line at all. Every exchange therefore ends
    with a sync message (SYNC below) whose reply marks the end of the replies.
  * SYST:ECHO ON (per link, not SCPI) adds "OK ..." / "ERR ..." lines: the client
    switches it off when it connects and after any console line that names ECHO.
  * a DTR-asserted host is required, and the port must never be opened at 1200 baud
    (that reboots the Pico into BOOTSEL mode);
  * DISARM acts as soon as its six letters arrive, anywhere in the input, and gives no
    reply (echo off). disarm() writes it at once, without waiting for a command in flight.
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

# Sent after each program message. Its reply "1;1" comes after every reply of the
# messages before it, and no single query answers like that, so it marks their end.
SYNC = "*OPC?;*OPC?"
SYNC_REPLY = "1;1"
LINE_MAX = 255  # characters of one program message (kProtocolLineMax - 1)


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
                    return line.decode("utf-8", "replace").rstrip("\r")  # a network name can be UTF-8
                if self._closed:
                    raise LinkError("link closed" + (": %s" % self.error if self.error else ""))
                left = deadline - time.monotonic()
                if left <= 0:
                    return None
                self._cv.wait(left)

    def write_line(self, text):
        with self._wlock:
            self._write((text + "\n").encode("utf-8"))

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
            self.proc.wait(timeout=2)  # no zombie process left behind
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


# ---------------------------------------------------------------- SCPI text
def split_units(line):
    """Split a response line at each ';' outside double quotes."""
    out, cur, quoted = [], [], False
    for c in line:
        if c == '"':
            quoted = not quoted  # a doubled quote toggles twice
        if c == ";" and not quoted:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(c)
    out.append("".join(cur))
    return out


def unquote(s):
    """A quoted response -> its text, an inner doubled quote made single. A text that is
    not quoted comes back unchanged."""
    s = s.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1].replace('""', '"')
    return s


def quote(s):
    return '"' + s.replace('"', '""') + '"'


def parse_error(line):
    """'-221,"Settings conflict;DELAY must ..."' -> (-221, 'Settings conflict;DELAY must ...').
    None if the line is not an error-queue entry."""
    m = re.match(r'^([-+]?\d+),(".*")$', line.strip())
    return (int(m.group(1)), unquote(m.group(2))) if m else None


def error_text(code, text):
    """(-221, 'Settings conflict;DELAY must ...') -> 'Settings conflict: DELAY must ... (error -221)'."""
    head, _, detail = text.partition(";")
    return "%s%s (error %d)" % (head, ": " + detail if detail else "", code)


def nr(s):
    """An NR1/NR3 response -> float; SCPI 'not a number' (9.91E+37) -> None."""
    v = float(s)
    return None if abs(v) >= 9.9e37 else v


# A console line that sets a passphrase: a header token PASS or PASSWORD, any case, short
# or long, absolute or relative, alone or in a compound line. Any token that starts with
# PASS counts (also a value glued to the header, "PASSsecret"): rather too much is masked.
_PASS_TOKEN = re.compile(r"(?i)(?:^|(?<=[:;\s*]))pass")


def mask_secret(text):
    """The text with everything from the first PASS... token to the end replaced, so a
    passphrase never reaches the console log, an error text or the page."""
    m = _PASS_TOKEN.search(text)
    if not m:
        return text
    word = re.match(r"(?i)pass(?:word)?", text[m.start():]).group(0)
    return text[:m.start()] + word + " ********"


# ---------------------------------------------------------------- Wi-Fi set-up values
def _is_control(c):
    """Control and writing-direction characters, as src/wifi_config.h wifiNameTextOk()."""
    o = ord(c)
    return (o < 0x20 or 0x7F <= o <= 0x9F or o in (0x061C, 0x200E, 0x200F) or 0x2028 <= o <= 0x202E
            or 0x2066 <= o <= 0x2069 or 0xD800 <= o <= 0xDFFF)


def wifi_check(ssid, passphrase):
    """None, or why the board cannot take this network name / passphrase (None = not
    sent). The limits are the firmware's (src/wifi_config.h, src/protocol.cpp): a name
    is 1 to 32 bytes of UTF-8 text, a passphrase 8 to 63 printable ASCII characters."""
    for what, text, lo, hi in (("network name", ssid, 1, 32), ("passphrase", passphrase, 8, 63)):
        if text is None or (what == "passphrase" and text == ""):
            continue
        if what == "passphrase" and any(not 32 <= ord(c) <= 126 for c in text):
            return "the passphrase can hold only printable ASCII characters"
        if any(_is_control(c) for c in text):
            return "the %s cannot contain control characters" % what
        size = len(text.encode("utf-8"))
        if not lo <= size <= hi:
            return ("the network name must have 1 to 32 bytes (in UTF-8; a letter outside ASCII is 2 or more)"
                    if what == "network name" else "the passphrase must have 8 to 63 characters")
        if text != text.strip():
            return "the %s cannot start or end with a space" % what
        if "disarm" in text.lower():
            return "the %s cannot contain the letters 'disarm': the board reads them as DISARM" % what
    return None


# ---------------------------------------------------------------- settings of the page
# name -> (SCPI header, kind). kind: "s" = time (the page sends whole ns), "hz" =
# frequency (whole Hz), "bool" = 0/1, "gate" = 0/1/2 for OFF/ARM/ALW.
SETTINGS = {
    "FREQ": (":FREQ", "hz"),
    "WIDTH": (":PULS:WIDT", "s"),
    "DELAY": (":PULS:DOUB:DEL", "s"),
    "MARKERWIDTH": (":MARK:WIDT", "s"),
    "COMBINE": (":OUTP:COMB", "bool"),
    "PIXGATE": (":PIX:GATE", "gate"),
    "PIXLEAD": (":PIX:LEAD", "s"),
    "PIXLAG": (":PIX:LAG", "s"),
}
GATE_NAMES = ["OFF", "ARM", "ALW"]
_COMBINE_TEXT = ["CH1 on LASER 1, CH2 on LASER 2", "CH1 + CH2 on LASER 1 and LASER 2"]
_GATE_TEXT = ["off: no pixel reset", "pixels reset between pulse pairs while armed",
              "pixels reset between pulse pairs, also while disarmed"]

# ---------------------------------------------------------------- restart detection
# A board restart is seen in its uptime (:DIAG:UPT?, which a query does not change,
# unlike *ESR?): the uptime is less than it was, plus the time that passed since then.
# The last uptime of each board is kept here, for the life of the GUI server, so that a
# restart is also seen across a reconnect (a restart closes the USB port and the
# network connection). A board is known by its *IDN? reply.
_RESTART_SLACK_S = 2.0  # host and board clocks, and the time a status read takes
_last_uptime = {}       # *IDN? -> (uptime in s, time.monotonic() of the read)
_last_uptime_lock = threading.Lock()


def note_uptime(board, uptime):
    """Records the board's uptime. True if the board restarted since the last record."""
    now = time.monotonic()
    with _last_uptime_lock:
        last = _last_uptime.get(board)
        _last_uptime[board] = (uptime, now)
    if last is None:
        return False
    expected = last[0] + (now - last[1])
    return uptime + _RESTART_SLACK_S < expected


# The status read-out: program messages and the names of their responses. Absolute
# headers, except below WLAN (a relative header after :SYST:COMM:WLAN? resolves below
# WLAN). Each response line stays far below 256 bytes: the two long texts (hardware
# problem, clock mode) and the link note have a message of their own.
_STATUS_MESSAGES = [
    (":FREQ?;:PULS:PER?;:PULS:WIDT?;:PULS:DOUB:DEL?;:MARK:WIDT?;:OUTP:COMB?;:PIX:GATE?;:PIX:LEAD?;:PIX:LAG?",
     ["FREQ", "PERIOD", "WIDTH", "DELAY", "MARKERWIDTH", "COMBINE", "PIXGATE", "PIXLEAD", "PIXLAG"]),
    (":PIX:WIND?;:SOUR:SYNC:FREQ?;:OUTP?;:OUTP:PEND?", ["PIXWIN", "SYNC", "ARMED", "PENDING"]),
    (":DIAG:CLOC?;:DIAG:VREG?;:DIAG:RES:CAUS?;:DIAG:WATC:RES?;:DIAG:WATC:PER?;:DIAG:TXDR?;:DIAG:UPT?",
     ["CLK", "VREG", "RESET", "WDT_RESETS", "WDT_PER", "TX_DROPPED", "UPTIME"]),
    (":DIAG:HARD?", ["HW"]),
    (":DIAG:CLOC:MODE?", ["CLKMODE"]),
    (":SYST:COMM:WLAN?;SSID?;SEC?;PEND?;SAV?;MAC?;IPAD?;RSSI?;PORT?;CLI?",
     ["WLAN", "SSID", "SEC", "PEND", "SAV", "MAC", "IPAD", "RSSI", "PORT", "CLI"]),
    (":SYST:COMM:WLAN:LINK?", ["LINK"]),
]


def build_status(r):
    """Responses by name -> {'fields', 'order', 'system', 'pixreset'} for the page.

    fields[name]: value (the realized value in the page's unit: ns, Hz, 0/1, 0/1/2),
    actual (ns or Hz), cycles (PIO cycles; for FREQ the period), unit, mode (a text for
    COMBINE and PIXGATE). system: the board's state under the key names of the page."""
    clk = int(r["CLK"])
    fields, order = {}, []
    for name, (header, kind) in SETTINGS.items():
        raw = r[name]
        if kind == "s":
            sec = float(raw)
            fields[name] = {"value": round(sec * 1e9, 3), "actual": sec * 1e9, "cycles": round(sec * clk),
                            "unit": "ns", "text": raw}
        elif kind == "hz":
            hz = float(raw)
            fields[name] = {"value": round(hz, 3), "actual": hz, "cycles": round(float(r["PERIOD"]) * clk),
                            "unit": "Hz", "text": raw}
        elif kind == "bool":
            v = int(raw)
            fields[name] = {"value": v, "mode": _COMBINE_TEXT[1 if v else 0], "text": raw}
        else:
            v = GATE_NAMES.index(raw) if raw in GATE_NAMES else 0
            fields[name] = {"value": v, "mode": _GATE_TEXT[v], "text": raw}
        order.append(name)
    reset_s, start_s, free_s = (float(x) for x in r["PIXWIN"].split(","))
    pixreset = ({"on": True, "reset_ns": reset_s * 1e9, "start_ns": start_s * 1e9, "free_ns": free_s * 1e9}
                if fields["PIXGATE"]["value"] else {"on": False})
    state, _, note = r["LINK"].partition(",")
    note = unquote(note)
    rssi = nr(r["RSSI"])
    ip, client = unquote(r["IPAD"]), unquote(r["CLI"])
    system = {
        "ARMED": r["ARMED"] == "1",
        "START_PENDING_US": str(round(float(r["PENDING"]) * 1e6)),
        "CLK": str(clk),
        "CLKMODE": unquote(r["CLKMODE"]),
        "VREG_V": r["VREG"],
        "HW": unquote(r["HW"]),
        "RESET": r["RESET"],
        "WDT_RESETS": r["WDT_RESETS"],
        "WDT_MS": str(round(float(r["WDT_PER"]) * 1000)),
        "TX_DROPPED": r["TX_DROPPED"],
        "UPTIME_S": r["UPTIME"],
        "SYNC_HZ": r["SYNC"],
        "WIFI": state + (" (%s)" % note if note else ""),
        "WIFI_STATE": state,
        "WIFI_NOTE": note,
        "WIFI_SSID": unquote(r["SSID"]),
        "WIFI_PASS": "SET" if r["SEC"] == "WPA2" else "NONE",
        "WIFI_AT_POWER_UP": r["WLAN"],
        "WIFI_PENDING": r["PEND"],
        "WIFI_SAVED": r["SAV"],
        "WIFI_MAC": unquote(r["MAC"]),
        "WIFI_IP": ip or "NONE",
        "WIFI_RSSI_DBM": "NONE" if rssi is None else str(int(rssi)),
        "NET_PORT": r["PORT"],
        "NET_CLIENT": client or "NONE",
    }
    return {"fields": fields, "order": order, "system": system, "pixreset": pixreset}


# ---------------------------------------------------------------- client
class PiEBV:
    """Thread-safe PiEBV client. One exchange is on the link at a time (except DISARM)."""

    def __init__(self, target, log_size=2000):
        self.target = target
        self.link = open_transport(target)
        # Re-entrant: a sequence of commands (wifi_setup) holds it from its first command
        # to its last, so another request cannot put a command in between.
        self._cmd = threading.RLock()
        # Order of ARM and DISARM on the wire. A command can wait for self._cmd for
        # seconds (behind a Wi-Fi set-up). An ARM that waited while a DISARM was sent
        # must not go out after it: disarm() counts under self._order, and arm() sends
        # only if the count is the one it saw when it was asked.
        self._order = threading.Lock()
        self._disarms = 0
        # SYNC replies still owed by exchanges that timed out. Their late replies must not
        # be taken for the replies of a later exchange: _ask() reads them away first.
        self._unsynced = 0
        self._log = deque(maxlen=log_size)
        self._log_seq = 0
        self._log_lock = threading.Lock()
        self.identity = None
        self.restart = None  # the last restart seen on this link: {"at": epoch s, "cause": ...}
        try:
            time.sleep(0.15)
            self._stale(0.2)  # replies a previous host left unread
            # Echo off: the USB link keeps it across host connections. Then empty the error
            # queue into the console (a boot-time hardware problem is reported there) and
            # clear the status registers.
            self._ask(":SYST:ECHO OFF", want=0)
            self.read_errors()
            self._ask("*CLS", want=0, log=False)
            self.identity = self.identify()
        except Exception:
            self.link.close()
            raise

    # ---- log (the GUI console)
    def _record(self, direction, text):
        with self._log_lock:
            self._log_seq += 1
            self._log.append((self._log_seq, time.time(), direction, text))

    def log_since(self, seq):
        with self._log_lock:
            return [{"seq": s, "t": t, "dir": d, "text": x} for s, t, d, x in self._log if s > seq], self._log_seq

    # ---- low level
    def _stale(self, quiet=0.0):
        """Log lines that nobody asked for (left in the input, or a late reply). They are
        masked: a late reply can belong to a console line that set a passphrase."""
        while True:
            line = self.link.readline(quiet)
            if line is None:
                return
            self._record("<", mask_secret(line))

    def _resync(self, timeout):
        """Read the late replies of exchanges that timed out, up to their SYNC replies."""
        deadline = time.monotonic() + timeout
        while self._unsynced:
            left = deadline - time.monotonic()
            line = self.link.readline(left) if left > 0 else None
            if line is None:
                raise LinkError("the board has not answered an earlier command yet")
            if line == SYNC_REPLY:
                self._unsynced -= 1
            else:
                self._record("<", mask_secret(line))

    def _ask(self, message, want=1, log=True, shown=None, timeout=1.5, send=None, mask=False):
        """Send one program message and return its reply lines (normally 0 or 1).

        The SYNC message follows it, and the lines up to SYNC's reply are the replies, so a
        message without a reply (a setting, or one that ended at a command error) costs no
        time-out. want: the number of lines expected; a different number raises LinkError
        (None = any number). log=False keeps the message and its reply out of the console
        log (the page's once-a-second poll). shown: the text the log gets in place of the
        message. mask: the reply lines are masked too (mask_secret). send: the caller's
        own write, which can decide not to send (then None is returned)."""
        with self._cmd:
            self._resync(timeout)
            self._stale()
            if send is not None:
                if not send():
                    return None
            else:
                if log:
                    self._record(">", message if shown is None else shown)
                self.link.write_line(message)
            self.link.write_line(SYNC)
            got = []
            deadline = time.monotonic() + timeout
            while True:
                left = deadline - time.monotonic()
                r = self.link.readline(left) if left > 0 else None
                if r is None:
                    self._unsynced += 1  # its SYNC reply can still come
                    # `shown`, not `message`: the text reaches the page and the log.
                    raise LinkError("no reply to %r (wrong port, or DTR off?)" % (shown or message))
                if r == SYNC_REPLY:
                    break
                if mask:
                    r = mask_secret(r)
                if log:
                    self._record("<", r)
                got.append(r)
            if want is not None and len(got) != want:
                errs = self.read_errors(log=log)
                why = "; ".join(error_text(c, t) for c, t in errs) or "%d reply lines" % len(got)
                raise LinkError("unexpected reply to %r: %s" % (shown or message, why))
            return got

    def _query(self, message, log=False):
        """The responses of one message of queries, split at ';'."""
        return split_units(self._ask(message, log=log)[0])

    def read_errors(self, log=True, mask=False):
        """Read the error queue until it is empty: [(code, text)]. Each entry is logged."""
        out = []
        with self._cmd:
            for _ in range(12):  # the queue holds 8 entries
                line = self._ask(":SYST:ERR?", log=False)[0]
                e = parse_error(line)
                if e is None:
                    raise LinkError("unexpected reply to :SYST:ERR?: %r" % line)
                if e[0] == 0:
                    break
                if mask:
                    e = (e[0], mask_secret(e[1]))
                if log:
                    self._record("<", '%d,%s' % (e[0], quote(e[1])))
                out.append(e)
        return out

    def _set_message(self, message, shown=None, timeout=1.5):
        """A setting and the first entry of the error queue in one message. Returns
        (code, text) of that entry; any later entries are read (and logged) too."""
        with self._cmd:
            line = self._ask(message + ";:SYST:ERR?", shown=None if shown is None else shown + ";:SYST:ERR?",
                             timeout=timeout)[0]
            e = parse_error(line)
            if e is None:
                raise LinkError("unexpected reply to %r: %r" % (shown or message, line))
            if e[0] != 0:
                self.read_errors()
            return e

    # ---- commands
    def identify(self):
        """*IDN? -> 'PiEBV,<model>,<serial>,<firmware>'."""
        line = self._ask("*IDN?")[0]
        if not line.startswith("PiEBV,"):
            raise LinkError("not a PiEBV: *IDN? gave %r" % line[:80])
        return line

    def status(self, log=False):
        r = {}
        with self._cmd:
            for message, names in _STATUS_MESSAGES:
                values = self._query(message, log=log)
                if len(values) != len(names):
                    raise LinkError("unexpected reply to %r" % message)
                r.update(zip(names, values))
        try:
            st = build_status(r)
            uptime = float(r["UPTIME"])
        except (ValueError, KeyError, IndexError) as exc:
            raise LinkError("unexpected status reply: %s" % exc)
        if note_uptime(self.identity, uptime):
            self.restart = {"at": time.time(), "cause": r["RESET"]}
            self._record("!", "The board restarted (reset cause: %s). It is DISARMED, with the default "
                              "settings unless they were sent again." % r["RESET"])
        if self.restart:
            st["system"]["RESTART_AT"] = self.restart["at"]
            st["system"]["RESTART_CAUSE"] = self.restart["cause"]
        return st

    def set(self, name, value):
        """One setting of the page. Returns (ok, reply): reply is the board's error-queue
        entry (<code>,"<text>"), 0,"No error" when it took the value."""
        name = name.upper()
        if name not in SETTINGS:
            return False, 'the page has no setting %s' % name
        header, kind = SETTINGS[name]
        value = int(value)
        if kind == "s":
            arg = "%dNS" % value
        elif kind == "hz":
            arg = "%dHZ" % value
        elif kind == "bool":
            arg = "1" if value else "0"
        else:
            if not 0 <= value <= 2:
                return False, "use 0 (off), 1 (while armed) or 2 (always)"
            arg = GATE_NAMES[value]
        code, text = self._set_message("%s %s" % (header, arg))
        return code == 0, "%d,%s" % (code, quote(text))

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
        """:OUTP ON, unless a DISARM was sent between this call and the moment the link is
        free for it (the call can wait behind another command). Returns (ok, text)."""
        asked = self._disarms
        message = ":OUTP ON;:SYST:ERR?;:OUTP?;:OUTP:PEND?"

        def send():
            with self._order:
                if self._disarms != asked:
                    return False
                self._record(">", message)
                self.link.write_line(message)
                return True

        with self._cmd:
            got = self._ask(message, send=send)
            if got is None:
                self._record("<", "ARM not sent: a DISARM came after it")
                return False, "ARM not sent: a DISARM came after it"
            units = split_units(got[0])
            e = parse_error(units[0]) if len(units) == 3 else None
            if e is None:
                raise LinkError("unexpected reply to :OUTP ON: %r" % got[0])
            if e[0] != 0:
                self.read_errors()
                return False, "ARM refused: " + error_text(*e)
            if units[1] != "1":
                return False, "ARM not confirmed: :OUTP? gave " + units[1]
            us = round(float(units[2]) * 1e6)
            return True, "ARMED" + (" (laser pulses start after a %d us hold-off)" % us if us else "")

    def disarm(self):
        """Written at once, even while another command is waiting for its reply."""
        with self._order:
            self._disarms += 1
            self._record(">", "DISARM")
            self.link.write_line("DISARM")
        # Confirm through the normal path (queued behind any command in flight).
        reply = self._ask(":OUTP?")[0]
        return reply == "0", ":OUTP? " + reply

    def _wifi_step(self, message, shown=None, long=False):
        """One Wi-Fi set-up command and the error it left (code, text)."""
        # The radio's power-up and the flash write can take seconds (the firmware
        # allows 8 s for them).
        return self._set_message(message, shown=shown, timeout=12.0 if long else 1.5)

    def wifi_setup(self, action, ssid=None, passphrase=None):
        """The board's Wi-Fi set-up (USB link only; the board refuses it over the network).
        action "on": join the network `ssid` and store the set-up. `passphrase` is its
        passphrase, or "" for an open network. None is permitted only for the network
        that the board has in use: the board then keeps its passphrase. "off": radio
        off. "clear": off, and erase the name and the passphrase.
        Returns (ok, texts, warning): warning is True for a change that is in use but not
        stored. Raises ValueError for a value the board cannot take."""
        if action not in ("on", "off", "clear"):
            raise ValueError("unknown Wi-Fi action")
        if action == "on":
            if ssid is None:
                raise ValueError("the network name is missing")
            why = wifi_check(ssid, passphrase)
            if why:
                raise ValueError(why)
        wlan = ":SYST:COMM:WLAN"
        with self._cmd:  # one sequence: no other command goes in between
            steps = []  # (message, text for the console log or None, long wait)
            if action == "off":
                steps.append((wlan + " OFF", None, True))
            elif action == "clear":
                steps.append((wlan + ":CLE", None, True))
            elif passphrase is None:
                # The board never tells its passphrase. WLAN ON alone joins the network in
                # use with it, but it would also take a name or passphrase that was sent
                # before and not joined (WLAN:PEND? 1), so that must not be there.
                in_use, pending, sec = self._query(wlan + ":SSID?;PEND?;SEC?")
                if ssid != unquote(in_use):
                    raise ValueError("type the passphrase of this network, or choose an open network")
                if pending != "0":
                    raise ValueError("the board holds a name or passphrase that was sent but not joined: "
                                     "type the passphrase of this network, or choose an open network")
                want_sec = sec
                steps.append((wlan + " ON", None, True))
            else:
                # WLAN:SSID discards a passphrase sent earlier; WLAN:PASS is always sent.
                want_sec = "WPA2" if passphrase else "NONE"
                steps.append((wlan + ":SSID " + quote(ssid), None, False))
                steps.append((wlan + ":PASS " + quote(passphrase),
                              wlan + ':PASS "********"' if passphrase else None, False))
                steps.append((wlan + " ON", None, True))
            texts, not_stored = [], ""
            for message, shown, long in steps:
                code, text = self._wifi_step(message, shown, long)
                if code == 101:  # a warning: the change is in use, but not in flash
                    not_stored = text.partition(";")[2] or "no reason given"
                elif code != 0:
                    texts.append(error_text(code, text))
                    return False, texts, False
            if action == "on":
                # The board names what it uses: it must be what was asked for.
                got_ssid, got_sec = self._query(wlan + ":SSID?;SEC?", log=True)
                if unquote(got_ssid) != ssid or got_sec != want_sec:
                    texts.append("the board uses another set-up than the one asked for: check it and join again")
                    return False, texts, False
                done = "Joined %s (%s)." % (quote(ssid), "WPA2" if want_sec == "WPA2" else "open network")
            else:
                done = "Radio off." if action == "off" else "Set-up erased."
            done += " In use, but not stored: %s." % not_stored if not_stored else " Stored."
            return True, [done], bool(not_stored)

    def raw(self, line):
        """One console line, sent as typed. Returns the reply lines and then the entries
        of the error queue that the line left. A line that names OUTP follows the ARM
        order rule (not sent if a DISARM was sent after it was asked); a line that sets a
        passphrase is masked in the log and in the replies."""
        asked = self._disarms
        secret = _PASS_TOKEN.search(line) is not None
        shown = mask_secret(line) if secret else line
        timeout = 12.0 if re.search(r"(?i)WLAN", line) else 3.0  # radio start: up to 12 s

        def send():
            with self._order:
                if re.search(r"(?i)OUTP", line) and self._disarms != asked:
                    return False
                self._record(">", shown)
                self.link.write_line(line)
                return True

        with self._cmd:
            got = self._ask(line, want=None, shown=shown, timeout=timeout, send=send, mask=secret)
            if got is None:
                self._record("<", "not sent: a DISARM came after it")
                return ["not sent: a DISARM came after it"]
            errs = self.read_errors(mask=secret)
            got += ["%d,%s" % (c, quote(t)) for c, t in errs]
            if re.search(r"(?i)ECHO", line):  # the client needs echo off on its link
                self._ask(":SYST:ECHO OFF", want=None, log=False)
                self._record("<", "(the GUI keeps :SYST:ECHO OFF on its link)")
                got.append("(the GUI keeps :SYST:ECHO OFF on its link)")
            return got

    def close(self):
        self.link.close()
