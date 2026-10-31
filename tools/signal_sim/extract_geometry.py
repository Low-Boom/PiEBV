# extract_geometry.py - routed geometry of the PiDG trigger/laser/sync nets for signal_sim.py.
# Run with KiCad 10 python (pcbnew + numpy). Reads ../../PiDG_Pico.kicad_pcb (read only);
# writes geometry.json next to this file. fd_cache.json holds the field-solver results
# (delete it to solve again: ~8 min).
# Part 1: stackup -> Z0 / Td per mm (Hammerstad-Jensen 1980 closed form, plus a 2-D
#         finite-difference field solve for the solder-mask and coplanar-pour corrections).
# Part 2: per-net graph of track segments, vias and pads, reduced to a tree of branches.
import os, sys, json, math
import numpy as np
import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
BOARD = os.path.normpath(os.path.join(HERE, "..", "..", "PiDG_Pico.kicad_pcb"))
OUT = os.path.join(HERE, "geometry.json")
C0 = 299792458.0
ETA0 = 376.730313668
MASK_ER = 3.8  # ESTIMATE: LPI solder mask er (stackup has no value; typical 3.3-4.0)

NETS = ["PWM_Trig", "PWM_TRIG_TAP", "CH1_J10", "_PULSE_OUT_CH1", "_PULSE_OUT_CH2",
        "CH1_GATED", "CH2_GATED", "CH1_DRIVE_RAW", "CH1_DRIVE", "CH1_OUT", "CH1_TERM",
        "CH2_DRIVE_RAW", "CH2_DRIVE", "CH2_OUT", "CH2_TERM",
        "EXT_SYNC_DRIVE_RAW", "EXT_SYNC_DRIVE", "EXT_SYNC_OUT", "EXT_SYNC_TERM",
        "TRIG_N"] + ["Trigger%d" % i for i in range(1, 7)] + ["SYNC_N"] + ["Sync%d" % i for i in range(1, 7)]

# Signal source pad per net (tree root). Fallback: first pad.
ROOT = {"PWM_Trig": "J14.15", "PWM_TRIG_TAP": "J10.2", "CH1_J10": "R19.2",
        "_PULSE_OUT_CH1": "J14.17", "_PULSE_OUT_CH2": "J14.16",
        "CH1_GATED": "U7.4", "CH2_GATED": "U8.4", "CH1_DRIVE_RAW": "U13.7", "CH2_DRIVE_RAW": "U13.5",
        "CH1_DRIVE": "R6.2", "CH2_DRIVE": "R7.2", "CH1_OUT": "J18.2", "CH2_OUT": "J19.2",
        "CH1_TERM": "J18.3", "CH2_TERM": "J19.3", "EXT_SYNC_DRIVE_RAW": "U19.7",
        "EXT_SYNC_DRIVE": "R30.2", "EXT_SYNC_OUT": "J21.2", "EXT_SYNC_TERM": "J21.3",
        "TRIG_N": "U5.4", "SYNC_N": "U1.4"}
for i in range(1, 7):
    ROOT["Trigger%d" % i] = "U6.%d" % [2, 4, 6, 8, 10, 12][i - 1]
    ROOT["Sync%d" % i] = "U2.%d" % [2, 4, 6, 8, 10, 12][i - 1]

# Pin names from datasheets (pin numbers as in the footprints).
PIN = {
    # UCC27524DR: TI SLUSBP4, "Pin Functions" table (D/DGN 8-pin)
    "UCC27524": {"1": "ENA", "2": "INA", "3": "GND", "4": "INB", "5": "OUTB", "6": "VDD", "7": "OUTA", "8": "ENB"},
    # Fitted parts (BOM LCSC C113521/C7827/C485074/C465729) are all TI.
    # SN74AHCT1G08DBVR: TI SCLS316, Pin Functions (DBV)
    "74AHCT1G08": {"1": "A", "2": "B", "3": "GND", "4": "Y", "5": "VCC"},
    # SN74LVC1G04DBVR: TI SCES214, Pin Functions (DBV)
    "74LVC1G04": {"1": "n.c.", "2": "A", "3": "GND", "4": "Y", "5": "VCC"},
    # SN74LVC04ADR (TI SCAS281, Pin Functions, D/PW 14-pin)
    "SN74LVC04AD": {"1": "1A", "2": "1Y", "3": "2A", "4": "2Y", "5": "3A", "6": "3Y", "7": "GND",
                    "8": "4Y", "9": "4A", "10": "5Y", "11": "5A", "12": "6Y", "13": "6A", "14": "VCC"},
}
# Raspberry Pi Pico 2 W pinout (Pico 2 W datasheet, pinout figure): physical pin -> GPIO.
PICO = {"14": "GP10", "15": "GP11", "16": "GP12", "17": "GP13"}

nm2mm = lambda v: v / 1e6

# ------------------------------------------------------------------ part 1: stackup / Z0
def hj_microstrip(w, h, t, er):
    """Hammerstad & Jensen 1980 microstrip (with H-J thickness correction). Returns Z0, eeff."""
    u = w / h; tn = t / h
    def z01(x):
        f = 6 + (2 * math.pi - 6) * math.exp(-(30.666 / x) ** 0.7528)
        return ETA0 / (2 * math.pi) * math.log(f / x + math.sqrt(1 + (2 / x) ** 2))
    def ee(x):
        a = 1 + math.log((x ** 4 + (x / 52) ** 2) / (x ** 4 + 0.432)) / 49 + math.log(1 + (x / 18.1) ** 3) / 18.7
        b = 0.564 * ((er - 0.9) / (er + 3)) ** 0.053
        return (er + 1) / 2 + (er - 1) / 2 * (1 + 10 / x) ** (-a * b)
    if tn > 0:
        du1 = tn / math.pi * math.log(1 + 4 * math.e / (tn / math.tanh(math.sqrt(6.517 * u)) ** 2))
        dur = 0.5 * (1 + 1 / math.cosh(math.sqrt(er - 1))) * du1
    else:
        du1 = dur = 0.0
    u1, ur = u + du1, u + dur
    z0 = z01(ur) / math.sqrt(ee(ur))
    eeff = ee(ur) * (z01(u1) / z01(ur)) ** 2
    return z0, eeff

_FDC = {}
_FDF = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fd_cache.json')
try:
    _FDC = json.load(open(_FDF))
except Exception:
    pass

def fd_line(*a, **k):
    key = repr((a, sorted(k.items())))
    if key not in _FDC:
        _FDC[key] = list(_fd_line(*a, **k)); json.dump(_FDC, open(_FDF, 'w'))
    return tuple(_FDC[key])

def _fd_line(w, h, t, er, mask_t=0.0, mask_er=1.0, gap=None, ncell_h=42, air=2.5, half=3.0):
    """2-D quasi-static finite-volume Laplace solve on the half cross-section (x>=0; x=0 is the
    symmetry plane). Units mm. GND plane at y=0, dielectric 0..h, trace (half-width w/2, thickness t)
    on top, conformal mask of mask_t, optional same-layer GND pour from x=w/2+gap (GCPW).
    Grid step dx=h/ncell_h so the dielectric height is exact. Top boundary phi=0, sides Neumann.
    C/eps0 = sum over edges k*dphi^2 (field energy, V=1). Returns Z0 [ohm], eeff."""
    dx = h / ncell_h
    nx = int(round(half / dx)) + 1
    jt0 = ncell_h; jt1 = ncell_h + max(1, int(round(t / dx)))        # trace node rows
    ny = jt1 + int(round(air / dx)) + 1
    iw = int(round(w / 2 / dx))                                       # last trace node column
    ig = None if gap is None else int(round((w / 2 + gap) / dx))     # first pour node column
    nm = int(round(mask_t / dx)) if mask_t > 0 else 0
    cond = np.zeros((nx, ny), bool); cond[:iw + 1, jt0:jt1 + 1] = True
    gnd = np.zeros((nx, ny), bool)
    if ig is not None: gnd[ig:, jt0:jt1 + 1] = True
    fixed = cond | gnd; fixed[:, 0] = True; fixed[:, -1] = True
    free = ~fixed
    def eps_cells(diel):
        e = np.ones((nx - 1, ny - 1))
        if diel:
            e[:, :ncell_h] = er
            if nm:
                m = np.zeros_like(e, bool)
                xe = ig if ig is not None else nx - 1
                m[iw:xe, ncell_h:ncell_h + nm] = True             # on laminate between conductors
                m[:iw + nm, jt1:jt1 + nm] = True                  # over trace
                m[iw:iw + nm, ncell_h:jt1 + nm] = True            # trace side wall
                if ig is not None:
                    m[ig - nm:, jt1:jt1 + nm] = True              # over pour
                    m[ig - nm:ig, ncell_h:jt1 + nm] = True        # pour side wall
                e[m] = mask_er
        return e
    def solve(e):
        ep = np.pad(e, ((0, 0), (1, 1)), mode="edge")             # rows outside -> copy (boundary rows fixed)
        kx = 0.5 * (ep[:, :-1] + ep[:, 1:])                         # (nx-1, ny) x-edges
        ky = np.zeros((nx, ny - 1))
        ky[1:-1] = 0.5 * (e[:-1] + e[1:])
        ky[0] = 0.5 * e[0]; ky[-1] = 0.5 * e[-1]                    # half control volume at x=0 and far side
        def A(p):
            q = np.zeros_like(p)
            d = kx * (p[:-1] - p[1:]); q[:-1] += d; q[1:] -= d
            d = ky * (p[:, :-1] - p[:, 1:]); q[:, :-1] += d; q[:, 1:] -= d
            return q
        dg = np.zeros((nx, ny)); dg[:-1] += kx; dg[1:] += kx; dg[:, :-1] += ky; dg[:, 1:] += ky
        phi = np.where(cond, 1.0, 0.0)
        r = -A(phi); r[fixed] = 0
        dinv = np.where(free, 1 / np.maximum(dg, 1e-30), 0)
        z = dinv * r; p = z.copy(); rz = (r * z).sum(); r0 = math.sqrt((r * r).sum())
        for it in range(40000):
            Ap = A(p); Ap[fixed] = 0
            a = rz / (p * Ap).sum(); phi += a * p; r -= a * Ap
            if math.sqrt((r * r).sum()) < 1e-9 * r0: break
            z = dinv * r; rzn = (r * z).sum(); p = z + (rzn / rz) * p; rz = rzn
        gx = phi[:-1] - phi[1:]; gy = phi[:, :-1] - phi[:, 1:]
        return 2 * ((kx * gx * gx).sum() + (ky * gy * gy).sum()), it
    cd, i1 = solve(eps_cells(True)); ca, i2 = solve(eps_cells(False))
    eeff = cd / ca
    z0 = 1 / (C0 * 8.8541878128e-12 * math.sqrt(cd * ca))
    return z0, float(eeff)

# ------------------------------------------------------------------ part 2: graph
def seg_point_dist(p, a, b):
    ax, ay = a; bx, by = b; px, py = p
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 == 0: return math.hypot(px - ax, py - ay), 0.0
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy)), t

class UF:
    def __init__(s): s.p = {}
    def f(s, a):
        s.p.setdefault(a, a)
        while s.p[a] != a:
            s.p[a] = s.p[s.p[a]]; a = s.p[a]
        return a
    def u(s, a, b):
        ra, rb = s.f(a), s.f(b)
        if ra != rb:
            # keep pad/via names as roots
            if isinstance(rb, str): ra, rb = rb, ra
            s.p[rb] = ra

def main():
    b = pcbnew.LoadBoard(BOARD)
    LN = lambda l: b.GetLayerName(l)
    # ---------------- stackup
    # stackup block parsed from the file text (BOARD_STACKUP is not wrapped in KiCad 10 python)
    import re
    txt = open(BOARD, encoding="utf-8").read()
    blk = txt[txt.index("(stackup"):txt.index("(copper_finish")]
    stack = []
    for m in re.finditer(r'\(layer "([^"]+)"(.*?)\n\t\t\t\)', blk, re.S):
        body = m.group(2); d = {"name": m.group(1)}
        for key, rx, cast in (("type", r'\(type "([^"]+)"\)', str), ("thickness_mm", r'\(thickness ([0-9.]+)\)', float),
                              ("material", r'\(material "([^"]+)"\)', str), ("epsilon_r", r'\(epsilon_r ([0-9.]+)\)', float),
                              ("loss_tangent", r'\(loss_tangent ([0-9.]+)\)', float)):
            mm = re.search(rx, body)
            if mm: d[key] = cast(mm.group(1))
        stack.append(d)
    th = {d["name"]: d.get("thickness_mm") for d in stack}
    er = [d for d in stack if d["name"] == "dielectric 1"][0]["epsilon_r"]
    h = th["dielectric 1"]; tcu = th["F.Cu"]; tmask = th["F.Mask"] or 0.01
    zc = [z for z in b.Zones() if z.GetNetname() == "GND" and z.GetLayer() == pcbnew.F_Cu][0]
    pour_gap = max(nm2mm(zc.GetLocalClearance() or 0), 0.2)

    # ---------------- nets
    pads_by_net = {}
    for p in b.GetPads():
        pads_by_net.setdefault(p.GetNetname(), []).append(p)
    tracks_by_net = {}
    for t in b.GetTracks():
        tracks_by_net.setdefault(t.GetNetname(), []).append(t)
    gnd_fill = {}
    for z in b.Zones():
        if z.GetNetname() == "GND" and z.IsFilled():
            for l in (pcbnew.F_Cu, pcbnew.B_Cu):
                if z.IsOnLayer(l):
                    gnd_fill.setdefault(LN(l), []).append(z.GetFilledPolysList(l))

    def pad_name(p): return "%s.%s" % (p.GetParentFootprint().GetReference(), p.GetNumber())
    def pad_info(p):
        fp = p.GetParentFootprint(); ref = fp.GetReference(); val = fp.GetValue(); n = p.GetNumber()
        fn = PIN.get(val, {}).get(n, "")
        if ref in ("J14", "U11") and n in PICO: fn = "Pico pin %s = %s" % (n, PICO[n])
        if not fn: fn = p.GetPinFunction() or ""
        x, y = pcbnew.ToMM(p.GetPosition())
        return {"pad": pad_name(p), "ref": ref, "value": val, "footprint": str(fp.GetFPID().GetLibItemName()),
                "pin": n, "function": fn, "smd": p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD,
                "x_mm": round(x, 4), "y_mm": round(y, 4)}

    widths_used = set()
    nets_out = {}
    import time; T0 = time.time()
    for net in NETS:
        print('graph', net, '%.1fs' % (time.time() - T0), flush=True)
        pads = pads_by_net.get(net, []); trks = tracks_by_net.get(net, [])
        if not pads:
            nets_out[net] = {"error": "net not on board"}; continue
        segs, vias = [], []
        for t in trks:
            if t.GetClass() == "PCB_VIA":
                vias.append(t)
            else:
                s = t.GetStart(); e = t.GetEnd()
                L = nm2mm(t.GetLength())
                segs.append({"layer": LN(t.GetLayer()), "lid": t.GetLayer(), "a": (s.x, s.y), "b": (e.x, e.y),
                             "w": t.GetWidth(), "len": L, "arc": t.GetClass() == "PCB_ARC", "cuts": []})
        uf = UF()
        # each segment endpoint is a point node ("s", idx, 0|1); interior cut points ("c", idx, k)
        vnames = {}
        for k, v in enumerate(vias):
            vx, vy = pcbnew.ToMM(v.GetPosition())
            vnames[k] = "VIA%d@(%.2f,%.2f)" % (k, vx, vy)
        notes = []
        for i, s in enumerate(segs):
            for end, pt in ((0, s["a"]), (1, s["b"])):
                node = ("s", i, end); uf.f(node)
                v2 = pcbnew.VECTOR2I(int(pt[0]), int(pt[1]))
                for p in pads:
                    if p.IsOnLayer(s["lid"]) and p.HitTest(v2):
                        uf.u(pad_name(p), node)
                for k, v in enumerate(vias):
                    vp = v.GetPosition()
                    if math.hypot(vp.x - pt[0], vp.y - pt[1]) <= v.GetWidth(s["lid"]) / 2 + 1:
                        uf.u(vnames[k], node)
                for j, o in enumerate(segs):
                    if j == i or o["lid"] != s["lid"]: continue
                    if o["arc"]:
                        for e2, q in ((0, o["a"]), (1, o["b"])):
                            if math.hypot(q[0] - pt[0], q[1] - pt[1]) <= o["w"] / 2:
                                uf.u(node, ("s", j, e2))
                        continue
                    d, tt = seg_point_dist(pt, o["a"], o["b"])
                    if d > o["w"] / 2 + 1: continue
                    da = math.hypot(o["a"][0] - pt[0], o["a"][1] - pt[1])
                    db = math.hypot(o["b"][0] - pt[0], o["b"][1] - pt[1])
                    if da <= o["w"] / 2 + 1: uf.u(node, ("s", j, 0))
                    elif db <= o["w"] / 2 + 1: uf.u(node, ("s", j, 1))
                    else:
                        cid = ("c", j, len(o["cuts"])); o["cuts"].append((tt, cid)); uf.u(node, cid)
        # vias sitting inside pads
        for k, v in enumerate(vias):
            for p in pads:
                if p.HitTest(v.GetPosition()):
                    uf.u(pad_name(p), vnames[k])
        # raw edges
        raw = []
        for i, s in enumerate(segs):
            pts = [(0.0, ("s", i, 0))] + sorted(s["cuts"]) + [(1.0, ("s", i, 1))]
            widths_used.add((s["layer"], round(nm2mm(s["w"]), 4)))
            for (t0, n0), (t1, n1) in zip(pts[:-1], pts[1:]):
                raw.append({"a": uf.f(n0), "b": uf.f(n1), "len": s["len"] * (t1 - t0),
                            "layer": s["layer"], "w": round(nm2mm(s["w"]), 4)})
        # drop zero-length pieces; pieces whose both ends resolve to the same pad are pad-internal copper
        pad_internal = []
        padset0 = {pad_name(p) for p in pads}
        keep_raw, seen_k, n_dup = [], set(), 0
        for e in raw:
            if e["a"] == e["b"]:
                if isinstance(e["a"], str) and e["a"] in padset0 and e["len"] >= 1e-3:
                    pad_internal.append({"pad": e["a"], "len_mm": round(e["len"], 4), "layer": e["layer"], "width_mm": e["w"]})
                continue
            # colinear overlapping tracks give identical sub-edges after cutting: keep one copy
            k = (frozenset((repr(e["a"]), repr(e["b"]))), e["layer"], round(e["len"], 3))
            if k in seen_k: n_dup += 1; continue
            seen_k.add(k); keep_raw.append(e)
        raw = keep_raw
        for p in pads: uf.f(pad_name(p))
        for k in vnames: uf.f(vnames[k])
        padset = {pad_name(p) for p in pads}
        # adjacency on raw graph
        adj = {}
        for idx, e in enumerate(raw):
            adj.setdefault(e["a"], []).append(idx); adj.setdefault(e["b"], []).append(idx)
        for pn in padset: adj.setdefault(uf.f(pn), [])
        for k in vnames: adj.setdefault(uf.f(vnames[k]), [])
        # connected components
        comp = {}; cid = 0
        for n0 in adj:
            if n0 in comp: continue
            stack_ = [n0]; comp[n0] = cid
            while stack_:
                n = stack_.pop()
                for ei in adj[n]:
                    m = raw[ei]["b"] if raw[ei]["a"] == n else raw[ei]["a"]
                    if m not in comp: comp[m] = cid; stack_.append(m)
            cid += 1
        ncomp = cid
        cycles = len(raw) - len(adj) + ncomp
        # node naming
        def is_pad(n): return isinstance(n, str) and n in padset
        def is_via(n): return isinstance(n, str) and n.startswith("VIA")
        # merge pad names that unified with other pads (pads touching): keep a label
        names = {}
        bp = 0
        for n in adj:
            if isinstance(n, str): names[n] = n
            else:
                deg = len(adj[n])
                if deg >= 3:
                    names[n] = "BP%d" % bp; bp += 1
                elif deg == 1:
                    names[n] = "STUB%d" % bp; bp += 1
                else:
                    names[n] = None  # degree-2 interior point
        # pads whose UF root is another pad (overlapping pads): alias
        alias = {pn: uf.f(pn) for pn in padset if uf.f(pn) != pn}
        # reduce: walk from each named node along degree-2 unnamed/via nodes
        def keep(n):
            if names.get(n) is None: return False
            if is_via(n) and len(adj[n]) == 2: return False
            return True
        used = set(); edges = []
        for n in adj:
            if not keep(n): continue
            for ei in adj[n]:
                if ei in used: continue
                path = []; cur = n; e = ei; nv = 0
                while True:
                    used.add(e); path.append(raw[e])
                    nxt = raw[e]["b"] if raw[e]["a"] == cur else raw[e]["a"]
                    if keep(nxt): break
                    if is_via(nxt): nv += 1
                    cand = [x for x in adj[nxt] if x not in used]
                    if not cand: break
                    cur, e = nxt, cand[0]
                # merge consecutive uniform runs
                runs = []
                for r in path:
                    if runs and runs[-1]["layer"] == r["layer"] and runs[-1]["width_mm"] == r["w"]:
                        runs[-1]["len_mm"] += r["len"]
                    else:
                        runs.append({"layer": r["layer"], "width_mm": r["w"], "len_mm": r["len"]})
                for r in runs: r["len_mm"] = round(r["len_mm"], 4)
                L = sum(r["len"] for r in path)
                bylayer = {}
                for r in runs: bylayer[r["layer"]] = bylayer.get(r["layer"], 0) + r["len_mm"]
                dom = max(runs, key=lambda r: r["len_mm"])
                edges.append({"a": names[n], "b": names[nxt], "len_mm": round(L, 4),
                              "layer": dom["layer"] if len(bylayer) == 1 else "+".join(sorted(bylayer)),
                              "width_mm": dom["width_mm"], "vias": nv, "runs": runs})
        # vias that remain as nodes (degree != 2) are named nodes already
        # orient from root by BFS on reduced graph
        root = ROOT.get(net, sorted(padset)[0])
        root = alias.get(root, root)
        g = {}
        for e in edges:
            g.setdefault(e["a"], []).append(e); g.setdefault(e["b"], []).append(e)
        dist = {root: 0.0}; nvia = {root: 0}; order = [root]; seen_e = set()
        while order:
            n = order.pop(0)
            for e in g.get(n, []):
                if id(e) in seen_e: continue
                seen_e.add(id(e))
                m = e["b"] if e["a"] == n else e["a"]
                if e["a"] != n:  # flip so a = upstream
                    e["a"], e["b"] = n, m; e["runs"] = e["runs"][::-1]
                if m not in dist:
                    dist[m] = dist[n] + e["len_mm"]; nvia[m] = nvia[n] + e["vias"]; order.append(m)
        unreached = sorted(p for p in padset if alias.get(p, p) not in dist)
        # gnd pour proximity per edge (sampled): min edge-to-pour distance and fraction < 1 mm
        total = round(sum(e["len_mm"] for e in edges), 4)
        pad_list = [pad_info(p) for p in sorted(pads, key=pad_name)]
        for pi in pad_list:
            pi["path_len_from_root_mm"] = round(dist.get(alias.get(pi["pad"], pi["pad"]), float("nan")), 4)
            pi["path_vias_from_root"] = nvia.get(alias.get(pi["pad"], pi["pad"]))
            if pi["pad"] in alias: pi["shorted_to_pad"] = alias[pi["pad"]]
        nets_out[net] = {"root": root, "total_len_mm": total,
                         "via_count": len(vias), "segment_count": len(segs),
                         "components": ncomp, "independent_loops": cycles,
                         "unreached_pads": unreached,
                         "edges": edges, "pads": pad_list,
                         "pad_internal_copper": pad_internal, "duplicate_overlap_pieces_removed": n_dup,
                         "pad_internal_len_mm": round(sum(q["len_mm"] for q in pad_internal), 4),
                         "kicad_pad_count": len(pads)}
        # coordinates of branch points / stubs
        bpc = {}
        for n, nm in names.items():
            if nm and (nm.startswith("BP") or nm.startswith("STUB")):
                kind, i, end = n
                s = segs[i]
                if kind == "s":
                    pt = s["a"] if end == 0 else s["b"]
                else:
                    tt = [t for t, c in s["cuts"] if c == n][0]
                    pt = (s["a"][0] + tt * (s["b"][0] - s["a"][0]), s["a"][1] + tt * (s["b"][1] - s["a"][1]))
                bpc[nm] = [round(nm2mm(pt[0]), 3), round(nm2mm(pt[1]), 3)]
        nets_out[net]["branch_points"] = bpc

    # pour proximity for each raw track segment, summarised per net/layer
    for net in NETS:
        if "edges" not in nets_out[net]: continue
        print('pour', net, '%.1fs' % (time.time() - T0), flush=True)
        prox = {}
        for t in tracks_by_net.get(net, []):
            if t.GetClass() != "PCB_TRACK": continue
            ln = LN(t.GetLayer()); w = t.GetWidth()
            s, e = t.GetStart(), t.GetEnd(); L = t.GetLength()
            n = max(2, int(nm2mm(L) / 0.25) + 1)
            for k in range(n):
                f = (k + 0.5) / n
                q = pcbnew.VECTOR2I(int(s.x + f * (e.x - s.x)), int(s.y + f * (e.y - s.y)))
                dmin = 1e18
                for sp in gnd_fill.get(ln, []):
                    try: dmin = min(dmin, math.sqrt(sp.SquaredDistance(q, False)))
                    except Exception: pass
                gap = nm2mm(dmin - w / 2)
                d = prox.setdefault(ln, {"len": 0, "lt0p35": 0, "lt0p6": 0, "lt1": 0})
                d["len"] += nm2mm(L) / n
                if gap < 0.35: d["lt0p35"] += nm2mm(L) / n
                if gap < 0.6: d["lt0p6"] += nm2mm(L) / n
                if gap < 1.0: d["lt1"] += nm2mm(L) / n
        nets_out[net]["gnd_pour_edge_gap"] = {ln: {"len_mm": round(d["len"], 2),
            "frac_gap_lt_0p35mm": round(d["lt0p35"] / d["len"], 3) if d["len"] else 0,
            "frac_gap_lt_0p6mm": round(d["lt0p6"] / d["len"], 3) if d["len"] else 0,
            "frac_gap_lt_1mm": round(d["lt1"] / d["len"], 3) if d["len"] else 0} for ln, d in prox.items()}

    # ---------------- per-width Z0 / Td
    layers = {}
    for ln, w in sorted(widths_used):
        key = "%s_w%.3f" % (ln, w)
        z_hj, e_hj = hj_microstrip(w, h, tcu, er)
        z_fd0, e_fd0 = fd_line(w, h, tcu, er)
        z_fdm, e_fdm = fd_line(w, h, tcu, er, mask_t=tmask, mask_er=MASK_ER)
        z_cp, e_cp = fd_line(w, h, tcu, er, mask_t=tmask, mask_er=MASK_ER, gap=pour_gap)
        # closed form + FD mask correction (ratio) = recommended value
        z_rec = z_hj * z_fdm / z_fd0; e_rec = e_hj * e_fdm / e_fd0
        td = math.sqrt(e_rec) / C0 * 1e-3 * 1e12
        layers[key] = {"layer": ln, "width_mm": w, "ref_plane": "In1.Cu GND" if ln == "F.Cu" else "In2.Cu +5V (AC ref)",
                       "h_mm": h, "t_mm": tcu, "er": er,
                       "z0_ohm": round(z_rec, 2), "eeff": round(e_rec, 3), "td_ps_per_mm": round(td, 3),
                       "L_nH_per_mm": round(z_rec * td * 1e-3, 4), "C_pF_per_mm": round(td / z_rec, 4),
                       "hj_bare": {"z0_ohm": round(z_hj, 2), "eeff": round(e_hj, 3)},
                       "fd_bare": {"z0_ohm": round(z_fd0, 2), "eeff": round(e_fd0, 3)},
                       "fd_masked": {"z0_ohm": round(z_fdm, 2), "eeff": round(e_fdm, 3)},
                       "fd_masked_gcpw_gap%.2f" % pour_gap: {"z0_ohm": round(z_cp, 2), "eeff": round(e_cp, 3),
                            "td_ps_per_mm": round(math.sqrt(e_cp) / C0 * 1e9, 3)}}
        z_ipc = 87 / math.sqrt(er + 1.41) * math.log(5.98 * h / (0.8 * w + tcu))
        td_ipc = 85 * math.sqrt(0.475 * er + 0.67) / 25.4
        layers[key]["ipc2141a_bare"] = {"z0_ohm": round(z_ipc, 2), "td_ps_per_mm": round(td_ipc, 3)}
        layers[key]["formula_check_note"] = "ipc2141a_bare: IPC-2141A eq. Z0=87/sqrt(er+1.41)*ln(5.98h/(0.8w+t)), Td=85*sqrt(0.475er+0.67) ps/in; no mask"
        print(key, layers[key]["z0_ohm"], layers[key]["td_ps_per_mm"], z_hj, z_fd0, z_fdm, z_cp, flush=True)
    # via model (estimates, Howard Johnson closed forms)
    v0 = [t for t in b.GetTracks() if t.GetClass() == "PCB_VIA"][0]
    vd = nm2mm(v0.GetWidth(pcbnew.F_Cu)); vdr = nm2mm(v0.GetDrillValue())
    tb = sum(d.get("thickness_mm", 0) or 0 for d in stack if d.get("type") in ("copper", "prepreg", "core"))
    hin = tb / 25.4; din = vdr / 25.4
    Lv = 5.08 * hin * (math.log(4 * hin / din) + 1)
    antipad = vd + 2 * 0.3  # ESTIMATE: plane clearance 0.3 mm around via pad
    Cv = 1.41 * er * hin * (vd / 25.4) / ((antipad - vd) / 25.4)
    via_model = {"pad_mm": vd, "drill_mm": vdr, "barrel_len_mm": round(tb, 4),
                 "L_nH_est": round(Lv, 3), "C_pF_est": round(Cv, 3),
                 "note": "ESTIMATE: H. Johnson, High-Speed Digital Design (1993) sec 7.3 via L=5.08h[ln(4h/d)+1] nH, C=1.41 er T D1/(D2-D1) pF (inch units); D2 assumes 0.3 mm plane clearance"}

    cn = b.GetConnectivity(); cn.RecalculateRatsnest()
    out = {"board": "PiDG_Pico.kicad_pcb", "units": "mm, ohm, ps",
           "kicad_connectivity_unconnected_total": cn.GetUnconnectedCount(False),
           "stackup": {"layers": stack, "source": "board (stackup) block; Hardware.md: JLC04161H-7628",
                       "mask_er_estimate": MASK_ER, "gnd_pour_clearance_mm": pour_gap,
                       "method": "Z0: Hammerstad-Jensen 1980 microstrip incl. H-J strip-thickness correction (bare, quasi-static), "
                                 "multiplied by the solder-mask correction ratio from a 2-D quasi-static finite-difference field solve "
                                 "(5 um grid, conformal 10 um mask, er_mask estimate). Coplanar GND-pour (GCPW) variant from the same FD solver."},
           "via_model": via_model, "layers": layers, "nets": nets_out}
    with open(OUT, "w") as f:
        json.dump(out, f, indent=1)
    for net in NETS:
        d = nets_out[net]
        if "edges" not in d: print(net, d); continue
        print("%-20s len %7.2f mm  vias %d  comps %d loops %d unreached %s padint %s dup %d" % (net, d["total_len_mm"], d["via_count"], d["components"], d["independent_loops"], d["unreached_pads"], [(q["pad"], q["len_mm"]) for q in d["pad_internal_copper"]], d["duplicate_overlap_pieces_removed"]))
        for pi in d["pads"]:
            print("      pad %-7s %-12s %-28s from root %7.2f mm vias %s" % (pi["pad"], pi["value"], pi["function"], pi["path_len_from_root_mm"], pi["path_vias_from_root"]))
        for e in d["edges"]:
            print("    %-24s -> %-24s %7.2f mm %-10s w%.3f vias %d" % (e["a"], e["b"], e["len_mm"], e["layer"], e["width_mm"], e["vias"]))

if __name__ == "__main__":
    main()
