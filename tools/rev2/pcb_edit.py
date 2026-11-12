#!/usr/bin/env python3
"""Rev 2 board edit: +VCAM power mux, status LEDs, rail test pads, In2 power islands.

Reads the Rev 1 board and the Rev 2 netlist and writes the Rev 2 board. It changes only what
Rev 2 needs: the camera lines, the laser pulse lanes and the output block keep their copper.

  1. nets: the netlist's new nets are added; the U1-U6 / C1-C3 supply copper moves to +VCAM;
  2. U9, C6 and C7 move to the top-centre supply block (their local copper is drawn again);
  3. new parts are placed and routed by hand-written coordinates (F.Cu, with B.Cu links);
  4. In2.Cu: the single +5V plane becomes islands (+5V, +3V3, +1V8, +VCAM, +12V) in a GND fill;
  5. silkscreen for the new parts; title block Rev 2.

Run with KiCad 10's Python:
  kicad-cli sch export netlist --format kicadsexpr -o rev2.net PiEBV_Pico.kicad_sch
  python pcb_edit.py REV1.kicad_pcb rev2.net OUT.kicad_pcb [KICAD_FOOTPRINT_DIR]
Then refill the zones and run DRC:
  kicad-cli pcb drc --schematic-parity --severity-all --refill-zones --save-board OUT.kicad_pcb
"""
import math
import re
import sys

import pcbnew

SRC, NET, DST = sys.argv[1:4]
FPDIR = sys.argv[4] if len(sys.argv) > 4 else "/usr/share/kicad/footprints"
b = pcbnew.LoadBoard(SRC)
MM = pcbnew.FromMM
F, B, IN2 = pcbnew.F_Cu, pcbnew.B_Cu, b.GetLayerID("In2.Cu")
SILK, FAB = b.GetLayerID("F.Silkscreen"), b.GetLayerID("F.Fab")


def P(x, y):
    return pcbnew.VECTOR2I(MM(x), MM(y))


def mm(v):
    return pcbnew.ToMM(v)


# ---- netlist -----------------------------------------------------------------------------------------
def sexpr(t):
    """Minimal S-expression reader: nested lists of strings."""
    tok = re.findall(r'"(?:[^"\\]|\\.)*"|[()]|[^\s()]+', t)
    pos = [0]

    def rd():
        out = []
        while pos[0] < len(tok):
            k = tok[pos[0]]
            pos[0] += 1
            if k == "(":
                out.append(rd())
            elif k == ")":
                return out
            else:
                out.append(k[1:-1].replace('\\"', '"') if k.startswith('"') else k)
        return out
    return rd()[0]


def find(node, key):
    return [c for c in node if isinstance(c, list) and c and c[0] == key]


nl = sexpr(open(NET, encoding="utf-8").read())
COMP = {}
for c in find(find(nl, "components")[0], "comp"):
    ref = find(c, "ref")[0][1]
    fields = {}
    for f in find(find(c, "fields")[0], "field") if find(c, "fields") else []:
        fields[find(f, "name")[0][1]] = f[2] if len(f) > 2 and isinstance(f[2], str) else ""
    COMP[ref] = dict(value=find(c, "value")[0][1], fp=find(c, "footprint")[0][1] if find(c, "footprint") else "",
                     uuid=find(c, "tstamps")[0][1], desc=fields.get("Description", ""), ds=fields.get("Datasheet", ""))
PADNET = {}
for nnode in find(find(nl, "nets")[0], "net"):
    name = find(nnode, "name")[0][1].lstrip("/")          # the board's net names have no root-sheet "/"
    for nd in find(nnode, "node"):
        PADNET[(find(nd, "ref")[0][1], find(nd, "pin")[0][1])] = name


def net(name):
    n = b.FindNet(name)
    if n is None:
        n = pcbnew.NETINFO_ITEM(b, name)
        b.Add(n)
    return n


# ---- copper helpers ------------------------------------------------------------------------------------
def track(name, pts, w=0.3, layer=F):
    for a, c in zip(pts, pts[1:]):
        t = pcbnew.PCB_TRACK(b)
        t.SetStart(P(*a))
        t.SetEnd(P(*c))
        t.SetWidth(MM(w))
        t.SetLayer(layer)
        t.SetNet(net(name))
        b.Add(t)


def via(name, x, y):
    v = pcbnew.PCB_VIA(b)
    v.SetPosition(P(x, y))
    v.SetWidth(F, MM(0.6))
    v.SetDrill(MM(0.3))
    v.SetLayerPair(F, B)
    v.SetNet(net(name))
    b.Add(v)


def near(p, x, y, tol=0.03):
    return abs(mm(p.x) - x) < tol and abs(mm(p.y) - y) < tol


# The Rev 1 copper is read once. On some KiCad 10 builds BOARD.Tracks() stops working after a few
# BOARD.Remove() calls, so the list is kept here and removed items stay referenced in GONE.
OLD = list(b.Tracks())
GONE = []


def drop_track(name, a, c):
    """Remove the track of net `name` with end points a and c (either order)."""
    for t in OLD:
        if t.Type() == pcbnew.PCB_VIA_T or t.GetNetname() != name:
            continue
        s, e = t.GetStart(), t.GetEnd()
        if (near(s, *a) and near(e, *c)) or (near(s, *c) and near(e, *a)):
            b.Remove(t)
            OLD.remove(t)
            GONE.append(t)
            return
    raise SystemExit("track not found: %s %s %s" % (name, a, c))


def drop_via(name, x, y):
    for t in OLD:
        if t.Type() == pcbnew.PCB_VIA_T and t.GetNetname() == name and near(t.GetPosition(), x, y):
            b.Remove(t)
            OLD.remove(t)
            GONE.append(t)
            return
    raise SystemExit("via not found: %s %s %s" % (name, x, y))


def pad_xy(ref, num):
    p = b.FindFootprintByReference(ref).FindPadByNumber(num).GetPosition()
    return mm(p.x), mm(p.y)


def check_pad(ref, num, x, y, tol=0.03):
    px, py = pad_xy(ref, num)
    assert abs(px - x) < tol and abs(py - y) < tol, "%s.%s at %.3f %.3f, expected %.3f %.3f" % (ref, num, px, py, x, y)


def ref_text(fp, dx, dy, size=0.8, show=True, angle=0):
    r = fp.Reference()
    r.SetVisible(show)
    r.SetLayer(SILK)
    r.SetTextSize(pcbnew.VECTOR2I(MM(size), MM(size)))
    r.SetTextThickness(MM(0.12))
    r.SetTextAngleDegrees(angle)
    c = fp.GetPosition()
    r.SetPosition(pcbnew.VECTOR2I(c.x + MM(dx), c.y + MM(dy)))


def place(ref, x, y, angle, rdx=None, rdy=None, rang=0):
    """Add the netlist part `ref` at (x, y). The reference text goes to (rdx, rdy) from the centre, or is hidden."""
    c = COMP[ref]
    lib, name = c["fp"].split(":")
    libdir = FPDIR + "/" + lib + ".pretty"
    fp = pcbnew.FootprintLoad(libdir, name)
    assert fp is not None, c["fp"]
    fp.SetFPID(pcbnew.LIB_ID(lib, name))
    fp.SetReference(ref)
    fp.SetValue(c["value"])
    fp.SetPosition(P(x, y))
    fp.SetOrientationDegrees(angle)
    fp.SetPath(pcbnew.KIID_PATH("/" + c["uuid"]))
    fp.SetSheetname("/")
    fp.SetSheetfile("PiEBV_Pico.kicad_sch")
    for fld in fp.GetFields():
        if fld.GetName() == "Description":
            fld.SetText(c["desc"])
        elif fld.GetName() == "Datasheet":
            fld.SetText(c["ds"])
    for p in fp.Pads():
        n = PADNET.get((ref, p.GetNumber()))
        if n:
            p.SetNet(net(n))
    b.Add(fp)
    ref_text(fp, rdx or 0, rdy or 0, show=rdx is not None, angle=rang)
    return fp


def move(ref, x, y, angle):
    fp = b.FindFootprintByReference(ref)
    fp.SetPosition(P(x, y))
    fp.SetOrientationDegrees(angle)
    return fp


def silk(text, x, y, size=0.8, just=0, angle=0):
    """Silkscreen text. just: -1 left, 0 centre, 1 right."""
    t = pcbnew.PCB_TEXT(b)
    t.SetText(text)
    t.SetLayer(SILK)
    t.SetPosition(P(x, y))
    t.SetTextSize(pcbnew.VECTOR2I(MM(size), MM(size)))
    t.SetTextThickness(MM(0.15))
    t.SetHorizJustify({-1: pcbnew.GR_TEXT_H_ALIGN_LEFT, 0: pcbnew.GR_TEXT_H_ALIGN_CENTER, 1: pcbnew.GR_TEXT_H_ALIGN_RIGHT}[just])
    t.SetTextAngleDegrees(angle)
    b.Add(t)


# ---- 1. nets: every part's pads follow the netlist; old +1V8 copper at the buffers becomes +VCAM ----------
for fp in b.GetFootprints():
    for p in fp.Pads():
        n = PADNET.get((fp.GetReference(), p.GetNumber()))
        if n and not n.startswith("unconnected-") and p.GetNetname() != n:
            assert (p.GetNetname(), n) in (("+1V8", "+VCAM"), ("", "ARMED_LED")), (fp.GetReference(), p.GetNumber(), p.GetNetname(), n)
            p.SetNet(net(n))

# ---- 2. U9 / C6 / C7 leave their Rev 1 site ------------------------------------------------------------------
for name, a, c in (("GND", (214.5, 75.463), (214.5, 74.875)), ("GND", (214.5, 74.325), (214.5, 74.875)),
                   ("GND", (221.938, 82.05), (222.525, 82.05)), ("GND", (223.075, 82.05), (222.525, 82.05)),
                   ("GND", (213.32, 83.0), (213.87, 83.0)), ("GND", (214.65, 83.0), (213.87, 83.0)),
                   ("+5V", (214.5, 77.537), (214.5, 78.675)), ("+5V", (214.65, 82.05), (213.32, 82.05)),
                   ("+5V", (214.65, 83.95), (213.32, 83.95)),
                   ("+1V8", (219.9, 82.0), (217.4, 82.0)), ("+1V8", (220.4, 82.5), (220.8, 82.9)),
                   ("+1V8", (220.8, 82.9), (220.8, 84.8)),
                   ("+3V3", (145.0, 39.1), (188.4, 39.1)), ("+3V3", (143.0, 41.1), (145.0, 39.1))):
    drop_track(name, a, c)
for name, x, y in (("GND", 214.5, 74.325), ("GND", 223.075, 82.05), ("GND", 213.32, 83.0),
                   ("+5V", 214.5, 78.675), ("+5V", 213.32, 82.05), ("+5V", 213.32, 83.95)):
    drop_via(name, x, y)
for t in OLD:                                           # what is left of +1V8 copper is the buffer supply
    if t.GetNetname() == "+1V8":
        t.SetNet(net("+VCAM"))

ROW = 34.8                                              # y of the status LED row
# -- supply block: C6, U9, C7, U20, C23, C24, J22, R34, R35, D1, R33 --
move("C6", 212.6, 42.7, 270)
check_pad("C6", "1", 212.6, 41.6625)                    # +5V pad up
move("U9", 217.2, 42.7, 0)
move("C7", 221.8, 42.8, 270)
check_pad("C7", "1", 221.8, 41.7625)                    # +1V8 pad up
for fp, dx, dy in (("C6", 0, 2.9), ("U9", 0.4, 2.6), ("C7", 0, -2.5)):
    ref_text(b.FindFootprintByReference(fp), dx, dy)
track("+5V", [(215.85, 41.75), (214.52, 41.75)], 0.5)
track("+5V", [(215.85, 43.65), (214.52, 43.65)], 0.5)
track("+5V", [(212.6, 41.6625), (213.2, 41.75), (214.52, 41.75)], 0.5)
via("+5V", 214.52, 41.75)
via("+5V", 214.52, 43.65)
track("GND", [(215.85, 42.7), (214.52, 42.7)], 0.4)
via("GND", 214.52, 42.7)
track("GND", [(212.6, 43.7375), (212.6, 45.2)], 0.4)
via("GND", 212.6, 45.2)
track("GND", [(221.8, 43.8375), (221.8, 45.3)], 0.4)
via("GND", 221.8, 45.3)

place("U20", 229.6, 42.0, 180, None)
check_pad("U20", "5", 228.86, 41.25)
check_pad("U20", "3", 230.34, 41.75)
# +1V8: U9.5 -> C7.1 -> U20.6 (VIN2), with the tap via into the +1V8 island and TP7
track("+1V8", [(218.55, 41.75), (221.8, 41.75), (227.6, 41.75)], 0.4)
track("+1V8", [(227.6, 41.75), (228.86, 41.75)], 0.25)
via("+1V8", 223.7, 41.75)
place("TP7", 225.0, 43.75, 0, None)
track("+1V8", [(225.0, 41.75), (225.0, 43.75)], 0.4)
# +3V3: MODE (pin 5) and VIN1 (pin 3), each to its own via into the +3V3 island
track("+3V3", [(228.86, 41.25), (228.1, 41.25), (228.1, 39.3)], 0.25)
via("+3V3", 228.1, 39.3)
track("+3V3", [(230.34, 41.75), (231.2, 41.75), (231.9, 41.05)], 0.25)
via("+3V3", 231.9, 41.0)
place("C24", 233.2, 37.5, 90, None)
check_pad("C24", "1", 233.2, 38.5375)                   # +3V3 pad down
track("+3V3", [(233.2, 38.5375), (233.2, 40.0)], 0.4)
via("+3V3", 233.2, 40.0)
track("GND", [(233.2, 36.4625), (233.2, 35.0)], 0.4)
via("GND", 233.2, 35.0)
# PR1 (pin 4) = VCAM_SEL -> J22.2, R34 to GND; J22.1 -> R35 -> +3V3
place("J22", 229.6, 35.3, 0, None)
check_pad("J22", "2", 229.6, 37.84)
track("VCAM_SEL", [(230.34, 41.25), (230.34, 40.3), (229.6, 39.56), (229.6, 37.84)], 0.25)
place("R34", 225.7, 37.84, 180, None)
check_pad("R34", "1", 226.7, 37.84)
track("VCAM_SEL", [(226.7, 37.84), (229.6, 37.84)], 0.3)
track("GND", [(224.7, 37.84), (223.3, 37.84)], 0.4)
via("GND", 223.3, 37.84)
place("R35", 225.7, 35.3, 0, None)
check_pad("R35", "2", 226.7, 35.3)
track("Net-(J22-Pin_1)", [(226.7, 35.3), (229.6, 35.3)], 0.3)
track("+3V3", [(224.7, 35.3), (223.3, 35.3)], 0.4)
via("+3V3", 223.3, 35.3)
place("TP6", 220.9, 36.6, 0, None)
track("+3V3", [(220.9, 36.6), (222.2, 35.3), (223.3, 35.3)], 0.4)
# VOUT (pins 2 + 7) = +VCAM: bridge under the body, C23, two vias into the corridor of the +VCAM island, TP8
track("+VCAM", [(228.86, 42.25), (230.34, 42.25)], 0.25)
track("+VCAM", [(230.34, 42.25), (232.9, 42.25)], 0.25)
track("+VCAM", [(232.9, 42.25), (232.9, 44.4), (232.6375, 45.0), (232.6375, 45.6)], 0.4)
place("C23", 231.6, 45.6, 180, None)
check_pad("C23", "1", 232.6375, 45.6)                   # +VCAM pad east
track("GND", [(230.34, 42.75), (230.34, 44.1)], 0.25)
via("GND", 230.34, 44.1)
track("GND", [(230.34, 44.1), (230.5625, 45.0), (230.5625, 45.6)], 0.4)
track("+VCAM", [(232.6375, 45.6), (232.6375, 46.9), (231.9, 47.64), (231.9, 47.9)], 0.4)
via("+VCAM", 231.9, 47.9)
track("+VCAM", [(231.9, 47.9), (230.5, 47.9)], 0.4)
via("+VCAM", 230.5, 47.9)
place("TP8", 230.5, 50.3, 0, None)
track("+VCAM", [(230.5, 47.9), (230.5, 50.3)], 0.4)
# D1 (3.3 V indicator): +VCAM -> R33 -> D1 -> GND
place("R33", 235.5, 39.7, 90, None)
check_pad("R33", "1", 235.5, 40.7)                      # +VCAM pad down
place("D1", 235.5, 35.7, 270, None)
check_pad("D1", "2", 235.5, 36.725)                     # anode down
track("+VCAM", [(232.9, 42.25), (234.9, 42.25), (235.5, 41.65), (235.5, 40.7)], 0.3)
assert PADNET[("R33", "1")] == "+VCAM" and PADNET[("D1", "1")] == "GND"
track(PADNET[("D1", "2")], [(235.5, 38.7), (235.5, 36.725)], 0.3)
track("GND", [(235.5, 34.675), (236.2, 34.0), (237.0, 34.0)], 0.3)
via("GND", 237.0, 34.0)

# -- 12 V good (D2) and ARMED (D3): D2.K and Q2.S share Q1 --
place("D2", 200.5, ROW, 180, None)
check_pad("D2", "1", 201.525, ROW)                      # cathode east
place("R36", 198.7, 38.1, 90, None)
check_pad("R36", "2", 198.7, 37.1)
place("Q1", 201.525, 38.7, 90, None)
check_pad("Q1", "3", 201.525, 37.7625)                  # drain up; gate (1) lower left, source (2) lower right
check_pad("Q1", "1", 200.575, 39.6375)
place("D3", 206.5, ROW, 0, None)
check_pad("D3", "1", 205.475, ROW)                      # cathode west
place("Q2", 205.475, 38.7, 90, None)
place("R37", 208.3, 38.1, 90, None)
check_pad("R37", "1", 208.3, 39.1)                      # LASER_EN pad down
place("R38", 206.4, 44.2, 270, None)
check_pad("R38", "1", 206.4, 43.2)                      # ARMED_LED pad up
nD2A, nN, nD3A, nD3K = PADNET[("D2", "2")], PADNET[("D2", "1")], PADNET[("D3", "2")], PADNET[("D3", "1")]
track(nD2A, [(199.475, ROW), (199.475, 35.6), (198.7, 36.4), (198.7, 37.1)], 0.3)
track("+5V", [(198.7, 39.1), (198.7, 41.3)], 0.4)
via("+5V", 198.7, 41.3)
track(nN, [(201.525, ROW), (201.525, 37.7625)], 0.3)
track("GND", [(202.475, 39.6375), (202.475, 41.1)], 0.3)
via("GND", 202.475, 41.1)
track("LASER_PWR_OK", [(200.575, 39.6375), (200.575, 41.1)], 0.3)
via("LASER_PWR_OK", 200.575, 41.1)
track(nD3K, [(205.475, ROW), (205.475, 37.7625)], 0.3)
track(nN, [(206.425, 39.6375), (206.425, 41.1)], 0.3)   # Q2 source -> B.Cu link -> Q1 drain
via(nN, 206.425, 41.1)
track(nN, [(206.425, 41.1), (203.5, 41.1), (203.5, 36.9)], 0.3, B)
via(nN, 203.5, 36.9)
track(nN, [(203.5, 36.9), (201.525, 36.9)], 0.3)
track(nD3A, [(207.525, ROW), (207.525, 35.6), (208.3, 36.4), (208.3, 37.1)], 0.3)
# LASER_EN: U7.1 -> R37
track("LASER_EN", [(222.65, 52.85), (222.65, 51.0), (222.15, 50.5), (208.8, 50.5), (208.3, 50.0), (208.3, 39.1)], 0.3)
# ARMED_LED: J15.19 (GP17) -> Q2 gate, R38 to GND
track("ARMED_LED", [(178.105, 41.61), (178.105, 38.8), (178.605, 38.3), (194.0, 38.3), (198.3, 42.6), (204.525, 42.6),
                    (204.525, 39.6375)], 0.3)
track("ARMED_LED", [(204.525, 42.6), (206.4, 42.6), (206.4, 43.2)], 0.3)
track("GND", [(206.4, 45.2), (206.4, 46.6)], 0.3)
via("GND", 206.4, 46.6)
# LASER_PWR_OK: R16.2 -> via -> B.Cu -> Q1 gate via
track("LASER_PWR_OK", [(234.6, 55.8), (232.9, 55.8)], 0.3)
via("LASER_PWR_OK", 232.9, 55.8)
track("LASER_PWR_OK", [(232.9, 55.8), (225.9, 48.8), (200.575, 48.8), (200.575, 41.1)], 0.3, B)
place("TP5", 201.0, 45.0, 0, None)
track("+5V", [(201.0, 45.0), (202.6, 45.0)], 0.4)
via("+5V", 202.6, 45.0)

# -- output activity cells: U21 (Laser 1), U22 (Laser 2), U23 (External Sync Out) --
CY = ROW + 5.3


def cell(k, cx):
    u, r0, c0, d = "U%d" % (21 + k), 39 + 4 * k, 25 + 2 * k, "D%d" % (4 + k)
    rext, rled, cext, cdec = "R%d" % (r0 + 2), "R%d" % (r0 + 3), "C%d" % c0, "C%d" % (c0 + 1)
    X = lambda uu: cx + uu
    Y = lambda vv: CY + vv
    fpu = place(u, cx, CY, 180, None)
    for pn in ("1", "4"):
        fpu.FindPadByNumber(pn).SetLocalZoneConnection(pcbnew.ZONE_CONNECTION_FULL)
    check_pad(u, "5", X(-1.7), Y(-0.975))               # Q upper left, VCC (8) lower left, B (2) right
    check_pad(u, "2", X(1.7), Y(0.325))
    nq, nrc, nce, nla = PADNET[(u, "5")], PADNET[(u, "7")], PADNET[(u, "6")], PADNET[(d, "2")]
    sense = PADNET[(u, "2")]
    # Q -> R_led -> LED -> GND
    place(rled, X(-0.7), Y(-3.1), 0, None)
    track(nq, [(X(-1.7), Y(-0.975)), (X(-1.7), Y(-3.1))], 0.25)
    place(d, X(-0.725), Y(-5.3), 0, None)
    check_pad(d, "2", X(0.3), Y(-5.3))                  # anode east
    track(nla, [(X(0.3), Y(-3.1)), (X(0.3), Y(-5.3))], 0.3)
    track("GND", [(X(-1.75), Y(-5.3)), (X(-3.25), Y(-5.3))], 0.3)
    via("GND", X(-3.25), Y(-5.3))
    # timing: Cext between pins 6 and 7, Rext from pin 7 to +5V
    place(cext, X(-4.0), Y(0.0), 90, None)
    check_pad(cext, "2", X(-4.0), Y(-1.0375))
    assert PADNET[(cext, "2")] == nce and PADNET[(cext, "1")] == nrc
    track(nce, [(X(-1.7), Y(-0.325)), (X(-3.0), Y(-0.325)), (X(-3.4), Y(-0.7))], 0.25)
    track(nrc, [(X(-1.7), Y(0.325)), (X(-3.0), Y(0.325)), (X(-3.4), Y(0.7))], 0.25)
    place(rext, X(-4.0), Y(3.9), 90, None)
    check_pad(rext, "2", X(-4.0), Y(2.9))
    assert PADNET[(rext, "2")] == nrc and PADNET[(rext, "1")] == "+5V"
    track(nrc, [(X(-4.0), Y(1.0375)), (X(-4.0), Y(2.9))], 0.3)
    # supply: VCC (8) and /CLR (3) to +5V, decoupling
    place(cdec, X(-0.7), Y(3.1), 0, None)
    assert PADNET[(cdec, "1")] == "+5V"
    track("+5V", [(X(-1.7), Y(0.975)), (X(-1.7), Y(3.1))], 0.25)
    track("+5V", [(X(1.7), Y(-0.325)), (X(0.0), Y(-0.325)), (X(0.0), Y(0.975)), (X(-1.7), Y(0.975))], 0.2)
    track("+5V", [(X(-1.7375), Y(3.1)), (X(-1.74), Y(4.75))], 0.4)
    via("+5V", X(-1.74), Y(4.75))
    track("+5V", [(X(-1.74), Y(4.75)), (X(-2.6), Y(4.75)), (X(-2.9), Y(4.9)), (X(-4.0), Y(4.9))], 0.3)
    # grounds: pin 4, pin 1 (/A) and the decoupling capacitor
    track("GND", [(X(1.7), Y(-0.975)), (X(2.9), Y(-0.975)), (X(2.9), Y(-2.3))], 0.25)
    via("GND", X(2.9), Y(-2.3))
    track("GND", [(X(1.7), Y(0.975)), (X(2.9), Y(0.975)), (X(2.9), Y(2.6)), (X(2.5), Y(3.1))], 0.25)
    via("GND", X(2.5), Y(3.1))
    track("GND", [(X(0.3375), Y(3.1)), (X(2.5), Y(3.1))], 0.3)
    # B (pin 2): out to the east side of the cell
    track(sense, [(X(1.7), Y(0.325)), (X(3.6), Y(0.325))], 0.25)
    return X(3.6), Y(0.325)


e1 = cell(0, 241.8)
e2 = cell(1, 250.8)
e3 = cell(2, 259.8)
# Laser 1: divider R39 / R40 above R6.1
place("R39", 247.1, 55.2, 90, None)
check_pad("R39", "1", 247.1, 56.2)
place("R40", 245.0, 55.2, 270, None)
check_pad("R40", "1", 245.0, 54.2)
track("CH1_DRIVE_RAW", [(247.1, 56.2), (247.1, 59.2)], 0.3)
track("CH1_SENSE", [(245.0, 54.2), (247.1, 54.2)], 0.3)
track("GND", [(245.0, 56.2), (245.0, 57.7)], 0.3)
via("GND", 245.0, 57.7)
track("CH1_SENSE", [(247.1, 54.2), (247.1, 49.0), (e1[0], 49.0 - (247.1 - e1[0])), e1], 0.3)
# Laser 2: divider R43 / R44 below R7.1, B.Cu link to the cell
place("R43", 247.1, 68.3, 270, None)
check_pad("R43", "1", 247.1, 67.3)
place("R44", 244.9, 68.3, 90, None)
check_pad("R44", "1", 244.9, 69.3)
track("CH2_DRIVE_RAW", [(247.1, 64.2), (247.1, 67.3)], 0.3)
track("CH2_SENSE", [(244.9, 69.3), (247.1, 69.3), (248.7, 69.3)], 0.3)
via("CH2_SENSE", 248.7, 69.3)
track("GND", [(244.9, 67.3), (243.4, 67.3)], 0.3)
via("GND", 243.4, 67.3)
track("CH2_SENSE", [(248.7, 69.3), (248.7, 53.0), (e2[0], 53.0 - (e2[0] - 248.7))], 0.3, B)
via("CH2_SENSE", e2[0], 53.0 - (e2[0] - 248.7))
track("CH2_SENSE", [(e2[0], 53.0 - (e2[0] - 248.7)), e2], 0.3)
# External Sync Out: divider R47 / R48 above R30.1, B.Cu link to the cell
place("R47", 252.9, 92.7, 90, None)
check_pad("R47", "1", 252.9, 93.7)
place("R48", 255.1, 92.7, 270, None)
check_pad("R48", "1", 255.1, 91.7)
track("EXT_SYNC_DRIVE_RAW", [(252.9, 93.7), (252.9, 96.7)], 0.3)
track("SYNC_SENSE", [(255.1, 91.7), (252.9, 91.7), (252.9, 90.2)], 0.3)
via("SYNC_SENSE", 252.9, 90.2)
track("GND", [(255.1, 93.7), (256.6, 93.7)], 0.3)
via("GND", 256.6, 93.7)
track("SYNC_SENSE", [(252.9, 90.2), (252.9, 53.6), (260.3, 46.2), (e3[0], 46.2)], 0.3, B)
via("SYNC_SENSE", e3[0], 46.2)
track("SYNC_SENSE", [(e3[0], 46.2), e3], 0.3)

# -- remaining rail test pads and island taps --
place("TP4", 237.0, 50.0, 0, None)
track("+12V", [(237.0, 50.0), (238.6, 50.0)], 0.4)
via("+12V", 238.6, 50.0)
place("TP9", 240.6, 48.6, 0, None)
track("GND", [(240.6, 48.6), (242.2, 48.6)], 0.4)
via("GND", 242.2, 48.6)
via("+3V3", 188.4, 39.1)
via("+VCAM", 231.5, 88.46)                              # U5 / U6 / C3 group: tap into the +VCAM island
via("+12V", 235.6, 76.9)                                # U17 output: second tap into the +12V island (C17.1 / R12.1)
track("+12V", [(236.41, 75.75), (235.6, 76.9)], 0.4)

# ---- 4. In2.Cu: power islands in a GND fill ----------------------------------------------------------------
from shapely.geometry import box, Polygon
from shapely.ops import unary_union

GAP = 0.5                                               # copper gap between two islands
I33 = unary_union([box(138.9, 30.5, 234.4, 39.9),       # +3V3: band along the top edge, from J15.5 to U20
                   box(141.35, 39.9, 143.75, 42.9),     #   tab down to the J15.5 socket pad
                   box(231.2, 39.5, 233.9, 41.7)])      #   lobe: U20 VIN1 via and C24 via
I18 = box(223.0, 40.45, 227.3, 42.9)                    # +1V8: patch under the U9 output track (tap via, C7)
I12 = unary_union([box(233.05, 47.0, 250.4, 80.5),      # +12V: U13, U17 and the U17 output capacitors
                   box(244.6, 80.0, 250.4, 101.5)])     #   lobe to C22 / C21 / U19
I12 = I12.difference(Polygon([(233.0, 78.0), (233.0, 80.6), (235.6, 80.6)]))   # corner cut: PWM_TRIG_TAP (B.Cu) stays over +VCAM
IVC = unary_union([box(183.2, 86.8, 260.0, 129.5),      # +VCAM: under U1-U6 and every B.Cu camera line
                   box(228.05, 47.0, 232.55, 87.5),     #   corridor up to U20 / C23
                   box(228.05, 81.0, 244.1, 87.5),
                   box(232.5, 77.0, 236.5, 81.5)])      #   under the PWM_TRIG_TAP run past the +12V corner
IVC = IVC.difference(I12.buffer(GAP, join_style=2))
I5 = Polygon([(130.5, 30.5), (265.0, 30.5), (265.0, 46.5), (227.55, 46.5), (227.55, 86.3), (182.7, 86.3),
              (182.7, 129.5), (130.5, 129.5)])          # +5V: Pico VSYS, U16, logic, status LED strip
I5 = I5.difference(unary_union([I33, I18, IVC, I12]).buffer(GAP, join_style=2))
ISLANDS = (("+5V", I5), ("+3V3", I33), ("+1V8", I18), ("+VCAM", IVC), ("+12V", I12))

old = [z for z in b.Zones() if z.GetNetname() == "+5V" and z.IsOnLayer(IN2)]
assert len(old) == 1
old = old[0]


def zone(name, poly, prio):
    assert poly.geom_type == "Polygon" and not poly.interiors, (name, poly.geom_type)
    z = pcbnew.Cast_to_ZONE(old.Duplicate(False))
    z.SetNet(net(name))
    z.SetAssignedPriority(prio)
    z.SetZoneName("In2 %s island" % name if prio else "In2 GND fill")
    o = z.Outline()
    o.RemoveAllContours()
    o.NewOutline()
    for x, y in list(poly.exterior.coords)[:-1]:
        o.Append(MM(round(x, 4)), MM(round(y, 4)))
    z.UnFill()
    b.Add(z)


for name, poly in ISLANDS:
    zone(name, poly, 1)
zone("GND", box(130.0, 30.0, 290.0, 130.0), 0)          # the rest of In2 is GND (lower priority: cut back from the islands)
b.Remove(old)

# ---- 5. silkscreen and title block ----------------------------------------------------------------------------
LY = ROW - 1.75
for x, t in ((200.5, "12V OK"), (206.5, "ARMED"), (229.6, "J22"), (235.5, "3V3"), (241.075, "L1"), (250.075, "L2"), (259.075, "SYNC")):
    silk(t, x, LY)
silk("CAMERA I/O LEVEL (J22)", 212.6, 47.2, just=-1)
silk("OPEN = 1V8  IDS", 212.6, 48.6, just=-1)
silk("SHUNT = 3V3  EVK4", 212.6, 50.0, just=-1)
for x, y, t, j in ((235.6, 50.0, "12V", 1), (199.6, 45.0, "5V", 1), (220.9, 38.2, "3V3", 0), (226.6, 44.3, "1V8", -1),
                   (229.2, 50.9, "VCAM", 1), (240.6, 47.0, "GND", 0)):
    silk(t, x, y, just=j)
tb = b.GetTitleBlock()
tb.SetTitle("Event-camera Synchronizer, IDS EVS / Prophesee EVK4 (Pico 2, EuroCard 160 x 100)")
tb.SetRevision("2")
tb.SetDate("2026-11-12")

pcbnew.SaveBoard(DST, b, True)                         # True: do not write the project settings (.kicad_pro)
print("pcb_edit: Rev 2 board written")
