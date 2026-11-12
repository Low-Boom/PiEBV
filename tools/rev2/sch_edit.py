#!/usr/bin/env python3
"""Rev 2 schematic edit: selectable camera I/O voltage (+VCAM), status LEDs and rail test points.

Reads the Rev 1 schematic and writes the Rev 2 schematic. Changes:
  * the supply of U1-U6 and C1-C3 moves from +1V8 to the new net +VCAM;
  * U20 (TPS2116 power mux) makes +VCAM from +1V8 (U9, VIN1) or +3V3 (Pico 3V3_OUT, VIN2).
    MODE is on +3V3 (manual mode); PR1 (net VCAM_SEL) has R34 (10k) to +3V3, so with J22 open
    the mux passes VIN1 = +1V8. A shunt on J22 pulls PR1 to 0.3 V through R35 (1k) and the mux
    passes VIN2 = +3V3. R51 (4.7k) discharges +VCAM;
  * R52-R69 (47R, 0805): one series resistor in each camera line at the camera header
    (source termination for the camera cable). The header-side nets are Sync1_C ... TDRSTN6_C;
  * C23 (1 uF, +VCAM) and C24 (1 uF, +3V3) at U20;
  * D1 + R33: blue LED from +VCAM to GND (Vf > 2.5 V: dark at 1.8 V, lit at 3.3 V);
  * D2 (green) "12 V good": Q1 on LASER_PWR_OK; D3 (red) "ARMED": LASER_EN -> R37 -> D3 -> Q2
    (gate = ARMED_LED, GP17) -> Q1. D3 is lit only if the firmware is ARMED, J11 is closed
    and the +12 V rail is in its window;
  * D4-D6 output activity: U21-U23 (74LVC1G123 monostables on +3V3, about 15 ms) triggered from the
    driver outputs CH1/CH2/EXT_SYNC_DRIVE_RAW through compensated 10k / 4.7k dividers (12 pF / 22 pF);
  * TP4-TP9: test pads on +12V, +5V, +3V3, +1V8, +VCAM and GND;
  * paper A3 -> A2 (the new circuits are below the Rev 1 drawing).
The edit is text-level (the file layout of KiCad 10 is kept), and it is not idempotent:
run it once on the Rev 1 file.

usage: sch_edit.py IN.kicad_sch OUT.kicad_sch [KICAD_SYMBOL_DIR] [PROJECT_SYMBOL_LIB]
"""
import re, sys, uuid

SRC, DST = sys.argv[1], sys.argv[2]
SYMDIR = sys.argv[3] if len(sys.argv) > 3 else "/usr/share/kicad/symbols"
LOCAL_LIB = sys.argv[4] if len(sys.argv) > 4 else None
s = open(SRC, encoding="utf-8").read()
ROOT = re.search(r'\(kicad_sch\n\t\(version \d+\)\n\t\(generator "[^"]+"\)\n\t\(generator_version "[^"]+"\)\n\t\(uuid "([^"]+)"\)', s).group(1)
assert '"+VCAM"' not in s, "already edited"


def block(text, i):
    """Return the balanced (...) block that starts at text[i]."""
    d = 0
    for j in range(i, len(text)):
        if text[j] == "(":
            d += 1
        elif text[j] == ")":
            d -= 1
            if d == 0:
                return text[i:j + 1]
    raise ValueError("unbalanced")


def uid():
    return str(uuid.uuid4())


def n(v):
    """Number in KiCad style (no trailing zeros)."""
    return ("%.4f" % v).rstrip("0").rstrip(".")


EFF = "\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)%s\n\t\t\t)\n"


def prop(name, val, x, y, rot=0, hide=False, just=None):
    j = "\n\t\t\t\t(justify %s)" % just if just else ""
    return ('\t\t(property "%s" "%s"\n\t\t\t(at %s %s %d)\n%s\t\t\t(show_name no)\n\t\t\t(do_not_autoplace no)\n%s\t\t)\n'
            % (name, val.replace('"', '\\"'), n(x), n(y), rot, "\t\t\t(hide yes)\n" if hide else "", EFF % j))


def symbol(lib_id, ref, val, x, y, rot, pins, fp="", desc="", ref_at=None, val_at=None, bom=True, board=True, unit=1):
    """One placed symbol. ref_at / val_at: (x, y, rot[, justify]) of the visible fields."""
    ra = ref_at or (x, y - 2.54, 0)
    va = val_at or (x, y + 2.54, 0)
    hidden_ref = ref.startswith("#")
    o = "\t(symbol\n\t\t(lib_id \"%s\")\n\t\t(at %s %s %d)\n\t\t(unit %d)\n\t\t(body_style 1)\n" % (lib_id, n(x), n(y), rot, unit)
    o += "\t\t(exclude_from_sim no)\n\t\t(in_bom %s)\n\t\t(on_board %s)\n\t\t(in_pos_files %s)\n\t\t(dnp no)\n" % (
        "yes" if bom else "no", "yes" if board else "no", "yes" if bom else "no")
    o += '\t\t(uuid "%s")\n' % uid()
    o += prop("Reference", ref, ra[0], ra[1], ra[2], hide=hidden_ref, just=ra[3] if len(ra) > 3 else None)
    o += prop("Value", val, va[0], va[1], va[2], just=va[3] if len(va) > 3 else None)
    o += prop("Footprint", fp, x, y, 0, hide=True)
    o += prop("Datasheet", "", x, y, 0, hide=True)
    o += prop("Description", desc, x, y, 0, hide=True)
    for p in pins:
        o += '\t\t(pin "%s"\n\t\t\t(uuid "%s")\n\t\t)\n' % (p, uid())
    o += ('\t\t(instances\n\t\t\t(project "PiEBV_Pico"\n\t\t\t\t(path "/%s"\n\t\t\t\t\t(reference "%s")\n\t\t\t\t\t(unit %d)\n'
          '\t\t\t\t)\n\t\t\t)\n\t\t)\n\t)\n' % (ROOT, ref, unit))
    return o


def wire(*pts):
    o = ""
    for a, b in zip(pts, pts[1:]):
        o += ("\t(wire\n\t\t(pts\n\t\t\t(xy %s %s) (xy %s %s)\n\t\t)\n\t\t(stroke\n\t\t\t(width 0)\n\t\t\t(type default)\n\t\t)\n"
              '\t\t(uuid "%s")\n\t)\n' % (n(a[0]), n(a[1]), n(b[0]), n(b[1]), uid()))
    return o


def junction(x, y):
    return '\t(junction\n\t\t(at %s %s)\n\t\t(diameter 0)\n\t\t(color 0 0 0 0)\n\t\t(uuid "%s")\n\t)\n' % (n(x), n(y), uid())


def text(t, x, y):
    return ('\t(text "%s"\n\t\t(exclude_from_sim no)\n\t\t(at %s %s 0)\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n'
            '\t\t\t(justify left bottom)\n\t\t)\n\t\t(uuid "%s")\n\t)\n' % (t.replace('"', '\\"').replace("\n", "\\n"), n(x), n(y), uid()))


def label(name, x, y, just="left"):
    """Local net label at a wire end. just: side the text is on ("left" = text runs right from x)."""
    return ('\t(label "%s"\n\t\t(at %s %s %d)\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n'
            '\t\t\t(justify %s bottom)\n\t\t)\n\t\t(uuid "%s")\n\t)\n' % (name, n(x), n(y), 0 if just == "left" else 180, just, uid()))


def noconn(x, y):
    return '\t(no_connect\n\t\t(at %s %s)\n\t\t(uuid "%s")\n\t)\n' % (n(x), n(y), uid())


def libsym(lib, name, new_name=None):
    """A symbol of a KiCad library file, renamed "lib:name" for the schematic's lib_symbols (extends is flattened)."""
    t = open("%s/%s.kicad_sym" % (SYMDIR, lib), encoding="utf-8").read()
    b = block(t, t.index('(symbol "%s"\n' % name))
    m = re.search(r'\(extends "([^"]+)"\)', b)
    if m:                                               # derived symbol: take the parent's graphics and pins, keep own fields
        base = m.group(1)
        p = block(t, t.index('(symbol "%s"\n' % base))
        props = []                                      # the derived symbol's own fields replace the parent's
        for q in re.finditer(r'\n\t\t\(property "', b):
            props.append(block(b, q.start() + 3))
        first = None
        while True:
            q = re.search(r'\n\t\t\(property "', p)
            if not q:
                break
            if first is None:
                first = q.start()
            pb = block(p, q.start() + 3)
            p = p[:q.start()] + p[q.start() + 3 + len(pb):]
        p = p[:first] + "".join("\n\t\t" + x for x in props) + p[first:]
        b = p.replace('(symbol "%s"\n' % base, '(symbol "%s"\n' % name, 1).replace('(symbol "%s_' % base, '(symbol "%s_' % name)
    b = b.replace('(symbol "%s"\n' % name, '(symbol "%s:%s"\n' % (lib, new_name or name), 1)
    return "\n".join(("\t" + l) if l else l for l in b.split("\n")).lstrip("\t")   # library files are one tab shallower


_pwr = [200]


def power(net, x, y, rot=0):
    """Power symbol with its pin at (x, y). rot 0 points up, 180 down, 270 right (GND: 0 points down)."""
    _pwr[0] += 1
    lib = {"+VCAM": "PiEBV_Local:+VCAM"}.get(net, "power:" + net)
    if net == "GND":
        va = (x, y + 5.08, 0)
    elif rot == 0:
        va = (x, y - 5.08, 0)
    elif rot == 180:
        va = (x, y + 3.81, 0)
    else:
        va = (x + 3.81, y, 90)
    return symbol(lib, "#PWR%d" % _pwr[0], net, x, y, rot, ["1"],
                  desc='Power symbol creates a global label with name "%s"' % net,
                  ref_at=(x, y + 3.81, 0), val_at=va)


# ---- 1. library symbols -------------------------------------------------------------------------
i0 = s.index("\t(lib_symbols")
libs = block(s, i0 + 1)
p18 = block(libs, libs.index('(symbol "power:+1V8"'))
vcam = (p18.replace('"power:+1V8"', '"PiEBV_Local:+VCAM"').replace('"+1V8_0_1"', '"+VCAM_0_1"')
        .replace('"+1V8_1_1"', '"+VCAM_1_1"').replace('"+1V8"', '"+VCAM"').replace('\\"+1V8\\"', '\\"+VCAM\\"'))
vcam = vcam.replace('Power symbol creates a global label with name \\"+VCAM\\"',
                    'Camera I/O supply, +1V8 or +3V3 as U20 / J22 select. Power symbol creates a global label with name \\"+VCAM\\"')
new = [vcam, libsym("Device", "LED"), libsym("Power_Management", "TPS2116DRL"), libsym("74xGxx", "74LVC1G123"),
       libsym("Transistor_FET", "2N7002")]
new_libs = libs[:-1].rstrip() + "".join("\n\t\t" + b for b in new) + "\n\t)"
s = s[:i0 + 1] + new_libs + s[i0 + 1 + len(libs):]

# ---- 2. buffer supply: +1V8 -> +VCAM at U1/U2, U3/U4, U5/U6 and C1-C3 ---------------------------
moved = 0
for at in ("86.36 119.38 0", "86.36 76.2 0", "86.36 31.75 0", "38.1 233.68 0"):
    m = re.search(r'\t\(symbol\n\t\t\(lib_id "power:\+1V8"\)\n\t\t\(at %s\)' % re.escape(at), s)
    b = block(s, m.start() + 1)
    nb = (b.replace('(lib_id "power:+1V8")', '(lib_id "PiEBV_Local:+VCAM")').replace('"Value" "+1V8"', '"Value" "+VCAM"')
          .replace('name \\"+1V8\\"', 'name \\"+VCAM\\"'))
    assert nb != b
    s = s[:m.start() + 1] + nb + s[m.start() + 1 + len(b):]
    moved += 1
assert moved == 4 and s.count('(lib_id "power:+1V8")') == 1   # only the U9 output symbol stays on +1V8

# ---- 3. GP17 = ARMED_LED: the no-connect flags at U11 pin 22 and J15 pad 19 become labels -------
for (x, y, just) in ((157.48, 229.87, "left"), (224.79, 273.05, "right")):
    m = re.search(r'\t\(no_connect\n\t\t\(at %s %s\)\n\t\t\(uuid "[^"]+"\)\n\t\)\n' % (n(x), n(y)), s)
    s = s[:m.start()] + label("ARMED_LED", x, y, just) + s[m.end():]

# ---- 3b. series resistors R52-R69 in the camera lines, at the header pins ---------------------------
R0603 = "Resistor_SMD:R_0805_2012Metric_Pad1.20x1.40mm_HandSolder"   # same footprint as the other resistors
WIRE = re.compile(r'\t\(wire\n\t\t\(pts\n\t\t\t\(xy ([-\d.]+) ([-\d.]+)\) \(xy ([-\d.]+) ([-\d.]+)\)\n')
ser, rn = "", 52
for sig, pin, side in (("Sync", 5, -1), ("Trigger", 4, 1), ("TDRSTN", 3, -1)):
    for k in range(1, 7):
        m = re.search(r'\(property "Reference" "J%d"' % k, s)
        a0 = s.rfind("\n\t(symbol", 0, m.start())
        jx0, jy0 = map(float, re.search(r"\(at ([-\d.]+) ([-\d.]+) 0\)", s[a0:a0 + 200]).groups())
        px = jx0 + (-5.08 if side < 0 else 7.62)                      # pin end (odd pins left, even pins right)
        py = jy0 - {3: 2.54, 4: 2.54, 5: 0.0}[pin]
        qx = px + side * 5.08                                         # new end of the buffer-side wire
        hit = [w for w in WIRE.finditer(s) if (abs(float(w.group(1)) - px) < 1e-6 and abs(float(w.group(2)) - py) < 1e-6)
               or (abs(float(w.group(3)) - px) < 1e-6 and abs(float(w.group(4)) - py) < 1e-6)]
        assert len(hit) == 1, (sig, k, len(hit))
        w = hit[0]
        x1, y1, x2, y2 = map(float, w.groups())
        assert abs(y1 - y2) < 1e-6, (sig, k, w.groups())              # horizontal
        name = "%s%d" % (sig, k)
        if abs(x1 - x2) < 5.08 - 1e-6:
            # Short wire to a vertical run: the resistor goes into the top of the vertical run.
            fx = x2 if abs(x1 - px) < 1e-6 else x1                    # corner of the horizontal and the vertical wire
            vh = [v for v in WIRE.finditer(s) if v.start() != w.start() and abs(float(v.group(1)) - float(v.group(3))) < 1e-6
                  and abs(float(v.group(1)) - fx) < 1e-6 and min(abs(float(v.group(2)) - py), abs(float(v.group(4)) - py)) < 1e-6]
            assert len(vh) == 1, (sig, k, len(vh))
            v = vh[0]
            assert abs(float(v.group(2)) - float(v.group(4))) >= 7.62 and max(float(v.group(2)), float(v.group(4))) > py
            if abs(float(v.group(2)) - py) < 1e-6:
                nv = v.group(0).replace("(xy %s %s) (xy" % (v.group(1), v.group(2)), "(xy %s %s) (xy" % (n(fx), n(py + 5.08)))
            else:
                nv = v.group(0).replace(") (xy %s %s)" % (v.group(3), v.group(4)), ") (xy %s %s)" % (n(fx), n(py + 5.08)))
            s = s[:v.start()] + nv + s[v.end():]
            lab = re.search(r'\t\(label "%s"\n\t\t\(at %s %s (\d+)\)' % (name, n(px), n(py)), s)
            assert lab, name                                          # the label at the pin becomes the header-side name
            s = s[:lab.start()] + lab.group(0).replace('"%s"' % name, '"%s_C"' % name) + s[lab.end():]
            ser += symbol("Device:R_Small", "R%d" % rn, "47", fx, py + 2.54, 0, ["1", "2"], fp=R0603,
                          desc="Series termination of %s at J%d (camera cable source termination)" % (name, k),
                          ref_at=(fx + 2.0, py + 1.9, 0), val_at=(fx + 2.0, py + 3.4, 0))
            ser += label(name, fx, py + 5.08, "left")
            rn += 1
            continue
        if abs(x1 - px) < 1e-6:
            nw = w.group(0).replace("(xy %s %s) (xy" % (w.group(1), w.group(2)), "(xy %s %s) (xy" % (n(qx), n(py)))
        else:
            nw = w.group(0).replace(") (xy %s %s)" % (w.group(3), w.group(4)), ") (xy %s %s)" % (n(qx), n(py)))
        s = s[:w.start()] + nw + s[w.end():]
        lab = re.search(r'\t\(label "%s"\n\t\t\(at %s %s (\d+)\)' % (name, n(px), n(py)), s)
        if lab:                                                       # a label at the pin end moves to the new wire end
            s = s[:lab.start()] + lab.group(0).replace("(at %s %s" % (n(px), n(py)), "(at %s %s" % (n(qx), n(py))) + s[lab.end():]
        ser += symbol("Device:R_Small", "R%d" % rn, "47", (px + qx) / 2, py, 90, ["1", "2"], fp=R0603,
                      desc="Series termination of %s at J%d (camera cable source termination)" % (name, k),
                      ref_at=((px + qx) / 2, py - 1.5, 90), val_at=((px + qx) / 2, py + 1.5, 90))
        ser += label(name + "_C", px, py, "left" if side > 0 else "right")
        rn += 1
assert rn == 70

# ---- 4. new parts ----------------------------------------------------------------------------------
C0805 = "Capacitor_SMD:C_0805_2012Metric_Pad1.18x1.45mm_HandSolder"
R0805 = "Resistor_SMD:R_0805_2012Metric_Pad1.20x1.40mm_HandSolder"
LED0805 = "LED_SMD:LED_0805_2012Metric_Pad1.15x1.40mm_HandSolder"
G = 2.54
o = ""


def cap(ref, val, x, y, desc, side=1):
    """Vertical capacitor, pin 1 at (x, y - 3.81), pin 2 at (x, y + 3.81). side: +1 text right, -1 text left."""
    j = "left" if side > 0 else "right"
    return symbol("Device:C", ref, val, x, y, 0, ["1", "2"], fp=C0805, desc=desc,
                  ref_at=(x + 1.905 * side, y - 1.27, 0, j), val_at=(x + 1.905 * side, y + 1.27, 0, j))


def res_v(ref, val, x, y, desc):
    """Vertical resistor, pins at (x, y - 2.54) and (x, y + 2.54)."""
    return symbol("Device:R_Small", ref, val, x, y, 0, ["1", "2"], fp=R0805, desc=desc,
                  ref_at=(x + 1.27, y - 0.635, 0, "left"), val_at=(x + 1.27, y + 1.27, 0, "left"))


def res_h(ref, val, x, y, desc):
    """Horizontal resistor, pins at (x - 2.54, y) and (x + 2.54, y)."""
    return symbol("Device:R_Small", ref, val, x, y, 90, ["1", "2"], fp=R0805, desc=desc,
                  ref_at=(x, y - 2.54, 90), val_at=(x, y + 2.54, 90))


def led(ref, val, x, y, desc):
    """Horizontal LED, anode at (x - 3.81, y), cathode at (x + 3.81, y)."""
    return symbol("Device:LED", ref, val, x, y, 180, ["1", "2"], fp=LED0805, desc=desc,
                  ref_at=(x, y - 3.81, 0), val_at=(x, y + 3.556, 0))


def nfet(ref, x, y, desc):
    """2N7002: gate at (x - 5.08, y), drain at (x + 2.54, y - 5.08), source at (x + 2.54, y + 5.08)."""
    return symbol("Transistor_FET:2N7002", ref, "2N7002", x, y, 0, ["1", "2", "3"], fp="Package_TO_SOT_SMD:SOT-23", desc=desc,
                  ref_at=(x + 5.08, y - 1.27, 0, "left"), val_at=(x + 5.08, y + 1.27, 0, "left"))


# -- 4a. camera I/O supply: U20 power mux, J22, C23, C24, D1 --
X, Y = 71.12, 340.36
o += symbol("Power_Management:TPS2116DRL", "U20", "TPS2116DRL", X, Y, 0, [str(k) for k in range(1, 9)],
            fp="Package_TO_SOT_SMD:SOT-583-8",
            desc="Power mux for +VCAM: VIN2 (+1V8) with J22 open, VIN1 (+3V3) with J22 fitted. MODE = VIN1, PR1 threshold 1.0 V.",
            ref_at=(X - 7.62, Y - 9.144, 0, "left"), val_at=(X, Y - 9.144, 0, "left"))
xl, xr = X - 10.16, X + 10.16
# VIN1 = +1V8 (U9; its output capacitor C7 is the VIN1 capacitor)
o += wire((xl, Y - 5.08), (xl - 5.08, Y - 5.08)) + power("+1V8", xl - 5.08, Y - 5.08, 0)
# PR1 = VCAM_SEL
o += wire((xl, Y - G), (xl - 10.16, Y - G)) + label("VCAM_SEL", xl - 10.16, Y - G, "right")
# MODE and VIN2 = +3V3 (Pico 3V3_OUT), with C24
o += wire((xl, Y + G), (xl - G, Y + G), (xl - G, Y + 5.08))
o += wire((xl, Y + 5.08), (xl - G, Y + 5.08), (xl - 22.86, Y + 5.08), (xl - 22.86, Y + 2.54)) + junction(xl - G, Y + 5.08)
o += power("+3V3", xl - 22.86, Y + 2.54, 0) + junction(xl - 15.24, Y + 5.08)
o += cap("C24", "1uF", xl - 15.24, Y + 8.89, "+3V3 input capacitor of U20 (VIN2)", -1) + power("GND", xl - 15.24, Y + 12.7)
# VOUT = +VCAM, C23, D1 + R33
vx = xr + 10.16
o += wire((xr, Y - 5.08), (vx, Y - 5.08), (vx + 10.16, Y - 5.08)) + junction(vx, Y - 5.08) + power("+VCAM", vx, Y - 5.08, 0)
o += cap("C23", "1uF", vx, Y - 1.27, "+VCAM output capacitor of U20") + power("GND", vx, Y + G)
o += wire((vx, Y - 5.08), (vx + 5.08, Y - 5.08))                         # R51: bleed, discharges +VCAM when J22 is removed
o += junction(vx + 5.08, Y - 5.08) + res_v("R51", "4.7k", vx + 5.08, Y - G, "+VCAM bleed resistor: 6 ms discharge after a change from 3.3 V to 1.8 V") + power("GND", vx + 5.08, Y)
o += res_h("R33", "100", vx + 12.7, Y - 5.08, "D1 series resistor")
o += led("D1", "Blue", vx + 19.05, Y - 5.08, "3.3 V indicator on +VCAM: a blue LED (Vf > 2.5 V) is dark at 1.8 V and lit at 3.3 V")
o += power("GND", vx + 22.86, Y - 5.08)
o += noconn(xr, Y + 5.08) + power("GND", X, Y + 10.16)
# J22 and the PR1 network
jx, jy = 27.94, 363.22
o += symbol("Connector:Conn_01x02_Pin", "J22", "3V3 camera I/O", jx, jy, 0, ["1", "2"],
            fp="Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
            desc="Camera I/O voltage: open = 1.8 V (IDS), shunt = 3.3 V (Prophesee EVK4). Fit the shunt only with no 1.8 V camera connected.",
            ref_at=(jx - 3.556, jy - 2.286, 0), val_at=(jx - 1.27, jy + 5.842, 0))
o += wire((jx + 5.08, jy), (jx + 10.16, jy)) + power("GND", jx + 10.16, jy)
o += wire((jx + 5.08, jy + G), (jx + 7.62, jy + G), (jx + 7.62, jy + 7.62), (jx + 12.7, jy + 7.62))
o += res_h("R35", "1k", jx + 15.24, jy + 7.62, "Series resistor between J22 and PR1 of U20")
o += wire((jx + 17.78, jy + 7.62), (jx + 22.86, jy + 7.62), (jx + 30.48, jy + 7.62)) + junction(jx + 22.86, jy + 7.62)
o += label("VCAM_SEL", jx + 30.48, jy + 7.62, "left")
o += res_v("R34", "10k", jx + 22.86, jy + 5.08, "PR1 pull-up: with J22 open the mux passes VIN1 = +1V8") + power("+3V3", jx + 22.86, jy + G, 0)
o += text("Camera I/O supply +VCAM (U1-U6). J22 open: 1.8 V (IDS uEye EVS). J22 fitted: 3.3 V (Prophesee EVK4).\n"
          "U20 (MODE high): PR1 high = VIN1 (+1V8), PR1 low = VIN2 (+3V3). R34 holds PR1 high with J22 open.\n"
          "A bridge from PR1 to pin 3 or pin 5, an open MODE pin or a missing Pico cannot give 3.3 V.\n"
          "D1 (blue) lights at 3.3 V only. Do not fit J22 with an IDS camera connected.", 20.32, 322.58)

# -- 4b. status LEDs: D2 "12 V good", D3 "ARMED" --
qx, qy = 160.02, 353.06
o += nfet("Q1", qx, qy, "Switch for D2 and D3: on while LASER_PWR_OK is high (+12 V in its window)")
o += wire((qx - 5.08, qy), (qx - 10.16, qy)) + label("LASER_PWR_OK", qx - 10.16, qy, "right") + power("GND", qx + G, qy + 5.08)
ny = qy - 5.08                                           # node PWR_OK_N = Q1 drain
o += power("+5V", qx - 20.32, ny - 5.08, 0) + wire((qx - 20.32, ny - 5.08), (qx - 17.78, ny - 5.08))
o += res_h("R36", "1k", qx - 15.24, ny - 5.08, "D2 series resistor")
o += led("D2", "Green", qx - 8.89, ny - 5.08, "12 V good: +12 V rail in its window (USB-C PD 15 V contract made, U17 regulating)")
o += wire((qx - 5.08, ny - 5.08), (qx + G, ny - 5.08), (qx + G, ny)) 
q2x, q2y = qx + 20.32, ny - 10.16
o += nfet("Q2", q2x, q2y, "Switch for D3: on while the firmware drives ARMED_LED (GP17) high")
o += wire((q2x + G, q2y + 5.08), (q2x + G, ny), (qx + G, ny)) + junction(qx + G, ny)
o += wire((q2x - 5.08, q2y), (q2x - 10.16, q2y), (q2x - 12.7, q2y)) + junction(q2x - 10.16, q2y) + label("ARMED_LED", q2x - 12.7, q2y, "right")
o += res_v("R38", "100k", q2x - 10.16, q2y + G, "Q2 gate pull-down: D3 off while GP17 is not driven (reset, no Pico)") + power("GND", q2x - 10.16, q2y + 5.08)
ay = q2y - 10.16
o += wire((q2x + G, q2y - 5.08), (q2x + G, ay), (q2x, ay))
o += led("D3", "Red", q2x - 3.81, ay, "ARMED: firmware ARMED and J11 interlock closed and +12 V good")
o += res_h("R37", "1k", q2x - 10.16, ay, "D3 series resistor, fed from LASER_EN (U10 output)")
o += wire((q2x - 12.7, ay), (q2x - 15.24, ay)) + label("LASER_EN", q2x - 15.24, ay, "right")
o += text("Status LEDs. D2 (green): +12 V in its window (LASER_PWR_OK).\n"
          "D3 (red) ARMED: current flows LASER_EN -> D3 -> Q2 -> Q1, so D3 is lit only if\n"
          "J11 is closed (LASER_EN), the firmware is ARMED (GP17 high) and +12 V is good.", 134.62, 322.58)

# -- 4c. output activity LEDs: U21 (Laser 1), U22 (Laser 2), U23 (External Sync Out) --
for k, (src, sense, what, colour) in enumerate((("CH1_DRIVE_RAW", "CH1_SENSE", "Laser 1 (J7)", "Red"),
                                                ("CH2_DRIVE_RAW", "CH2_SENSE", "Laser 2 (J8)", "Red"),
                                                ("EXT_SYNC_DRIVE_RAW", "SYNC_SENSE", "External Sync Out (J12)", "Yellow"))):
    ux, uy = 281.94 + 119.38 * k, 345.44
    u, r0, c0 = "U%d" % (21 + k), 39 + 4 * k, 25 + 2 * k
    o += symbol("74xGxx:74LVC1G123", u, "74LVC1G123", ux, uy, 0, ["1", "2", "3", "5", "6", "7"], fp="Package_SO:SSOP-8_2.95x2.8mm_P0.65mm",
                desc="Pulse stretcher for the %s activity LED: each pulse of 3 ns or more gives about 15 ms" % what,
                ref_at=(ux - 7.62, uy - 9.144, 0, "left"), val_at=(ux + 1.27, uy - 9.144, 0, "left"))
    pl = ux - 12.7
    # RCext: R to +5V, C to Cext
    o += wire((pl, uy - 5.08), (pl - 7.62, uy - 5.08), (pl - 12.7, uy - 5.08)) + junction(pl - 7.62, uy - 5.08)
    o += res_v("R%d" % (r0 + 2), "150k", pl - 7.62, uy - 7.62, "Timing resistor (with C%d: about 15 ms)" % c0) + power("+3V3", pl - 7.62, uy - 10.16, 0)
    o += cap("C%d" % c0, "0.1uF", pl - 12.7, uy - 1.27, "Timing capacitor of %s" % u, -1)
    o += wire((pl, uy - G), (pl - 10.16, uy - G), (pl - 10.16, uy + G), (pl - 12.7, uy + G))
    # /A low (global GND label, as at the Pico pins), B = sense, /CLR high
    o += ('\t(global_label "GND"\n\t\t(shape bidirectional)\n\t\t(at %s %s 180)\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n'
          '\t\t\t(justify right)\n\t\t)\n\t\t(uuid "%s")\n\t\t(property "Intersheetrefs" "${INTERSHEET_REFS}"\n\t\t\t(at %s %s 0)\n'
          '\t\t\t(hide yes)\n\t\t\t(show_name no)\n\t\t\t(do_not_autoplace no)\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n'
          '\t\t\t\t)\n\t\t\t)\n\t\t)\n\t)\n' % (n(pl), n(uy + G), uid(), n(pl), n(uy + G)))
    by = uy + 5.08
    o += wire((pl, by), (pl - 10.16, by), (pl - 17.78, by), (pl - 19.05, by), (pl - 20.32, by))
    o += junction(pl - 17.78, by) + junction(pl - 10.16, by) + junction(pl - 19.05, by) + label(sense, pl - 8.89, by, "left")
    o += res_v("R%d" % (r0 + 1), "4.7k", pl - 17.78, by + G, "Sense divider, lower resistor") + power("GND", pl - 17.78, by + 5.08)
    o += res_h("R%d" % r0, "10k", pl - 22.86, by, "Sense divider, upper resistor: 12 V driver output to 3.7-3.9 V at %s pin B" % u)
    o += wire((pl - 25.4, by), (pl - 26.67, by), (pl - 27.94, by)) + junction(pl - 26.67, by) + label(src, pl - 27.94, by, "right")
    # compensation: C_top across the upper resistor, C_bot across the lower one (C_top / C_bot = R_bot / R_top)
    ct, cb = "C%d" % (31 + 2 * k), "C%d" % (32 + 2 * k)
    o += symbol("Device:C", ct, "12pF", pl - 22.86, by - 5.08, 90, ["1", "2"], fp=C0805,
                desc="Sense divider compensation, across the upper resistor (C0G)",
                ref_at=(pl - 22.86, by - 9.652, 90), val_at=(pl - 22.86, by - 7.874, 90))
    o += wire((pl - 26.67, by), (pl - 26.67, by - 5.08)) + wire((pl - 19.05, by), (pl - 19.05, by - 5.08))
    o += cap(cb, "22pF", pl - 10.16, by + 3.81, "Sense divider compensation, across the lower resistor (C0G)") + power("GND", pl - 10.16, by + 7.62)
    o += power("+3V3", ux, uy + 12.7, 180)
    # Q -> R -> LED -> GND
    qy2 = uy - 5.08
    o += wire((ux + 12.7, qy2), (ux + 15.24, qy2)) + res_h("R%d" % (r0 + 3), "750", ux + 17.78, qy2, "Activity LED series resistor")
    o += led("D%d" % (4 + k), colour, ux + 24.13, qy2, "Activity: flashes for each pulse at the %s driver output" % what)
    o += power("GND", ux + 27.94, qy2)
    # supply unit and decoupling
    sx, sy = ux + 35.56, uy + 12.7
    o += symbol("74xGxx:74LVC1G123", u, "74LVC1G123", sx, sy, 0, ["4", "8"], fp="Package_SO:SSOP-8_2.95x2.8mm_P0.65mm",
                desc="Pulse stretcher for the %s activity LED: each pulse of 3 ns or more gives about 15 ms" % what,
                ref_at=(sx + 6.35, sy + 3.81, 0, "left"), val_at=(sx + 6.35, sy + 6.35, 0, "left"), unit=2)
    o += power("+3V3", sx, sy - 12.7, 0) + power("GND", sx, sy + 12.7)
    o += wire((sx, sy - 12.7), (sx + 10.16, sy - 12.7), (sx + 10.16, sy - 10.16))
    o += cap("C%d" % (c0 + 1), "0.1uF", sx + 10.16, sy - 6.35, "Decoupling of %s" % u) + power("GND", sx + 10.16, sy - G)
o += text("Output activity LEDs. Each monostable (VCC = +3V3, VIH 2.0 V) is triggered by the rising edge at its 12 V driver output\n"
          "(after all three laser gates), divided to about 3.8 V by a compensated divider: 10k / 4.7k with 12 pF / 22 pF.\n"
          "One pulse gives a flash of about 15 ms; above about 70 Hz the LED is on continuously. Load on each driver: 0.8 mA.", 243.84, 322.58)

# -- 4d. rail test pads (top-layer taps of the In2 power islands) --
TX, TY = 304.8, 248.92
for k, (ref, net) in enumerate((("TP4", "+12V"), ("TP5", "+5V"), ("TP6", "+3V3"), ("TP7", "+1V8"), ("TP8", "+VCAM"), ("TP9", "GND"))):
    x = TX + 10.16 * k
    o += symbol("Connector:TestPoint", ref, net, x, TY, 0, ["1"], fp="TestPoint:TestPoint_Pad_D1.5mm",
                desc="Rail test pad (top-layer tap of the In2 power island)", bom=False,
                ref_at=(x, TY - 6.858, 0), val_at=(x, TY - 5.08, 0))
    o += wire((x, TY), (x, TY + G)) + power(net, x, TY + G, 0 if net == "GND" else 180)
o += text("Rail test pads TP4-TP9 (bare 1.5 mm pads, no part): one tap on each In2 power island and on GND.", TX - 5.08, TY - 10.16)

i1 = s.rindex("\t(sheet_instances")
s = s[:i1] + ser + o + s[i1:]

# ---- 5. paper and title block -----------------------------------------------------------------------
s = s.replace('(paper "A3")', '(paper "A2")', 1)
s = re.sub(r'\(title "IDS EVS Event-camera Synchronizer \(Pico 2\)"\)', '(title "Event-camera Synchronizer, IDS EVS / Prophesee EVK4 (Pico 2)")', s, count=1)
s = re.sub(r'(\(title_block.*?\(date ")[^"]+(")', r'\g<1>2026-11-12\2', s, count=1, flags=re.S)
s = re.sub(r'(\(title_block.*?\(rev ")[^"]+(")', r'\g<1>2\2', s, count=1, flags=re.S)
open(DST, "w", encoding="utf-8", newline="\n").write(s)

# ---- 6. project symbol library: add +VCAM ------------------------------------------------------------
if LOCAL_LIB:
    L = open(LOCAL_LIB, encoding="utf-8").read()
    if '(symbol "+VCAM"' not in L:
        v = vcam.replace('"PiEBV_Local:+VCAM"', '"+VCAM"')
        for tok in ("(in_pos_files yes)", "(duplicate_pin_numbers_are_jumpers no)", "(show_name no)", "(do_not_autoplace no)"):
            v = re.sub(r"\n\t*" + re.escape(tok), "", v)
        v = "\n".join(l[1:] if l.startswith("\t") else l for l in v.split("\n"))
        L = L.rstrip()[:-1].rstrip() + "\n\t" + v + "\n)\n"
        open(LOCAL_LIB, "w", encoding="utf-8", newline="\n").write(L)
print("sch_edit: %d supply symbols moved to +VCAM; U20-U23, Q1, Q2, D1-D6, J22, C23-C36, R33-R69, TP4-TP9 added" % moved)
