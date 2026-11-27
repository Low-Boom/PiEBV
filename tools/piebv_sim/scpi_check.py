#!/usr/bin/env python3
"""SCPI check: the firmware's command protocol (src/protocol.cpp), run in the simulator.

    python tools/piebv_sim/scpi_check.py [path to piebv_sim]

Each check sends program messages to a fresh simulator and compares the replies. The
simulator runs the real protocol code, so a pass here means the same on the board for
everything that does not need hardware (see README.md). Exit code 0 = all passed.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SIM = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "piebv_sim.exe" if os.name == "nt" else "piebv_sim")

failures = 0


def run(*lines, args=()):
    """Send the lines (each one program message) and return the reply lines."""
    data = "".join(l + "\n" for l in lines).encode("utf-8")
    out = subprocess.run([SIM, *args], input=data, capture_output=True, timeout=20).stdout
    text = out.decode("utf-8", "replace")
    assert text == "" or text.endswith("\r\n"), "every reply ends in CR LF: %r" % text[-20:]
    return text.split("\r\n")[:-1] if text else []


def check(name, got, want):
    global failures
    def same(g, w):
        if isinstance(w, re.Pattern):
            return isinstance(g, str) and w.fullmatch(g) is not None
        return g == w
    if isinstance(want, list):
        ok = isinstance(got, list) and len(got) == len(want) and all(same(g, w) for g, w in zip(got, want))
    else:
        ok = same(got, want)
    if not ok:
        failures += 1
        print("FAIL %s\n  got:  %r\n  want: %r" % (name, got, want))


NR3 = r"[0-9]\.[0-9]{9}E[+-][0-9]{2}"

# --- identification and IEEE 488.2 common commands
check("*IDN?", run("*IDN?"), ["PiEBV,simulator,0,protocol and timing code from ../../src"])
check("no greeting, nothing unasked", run(), [])
check("power-on bit", run("*ESR?", "*ESR?"), ["128", "0"])
check("*OPC? *TST?", run("*OPC?;*TST?"), ["1;0"])
check("*OPC sets bit 0", run("*ESR?", "*OPC", "*ESR?"), ["128", "1"])
check("*ESE / *SRE", run("*ESE 36;*ESE?;*SRE 255;*SRE?"), ["36;191"])
check("*STB? with an error", run("*CLS", "FOO", "*ESE 32;*STB?"), ["36"])
check("*CLS clears the queue", run("FOO", "*CLS", "SYST:ERR:COUN?"), ["0"])
check("*RST: defaults, disarmed", run("FREQ 2000;OUTP ON", "*RST", "FREQ?;OUTP?"), ["1.000000000E+03;0"])

# --- settings are silent; queries return realized values in NR3
check("settings give no reply", run("FREQ 1000", "PULS:WIDT 100 NS", "OUTP:COMB OFF", "PIX:GATE OFF"), [])
check("realized width", run("PULS:WIDT 101NS", "PULS:WIDT?"), ["1.000000000E-07"])
check("realized delay", run("PULS:DOUB:DEL 1003 ns", "PULS:DOUB:DEL?"), ["1.000000000E-06"])
check("seconds without suffix", run("PULS:WIDT 2E-7", "PULS:WIDT?"), ["2.000000000E-07"])
check("suffixes", run("PULS:DOUB:DEL 0.002 MS;:MARK:WIDT 1US;:FREQ 2 KHZ", "PULS:DOUB:DEL?;:MARK:WIDT?;:FREQ?"),
      ["2.000000000E-06;1.000000000E-06;2.000000000E+03"])
check("MHZ is mega", run("FREQ 0.001 MHZ", "FREQ?"), ["1.000000000E+03"])
check("6.667 ns steps", run("PULS:WIDT 21NS", "PULS:WIDT?"), ["2.000000000E-08"])
check("6.667 ns steps, not exact", run("PULS:WIDT 27NS", "PULS:WIDT?"), ["2.666666667E-08"])
check("period", run("FREQ 1000", "PULS:PER?"), ["1.000000000E-03"])
check("sync clock", run("SOUR:SYNC:FREQ?"), ["1.000000000E+06"])
check("double pulse always on", run("PULS:DOUB?"), ["1"])
check("DEFault", run("PULS:WIDT 200NS", "PULS:WIDT DEF", "PULS:WIDT?"), ["1.000000000E-07"])
check("300 MHz steps", run("PULS:WIDT 12NS", "PULS:WIDT?", args=("--overclock",)), ["1.333333333E-08"])
check("pixel gate", run("PIX:GATE ARMED", "PIX:GATE?", "PIX:GATE ALW;GATE?", "PIX:GATE OFF;GATE?"),
      ["ARM", "ALW", "OFF"])
check("combine", run("OUTP:COMB ON", "OUTP:COMB?", "OUTP:COMB 0;COMB?"), ["1", "0"])
check("pixel window", run("FREQ 2000;:PIX:GATE ALW", "PIX:WIND?"), [re.compile(NR3 + "," + NR3 + "," + NR3)])

# --- headers: long and short forms, any case, optional nodes, current path
check("long forms", run(":SOURce:PULSe:WIDTh?"), ["1.000000000E-07"])
check("lower case", run("source:frequency:cw?"), ["1.000000000E+03"])
check("compound, relative path", run(":PULS:WIDT?;DOUB:DEL?;:FREQ?"), ["1.000000000E-07;1.000000000E-05;1.000000000E+03"])
check("path after an inner node", run(":OUTP:COMB ON;:OUTP?;COMB?"), ["0;1"])
check("relative from the root (lenient)", run("PULS:WIDT?;FREQ?"), ["1.000000000E-07;1.000000000E+03"])
check("query with spaces", run("  FREQ?  ;  PULS:WIDT?  "), ["1.000000000E+03;1.000000000E-07"])

# --- arming
check("arm, disarm", run("OUTP ON", "OUTP?", "OUTP OFF", "OUTP?"), ["1", "0"])
check("hold-off is reported", run("OUTP ON;:OUTP?;PEND?"), [re.compile("1;" + NR3)])
check("ABORt disarms", run("OUTP ON", "ABOR", "OUTP?"), ["0"])
check("DISARM anywhere in the input", run("OUTP ON", "xx disarm yy", "OUTP?"), ["0"])
check("DISARM inside a string", run("OUTP ON", 'SYST:COMM:WLAN:SSID "my disarm net"', "OUTP?"), ["0"])
check("old commands are gone", run("ARM", "STATUS", "HELP", "SYST:ERR?;ERR?;ERR?"),
      ['-113,"Undefined header;ARM";-113,"Undefined header;STATUS";-113,"Undefined header;HELP"'])

# --- the error queue
check("empty queue", run("SYST:ERR?"), ['0,"No error"'])
check("settings conflict", run("FREQ 1500000", "SYST:ERR?"), [re.compile(r'-221,"Settings conflict;DELAY must leave.*"')])
check("rejected setting changes nothing", run("FREQ 1500000", "FREQ?"), ["1.000000000E+03"])
check("FIFO order", run("FOO", "BAR", "SYST:ERR:COUN?;:SYST:ERR?;:SYST:ERR?;:SYST:ERR?"),
      ['2;-113,"Undefined header;FOO";-113,"Undefined header;BAR";0,"No error"'])
check("overflow", run(*["FOO"] * 10, "SYST:ERR:COUN?"), ["8"])
check("overflow entry", run(*["FOO"] * 10, *["SYST:ERR?"] * 8)[-1], '-350,"Queue overflow"')
check("missing parameter", run("FREQ", "SYST:ERR?"), ['-109,"Missing parameter"'])
check("parameter not allowed", run("FREQ? 5", "SYST:ERR?"), ['-108,"Parameter not allowed"'])
check("query only", run("PULS:PER 1", "SYST:ERR?"), [re.compile(r'-113,"Undefined header;this is a query only.*"')])
check("no query form", run("ABOR?", "SYST:ERR?"), [re.compile(r'-113,"Undefined header;this command has no query form"')])
check("invalid suffix", run("FREQ 5 XS", "SYST:ERR?"), [re.compile(r'-131,"Invalid suffix;.*"')])
check("suffix not allowed", run("*ESE 5 HZ", "SYST:ERR?"), ['-138,"Suffix not allowed"'])
check("negative time", run("PULS:WIDT -1", "SYST:ERR?"), [re.compile(r'-222,"Data out of range;.*negative"')])
check("MIN/MAX not supported", run("PULS:WIDT MIN", "SYST:ERR?"), [re.compile(r'-224,"Illegal parameter value;.*"')])
check("bad boolean", run("OUTP MAYBE", "SYST:ERR?"), [re.compile(r'-224,"Illegal parameter value;.*"')])
check("syntax", run("FREQ=5", "SYST:ERR?"), [re.compile(r'-102,"Syntax error;.*"')])
check("a command error ends the message", run("FOO;FREQ?"), [])
check("an execution error ends only its unit", run("FREQ 1500000;FREQ?"), ["1.000000000E+03"])
check("line too long", run("FREQ?" + " " * 300, "SYST:ERR?"), [re.compile(r'-363,"Input buffer overrun;.*"')])
check("unterminated string", run('SYST:COMM:WLAN:SSID "abc', "SYST:ERR?"), [re.compile(r'-151,"Invalid string data;.*"')])

# --- echo (not SCPI)
check("echo", run("SYST:ECHO ON", "PULS:DOUB:DEL 1003NS", "FOO", "SYST:ECHO OFF", "FREQ 2000"),
      ["OK :SYST:ECHO 1", "OK :PULS:DOUB:DEL 1.000000000E-06 (1000.000 ns, 150 cyc)",
       'ERR -113,"Undefined header;FOO"'])
check("echo query", run("SYST:ECHO?", "SYST:ECHO 1;ECHO?"), ["0", "OK :SYST:ECHO 1", "1"])

# --- network link (the simulator is the USB link and has a radio that joins at once)
check("Wi-Fi set-up", run(':SYST:COMM:WLAN:SSID "Lab ""A"" Net";PASS \'correct horse\'', ":SYST:COMM:WLAN:PEND?",
                          ":SYST:COMM:WLAN ON", ":SYST:COMM:WLAN?;SSID?;SEC?;LINK?;PEND?"),
      ["1", '1;"Lab ""A"" Net";WPA2;CONNECTED,"";0'])
check("new name discards the passphrase", run(':SYST:COMM:WLAN:SSID "a";PASS "secret123"', ':SYST:COMM:WLAN:SSID "b"',
                                              ":SYST:COMM:WLAN ON", ":SYST:COMM:WLAN:SEC?"), ["NONE"])
check("OFF keeps the set-up in use", run(':SYST:COMM:WLAN:SSID "a";:SYST:COMM:WLAN ON', ':SYST:COMM:WLAN:SSID "b"', ":SYST:COMM:WLAN OFF",
                                         ":SYST:COMM:WLAN?;SSID?;PEND?"), ['0;"a";0'])
check("CLEar", run(':SYST:COMM:WLAN:SSID "a";:SYST:COMM:WLAN ON', ":SYST:COMM:WLAN:CLE", ":SYST:COMM:WLAN?;SSID?"), ['0;""'])
check("ON without a name", run(":SYST:COMM:WLAN ON", "SYST:ERR?"), [re.compile(r'-221,"Settings conflict;no network name.*"')])
check("refused while armed", run(':SYST:COMM:WLAN:SSID "a"', "OUTP ON", ":SYST:COMM:WLAN ON", "SYST:ERR?",
                                 ":SYST:COMM:WLAN:PEND?"),
      [re.compile(r'-200,"Execution error;DISARM first.*discarded\)"'), "0"])
check("not stored (simulator)", run(':SYST:COMM:WLAN:SSID "a"', ":SYST:COMM:WLAN ON", "SYST:ERR?"),
      ['101,"Set-up not stored;simulator: nothing is stored"'])
check("passphrase never printed", any("secret" in l for l in run("SYST:ECHO ON", ':SYST:COMM:WLAN:SSID "a"',
                                                                  ':SYST:COMM:WLAN:PASS "secret12"')), False)
check("name too long", run(':SYST:COMM:WLAN:SSID "%s"' % ("x" * 33), "SYST:ERR?"),
      [re.compile(r'-222,"Data out of range;the network name is longer than 32 bytes"')])
check("name not quoted", run(":SYST:COMM:WLAN:SSID lab", "SYST:ERR?"), [re.compile(r'-104,"Data type error;.*"')])
check("network queries", run(":SYST:COMM:WLAN:SSID 'a'", ":SYST:COMM:WLAN ON", ":SYST:COMM:WLAN:IPAD?;MAC?;RSSI?;PORT?;CLI?;SAV?"),
      ['"192.0.2.10";"02:00:00:00:00:01";-50;4242;"";0'])

# --- system and diagnostics
check("SYSTem:VERSion?", run("SYST:VERS?"), ["1999.0"])
check("diagnostics", run(":DIAG:HARD?;CLOC?;CLOC:MODE?;:DIAG:VREG?;RES:CAUS?;:DIAG:WATC:PER?;RES?;:DIAG:TXDR?"),
      ['"OK";150000000;"STANDARD";1.100000000E+00;POWER_ON;3.000000000E+00;0;0'])

check("uptime", run(":DIAG:UPT?"), [re.compile(NR3)])
up = run(":DIAG:UPT?", "*OPC?", ":DIAG:UPT?")
check("uptime rises", float(up[2]) >= float(up[0]), True)

# --- help: a definite-length block whose length is exact
help_raw = subprocess.run([SIM], input=b"SYST:HELP:HEAD?\n", capture_output=True, timeout=20).stdout
m = re.match(rb"#(\d)", help_raw)
ok = False
if m:
    nd = int(m.group(1))
    length = int(help_raw[2:2 + nd])
    block = help_raw[2 + nd:2 + nd + length]
    ok = help_raw[2 + nd + length:] == b"\r\n" and b":SYSTem:ERRor[:NEXT]/qonly/\r\n" in block
check("help block length", ok, True)

if failures:
    print("%d check(s) FAILED" % failures)
    sys.exit(1)
print("scpi_check: all checks passed")
