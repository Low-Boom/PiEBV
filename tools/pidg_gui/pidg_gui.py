#!/usr/bin/env python3
"""PiDG web GUI: a local web server that drives the PiDG over USB serial.

    python tools/pidg_gui/pidg_gui.py                    # then open http://127.0.0.1:8765
    python tools/pidg_gui/pidg_gui.py --connect COM7     # connect at start-up
    python tools/pidg_gui/pidg_gui.py --connect sim      # the simulator (tools/pidg_sim)
    python tools/pidg_gui/pidg_gui.py --connect socket://pidg.local:4242   # future Wi-Fi link

The server owns the serial port; any number of browser tabs share it. It binds to
127.0.0.1 only unless --host says otherwise: whoever can reach the page can ARM the
lasers. Serial needs pyserial (python -m pip install pyserial); the simulator does not.
Closing the page or stopping the server does NOT disarm -- only DISARM does.
"""
import argparse
import json
import mimetypes
import os
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pidg_device

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# Settings the GUI keeps at one value: the page shows them read-only, and the server refuses
# any other value, from the settings form or typed in the console.
FIXED = {"SYNC": 1000000}


def fixed_violation(line):
    """Why a console line may not be sent, or None. Lines holding DISARM always go through."""
    words = line.split()
    if not words or "DISARM" in line.upper():
        return None
    name = words[0].upper()
    if name in FIXED and len(words) > 1:
        if len(words) == 2 and words[1].isdigit() and int(words[1]) == FIXED[name]:
            return None
        return "%s is fixed at %d in the GUI; not sent" % (name, FIXED[name])
    return None


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.dev = None
        self.error = None

    def device(self):
        with self.lock:
            if self.dev is None:
                raise pidg_device.LinkError("not connected")
            return self.dev

    def connect(self, target):
        with self.lock:
            if self.dev is not None:
                self.dev.close()
                self.dev = None
            self.error = None
            try:
                self.dev = pidg_device.PiDG(target)
            except Exception as exc:
                self.error = str(exc)
                raise

    def disconnect(self):
        with self.lock:
            if self.dev is not None:
                self.dev.close()
            self.dev = None


STATE = State()


def snapshot():
    """Everything the page shows, in one JSON object."""
    with STATE.lock:
        dev, err = STATE.dev, STATE.error
    if dev is None:
        return {"connected": False, "error": err}
    try:
        st = dev.status(log=False)  # the poll stays out of the console
    except Exception as exc:
        if dev.link.closed:
            STATE.disconnect()
            return {"connected": False, "error": "link lost: %s" % exc}
        return {"connected": True, "target": dev.target, "identity": dev.identity, "error": str(exc)}
    return {"connected": True, "target": dev.target, "identity": dev.identity, "status": st, "error": None}


class Handler(BaseHTTPRequestHandler):
    server_version = "PiDG-GUI/1"

    def log_message(self, fmt, *args):  # quiet
        pass

    # ---- helpers
    def _json(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            return {}
        return json.loads(self.rfile.read(n).decode("utf-8") or "{}")

    def _static(self, path):
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        full = os.path.normpath(os.path.join(STATIC, rel))
        if not full.startswith(STATIC) or not os.path.isfile(full):
            self.send_error(404)
            return
        data = open(full, "rb").read()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(full)[0] or "application/octet-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # ---- routes
    def do_GET(self):
        url = urlparse(self.path)
        try:
            if url.path == "/api/state":
                return self._json(snapshot())
            if url.path == "/api/ports":
                return self._json({"ports": pidg_device.list_ports(),
                                   "sim": os.path.exists(os.path.normpath(pidg_device.SIM_EXE))})
            if url.path == "/api/log":
                since = int(parse_qs(url.query).get("since", ["0"])[0])
                with STATE.lock:
                    dev = STATE.dev
                if dev is None:
                    return self._json({"entries": [], "next": since})
                entries, last = dev.log_since(since)
                return self._json({"entries": entries, "next": last})
        except Exception as exc:
            return self._json({"error": str(exc)}, 500)
        return self._static(url.path)

    def do_POST(self):
        url = urlparse(self.path)
        try:
            body = self._body()
            if url.path == "/api/connect":
                STATE.connect(str(body.get("target", "")).strip())
                return self._json(snapshot())
            if url.path == "/api/disconnect":
                STATE.disconnect()
                return self._json(snapshot())
            dev = STATE.device()
            if url.path == "/api/disarm":
                ok, reply = dev.disarm()
                return self._json({"ok": ok, "reply": reply, "state": snapshot()})
            if url.path == "/api/arm":
                ok, reply = dev.arm()
                return self._json({"ok": ok, "reply": reply, "state": snapshot()})
            if url.path == "/api/apply":
                settings = {str(k).upper(): int(v) for k, v in (body.get("settings") or {}).items()}
                bad = [n for n, v in settings.items() if n in FIXED and v != FIXED[n]]
                if bad:
                    return self._json({"error": "%s is fixed at %d in the GUI" % (bad[0], FIXED[bad[0]])}, 400)
                results = dev.apply(settings)
                return self._json({"results": [{"name": n, "ok": ok, "reply": r} for n, ok, r in results],
                                   "state": snapshot()})
            if url.path == "/api/command":
                line = str(body.get("line", "")).strip()
                if not line or len(line) > 120 or any(ord(c) < 32 for c in line):
                    return self._json({"error": "one printable command line, up to 120 characters"}, 400)
                why = fixed_violation(line)
                if why:
                    return self._json({"error": why}, 400)
                return self._json({"lines": dev.raw(line), "state": snapshot()})
        except pidg_device.LinkError as exc:
            return self._json({"error": str(exc), "state": snapshot()}, 409)
        except Exception as exc:
            return self._json({"error": "%s: %s" % (type(exc).__name__, exc)}, 500)
        self.send_error(404)


def main():
    ap = argparse.ArgumentParser(description="PiDG web GUI (local web server for the PiDG delay generator)")
    ap.add_argument("--connect", metavar="TARGET",
                    help="connect at start-up: a serial port (COM7, /dev/ttyACM0), 'auto', 'sim', or a pyserial URL")
    ap.add_argument("--host", default="127.0.0.1", help="interface to serve on (default 127.0.0.1: this computer only)")
    ap.add_argument("--http-port", type=int, default=8765, help="web server port (default 8765)")
    ap.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    args = ap.parse_args()

    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print("WARNING: serving on %s -- anyone who can reach this address can ARM the lasers." % args.host,
              file=sys.stderr)
    if args.connect:
        target = args.connect
        if target == "auto":
            pidgs = [p["device"] for p in pidg_device.list_ports() if p["pidg"]]
            if not pidgs:
                sys.exit("no PiDG found on USB (VID 0x2E8A); pass --connect PORT")
            target = pidgs[0]
        try:
            STATE.connect(target)
            print("connected to %s: %s" % (target, STATE.dev.identity))
        except Exception as exc:
            print("could not connect to %s: %s" % (target, exc), file=sys.stderr)

    httpd = ThreadingHTTPServer((args.host, args.http_port), Handler)
    url = "http://%s:%d/" % ("127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host, args.http_port)
    print("PiDG GUI on %s  (Ctrl+C to stop; stopping does not disarm)" % url)
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        STATE.disconnect()


if __name__ == "__main__":
    main()
