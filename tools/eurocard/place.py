# EuroCard (160 x 100 mm) re-placement of PiEBV_Pico.kicad_pcb with KiCad's pcbnew API.
# usage: python.exe place.py <in.kicad_pcb> <out.kicad_pcb>
# Rigid groups keep the hand layout inside each block (laser/ext-sync output block keeps its
# length-matched copper geometry when the tracks are re-imported). All tracks/vias are removed.
import sys, pcbnew
from pcbnew import VECTOR2I, FromMM, ToMM, EDA_ANGLE, DEGREES_T

SRC, OUT = sys.argv[1], sys.argv[2]
b = pcbnew.LoadBoard(SRC)
assert not any(t.IsLocked() for t in b.GetTracks()), "source has locked tracks"
# Original poses and pads, for carrying copper with its footprint (see the end).
old_pose = {f.GetReference(): (ToMM(f.GetPosition().x), ToMM(f.GetPosition().y), f.GetOrientationDegrees()) for f in b.GetFootprints()}
old_pads = [(ToMM(p.GetPosition().x), ToMM(p.GetPosition().y), p.GetNetname(), f.GetReference()) for f in b.GetFootprints() for p in f.Pads()]
old_padpos = {(f.GetReference(), p.GetNumber()): (ToMM(p.GetPosition().x), ToMM(p.GetPosition().y)) for f in b.GetFootprints() for p in f.Pads()}

# Hand-routed local paths kept with their parts (the parts of each pair move rigidly together):
# decoupling caps to their IC supply pins, and the buck's input, ground, SW and BST connections.
LOCAL_PATHS = [("C1", "1", "U1", "5"), ("C1", "1", "U2", "14"), ("C2", "1", "U3", "5"), ("C2", "1", "U4", "14"),
               ("C3", "1", "U5", "5"), ("C3", "1", "U6", "14"),
               ("C12", "1", "U15", "3"), ("U15", "3", "U15", "2"), ("C12", "2", "U15", "4"),
               ("U15", "5", "L1", "1"), ("U15", "5", "C13", "2"), ("U15", "6", "C13", "1"),
               ("J17", "A9", "J17", "B9")]   # hand VBUS join: A9/B9 stubs 4.12 mm + bar 3.04 mm
def copper_path(ra, na, rb, nb):
    """Tracks/vias of the shortest original copper path between two pads (endpoints within 0.8 mm
    of a pad centre are its terminals; track ends join within 0.05 mm, or inside a via's ring)."""
    import heapq
    net = [p for p in b.FindFootprintByReference(ra).Pads() if p.GetNumber() == na][0].GetNetname()
    items = [t for t in b.GetTracks() if t.GetNetname() == net]
    pts = []                                     # (x, y, item)
    for t in items:
        if t.GetClass() == "PCB_VIA": pts.append((ToMM(t.GetPosition().x), ToMM(t.GetPosition().y), t))
        else:
            pts.append((ToMM(t.GetStart().x), ToMM(t.GetStart().y), t)); pts.append((ToMM(t.GetEnd().x), ToMM(t.GetEnd().y), t))
    adj = {}
    def link(i, j, w, it): adj.setdefault(i, []).append((j, w, it)); adj.setdefault(j, []).append((i, w, it))
    for k in range(0, len(pts)):
        x, y, t = pts[k]
        for m in range(k + 1, len(pts)):
            x2, y2, t2 = pts[m]
            r, via = 0.05, None
            if t.GetClass() == "PCB_VIA" or t2.GetClass() == "PCB_VIA":
                via = t if t.GetClass() == "PCB_VIA" else t2
                r = ToMM(via.GetWidth(pcbnew.F_Cu)) / 2 + 0.05
            if math.hypot(x - x2, y - y2) < r: link(k, m, 0.0, via)   # a via on the path is kept too
    for k, (x, y, t) in enumerate(pts):          # the two ends of one segment
        if t.GetClass() != "PCB_VIA" and k + 1 < len(pts) and pts[k + 1][2] is t:
            link(k, k + 1, ToMM(int(t.GetLength())), t)
    def term(r, n):
        cx, cy = old_padpos[(r, n)]
        return [k for k, (x, y, t) in enumerate(pts) if math.hypot(x - cx, y - cy) <= 0.8]
    src, dst = term(ra, na), set(term(rb, nb))
    dist = {k: 0.0 for k in src}; prev = {}; q = [(0.0, k) for k in src]; heapq.heapify(q)
    while q:
        d, u = heapq.heappop(q)
        if d > dist.get(u, 1e9): continue
        if u in dst:
            path = set(); 
            while u in prev:
                u, it = prev[u]
                if it is not None: path.add(it.m_Uuid.AsString())
            return path
        for v, w, it in adj.get(u, []):
            if d + w < dist.get(v, 1e9): dist[v] = d + w; prev[v] = (u, it); heapq.heappush(q, (d + w, v))
    return set()
import math
local_items = {}                                 # track UUID -> owner footprint
for ra, na, rb, nb in LOCAL_PATHS:
    for i in copper_path(ra, na, rb, nb): local_items[i] = ra
print("local paths:", len(LOCAL_PATHS), "->", len(local_items), "tracks")
X0, Y0, W, H = 130.0, 30.0, 160.0, 100.0          # new board outline (mm)

def P(x, y): return VECTOR2I(FromMM(x), FromMM(y))
def A(d): return EDA_ANGLE(d, DEGREES_T)
def fp(r):
    f = b.FindFootprintByReference(r)
    assert f, r
    return f

# Board drawings (silkscreen text/shapes) by their ORIGINAL centre, so groups can claim them.
draw = []
for d in [x.Cast() for x in b.GetDrawings()]:
    if b.GetLayerName(d.GetLayer()) == "Edge.Cuts": continue
    c = d.GetBoundingBox().GetCenter()
    draw.append((d, ToMM(c.x), ToMM(c.y)))
claimed = set()
def drawings_in(x1, y1, x2, y2, exclude=()):
    out = []
    for d, x, y in draw:
        if id(d) in claimed: continue
        if x1 <= x <= x2 and y1 <= y <= y2 and not any(e(d) for e in exclude):
            out.append(d); claimed.add(id(d))
    return out
def text_is(*names): return lambda d: d.GetClass() == "PCB_TEXT" and d.GetText() in names

def move(items, dx, dy, rot=0.0, pivot=None):
    for it in items:
        if rot: it.Rotate(P(*pivot), A(rot))
        it.Move(P(dx, dy))

# ---- groups ---------------------------------------------------------------------------------
# Laser + External Sync output block: BNCs on the right edge (old edge x=258 -> new 290), J7 low
# enough that an M3 washer at MH2 (the corner hole) clears its body.
laser = [fp(r) for r in "J7 J8 J12 J18 J19 J21 R25 R26 R27 R28 R31 R32 R6 R7 R30 U13 U19 C9 C10 C21 C22 U7 U8 C4 C5 R16".split()]
laser += drawings_in(228, 68, 256, 125, exclude=[text_is("CH1", "TRG", "MKR", "CAMERA TRIGGER:", "TRG-MKR = MARKER", "TRG-CH1 = LASER 1")])
move(laser, 32.0, -30.2)

# J12 offset write-in field (title, three boxes, labels) -> bottom of the left strip.
field = drawings_in(222, 130, 250, 146)
move(field, 152.0 - 225.0, 72.0 - 131.8)

# Pico sockets: rotate +90 (USB end to the left edge), J14 pad 1 at (132.385, 59.39).
pico = [fp("J14"), fp("J15")] + drawings_in(158, 30, 180, 83)
move(pico, 132.385 - 160.015, 59.39 - 32.385, rot=90, pivot=(160.015, 32.385))
for d in drawings_in(180, 32, 195, 36):           # CONTROL / PROGRAM, PICO MICRO-USB
    d.SetTextAngle(A(0)); move([d], 146.0 - 181.0, 34.0 - 32.6)

# TP3 1 MHz scope header below the Pico, pins toward the left edge, tips 1 mm inside the outline.
tp3 = [fp("TP3")] + drawings_in(140, 30, 158, 41, exclude=[text_is("CONTROL / PROGRAM", "PICO MICRO-USB")])
move(tp3, 0, 0, rot=90, pivot=(152.002076, 38.0))
move(tp3, 141.0 - 152.002076, 67.0 - 38.0)

# Camera headers: one row of six along the bottom, 12 mm pitch, ribbons up, below their buffers.
for r, (x, y) in zip("J1 J2 J3 J4 J5 J6".split(), [(193.04 + 12 * i, 111.5) for i in range(6)]):
    f = fp(r); f.SetPosition(P(x, y)); f.SetOrientationDegrees(0)

# Clock jumper J20 + R29 + its text, beside the Pico's right end.
clk = [fp("J20")] + drawings_in(138, 59, 151, 68)
move(clk, 186.0 - 152.4, 70.0 - 65.41)

# Trigger-source jumper J10 + its text: left strip, right of the camera headers.
j10 = [fp("J10")] + drawings_in(212, 101, 227, 110)
move(j10, 200.0 - 217.0, 56.0 - 101.0)

# Interlock: U10, R2, R3, R8, J11 + text.
lock = [fp(r) for r in "U10 R2 R3 R8 J11".split()] + drawings_in(182, 74, 205, 81)
move(lock, 9.0, 4.0)

# Pull-downs / series resistors at the Pico's GPIO end (window column).
for r, (x, y, a) in {"R24": (191.0, 41.0, 0), "R17": (191.0, 46.0, 0), "R19": (191.0, 52.0, 0), "R18": (194.0, 66.5, 0), "R29": (191.0, 70.5, 0)}.items():
    f = fp(r); f.SetPosition(P(x, y)); f.SetOrientationDegrees(a)

# 1.8 V LDO (U9, C6, C7): centred above the buffer row between U4 and U6, right of the J11
# interlock text (x <= 213.0).
for r, (x, y, a) in {"C7": (220.9, 82.05, 0), "U9": (216.0, 83.0, 0), "C6": (214.5, 76.5, 90)}.items():   # C6 down 2.2mm: clears the VBUS_PD y~80 straight run (was a 9-jog staircase around C6's +5V pad)
    f = fp(r); f.SetPosition(P(x, y)); f.SetOrientationDegrees(a)

# Camera buffer trios in a row directly above the headers (as on the original board).
for refs, (dx, dy) in [("U2 U1 C1", (189.5 - 138.1, -17.9)), ("U4 U3 C2", (206.0 - 162.2, -17.9)), ("U6 U5 C3", (222.5 - 185.8, -17.9))]:
    move([fp(r) for r in refs.split()], dx, dy)
f = fp("R9"); f.SetPosition(P(210.0, 56.0)); f.SetOrientationDegrees(0)   # PWM_TRIG_TAP pull-down, by J10

# Power input on the LEFT edge, below TP3: J17 facing left with the PD controller (rotate +90 about
# J17), then the buck and ideal diode in their original orientation (VBUS_PD in on the left).
pd = [fp(r) for r in "J17 U14 C11 R10".split()] + drawings_in(219, 32, 231, 36)
move(pd, 0, 0, rot=90, pivot=(214.0, 33.4))
move(pd, 133.4 - 214.0, 106.0 - 33.4)
fp("U14").SetOrientationDegrees(180)              # CC/VBUS pins (6-10) toward J17
buck = [fp(r) for r in "U15 L1 C12 C13 C14 C15 U16".split()]
move(buck, 154.0 - 225.0, 112.0 - 44.0)
# 12 V LDO + power-good cluster, beside U13 (its load).
move([fp(r) for r in "U17 C16 C17 C18 C19 R12 R13 R20 U18 R21 R22 R23 C20".split()], 22.0, 2.5)

# Spread the tight machine-assembly clusters about their IC (hand placement / hot plate):
# position = anchor + s * (position - anchor).
def spread(anchor, refs, s):
    a = fp(anchor).GetPosition()
    for r in refs.split():
        f = fp(r); p = f.GetPosition()
        f.SetPosition(VECTOR2I(int(a.x + s * (p.x - a.x)), int(a.y + s * (p.y - a.y))))
spread("U17", "C16 C17 C18 C19 R12 R13 R20 U18 R21 R22 R23 C20", 1.35)
spread("U18", "R21 R22 R23 C20", 1.3)
# Buck output caps and ideal diode in a row next to L1.2 (U15/C12/L1/C13 stay as drawn: hot loop, SW node).
# Courtyard gaps L1-C14 0.58 mm, C14-C15 0.55 mm: the 0.5 mm tweezer spacing is kept.
for r, (x, y, a) in {"C14": (164.4, 114.86, -90), "C15": (167.0, 114.86, -90), "U16": (170.7, 114.34, 0)}.items():
    f = fp(r); f.SetPosition(P(x, y)); f.SetOrientationDegrees(a)
for r, (x, y, a) in {"C17": (235.6, 78.5, 180),            # U17 output cap beside pins 11/12
                     "C20": (221.0, 71.9, 180)}.items():   # U18 bypass beside pin 5
    f = fp(r); f.SetPosition(P(x, y)); f.SetOrientationDegrees(a)
f = fp("C11"); f.SetPosition(P(148.6, 118.4)); f.SetOrientationDegrees(90)   # U14 VHV (pin 1) decoupling, beside pin 1
f = fp("R10"); f.SetPosition(P(140.5, 121.0)); f.SetOrientationDegrees(0)   # U14 CFG1 resistor, below pad 9

# Mounting holes: a corner rectangle 4 mm from the short edges and 6 mm from the long edges, so a 7 mm
# M3 washer stays out of the 2.5 mm card-guide strips; their copper keep-outs follow.
mh = {"MH1": (134, 36), "MH2": (286, 36), "MH3": (134, 124), "MH4": (286, 124)}
old = {}
for r, (x, y) in mh.items():
    f = fp(r); p = f.GetPosition(); old[r] = (ToMM(p.x), ToMM(p.y)); f.SetPosition(P(x, y))

# ---- outline and zones ----------------------------------------------------------------------
edges = [d.Cast() for d in b.GetDrawings() if b.GetLayerName(d.GetLayer()) == "Edge.Cuts"]
corners = [(X0, Y0), (X0 + W, Y0), (X0 + W, Y0 + H), (X0, Y0 + H)]
assert len(edges) == 4
for e, i in zip(edges, range(4)):
    e.SetStart(P(*corners[i])); e.SetEnd(P(*corners[(i + 1) % 4]))
for z in b.Zones():
    if z.GetIsRuleArea():                         # MH keep-out circle: move with its hole
        c = z.GetBoundingBox().GetCenter(); cx, cy = ToMM(c.x), ToMM(c.y)
        r = min(old, key=lambda k: (old[k][0] - cx) ** 2 + (old[k][1] - cy) ** 2)
        z.Move(P(mh[r][0] - old[r][0], mh[r][1] - old[r][1]))
    else:                                         # plane / pour: whole board
        o = z.Outline(); o.RemoveAllContours(); o.NewOutline()
        for x, y in corners: o.Append(FromMM(x), FromMM(y))
        z.UnFill()

# ---- silkscreen fixes after the rotations ----------------------------------------------------
def txt(s):
    m = [d for d, x, y in draw if d.GetClass() == "PCB_TEXT" and d.GetText() == s]
    assert len(m) == 1, s
    return m[0]
def put(s, x, y, just):
    t = txt(s); t.SetTextAngle(A(0)); t.SetHorizJustify(just); t.SetPosition(P(x, y))
L, R = pcbnew.GR_TEXT_H_ALIGN_LEFT, pcbnew.GR_TEXT_H_ALIGN_RIGHT
put("1MHz Clock", 143.6, 67.0, L); put("GND", 143.6, 64.46, L)
# Pico pin-1 mark above J14 pad 1 (Rev 1 had it beside J14.1); the TP3 group claims it by its old centre.
put("1", 132.385, 56.6, pcbnew.GR_TEXT_H_ALIGN_CENTER)
jlc = [d for d, x, y in draw if d.GetClass() == "PCB_TEXT" and d.GetText() == "JLCJLCJLCJLC"][0]
jlc.SetPosition(P(232.0, 124.0))                  # JLC order-number placeholder, back silkscreen
put("POWER ONLY", 138.6, 99.6, L); put("USB-C PD 15 V", 138.6, 101.2, L)
for r, (x, y) in {"MH1": (138.8, 36), "MH2": (281.2, 36), "MH3": (134, 119.4), "MH4": (281.2, 124)}.items():
    t = fp(r).Reference(); t.SetTextAngle(A(0)); t.SetPosition(P(x, y))

# ---- copper: carry the hand-routed laser/ext-sync block and the EP thermal vias, lock them ----
# Everything else is removed for the autorouter. A kept item moves with the footprint that owns it:
# internal nets of the output block, and GND items whose nearest GND pad (<= 3 mm) is in a carried part.
CARRY_NETS = set("CH1_GATED CH2_GATED CH1_DRIVE_RAW CH2_DRIVE_RAW CH1_DRIVE CH2_DRIVE CH1_OUT CH2_OUT "
                 "CH1_TERM CH2_TERM EXT_SYNC_DRIVE_RAW EXT_SYNC_DRIVE EXT_SYNC_OUT EXT_SYNC_TERM".split())
CARRY_GND = set(f.GetReference() for f in laser if f.GetClass() == "FOOTPRINT") | {"U14", "U17", "C12"}
new = {f.GetReference(): (ToMM(f.GetPosition().x), ToMM(f.GetPosition().y), f.GetOrientationDegrees()) for f in b.GetFootprints()}
import math
def carry(x, y, ref):
    ox, oy, oa = old_pose[ref]; nx, ny, na = new[ref]
    a = math.radians(na - oa); dx, dy = x - ox, y - oy      # KiCad: +angle = CCW on screen (y down)
    return nx + dx * math.cos(a) + dy * math.sin(a), ny - dx * math.sin(a) + dy * math.cos(a)
def owner(net, pts):
    best = None
    for x, y in pts:
        for px, py, pnet, ref in old_pads:
            if pnet != net: continue
            d = math.hypot(px - x, py - y)
            if best is None or d < best[0]: best = (d, ref)
    return best
kept = 0
for t in list(b.GetTracks()):
    via = t.GetClass() == "PCB_VIA"
    pts = [(ToMM(t.GetPosition().x), ToMM(t.GetPosition().y))] if via else \
          [(ToMM(t.GetStart().x), ToMM(t.GetStart().y)), (ToMM(t.GetEnd().x), ToMM(t.GetEnd().y))]
    net = t.GetNetname(); ref = None
    o = owner(net, pts)
    if t.m_Uuid.AsString() in local_items: ref = local_items[t.m_Uuid.AsString()]
    elif net in CARRY_NETS and o: ref = o[1]
    elif net == "GND" and o and o[0] <= 3.0 and o[1] in CARRY_GND: ref = o[1]
    if ref is None: continue
    if via: t.SetPosition(P(*carry(*pts[0], ref)))
    else: t.SetStart(P(*carry(*pts[0], ref))); t.SetEnd(P(*carry(*pts[1], ref)))
    t.SetLocked(True); kept += 1
print("carried and locked:", kept)

# ---- equal-length laser pulse lanes (GPIO pin -> U7/U8 input), locked before autorouting ----------
# Each lane: from the J14 pad straight to the U7/U8 input's row, one 45-degree corner of C mm, then
# along the row to the pad. GPIO pad -> U13 input is equal when L(CH2) = L(CH1) + D, D = carried
# U7.4->U13.2 (10.41 mm) minus U8.4->U13.4 (9.67 mm). The shorter lane gets a 45-degree bump of height
# h on its row run (adds h * (2*sqrt2 - 2)), pointing away from the other lane.
C = 1.0; S2 = math.sqrt(2); D = 10.41 - 9.67
def padxy(ref, num):
    q = [p for p in fp(ref).Pads() if p.GetNumber() == num][0].GetPosition()
    return ToMM(q.x), ToMM(q.y)
def lpath(start, end):
    (xs, ys), (xe, ye) = start, end
    sg = 1 if ye > ys else -1
    return [(xs, ys), (xs, ye - sg * C), (xs + C, ye), (xe, ye)]
def plen(pts): return sum(math.hypot(x2 - x1, y2 - y1) for (x1, y1), (x2, y2) in zip(pts, pts[1:]))
def bump(pts, extra, away, x0, width=2.0):
    h = extra / (2 * S2 - 2); y = pts[-1][1]
    return pts[:-1] + [(x0, y), (x0 + h, y + away * h), (x0 + h + width, y + away * h), (x0 + 2 * h + width, y)] + pts[-1:]
ch1 = lpath(padxy("J14", "17"), padxy("U7", "2")); ch2 = lpath(padxy("J14", "16"), padxy("U8", "2"))
up1 = -1 if ch1[-1][1] < ch2[-1][1] else 1                     # CH1's row is above CH2's: bump CH1 up
e = plen(ch2) - (plen(ch1) + D)
if e > 0: ch1 = bump(ch1, e, up1, ch1[2][0] + 8.0)
elif e < 0: ch2 = bump(ch2, -e, -up1, ch2[2][0] + 8.0)
# Resistor branches, drawn and locked with the lanes (the router no longer picks them; the CH1/CH2 load
# balance is fixed here). CH1: R19.1 and R17.1 sit on x = 190 above CH1's row, one straight branch from
# the row through R19.1 to R17.1; the row is split at the tap so every joint is end-to-end.
# CH2: R18 is its only branch. A balance stub leaves the CH2 lane corner on the corner's 45-degree line,
# runs G mm (centre to centre) below the lane, and drops into R18.1. Its length (set by R18's x in the
# placement table) trims the CH1-minus-CH2 skew at U7/U8 for the R19/J10 load on CH1 (signal_sim).
G = 0.9                                                         # 0.6 mm edge gap at 0.3 mm width
r19, r17, r18 = padxy("R19", "1"), padxy("R17", "1"), padxy("R18", "1")
tap1 = (r19[0], ch1[-1][1])
assert ch1[-2][0] < tap1[0] < ch1[-1][0] and r17[0] == r19[0], "CH1 tap not on the row run"
ch1 = ch1[:-1] + [tap1] + ch1[-1:]
br1 = [tap1, r19, r17]
assert e > 0, "CH2 would get the bump; it would cross the balance stub"
c2 = ch2[2]                                                     # CH2 lane corner (end of the 45-degree run)
br2 = [c2, (c2[0] + G, c2[1] + G), (r18[0] - 0.7, c2[1] + G), (r18[0], c2[1] + G + 0.7), r18]
lanes = {"_PULSE_OUT_CH1": ch1, "_PULSE_OUT_CH2": ch2}
for net, pts in list(lanes.items()) + [("_PULSE_OUT_CH1", br1), ("_PULSE_OUT_CH2", br2)]:
    n = b.FindNet(net)
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        t = pcbnew.PCB_TRACK(b); t.SetStart(P(x1, y1)); t.SetEnd(P(x2, y2)); t.SetWidth(FromMM(0.3))
        t.SetLayer(pcbnew.F_Cu); t.SetNet(n); t.SetLocked(True); b.Add(t)
# R19 -> J10.1 (CH1_J10) is part of CH1's load (behind 100 ohm): drawn too, so the trim above holds for
# every routing run. F.Cu 45-degree to a via clear of CH1's row, then B.Cu under the row to the J10.1 pin.
r19b, j10 = padxy("R19", "2"), padxy("J10", "1")
v1 = (r19b[0] + 0.9, r19b[1] + 0.9)
assert v1[1] + 0.3 + 0.2 <= ch1[-1][1] - 0.15, "R19 -> J10 via too close to CH1's row"
nj = b.FindNet("CH1_J10")
for (x1, y1), (x2, y2), lay in [(r19b, v1, pcbnew.F_Cu), (v1, (v1[0] + (j10[1] - v1[1]), j10[1]), pcbnew.B_Cu),
                                 ((v1[0] + (j10[1] - v1[1]), j10[1]), j10, pcbnew.B_Cu)]:
    t = pcbnew.PCB_TRACK(b); t.SetStart(P(x1, y1)); t.SetEnd(P(x2, y2)); t.SetWidth(FromMM(0.3))
    t.SetLayer(lay); t.SetNet(nj); t.SetLocked(True); b.Add(t)
v = pcbnew.PCB_VIA(b); v.SetPosition(P(*v1)); v.SetWidth(FromMM(0.6)); v.SetDrill(FromMM(0.3))
v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu); v.SetNet(nj); v.SetLocked(True); b.Add(v)
for net, pts in lanes.items(): print(net, "lane", round(plen(pts), 3), "mm")
print("lane branches: CH1 R19/R17", round(plen(br1), 3), "mm, CH2 R18 balance stub", round(plen(br2), 3), "mm")

# VBUS_PD feed: carried A9-B9 bar (B9 end, 4.12 mm east of the pad) -> U15.3 (VIN), 0.5 mm F.Cu, locked.
bx, by = padxy("J17", "B9"); vx, vy = padxy("U15", "3")
vb = [(bx + 4.12, by), (146.0, by), (150.5, by + 4.5), (150.5, vy), (vx, vy)]
for (x1, y1), (x2, y2) in zip(vb, vb[1:]):
    t = pcbnew.PCB_TRACK(b); t.SetStart(P(x1, y1)); t.SetEnd(P(x2, y2)); t.SetWidth(FromMM(0.5))
    t.SetLayer(pcbnew.F_Cu); t.SetNet(b.FindNet("VBUS_PD")); t.SetLocked(True); b.Add(t)
print("VBUS_PD lane", round(plen(vb), 3), "mm")

# +12V output lane: U17 pins 11/12 along the pad row (0.4 mm, as on the hand board), then 45 degrees to C17.1.
q11, q12, qc = padxy("U17", "11"), padxy("U17", "12"), padxy("C17", "1")
v12 = [q11, q12, (q12[0] - (qc[1] - q12[1]), qc[1]), qc]
n12 = b.FindNet("+12V")
for (x1, y1), (x2, y2) in zip(v12, v12[1:]):
    t = pcbnew.PCB_TRACK(b); t.SetStart(P(x1, y1)); t.SetEnd(P(x2, y2)); t.SetWidth(FromMM(0.4))
    t.SetLayer(pcbnew.F_Cu); t.SetNet(n12); t.SetLocked(True); b.Add(t)
print("+12V lane", round(plen(v12), 3), "mm")

# F.Cu track/via keep-out under the J17 receptacle body (GND shell on the mask): no VBUS_PD under it.
ko = pcbnew.ZONE(b); ko.SetIsRuleArea(True); ko.SetDoNotAllowTracks(True); ko.SetDoNotAllowVias(True)
ko.SetDoNotAllowZoneFills(False); ko.SetDoNotAllowPads(False); ko.SetDoNotAllowFootprints(False)
ko.SetLayer(pcbnew.F_Cu); ko.SetZoneName("J17 body keep-out")
o = ko.Outline(); o.NewOutline()
for x, y in [(130.0, 101.5), (135.45, 101.5), (135.45, 110.5), (130.0, 110.5)]: o.Append(FromMM(x), FromMM(y))
b.Add(ko)

# Remove the rest last: after Remove() the SWIG wrappers of later queries break.
for t in list(b.GetTracks()):
    if not t.IsLocked(): b.Remove(t)
pcbnew.SaveBoard(OUT, b)
print("unclaimed drawings:", [(d.GetText() if d.GetClass() == "PCB_TEXT" else d.GetClass(), round(x, 1), round(y, 1)) for d, x, y in draw if id(d) not in claimed])
