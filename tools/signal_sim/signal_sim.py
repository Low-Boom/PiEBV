"""signal_sim.py - transmission-line simulation of the PiDG timing nets.

Run with KiCad 10's Python (numpy is included; pcbnew is not needed):
    "%LOCALAPPDATA%\\Programs\\KiCad\\10.0\\bin\\python.exe" signal_sim.py
Inputs: geometry.json (routed board geometry, from extract_geometry.py) and devices.json (device
parameters with sources). Output: results.md and results.json next to this file.

The circuit is cut at every gate into stages. A gate input does not load the stage before it
except by its input capacitance, so each stage is simulated on its own and the delays add:
  A  GPIO pads -> PWM_Trig / J10 / PWM_TRIG_TAP / _PULSE_OUT_CH1/2 -> U5, U19, U7, U8 inputs
  B1 U5 output -> TRIG_N -> U6 inputs        B2 U6 outputs -> Trigger1..6 -> J1..J6 pin 4
  C  U19 output -> R30 -> J21/R31/R32 -> J12 -> RG-58 -> load
  D1 U7/U8 outputs -> CH1/CH2_GATED -> U13   D2 U13 outputs -> R6/R7 -> J18/J19 -> J7/J8 -> load
Every gate is "input threshold crossing + internal delay -> output ramp behind an output
resistance". The internal delay is calibrated so that the gate model, driven and loaded as in its
datasheet test circuit, reproduces the datasheet propagation delay.
"""
import ctypes, os, sys, json, math, re, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
# Default: KiCad 10 per-user install (%LOCALAPPDATA%\Programs\KiCad\10.0\bin); KICAD_BIN overrides.
KICAD_BIN = os.environ.get("KICAD_BIN") or os.path.join(
    os.environ.get("LOCALAPPDATA", ""), "Programs", "KiCad", "10.0", "bin")
GEOM = json.load(open(os.path.join(HERE, "geometry.json")))
DEV = json.load(open(os.path.join(HERE, "devices.json")))
LAYERS = GEOM["layers"]
VIA = GEOM["via_model"]

TMAX_PS = 2.5        # max SPICE time step; every T element is longer than LUMP_MM (TD >= 12 ps)
LUMP_MM = 2.0        # board runs shorter than this are one lumped LC pi section
T_R, T_F, T_END = 5.0, 85.0, 160.0   # stage A: GPIO rise / fall start, stop time (ns)
CORNERS = ("min", "typ", "max")
GPIO_CORNERS = ("strong", "typ", "weak")
EDGES = ("rise", "fall")


# ----------------------------------------------------------------------------- ngspice
class Spice:
    """KiCad's ngspice.dll through ctypes. One circuit at a time; vectors read from memory."""
    class _VI(ctypes.Structure):
        _fields_ = [("name", ctypes.c_char_p), ("type", ctypes.c_int), ("flags", ctypes.c_short),
                    ("real", ctypes.POINTER(ctypes.c_double)), ("comp", ctypes.c_void_p),
                    ("length", ctypes.c_int)]

    def __init__(self, bindir):
        os.add_dll_directory(bindir)
        self.ng = ctypes.CDLL(os.path.join(bindir, "ngspice.dll"))
        self.log = []
        pf = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p)
        self._cb = pf(lambda s, i, u: (self.log.append(s.decode(errors="replace")), 0)[1])
        ex = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.c_bool, ctypes.c_bool,
                              ctypes.c_int, ctypes.c_void_p)
        self._ex = ex(lambda *a: 0)
        self.ng.ngSpice_Init(self._cb, None, self._ex, None, None, None, None)
        self.ng.ngGet_Vec_Info.restype = ctypes.POINTER(self._VI)
        self.ng.ngGet_Vec_Info.argtypes = [ctypes.c_char_p]
        self.runs = 0
        self.points = 0

    def _vec(self, name):
        p = self.ng.ngGet_Vec_Info(name.encode())
        if not p:
            return None
        v = p.contents
        return np.ctypeslib.as_array(v.real, shape=(v.length,)).copy()

    def run(self, lines, nodes):
        self.log.clear()
        net = list(lines) + [".end"]
        arr = (ctypes.c_char_p * (len(net) + 1))(*[s.encode() for s in net], None)
        self.ng.ngSpice_Circ(arr)
        self.ng.ngSpice_Command(b"run")
        bad = [l for l in self.log if re.search(r"error|singular|too small|aborted", l, re.I)]
        t = self._vec("time")
        w = {n: self._vec(f"v({n})") for n in nodes}
        self.ng.ngSpice_Command(b"destroy all")
        self.ng.ngSpice_Command(b"remcirc")
        if bad or t is None or any(v is None for v in w.values()):
            open(os.path.join(HERE, "failed_netlist.cir"), "w").write("\n".join(net))
            raise RuntimeError("ngspice failed (netlist in failed_netlist.cir): %s" % bad[:4])
        self.runs += 1
        self.points += len(t)
        return t * 1e9, w          # time in ns


# ----------------------------------------------------------------------------- netlist
def node(name):
    """SPICE node for a pad 'U19.2' -> n_u19_2."""
    return "n_" + re.sub(r"[^A-Za-z0-9]", "_", name).lower()


class Ckt:
    def __init__(self, title, tmax_ps):
        self.lines = [f"* {title}", ".model DESD D(IS=1e-14 N=1.2 RS=5)",
                      ".model DCL D(IS=1e-15 N=1.0 RS=10)"]
        self.k = 0
        self.tmax = tmax_ps

    def uid(self, p="x"):
        self.k += 1
        return f"{p}{self.k}"

    def add(self, *ls):
        self.lines.extend(ls)

    def C(self, a, pf, b="0"):
        if pf > 0:
            self.add(f"C{self.uid()} {a} {b} {pf:.5g}p")

    def R(self, a, b, ohm):
        self.add(f"R{self.uid()} {a} {b} {max(ohm, 1e-3):.6g}")

    def L(self, a, b, nh):
        self.add(f"L{self.uid()} {a} {b} {nh:.5g}n")

    def T(self, a, b, z0, td_ns, ref="0"):
        # REL/ABS 10: fewer slope breakpoints; results equal to the default within 0.1 mV (checked)
        self.add(f"T{self.uid()} {a} {ref} {b} {ref} Z0={z0:.5g} TD={td_ns:.6g}n REL=10 ABS=10")

    def run_line(self, a, b, layer, width, mm):
        p = LAYERS[f"{layer}_w{width:.3f}"]
        if mm < 1e-3:
            self.R(a, b, 1e-3)
        elif mm < LUMP_MM:
            self.C(a, p["C_pF_per_mm"] * mm / 2)
            self.L(a, b, p["L_nH_per_mm"] * mm)
            self.C(b, p["C_pF_per_mm"] * mm / 2)
        else:
            self.T(a, b, p["z0_ohm"], p["td_ps_per_mm"] * mm * 1e-3)

    def via(self, a, b):
        self.C(a, VIA["C_pF_est"] / 2)
        self.L(a, b, VIA["L_nH_est"])
        self.C(b, VIA["C_pF_est"] / 2)

    def runs(self, a, b, runs):
        cur = a
        nv = 0
        for i, r in enumerate(runs):
            if i > 0 and runs[i - 1]["layer"] != r["layer"]:
                v = self.uid("v")
                self.via(cur, v)
                cur = v
                nv += 1
            nxt = b if i == len(runs) - 1 else self.uid("w")
            self.run_line(cur, nxt, r["layer"], r["width_mm"], r["len_mm"])
            cur = nxt
        return nv

    def net(self, name, skip=()):
        """All routed branches of a board net (geometry.json). skip: (a, b) pad pairs to leave out."""
        g = GEOM["nets"][name]
        for e in g["edges"]:
            if (e["a"], e["b"]) in skip:
                continue
            pn = lambda p: node(name + "_" + p) if p.startswith("BP") else node(p)
            nv = self.runs(pn(e["a"]), pn(e["b"]), e["runs"])
            assert nv == e["vias"], (name, e["a"], e["b"], nv, e["vias"])

    def tran(self, tstop_ns):
        self.add(f".tran {self.tmax * 0.4:.4g}p {tstop_ns}n 0 {self.tmax:.4g}p")


# ----------------------------------------------------------------------------- devices
G = DEV["gpio"]
PICO = DEV["pico_path"]
GATES = DEV["gates"]
DRV = DEV["drivers"]
DRVC = DRV["_common"]
OC = DEV["output_corners"]
BP = DEV["board_parts"]
AMP = {"min": "high", "typ": "typ", "max": "low"}    # timing corner -> amplitude corner


def gpio_scale(drive, strength):
    """(up, down) strength scale. 'floor' puts the pad on RP2350 Table 1683 VOH/VOL at the set current."""
    if strength != "floor":
        s = G["strength_scale_est"][strength]
        return s, s
    d = G["drive"][str(drive)]
    i = drive * 1e-3
    up = i / (d["isat_up_mA"] * 1e-3 * math.tanh((G["iovdd"] - G["floor"]["voh_min"]) / (d["rs_up"] * d["isat_up_mA"] * 1e-3)))
    dn = i / (d["isat_dn_mA"] * 1e-3 * math.tanh(G["floor"]["vol_max"] / (d["rs_dn"] * d["isat_dn_mA"] * 1e-3)))
    return up, dn


def add_gpio(c, name, pad, drive, slew, strength, t_r=T_R, t_f=T_F):
    """RP2350 pad (tanh V-I model, ramp-switched) + package + Pico trace + socket, to board pad."""
    d = G["drive"][str(drive)]
    su, sd = gpio_scale(drive, strength)
    iu, ru = d["isat_up_mA"] * 1e-3 * su, d["rs_up"] / su
    idn, rd = d["isat_dn_mA"] * 1e-3 * sd, d["rs_dn"] / sd
    rp = G["ramp_ns_est"][slew]
    vdd = G["iovdd"]
    k, die, pkg, pin = (f"{name}_{s}" for s in ("k", "die", "pkg", "pin"))
    pa = G["pad"]
    c.add(f"V{name}k {k} 0 PWL(0 0 {t_r}n 0 {t_r + rp}n 1 {t_f}n 1 {t_f + rp}n 0)",
          f"B{name} {die} 0 I=(1-V({k}))*{idn:.6g}*tanh(V({die})/{rd * idn:.6g})"
          f" - V({k})*{iu:.6g}*tanh(({vdd}-V({die}))/{ru * iu:.6g})")
    if not any(l.startswith("Vio ") for l in c.lines):
        c.add(f"Vio vio 0 {vdd}")
    c.add(f"D{name}u {die} vio DESD", f"D{name}d 0 {die} DESD")
    c.C(die, pa["c_die_pF"])
    c.L(die, pkg, pa["l_bond_nH"])
    c.C(pkg, pa["c_pkg_pF"])
    c.T(pkg, pin, PICO["trace_z0"], PICO["trace_mm"] * PICO["trace_ps_per_mm"] * 1e-3)
    c.C(pin, PICO["pin_pF"])
    c.L(pin, node(pad), PICO["socket_nH"])
    c.C(node(pad), PICO["socket_pF"])


def add_switch_out(c, name, out, vhi, r_up, r_dn, ramp, t_a, t_b, start_high):
    """Gate/driver output: internal ramp (0..vhi) behind r_up when high, r_dn when low.
    The ramp starts at t_a and returns at t_b."""
    s = f"{name}_s"
    v0, v1 = (vhi, 0.0) if start_high else (0.0, vhi)
    c.add(f"V{name} {s} 0 PWL(0 {v0} {t_a}n {v0} {t_a + ramp}n {v1} {t_b}n {v1} {t_b + ramp}n {v0})",
          f"B{name} {s} {out} I=(V({s})-V({out}))/({r_dn:.6g}+({r_up - r_dn:.6g})*V({s})/{vhi})")


def add_input(c, pad, ci_pf, clamp):
    c.C(node(pad), ci_pf)
    if clamp:
        c.add(f"D{c.uid()} 0 {node(pad)} DCL")


def add_r(c, a, b, ohm, kind):
    """Board resistor between pads a and b (b may be '0'). kind: '2512' or '0805'.
    Returns (node a, internal node, ohm): the resistive element sits between the two nodes,
    so its power is (V(a) - V(internal))^2 / ohm."""
    p = BP["r2512"] if kind == "2512" else BP["r0805"]
    na, nb = node(a), (node(b) if b != "0" else "0")
    m = c.uid("r")
    c.R(na, m, ohm)
    c.L(m, nb, p["esl_nH"])
    c.C(na, p["cp_pF"], nb)
    if kind == "2512":
        c.C(na, p["pad_pF"])
        if nb != "0":
            c.C(nb, p["pad_pF"])
    return na, m, max(ohm, 1e-3)


# ----------------------------------------------------------------------------- waveform tools
def cross(t, v, th, rising, t_from, t_to=None):
    m = (t >= t_from) & ((t <= t_to) if t_to is not None else True)
    tt, vv = t[m], v[m]
    s = (vv[:-1] < th) & (vv[1:] >= th) if rising else (vv[:-1] > th) & (vv[1:] <= th)
    i = np.nonzero(s)[0]
    if not len(i):
        return None
    i = i[0]
    return float(tt[i] + (th - vv[i]) * (tt[i + 1] - tt[i]) / (vv[i + 1] - vv[i]))


def ring_back(t, v, tc, t_end, rising, hyst=0.02):
    """Ring-back after the first peak that follows the crossing at tc: the lowest value after
    the first peak of a rising edge (highest after the first dip of a falling edge).
    None = the edge is monotonic (no peak by more than hyst volts) in the window."""
    seg = v[(t > tc) & (t <= t_end)]
    if len(seg) < 3:
        return None
    if rising:
        i = np.nonzero(np.maximum.accumulate(seg) - seg > hyst)[0]
        return float(seg[i[0]:].min()) if len(i) else None
    i = np.nonzero(seg - np.minimum.accumulate(seg) > hyst)[0]
    return float(seg[i[0]:].max()) if len(i) else None


def edge_stats(t, v, ths, t_r, t_f, t_end):
    """Per threshold: first crossing (rise / fall window) and the ring-back after it."""
    out = {"rise": {}, "fall": {}}
    wr = (t >= t_r) & (t < t_f)
    wf = (t >= t_f) & (t <= t_end)
    out["rise"]["vmax"], out["rise"]["vmin"] = float(v[wr].max()), float(v[wr].min())
    out["fall"]["vmax"], out["fall"]["vmin"] = float(v[wf].max()), float(v[wf].min())
    for th in ths:
        tc = cross(t, v, th, True, t_r, t_f)
        out["rise"][th] = (tc, None if tc is None else ring_back(t, v, tc, t_f, True))
        tc = cross(t, v, th, False, t_f, t_end)
        out["fall"][th] = (tc, None if tc is None else ring_back(t, v, tc, t_end, False))
    return out


def vth(spec, corner, in_rising):
    """Threshold for the fast/slow corner: min corner = earliest crossing."""
    if corner == "typ":
        return spec["typ"]
    fast = corner == "min"
    return spec["min"] if fast == in_rising else spec["max"]


def drv_th(drv, corner, in_rising):
    return vth(drv["vin_h"], corner, True) if in_rising else vth(drv["vin_l"], corner, False)


def all_thresholds():
    u5 = sorted(set(GATES["SN74LVC1G04"]["vsw"].values()))
    ahct = sorted(set(GATES["SN74AHCT1G08"]["vsw"].values()))
    ucc = sorted({v for k, d in DRV.items() if not k.startswith("_") for s in ("vin_h", "vin_l") for v in d[s].values()})
    return u5, ahct, ucc


# ----------------------------------------------------------------------------- calibration
class Model:
    def __init__(self, spice, tmax_ps=TMAX_PS):
        self.sp = spice
        self.tmax = tmax_ps
        self.cache = {}

    def ckt(self, title):
        return Ckt(title, self.tmax)

    def _load_delay(self, vhi, r_up, r_dn, ramp, cl_pf, rl, th, out_rising):
        """Model output stage into a test load: time from ramp start to the absolute level th."""
        c = self.ckt("calibration")
        if out_rising:
            add_switch_out(c, "o", "out", vhi, r_up, r_dn, ramp, 5.0, 500.0, start_high=False)
            t_edge, t_stop = 5.0, 60.0
        else:   # settle high first, then fall
            add_switch_out(c, "o", "out", vhi, r_up, r_dn, ramp, 1.0, 60.0, start_high=False)
            t_edge, t_stop = 60.0, 120.0
        c.C("out", cl_pf)
        if rl:
            c.R("out", "0", rl)
        c.tran(t_stop)
        t, w = self.sp.run(c.lines, ["out"])
        return cross(t, w["out"], th, out_rising, t_edge, t_stop) - t_edge

    def gate_tint(self, gname, corner, in_rising):
        """Internal delay of a logic gate: datasheet tpd minus the test-input threshold offset
        minus the model's own output delay into the datasheet test load."""
        key = ("gate", gname, corner, in_rising)
        if key in self.cache:
            return self.cache[key]
        g = GATES[gname]
        inverting = gname != "SN74AHCT1G08"
        out_rising = in_rising != inverting
        te = g["test"]
        vsw = vth(g["vsw"], corner, in_rising)
        slope = te["vin_high"] / te["tr_in_ns"]
        dth = (vsw - te["vm_in"]) / slope if in_rising else (te["vm_in"] - vsw) / slope
        r = g["rout"][corner]
        dl = self._load_delay(g["vcc"], r, r, g["ramp_ns_est"][corner], te["cl_pF"], te["rl"], te["vm_out"], out_rising)
        tint = g["tpd"][corner] - dth - dl
        res = {"tint": max(tint, 0.0), "raw": tint, "vsw": vsw, "dload": dl, "dth": dth}
        self.cache[key] = res
        return res

    def drv_tint(self, dname, corner, in_rising):
        """Driver internal delay: tD (VIN crossing to 10 % rise / 90 % fall into 1.8 nF) minus the
        model's start-to-10 % (or 90 %) time into 1.8 nF."""
        key = ("drv", dname, corner, in_rising)
        if key in self.cache:
            return self.cache[key]
        d = DRV[dname]
        roh, rol = d["roh"][corner], d["rol"][corner]
        rup_t = 1.0 / (1.0 / roh + 1.0 / DRVC["r_boost"])
        ramp = DRVC["ramp_ns"][corner]
        if in_rising:
            dl = self._load_delay(12.0, rup_t, rol, ramp, DRVC["test_cl_pF"], None, 0.1 * 12.0, True)
            td = d["td_rise"][corner]
        else:
            dl = self._load_delay(12.0, rup_t, rol, ramp, DRVC["test_cl_pF"], None, 0.9 * 12.0, False)
            td = d["td_fall"][corner]
        res = {"tint": max(td - dl, 0.0), "raw": td - dl, "dload": dl, "vth": drv_th(d, corner, in_rising)}
        self.cache[key] = res
        return res

    # ------------------------------------------------------------------------- stage A
    def stage_a(self, j10="23", r19=None, drive=4, slew="slow", strength="typ", optd=False):
        """GPIO pads -> J10 / PWM_TRIG_TAP / laser nets. Returns crossing stats per receiver."""
        r19 = BP["r19"] if r19 is None else r19
        key = ("A", j10, r19, drive, slew, strength, optd)
        if key in self.cache:
            return self.cache[key]
        c = self.ckt(f"stage A j10={j10} r19={r19} {drive}mA {slew} {strength}")
        for name, pad in (("gp11", "J14.15"), ("gp12", "J14.16"), ("gp13", "J14.17")):
            add_gpio(c, name, pad, drive, slew, strength)
        c.net("PWM_Trig")
        c.net("PWM_TRIG_TAP", skip=(("R9.1", "U19.2"),) if optd else ())
        c.net("CH1_J10")
        c.net("_PULSE_OUT_CH1")
        c.net("_PULSE_OUT_CH2")
        for p in ("J10.1", "J10.2", "J10.3"):
            c.C(node(p), BP["header_pin_pF_est"])
        if j10 == "23":
            c.L(node("J10.3"), node("J10.2"), BP["shunt_nH_est"])
        elif j10 == "12":
            c.L(node("J10.1"), node("J10.2"), BP["shunt_nH_est"])
        add_r(c, "R19.1", "R19.2", r19, "0805")
        add_r(c, "R9.1", "0", BP["r9"], "0805")
        add_r(c, "R17.1", "0", BP["r17"], "0805")
        add_r(c, "R18.1", "0", BP["r18"], "0805")
        add_input(c, "U5.2", GATES["SN74LVC1G04"]["ci_pF"], True)
        add_input(c, "U19.2", DRVC["ci_pF"], False)
        add_input(c, "U7.2", GATES["SN74AHCT1G08"]["ci_pF"], True)
        add_input(c, "U8.2", GATES["SN74AHCT1G08"]["ci_pF"], True)
        c.C(node("TP4.1"), BP["tp4_pF_est"])
        nodes = ["J14.15", "J14.16", "J14.17", "U5.2", "U19.2", "U7.2", "U8.2", "J10.2"]
        if optd:
            add_gpio(c, "gp14", "J14.19", drive, slew, strength)
            nv = c.runs(node("J14.19"), node("U19.2"), DEV["option_d"]["trace"])
            assert nv == 1
            nodes.append("J14.19")
        c.tran(T_END)
        t, w = self.sp.run(c.lines, [node(n) for n in nodes])
        u5, ahct, ucc = all_thresholds()
        ths = {"J14.15": [1.65], "J14.16": [1.65], "J14.17": [1.65], "J14.19": [1.65],
               "U5.2": u5, "U19.2": ucc, "U7.2": ahct, "U8.2": ahct, "J10.2": [1.65]}
        res = {n: edge_stats(t, w[node(n)], ths[n], T_R, T_F, T_END) for n in nodes}
        self.cache[key] = res
        return res

    # ------------------------------------------------------------------------- stage B (camera)
    def stage_b(self, corner):
        """U5 output start -> U6 input crossings (B1); U6 output start -> J1..J6 pin 4 0.9 V (B2).
        Times relative to the ramp start, for the GP11 rise and fall."""
        key = ("B", corner)
        if key in self.cache:
            return self.cache[key]
        ta, tb, te = 5.0, 45.0, 85.0
        g5, g6 = GATES["SN74LVC1G04"], GATES["SN74LVC04A"]
        c = self.ckt(f"stage B1 {corner}")
        r = g5["rout"][corner]
        add_switch_out(c, "u5", node("U5.4"), g5["vcc"], r, r, g5["ramp_ns_est"][corner], ta, tb, start_high=True)
        c.net("TRIG_N")
        ins = {1: 2, 3: 4, 5: 6, 9: 8, 11: 10, 13: 12}     # U6 nA -> nY (SCAS281T pin functions)
        for p in ins:
            add_input(c, f"U6.{p}", g6["ci_pF"], True)
        c.tran(te)
        t, w = self.sp.run(c.lines, [node(f"U6.{p}") for p in ins])
        b1 = {}
        for p in ins:
            v = w[node(f"U6.{p}")]
            # GP11 rise -> U5 out falls -> U6 input falling
            th_r = vth(g6["vsw"], corner, False)
            th_f = vth(g6["vsw"], corner, True)
            b1[p] = {"rise": cross(t, v, th_r, False, ta, tb) - ta, "fall": cross(t, v, th_f, True, tb, te) - tb,
                     "vmin": float(v.min()), "vmax": float(v.max())}
        c = self.ckt(f"stage B2 {corner}")
        r = g6["rout"][corner]
        for i, (p, q) in enumerate(ins.items()):
            add_switch_out(c, f"u6y{q}", node(f"U6.{q}"), g6["vcc"], r, r, g6["ramp_ns_est"][corner], ta, tb, start_high=False)
            c.net(f"Trigger{i + 1}")
            c.C(node(f"J{i + 1}.4"), DEV["loads"]["camera_pF_est"])
        c.tran(te)
        t, w = self.sp.run(c.lines, [node(f"J{i}.4") for i in range(1, 7)])
        b2 = {}
        for i in range(1, 7):
            v = w[node(f"J{i}.4")]
            b2[i] = {"rise": cross(t, v, 0.9, True, ta, tb) - ta, "fall": cross(t, v, 0.9, False, tb, te) - tb,
                     "vmax": float(v.max()), "vmin": float(v.min())}
        res = {"b1": b1, "b2": b2, "map": ins}
        self.cache[key] = res
        return res

    # ------------------------------------------------------------------------- output chains
    CHAINS = {
        "ext": dict(drv="U19.7", raw="EXT_SYNC_DRIVE_RAW", rs="R30", drive="EXT_SYNC_DRIVE", rx="R31",
                    jp="J21", out="EXT_SYNC_OUT", term="EXT_SYNC_TERM", rp="R32", bnc="J12"),
        "ch1": dict(drv="U13.7", raw="CH1_DRIVE_RAW", rs="R6", drive="CH1_DRIVE", rx="R25",
                    jp="J18", out="CH1_OUT", term="CH1_TERM", rp="R27", bnc="J7"),
        "ch2": dict(drv="U13.5", raw="CH2_DRIVE_RAW", rs="R7", drive="CH2_DRIVE", rx="R26",
                    jp="J19", out="CH2_OUT", term="CH2_TERM", rp="R28", bnc="J8"),
    }

    def add_chain(self, c, ch, mode, cable_m, load, amp):
        """One output chain (R68, J-mode jumper, R47, R82, BNC, cable, load). load: '50', 'hiz'
        (1 Mohm || 15 pF) or 'short' (1 mohm at the far end of the cable). Resistor nodes for the
        power check are kept in self.rnodes[ch]."""
        k = self.CHAINS[ch]
        for n in (k["raw"], k["drive"], k["out"], k["term"]):
            c.net(n)
        self.rnodes = getattr(self, "rnodes", {})
        self.rnodes[ch] = {
            "rs": add_r(c, k["rs"] + ".1", k["rs"] + ".2", OC["r68"][amp], "2512"),
            "rx": add_r(c, k["rx"] + ".1", k["rx"] + ".2", OC["r47"][amp], "2512"),
            "rp": add_r(c, k["rp"] + ".1", "0", OC["r82"][amp], "2512")}
        for p in (1, 2, 3):
            c.C(node(f"{k['jp']}.{p}"), BP["header_pin_pF_est"])
        if mode == "50":
            c.L(node(k["jp"] + ".1"), node(k["jp"] + ".2"), BP["shunt_nH_est"])
        elif mode == "hiz":
            c.L(node(k["jp"] + ".2"), node(k["jp"] + ".3"), BP["shunt_nH_est"])
        b = DEV["bnc"]
        j = node(k["bnc"] + ".1")
        c.C(j, b["launch_pF"])
        be, far = f"{ch}_bnc", f"{ch}_far"
        c.T(j, be, b["z0"], b["td_ns"])
        c.T(be, far, DEV["coax"]["z0"], DEV["coax"]["td_ns_per_m"] * cable_m)
        if load == "50":
            c.R(far, "0", DEV["loads"]["r50"])
        elif load == "short":
            c.R(far, "0", 1e-3)
        else:
            c.R(far, "0", DEV["loads"]["scope_hiz"]["r"])
            c.C(far, DEV["loads"]["scope_hiz"]["c_pF"])
        return j, far

    def stage_out(self, chs, dname, corner, mode, cable_m, load):
        """Driver output ramp start -> BNC pad and far-end load. Times relative to ramp start."""
        key = ("C", tuple(chs), dname, corner, mode, cable_m, load)
        if key in self.cache:
            return self.cache[key]
        ta, width = 2.0, 150.0
        tb, te = ta + width, ta + width + 100.0
        d = DRV[dname]
        amp = AMP[corner]
        vdd = OC["vdd12"][amp]
        c = self.ckt(f"stage C {chs} {dname} {corner} {mode} {cable_m} m {load}")
        nodes = []
        for ch in chs:
            k = self.CHAINS[ch]
            add_switch_out(c, ch + "d", node(k["drv"]), vdd, d["roh"][corner], d["rol"][corner],
                           DRVC["ramp_ns"][corner], ta, tb, start_high=False)
            j, far = self.add_chain(c, ch, mode, cable_m, load, amp)
            nodes += [j, far]
        c.tran(te)
        t, w = self.sp.run(c.lines, nodes)
        res = {}
        for ch in chs:
            k = self.CHAINS[ch]
            j, far = node(k["bnc"] + ".1"), f"{ch}_far"
            r = {}
            for wn, v in (("bnc", w[j]), ("far", w[far])):
                hi = float(v[(t > tb - 5) & (t < tb)].mean())
                lo = float(v[(t > te - 5)].mean())
                tr = cross(t, v, 0.5 * hi, True, ta, tb)
                tf = cross(t, v, 0.5 * hi, False, tb, te)
                vmax = float(v[(t >= ta) & (t < tb)].max())
                vmin = float(v[t >= tb].min())
                band = 0.02 * hi
                m = (t >= ta) & (t < tb)
                outside = np.nonzero(np.abs(v[m] - hi) > band)[0]
                settle_r = float(t[m][outside[-1]] - tr) if len(outside) and tr is not None else None
                m = t >= tb
                outside = np.nonzero(np.abs(v[m] - lo) > band)[0]
                settle_f = float(t[m][outside[-1]] - tf) if len(outside) and tf is not None else None
                r[wn] = {"high": hi, "low": lo, "t_rise": None if tr is None else tr - ta,
                         "t_fall": None if tf is None else tf - tb, "vmax": vmax, "vmin": vmin,
                         "overshoot_pct": 100.0 * (vmax - hi) / hi, "settle_rise": settle_r, "settle_fall": settle_f}
            res[ch] = r
        self.cache[key] = res
        return res

    def stage_power(self, mode, load, corner, dname="UCC27524_new", cable_m=1.0):
        """J12 chain held high for 300 ns: power in R30 / R31 / R32 (W) averaged over the last
        50 ns of the high time (steady state), and the peak instantaneous R30 power."""
        key = ("P", mode, load, corner, dname, cable_m)
        if key in self.cache:
            return self.cache[key]
        ta, tb = 2.0, 302.0
        d = DRV[dname]
        amp = AMP[corner]
        vdd = OC["vdd12"][amp]
        c = self.ckt(f"stage P {mode} {load} {corner}")
        add_switch_out(c, "extd", node("U19.7"), vdd, d["roh"][corner], d["rol"][corner],
                       DRVC["ramp_ns"][corner], ta, tb, start_high=False)
        self.add_chain(c, "ext", mode, cable_m, load, amp)
        rn = self.rnodes["ext"]
        c.tran(tb)
        nodes = sorted({n for v in rn.values() for n in v[:2]})
        t, w = self.sp.run(c.lines, nodes)
        res = {}
        ss = t > tb - 50.0
        for name, (na, m, ohm) in rn.items():
            p = (w[na] - w[m]) ** 2 / ohm
            res[name] = {"p_ss": float(p[ss].mean()), "p_peak": float(p.max()),
                         "i_ss": float(((w[na] - w[m]) / ohm)[ss].mean())}
        self.cache[key] = res
        return res

    # ------------------------------------------------------------------------- stage D1 (laser gates)
    def stage_d1(self, corner, dname="UCC27524_new"):
        key = ("D1", corner, dname)
        if key in self.cache:
            return self.cache[key]
        ta, tb, te = 5.0, 45.0, 85.0
        g = GATES["SN74AHCT1G08"]
        d = DRV[dname]
        c = self.ckt(f"stage D1 {corner}")
        r = g["rout"][corner]
        for ref, net, inp in (("U7", "CH1_GATED", "U13.2"), ("U8", "CH2_GATED", "U13.4")):
            add_switch_out(c, ref.lower(), node(ref + ".4"), g["vcc"], r, r, g["ramp_ns_est"][corner], ta, tb, start_high=False)
            c.net(net)
            add_input(c, inp, DRVC["ci_pF"], False)
        c.tran(te)
        t, w = self.sp.run(c.lines, [node("U13.2"), node("U13.4")])
        res = {}
        for inp in ("U13.2", "U13.4"):
            v = w[node(inp)]
            res[inp] = {"rise": cross(t, v, drv_th(d, corner, True), True, ta, tb) - ta,
                        "fall": cross(t, v, drv_th(d, corner, False), False, tb, te) - tb}
        self.cache[key] = res
        return res


# ----------------------------------------------------------------------------- path timing
def a_cross(a, pad, edge, th):
    return a[pad][edge][th][0]


def edge_t0(edge):
    return T_R if edge == "rise" else T_F


def j12_delay(M, a, dname, corner, edge, mode="50", cable=1.0, load="50", ref="far"):
    """t0 (GPIO internal edge start) -> J12 50 %. ref 'bnc' = J12.1 pad; 'far' = load
    (minus the cable delay, so it is referred to J12)."""
    d = DRV[dname]
    rising = edge == "rise"
    th = drv_th(d, corner, rising)
    tin = a_cross(a, "U19.2", edge, th)
    if tin is None:
        return None
    ti = M.drv_tint(dname, corner, rising)["tint"]
    o = M.stage_out(("ext",), dname, corner, mode, cable, load)["ext"][ref]
    dout = o["t_rise"] if rising else o["t_fall"]
    if ref == "far":
        dout -= DEV["coax"]["td_ns_per_m"] * cable
    return tin - edge_t0(edge) + ti + dout


def camera_delays(M, a, corner, edge):
    """t0 -> J1..J6 pin 4 at 0.9 V (list of 6)."""
    rising = edge == "rise"
    g5 = GATES["SN74LVC1G04"]
    tin = a_cross(a, "U5.2", edge, vth(g5["vsw"], corner, rising))
    if tin is None:
        return None
    t5 = M.gate_tint("SN74LVC1G04", corner, rising)["tint"]
    t6 = M.gate_tint("SN74LVC04A", corner, not rising)["tint"]
    b = M.stage_b(corner)
    out = []
    for i, (p, q) in enumerate(b["map"].items()):
        out.append(tin - edge_t0(edge) + t5 + b["b1"][p][edge] + t6 + b["b2"][i + 1][edge])
    return out


def laser_delays(M, a, corner, edge, dname="UCC27524_new"):
    """t0 -> J7 / J8 50 % into 50 ohm via 1 m RG-58 (referred to the BNC), J18/J19 on 1-2."""
    rising = edge == "rise"
    g = GATES["SN74AHCT1G08"]
    th = vth(g["vsw"], corner, rising)
    tg = M.gate_tint("SN74AHCT1G08", corner, rising)["tint"]
    d1 = M.stage_d1(corner, dname)
    tu = M.drv_tint(dname, corner, rising)["tint"]
    o = M.stage_out(("ch1", "ch2"), dname, corner, "50", 1.0, "50")
    res = {}
    for ch, pad, inp in (("ch1", "U7.2", "U13.2"), ("ch2", "U8.2", "U13.4")):
        tin = a_cross(a, pad, edge, th)
        dd = o[ch]["far"]["t_rise" if rising else "t_fall"] - DEV["coax"]["td_ns_per_m"]
        res[ch] = None if tin is None else tin - edge_t0(edge) + tg + d1[inp][edge] + tu + dd
    return res


# ----------------------------------------------------------------------------- report helpers
def f(x, n=2):
    if x is None:
        return "n/a"
    s = f"{x:.{n}f}"
    return s[1:] if s.startswith("-") and float(s) == 0 else s     # no "-0.000"


def table(head, rows):
    s = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    s += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(s)


DRIVE_SETTINGS = [(4, "slow"), (4, "fast"), (8, "slow"), (8, "fast"), (12, "slow"), (12, "fast")]


def main():
    t_start = time.time()
    sp = Spice(KICAD_BIN)
    M = Model(sp)
    R = {"meta": {"tmax_ps": TMAX_PS, "lump_mm": LUMP_MM}}
    md = []
    P = lambda *s: md.extend(s)

    # ======================================================================= case 1: CH1 vs CH2 skew
    c1 = []
    for drive, slew in ((4, "slow"), (12, "fast")):
        for j10 in ("23", "12", "open"):
            for r19 in (BP["r19"], 0.0):
                for st in GPIO_CORNERS:
                    a = M.stage_a(j10, r19, drive, slew, st)
                    row = {"drive": drive, "slew": slew, "j10": j10, "r19": r19, "gpio": st}
                    for edge in EDGES:
                        g = GATES["SN74AHCT1G08"]["vsw"]
                        sk = {}
                        for lab, th in (("typ", g["typ"]), ("lo", g["min"]), ("hi", g["max"])):
                            t1, t2 = a_cross(a, "U7.2", edge, th), a_cross(a, "U8.2", edge, th)
                            sk[lab] = None if (t1 is None or t2 is None) else t1 - t2
                        las = laser_delays(M, a, "typ", edge)
                        row[edge] = {"u7_in": a_cross(a, "U7.2", edge, g["typ"]) - edge_t0(edge),
                                     "u8_in": a_cross(a, "U8.2", edge, g["typ"]) - edge_t0(edge),
                                     "skew_in": sk, "j7": las["ch1"], "j8": las["ch2"],
                                     "skew_out": las["ch1"] - las["ch2"],
                                     "u5_in": a_cross(a, "U5.2", edge, 0.9),
                                     "u19_in": a_cross(a, "U19.2", edge, 2.0 if edge == "rise" else 1.0)}
                        for k in ("u5_in", "u19_in"):
                            if row[edge][k] is not None:
                                row[edge][k] -= edge_t0(edge)
                    c1.append(row)
    R["case1"] = c1

    P("## Case 1: CH1 versus CH2 skew (R19 and J10)", "",
      "GP12 and GP13 switch at the same instant t0. Skew = CH1 minus CH2 (positive: CH1 late). "
      "U7.2 / U8.2: crossing of the AHCT threshold (1.4 V est; in brackets the skew at "
      "0.8 V and at 2.0 V, the guaranteed band). J7 / J8: 50 % into 50 ohm through 1 m RG-58, all devices typical and "
      "identical on both channels, so the J7-J8 skew is from routing and loading only (U13 channel "
      "matching, SLUSFA9 tM 1 / 2 ns, comes on top). J10 'open' and '2-3' are the same circuit for "
      "CH1 (J10.1 open in both). The GPIO setting applies to GP11, GP12 and GP13. With J10 on 1-2 "
      "the CH1 edge has a reflection step; where the step sits near 0.8 V or 2.0 V, the skew at "
      "that threshold jumps (bracketed values above 1 ns).", "")
    rows = []
    for r in c1:
        if r["gpio"] != "typ":
            continue
        for edge in EDGES:
            e = r[edge]
            rows.append([f"{r['drive']} mA {r['slew']}", {"23": "2-3", "12": "1-2", "open": "open"}[r["j10"]],
                         f"{r['r19']:.0f}", edge, f(e["u7_in"]), f(e["u8_in"]),
                         f"{f(e['skew_in']['typ'], 3)} [{f(e['skew_in']['lo'], 3)}, {f(e['skew_in']['hi'], 3)}]",
                         f(e["skew_out"], 3)])
    P(table(["GPIO", "J10", "R19 (ohm)", "edge", "t0 -> U7.2 (ns)", "t0 -> U8.2 (ns)",
             "skew at U7/U8 (ns)", "skew at J7/J8 (ns)"], rows), "")
    rows = []
    for drive, slew in ((4, "slow"), (12, "fast")):
        for j10 in ("23", "12"):
            for r19 in (BP["r19"], 0.0):
                sel = [r for r in c1 if r["drive"] == drive and r["slew"] == slew and r["j10"] == j10 and r["r19"] == r19]
                vals = [r[e]["skew_in"][k] for r in sel for e in EDGES for k in ("typ", "lo", "hi") if r[e]["skew_in"][k] is not None]
                outs = [r[e]["skew_out"] for r in sel for e in EDGES]
                rows.append([f"{drive} mA {slew}", {"23": "2-3", "12": "1-2"}[j10], f"{r19:.0f}",
                             f"{min(vals):.3f} .. {max(vals):.3f}", f"{min(outs):.3f} .. {max(outs):.3f}"])
    P("Range over the strong / typical / weak GPIO corners, both edges and the AHCT threshold band:", "",
      table(["GPIO", "J10", "R19 (ohm)", "skew at U7/U8 (ns)", "skew at J7/J8 (ns)"], rows), "")
    cam_cost = []
    for r19 in (BP["r19"], 0.0):
        r12 = [r for r in c1 if r["drive"] == 4 and r["j10"] == "12" and r["r19"] == r19 and r["gpio"] == "typ"][0]
        cam_cost.append([f"{r19:.0f}", f(r12["rise"]["u5_in"]), f(r12["fall"]["u5_in"]),
                         f(r12["rise"]["u19_in"]), f(r12["fall"]["u19_in"])])
    r23 = [r for r in c1 if r["drive"] == 4 and r["j10"] == "23" and r["r19"] == BP["r19"] and r["gpio"] == "typ"][0]
    cam_cost.append(["(J10 2-3, from GP11)", f(r23["rise"]["u5_in"]), f(r23["fall"]["u5_in"]),
                     f(r23["rise"]["u19_in"]), f(r23["fall"]["u19_in"])])
    P("Cost of R19 to the camera / J12 input with J10 on 1-2 (4 mA slow, typical GPIO): t0 to the "
      "U5.2 crossing of 0.9 V and the U19.2 crossing of VIN_H 2.0 V / VIN_L 1.0 V:", "",
      table(["R19 (ohm)", "U5.2 rise (ns)", "U5.2 fall (ns)", "U19.2 rise (ns)", "U19.2 fall (ns)"], cam_cost), "")

    # ======================================================================= case 2: J12 vs camera
    die_list = ("UCC27524_new", "UCC27524_legacy")
    loads = [("50", 1.0, "50"), ("50", 3.0, "50"), ("hiz", 1.0, "hiz"), ("hiz", 3.0, "hiz")]
    A = {st: M.stage_a("23", None, 4, "slow", st) for st in GPIO_CORNERS + ("floor",)}
    c2 = {"pin50": {}, "j12": {}, "cam": {}, "off": {}, "wave": {}}
    for st, a in A.items():
        c2["pin50"][st] = {e: a_cross(a, "J14.15", e, 1.65) - edge_t0(e) for e in EDGES}
    for dn in die_list:
        for (mode, cab, ld) in loads:
            key = f"{dn}|{mode}|{cab}"
            c2["j12"][key] = {}
            for edge in EDGES:
                c2["j12"][key][edge] = {}
                for st in GPIO_CORNERS:
                    c2["j12"][key][edge][st] = {cn: j12_delay(M, A[st], dn, cn, edge, mode, cab, ld) for cn in CORNERS}
                c2["j12"][key][edge]["floor"] = {cn: j12_delay(M, A["floor"], dn, cn, edge, mode, cab, ld) for cn in CORNERS}
            for cn in CORNERS:
                c2["wave"][f"{key}|{cn}"] = M.stage_out(("ext",), dn, cn, mode, cab, ld)["ext"]
    for edge in EDGES:
        c2["cam"][edge] = {st: {cn: camera_delays(M, A[st], cn, edge) for cn in CORNERS} for st in GPIO_CORNERS + ("floor",)}

    def jd(dn, mode, cab, edge, st, cn):
        return c2["j12"][f"{dn}|{mode}|{cab}"][edge][st][cn]

    def cm(edge, st, cn):
        v = c2["cam"][edge][st][cn]
        return None if v is None else float(np.mean(v))

    def offsets(dn, edge, mode="50", cab=1.0):
        typ = jd(dn, mode, cab, edge, "typ", "typ") - cm(edge, "typ", "typ")
        lo = min(jd(dn, mode, cab, edge, st, "min") - cm(edge, st, "max") for st in GPIO_CORNERS)
        hi = max(jd(dn, mode, cab, edge, st, "max") - cm(edge, st, "min") for st in GPIO_CORNERS)
        return lo, typ, hi

    for dn in die_list:
        c2["off"][dn] = {e: offsets(dn, e) for e in EDGES}
    R["case2"] = c2

    P("## Case 2: J12 delay, waveform and offset from the camera triggers", "",
      "J10 on 2-3, GP11 at the reset default (4 mA, slow slew). Delays start at t0, the GP11 "
      "internal edge (the PIO SET instant). 'From pin' subtracts the time from t0 to the 50 % "
      "(1.65 V) crossing at the J14.15 pad, for the same GPIO corner. Corners: min = strong GPIO "
      "with every device at its fast corner, typ = all typical, max = weak GPIO with every device at "
      "its slow corner, floor = GPIO on the RP2350 Table 1683 VOH/VOL limit with devices at max. "
      "50 ohm mode: 50 % at the load, minus the cable delay (= J12.1). Hi-Z mode: same, at the "
      "1 Mohm || 15 pF load (J12.1 itself steps to about half amplitude first).", "")
    pr = c2["pin50"]
    P(table(["GPIO corner", "t0 -> J14.15 50 %, rise (ns)", "fall (ns)"],
            [[st, f(pr[st]["rise"]), f(pr[st]["fall"])] for st in GPIO_CORNERS + ("floor",)]), "")
    for dn in die_list:
        rows = []
        for (mode, cab, ld) in loads:
            for edge in EDGES:
                mn = jd(dn, mode, cab, edge, "strong", "min")
                ty = jd(dn, mode, cab, edge, "typ", "typ")
                mx = jd(dn, mode, cab, edge, "weak", "max")
                fl = jd(dn, mode, cab, edge, "floor", "max")
                rows.append([f"{'50 ohm' if mode == '50' else 'Hi-Z'}, {cab:.0f} m", edge, f(mn), f(ty), f(mx), f(fl),
                             f(ty - pr["typ"][edge])])
        P(f"J12 delay, {DRV[dn]['label']}:", "",
          table(["J21 mode, cable", "edge", "min (ns)", "typ (ns)", "max (ns)", "floor (ns)", "typ from pin (ns)"], rows), "")
    rows = []
    for (mode, cab, ld) in loads:
        for cn in CORNERS:
            w = c2["wave"][f"UCC27524_new|{mode}|{cab}|{cn}"]["far"]
            rows.append([f"{'50 ohm' if mode == '50' else 'Hi-Z'}, {cab:.0f} m", cn, f(w["high"]), f(w["vmax"]), f(w["overshoot_pct"], 1),
                         f(w["vmin"]), f(w["low"], 3), f(w["settle_rise"], 1), f(w["settle_fall"], 1)])
    P("J12 waveform at the load (UCC27524 new die; corner sets VDD, ROH/ROL, 1 % resistors and the "
      "output ramp: min = 12.05 V / high amplitude, max = 11.54 V / low amplitude). Settling: last "
      "exit from a +/- 2 % band, after the 50 % crossing:", "",
      table(["J21 mode, cable", "corner", "high (V)", "peak (V)", "overshoot (%)", "undershoot (V)", "low (V)",
             "settle rise (ns)", "settle fall (ns)"], rows), "")
    rows = []
    for edge in EDGES:
        for st in ("strong", "typ", "weak", "floor"):
            for cn in CORNERS:
                if (st, cn) not in (("strong", "min"), ("typ", "typ"), ("weak", "max"), ("floor", "max")):
                    continue
                v = c2["cam"][edge][st][cn]
                rows.append([edge, f"{st} / {cn}"] + [f(x) for x in v] + [f(max(v) - min(v), 3)])
    P("Camera trigger delay, t0 to J1..J6 pin 4 at 0.9 V (5 pF est per pin; ribbon cable not modelled):", "",
      table(["edge", "GPIO / devices", "J1", "J2", "J3", "J4", "J5", "J6", "J1-J6 spread"], rows), "")
    rows = []
    for dn in die_list:
        for edge in EDGES:
            lo, ty, hi = c2["off"][dn][edge]
            rows.append([DRV[dn]["label"], edge, f(lo), f(ty), f(hi)])
    P("J12 (50 ohm, 1 m) minus camera trigger (mean of J1-J6). The GPIO corner is shared by both "
      "paths; the device corners are taken independently (min = J12 fast and cameras slow):", "",
      table(["U19", "edge", "min (ns)", "typ (ns)", "max (ns)"], rows), "")
    a = A["typ"]
    br = []
    for dn in die_list:
        for edge in EDGES:
            rising = edge == "rise"
            d = DRV[dn]
            tin = a_cross(a, "U19.2", edge, drv_th(d, "typ", rising)) - edge_t0(edge)
            ti = M.drv_tint(dn, "typ", rising)
            o = M.stage_out(("ext",), dn, "typ", "50", 1.0, "50")["ext"]["far"]
            dout = (o["t_rise"] if rising else o["t_fall"]) - DEV["coax"]["td_ns_per_m"]
            u5 = a_cross(a, "U5.2", edge, 0.9) - edge_t0(edge)
            br.append([DRV[dn]["label"], edge, f(tin), f(ti["tint"]), f(ti["dload"]), f(dout), f(u5),
                       f(M.gate_tint("SN74LVC1G04", "typ", rising)["tint"]), f(M.gate_tint("SN74LVC04A", "typ", not rising)["tint"])])
    P("Typical breakdown: t0 -> U19.2 VIN crossing; U19 internal delay (= tD minus the model's "
      "start-to-10 % / 90 % time into 1.8 nF, given as 'cal'); U19 ramp start -> J12 50 %; t0 -> "
      "U5.2 0.9 V; U5 and U6 internal delays (tpd minus their test-load time):", "",
      table(["U19", "edge", "t0->U19.2", "U19 int.", "cal", "U19->J12", "t0->U5.2", "U5 int.", "U6 int."], br), "")

    # ======================================================================= case 3: J7/J8 levels
    rows = []
    c3 = {}
    for dn in die_list:
        for cn in CORNERS:
            o = M.stage_out(("ch1", "ch2"), dn, cn, "50", 1.0, "50")
            amp = AMP[cn]
            hand = OC["vdd12"][amp] * 50 / (50 + OC["r68"][amp] + DRV[dn]["roh"][cn])
            c3[f"{dn}|{cn}"] = {"ch1": o["ch1"]["far"], "ch2": o["ch2"]["far"], "hand": hand}
            rows.append([DRV[dn]["label"], f"{amp} ({OC['vdd12'][amp]} V, R6 {OC['r68'][amp]}, ROH {DRV[dn]['roh'][cn]:g})",
                         f(hand, 3), f(o["ch1"]["far"]["high"], 3), f(o["ch2"]["far"]["high"], 3),
                         f(o["ch1"]["far"]["overshoot_pct"], 1), f(o["ch1"]["far"]["low"], 4), f(o["ch1"]["far"]["vmin"], 3)])
    R["case3"] = c3
    P("## Case 3: laser outputs J7 / J8 into 50 ohm", "",
      "J18/J19 on 1-2, 1 m RG-58, 50 ohm load. Hand value = VDD x 50 / (50 + R6 + ROH) (Hardware.md "
      "'Amplitude budget': 4.54 / 4.79 / 5.14 V). LDP-V window: 4.5-5.2 V high, <= 0.2 V low.", "",
      table(["U13", "corner", "hand (V)", "J7 high (V)", "J8 high (V)", "overshoot (%)", "low (V)", "undershoot (V)"], rows), "")
    # ======================================================================= case 4: R30 power
    rows, c4 = [], []
    duty_m, duty_c = DEV["firmware_duty"]["marker"], DEV["firmware_duty"]["combine"]
    for mode in ("50", "hiz"):
        for load in ("50", "short", "hiz"):
            if mode == "50" and load == "hiz":      # no current: nothing to check
                continue
            for cn in CORNERS:
                amp = AMP[cn]
                d = DRV["UCC27524_new"]
                v, rs, rx, rp = OC["vdd12"][amp], OC["r68"][amp], OC["r47"][amp], OC["r82"][amp]
                rl = {"50": DEV["loads"]["r50"], "short": 1e-3, "hiz": DEV["loads"]["scope_hiz"]["r"]}[load]
                # hand: series circuit ROH + R30 (+ R31 + R32 || load in Hi-Z mode; R31 bypassed and
                # R32 not connected in 50 ohm mode)
                rest = rl if mode == "50" else rx + rp * rl / (rp + rl)
                i = v / (d["roh"][cn] + rs + rest)
                hand30 = i * i * rs
                hand31 = i * i * rx if mode == "hiz" else 0.0
                vj = i * (rp * rl / (rp + rl)) if mode == "hiz" else 0.0
                hand32 = vj * vj / rp
                p = M.stage_power(mode, load, cn)
                c4.append({"mode": mode, "load": load, "corner": cn, "hand": [hand30, hand31, hand32], "sim": p})
                rows.append([{"50": "50 ohm", "hiz": "Hi-Z"}[mode],
                             {"50": "50 ohm", "short": "short", "hiz": "1 Mohm"}[load], amp,
                             f(1e3 * p["rs"]["i_ss"], 1), f(hand30, 3), f(p["rs"]["p_ss"], 3),
                             f(p["rs"]["p_ss"] * duty_m, 3), f(p["rs"]["p_ss"] * duty_c, 3),
                             f(hand31, 3), f(p["rx"]["p_ss"], 3), f(hand32, 3), f(p["rp"]["p_ss"], 3)])
    R["case4"] = c4
    P("## Case 4: R30 power (sanity check)", "",
      "J12 chain, UCC27524 new die, held high for 300 ns through 1 m RG-58 into the load named; "
      "'short' = 1 mohm at the cable end. Power = steady state while high (last 50 ns). Hand = the "
      "series circuit VDD / (ROH + R30 [+ R31 + R32 || load]). Average = power while high x the "
      f"firmware's duty limit: {duty_m:.0%} (2 x MARKERWIDTH <= 1/FREQ) or {duty_c:.0%} (J10 on 1-2 "
      "with COMBINE 1). Corner: high = 12.05 V, ROH 0.01 ohm, 1 % resistors low; low = 11.54 V, "
      "ROH 8.5 ohm, resistors high. Compare Hardware.md 'Board output rating' and 'Output mode': "
      "0.71 W into 50 ohm, 1.5-2.16 W stuck high into a short, 1.08 W / 1.45 W average, R31 0.52 W "
      "and R32 0.31 W in Hi-Z mode. R30 is a 2 W 2512.", "",
      table(["J21 mode", "load", "corner", "I(R30) (mA)", "R30 hand (W)", "R30 sim (W)",
             f"R30 avg {duty_m:.0%} (W)", f"R30 avg {duty_c:.0%} (W)", "R31 hand (W)", "R31 sim (W)",
             "R32 hand (W)", "R32 sim (W)"], rows), "")

    # ======================================================================= case 5: options
    c5 = {"fw": [], "drivers": [], "optd": [], "ring": []}
    for drive, slew in DRIVE_SETTINGS:
        for st in GPIO_CORNERS:
            a = M.stage_a("23", None, drive, slew, st)
            row = {"drive": drive, "slew": slew, "gpio": st}
            for nd in ("J14.15", "U5.2", "U19.2"):
                row[nd] = {e: {"vmax": a[nd][e]["vmax"], "vmin": a[nd][e]["vmin"]} for e in EDGES}
            # ring-back after the first threshold crossing
            b5, b19 = GATES["SN74LVC1G04"]["vsw"], DRV["UCC27524_new"]
            row["u5_rb"] = {"rise": a["U5.2"]["rise"][b5["max"]][1], "fall": a["U5.2"]["fall"][b5["min"]][1]}
            row["u19_rb"] = {"rise": a["U19.2"]["rise"][b19["vin_h"]["max"]][1],
                             "fall": a["U19.2"]["fall"][b19["vin_l"]["min"]][1]}
            c5["ring"].append(row)
    rows = []
    rb = lambda x: "monotonic" if x is None else f(x)
    for r in c5["ring"]:
        u5b = GATES["SN74LVC1G04"]["vsw"]
        risk5 = (r["u5_rb"]["rise"] is not None and r["u5_rb"]["rise"] < u5b["max"]) or \
                (r["u5_rb"]["fall"] is not None and r["u5_rb"]["fall"] > u5b["min"])
        nd = DRV["UCC27524_new"]
        risk19 = (r["u19_rb"]["rise"] is not None and r["u19_rb"]["rise"] < nd["vin_l"]["max"]) or \
                 (r["u19_rb"]["fall"] is not None and r["u19_rb"]["fall"] > nd["vin_h"]["min"])
        rows.append([f"{r['drive']} mA {r['slew']}", r["gpio"], f(r["J14.15"]["rise"]["vmax"]), f(r["J14.15"]["fall"]["vmin"]),
                     f(r["U5.2"]["rise"]["vmax"]), f(r["U5.2"]["fall"]["vmin"]),
                     rb(r["u5_rb"]["rise"]), rb(r["u5_rb"]["fall"]), "yes" if risk5 else "no",
                     rb(r["u19_rb"]["rise"]), rb(r["u19_rb"]["fall"]), "yes" if risk19 else "no"])
    P("## Case 5: delay-reduction options", "",
      "### GP11 drive strength and slew rate: ringing on PWM_Trig / PWM_TRIG_TAP", "",
      "J10 on 2-3. Pin = J14.15 pad (absolute maximum 3.8 V, RP2350 Table 1680). Ring-back = the "
      "lowest value after the first peak of a rising edge (highest after the first dip of a falling "
      "edge), taken after the edge has left the receiver's threshold band (U5: above 1.17 V / below "
      "0.63 V; U19: above 2.3 V / below 0.8 V); 'monotonic' = no peak. The value includes a dip "
      "inside a stepped edge, not only the ring after the final level (a value well below the "
      "final level, above the band, is such a dip). U5 has no hysteresis: "
      "'risk' = the ring-back re-enters its 0.63-1.17 V band, so a camera trigger can fire twice. "
      "U19 'risk' = the ring-back passes VIN_L max 1.2 V (rise) or VIN_H min 1.8 V (fall). The U5 "
      "input clamp to GND is modelled (est). For the effect of the pad setting on the CH1/CH2 "
      "skew, see the 12 mA fast rows of case 1.", "",
      table(["GP11", "GPIO", "pin max (V)", "pin min (V)", "U5.2 max (V)", "U5.2 min (V)",
             "U5 ring-back rise (V)", "fall (V)", "U5 risk", "U19 ring-back rise (V)", "fall (V)", "U19 risk"], rows), "")
    rows = []
    for dn in ("UCC27524_new", "UCC27524_legacy", "2EDN7524F", "UCC27517A"):
        for drive, slew in ((4, "slow"), (12, "slow"), (12, "fast")):
            AA = {st: M.stage_a("23", None, drive, slew, st) for st in GPIO_CORNERS}
            ent = {"driver": dn, "drive": drive, "slew": slew}
            for edge in EDGES:
                jt = j12_delay(M, AA["typ"], dn, "typ", edge)
                ct = float(np.mean(camera_delays(M, AA["typ"], "typ", edge)))
                lo = min(j12_delay(M, AA[st], dn, "min", edge) - float(np.mean(camera_delays(M, AA[st], "max", edge))) for st in GPIO_CORNERS)
                hi = max(j12_delay(M, AA[st], dn, "max", edge) - float(np.mean(camera_delays(M, AA[st], "min", edge))) for st in GPIO_CORNERS)
                ent[edge] = {"j12_typ": jt, "j12_min": j12_delay(M, AA["strong"], dn, "min", edge),
                             "j12_max": j12_delay(M, AA["weak"], dn, "max", edge), "cam_typ": ct,
                             "off_typ": jt - ct, "off_min": lo, "off_max": hi}
                rows.append([DRV[dn]["label"], f"{drive} mA {slew}", edge, f(ent[edge]["j12_min"]), f(jt), f(ent[edge]["j12_max"]),
                             f(ct), f(lo), f(jt - ct), f(hi)])
            c5["drivers"].append(ent)
    P("### U19 driver choice and GP11 pad setting", "",
      "J12: 50 ohm mode, 1 m. Camera: mean of J1-J6. Offset = J12 minus camera. The GP11 pad "
      "setting is a firmware change (gpio_set_drive_strength / gpio_set_slew_rate); 12 mA fast "
      "exceeds the pin absolute maximum (table above).", "",
      table(["U19", "GP11", "edge", "J12 min (ns)", "J12 typ (ns)", "J12 max (ns)", "camera typ (ns)",
             "offset min (ns)", "offset typ (ns)", "offset max (ns)"], rows), "")
    rows = []
    for dn in ("UCC27524_new", "2EDN7524F"):
        for drive, slew in ((4, "slow"), (12, "fast")):
            AD = {st: M.stage_a("23", None, drive, slew, st, optd=True) for st in GPIO_CORNERS}
            for edge in EDGES:
                jt = j12_delay(M, AD["typ"], dn, "typ", edge)
                ct = float(np.mean(camera_delays(M, AD["typ"], "typ", edge)))
                lo = min(j12_delay(M, AD[st], dn, "min", edge) - float(np.mean(camera_delays(M, AD[st], "max", edge))) for st in GPIO_CORNERS)
                hi = max(j12_delay(M, AD[st], dn, "max", edge) - float(np.mean(camera_delays(M, AD[st], "min", edge))) for st in GPIO_CORNERS)
                t19 = a_cross(AD["typ"], "U19.2", edge, drv_th(DRV[dn], "typ", edge == "rise")) - edge_t0(edge)
                c5["optd"].append({"driver": dn, "drive": drive, "slew": slew, "edge": edge, "j12_typ": jt, "cam_typ": ct,
                                   "off": [lo, jt - ct, hi], "t0_u19": t19})
                rows.append([DRV[dn]["label"], f"{drive} mA {slew}", edge, f(t19), f(jt), f(ct), f(lo), f(jt - ct), f(hi)])
    P("### Option d: U19 on its own GPIO (GP14, estimated 90 mm trace), no PIO lead", "",
      "U19.2 is cut from PWM_TRIG_TAP; GP14 and GP11 switch at the same t0. A PIO lead of N "
      "cycles on GP14 subtracts N x 6.67 ns (150 MHz) or N x 3.33 ns (300 MHz) from every J12 "
      "number and offset below.", "",
      table(["U19", "GPIO", "edge", "t0 -> U19.2 (ns)", "J12 typ (ns)", "camera typ (ns)",
             "offset min (ns)", "offset typ (ns)", "offset max (ns)"], rows), "")
    R["case5"] = c5

    # ======================================================================= hand checks
    checks = []
    # 1. amplitude into 50 ohm (J12 chain, 50 ohm mode)
    for cn in CORNERS:
        amp = AMP[cn]
        d = DRV["UCC27524_new"]
        hand = OC["vdd12"][amp] * 50 / (50 + OC["r68"][amp] + d["roh"][cn])
        sim = c2["wave"][f"UCC27524_new|50|1.0|{cn}"]["far"]["high"]
        checks.append([f"J12 high into 50 ohm, {amp}", "VDD x 50 / (50 + R30 + ROH)", f(hand, 3), f(sim, 3), f(sim - hand, 3)])
    # 2. Hi-Z open-circuit level and Hi-Z mode into 50 ohm
    for cn in CORNERS:
        amp = AMP[cn]
        d = DRV["UCC27524_new"]
        rs, rx, rp, v = OC["r68"][amp] + d["roh"][cn], OC["r47"][amp], OC["r82"][amp], OC["vdd12"][amp]
        rl = DEV["loads"]["scope_hiz"]["r"]
        rpl = rp * rl / (rp + rl)
        hand = v * rpl / (rs + rx + rpl)
        sim = c2["wave"][f"UCC27524_new|hiz|1.0|{cn}"]["far"]["high"]
        checks.append([f"J12 Hi-Z mode into 1 Mohm, {amp}", "VDD x Rp / (R30 + ROH + R31 + Rp)", f(hand, 3), f(sim, 3), f(sim - hand, 3)])
        vth_, rth = v * rp / (rs + rx + rp), (rs + rx) * rp / (rs + rx + rp)   # Thevenin at J12
        hand = vth_ * 50 / (rth + 50)
        o = M.stage_out(("ext",), "UCC27524_new", cn, "hiz", 1.0, "50")["ext"]["far"]["high"]
        checks.append([f"J12 Hi-Z mode into 50 ohm, {amp}", "Thevenin VDD Rp/(Rs+Rx+Rp) behind (Rs+Rx) parallel Rp",
                       f(hand, 3), f(o, 3), f(o - hand, 3)])
    # 3. cable delay: 3 m minus 1 m far-end crossing, 50 ohm mode
    w1 = M.stage_out(("ext",), "UCC27524_new", "typ", "50", 1.0, "50")["ext"]["far"]["t_rise"]
    w3 = M.stage_out(("ext",), "UCC27524_new", "typ", "50", 3.0, "50")["ext"]["far"]["t_rise"]
    hand = 2 * DEV["coax"]["td_ns_per_m"]
    checks.append(["J12 load 50 %: 3 m minus 1 m RG-58", "2 m x 5.05 ns/m", f(hand, 3), f(w3 - w1, 3), f(w3 - w1 - hand, 3)])
    # 4. wavefront arrival through the extracted geometry (ideal matched step, no loads)
    c = M.ckt("check: wavefront")
    z = LAYERS["F.Cu_w0.300"]["z0_ohm"]
    c.add("Vs s 0 PWL(0 0 1n 0 1.005n 1)")
    c.R("s", node("J14.15"), z)
    c.net("PWM_Trig")
    c.L(node("J10.3"), node("J10.2"), 1e-4)
    c.net("PWM_TRIG_TAP")
    c.tran(4.0)
    t, w = sp.run(c.lines, [node("U5.2"), node("U19.2")])
    def path_ps(net, pad):
        g = GEOM["nets"][net]
        return sum(r["len_mm"] * LAYERS[f"{r['layer']}_w{r['width_mm']:.3f}"]["td_ps_per_mm"]
                   for e in g["edges"] for r in e["runs"] if e["b"] in path_edges(g, pad))
    def path_edges(g, pad):
        par = {e["b"]: e["a"] for e in g["edges"]}
        out, p = set(), pad
        while p in par:
            out.add(p)
            p = par[p]
        return out
    via_ps = math.sqrt(VIA["L_nH_est"] * 1e-9 * VIA["C_pF_est"] * 1e-12) * 1e12
    base = path_ps("PWM_Trig", "J10.3") + via_ps
    for pad in ("U5.2", "U19.2"):
        hand = (base + path_ps("PWM_TRIG_TAP", pad)) * 1e-3
        sim = cross(t, w[node(pad)], 0.05, True, 1.0) - 1.0
        checks.append([f"first arrival J14.15 -> {pad} (ideal step, no loads)", "sum of run length x Td/mm + 1 via sqrt(LC)",
                       f(hand, 3), f(sim, 3), f(sim - hand, 3)])
    # 5. gate calibration: model into the datasheet test load gives tpd back
    g5 = M.gate_tint("SN74LVC1G04", "typ", True)
    checks.append(["U5 model tpd into 30 pF parallel 1 k (typ)", "datasheet tpd (est typ 4.1 ns)", "4.100",
                   f(g5["tint"] + g5["dload"] + g5["dth"], 3), f(g5["tint"] + g5["dload"] + g5["dth"] - 4.1, 3)])
    # 6. R30 power (case 4): 50 ohm mode, high corner, into 50 ohm and into a short
    for e in c4:
        if e["mode"] == "50" and e["corner"] == "min" and e["load"] in ("50", "short"):
            checks.append([f"R30 power while high, 50 ohm mode into {'50 ohm' if e['load'] == '50' else 'a short'}, high",
                           "VDD^2 x R30 / (ROH + R30 + RL)^2", f(e["hand"][0], 3), f(e["sim"]["rs"]["p_ss"], 3),
                           f(e["sim"]["rs"]["p_ss"] - e["hand"][0], 3)])
    R["checks"] = checks

    # numerical check: halve the time step for the typical J12 and camera numbers
    M2 = Model(sp, TMAX_PS / 2)
    a1, a2 = A["typ"], M2.stage_a("23", None, 4, "slow", "typ")
    numc = []
    for edge in EDGES:
        j1, j2 = j12_delay(M, a1, "UCC27524_new", "typ", edge), j12_delay(M2, a2, "UCC27524_new", "typ", edge)
        k1, k2 = np.mean(camera_delays(M, a1, "typ", edge)), np.mean(camera_delays(M2, a2, "typ", edge))
        numc.append([edge, f(j1, 4), f(j2, 4), f(j2 - j1, 4), f(k1, 4), f(k2, 4), f(k2 - k1, 4)])
    R["numeric_check"] = numc

    cal = []
    for gname in ("SN74LVC1G04", "SN74LVC04A", "SN74AHCT1G08"):
        for cn in CORNERS:
            for ir in (True, False):
                r = M.gate_tint(gname, cn, ir)
                cal.append([gname, cn, "rise" if ir else "fall", f(GATES[gname]["tpd"][cn]), f(r["dth"]), f(r["dload"]), f(r["raw"]),
                            "clamped to 0" if r["raw"] < 0 else ""])
    for dn in ("UCC27524_new", "UCC27524_legacy", "2EDN7524F", "UCC27517A"):
        for cn in CORNERS:
            for ir in (True, False):
                r = M.drv_tint(dn, cn, ir)
                cal.append([dn, cn, "rise" if ir else "fall", f(DRV[dn]["td_rise" if ir else "td_fall"][cn]), "0.00", f(r["dload"]), f(r["raw"]),
                            "clamped to 0" if r["raw"] < 0 else ""])
    tail = ["## Gate model calibration", "",
            "Internal delay = datasheet delay - (threshold offset on the datasheet test input) - (model "
            "output delay into the datasheet test load). Input edge named.", "",
            table(["device", "corner", "input edge", "datasheet (ns)", "threshold offset", "test-load delay", "internal delay", "note"], cal), ""]
    # ======================================================================= write
    elapsed = time.time() - t_start
    head = [
        "# signal_sim results", "",
        f"Generated by `signal_sim.py` from `geometry.json` and `devices.json`. {sp.runs} ngspice runs, "
        f"{sp.points / 1e6:.1f} M time points, {elapsed:.0f} s. Maximum time step {TMAX_PS} ps; board runs "
        f"shorter than {LUMP_MM} mm are lumped LC sections, longer runs are lossless T lines.", "",
        "All times in ns, voltages in V. Many device values are estimates (see `devices.json` and the "
        "README); treat the typical columns as a model result, not a measurement.", "",
        "## Checks against hand calculations", "",
        table(["quantity", "hand calculation", "hand", "sim", "sim - hand"], checks), "",
        f"Time-step check (typical corner, 4 mA slow): maximum step {TMAX_PS} ps against {TMAX_PS / 2} ps.", "",
        table(["edge", "J12", "J12 half step", "difference", "camera", "camera half step", "difference"], numc), "",
    ]
    text = "\n".join(head + md + tail)
    open(os.path.join(HERE, "results.md"), "w", encoding="utf-8").write(text)
    json.dump(R, open(os.path.join(HERE, "results.json"), "w"), indent=1, default=lambda o: None)
    print(text)
    print(f"\n{sp.runs} runs, {elapsed:.1f} s")


if __name__ == "__main__":
    main()
