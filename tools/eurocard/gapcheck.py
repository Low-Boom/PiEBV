#!/usr/bin/env python
# Independent edge-to-edge gap measurement for specific net pairs on the residuals board.
# Expected (documented + agent report): CH2-lane run vs CLK_SEL ~0.538 mm (parallel run x171.5-172.4, y64.3-65.2);
# R18 branch vs PWM_1MHz/SYNC_N ~21.70 mm. No bounding-box cutoff: a fixed cutoff discards every pair when the
# true minimum is larger than the cutoff (the 21.70 mm lane pair is >1 mm apart everywhere) and reports
# "no same-layer pairs" instead of measuring.
import re, math, sys

def parse(path):
    text = open(path, encoding='utf-8').read()
    pat = re.compile(r'\(segment\s+\(start\s+(-?[\d.]+)\s+(-?[\d.]+)\)\s+\(end\s+(-?[\d.]+)\s+(-?[\d.]+)\)\s+\(width\s+([\d.]+)\)\s+\(layer\s+"([^"]+)"\)\s+\(net\s+"([^"]+)"\)')
    segs = []
    for m in pat.finditer(text):
        x1, y1, x2, y2, w = (float(m.group(i)) for i in range(1, 6))
        segs.append((x1, y1, x2, y2, w, m.group(6), m.group(7)))  # ..., layer, net
    return segs

def seg_dist(s1, s2):
    """Minimum centerline distance between two segments."""
    def proj(px, py, x1, y1, x2, y2):
        dx, dy = x2 - x1, y2 - y1
        if dx == 0 and dy == 0:
            return x1, y1
        t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
        t = max(0.0, min(1.0, t))
        return x1 + t * dx, y1 + t * dy
    (ax, ay, bx, by) = s1[0], s1[1], s1[2], s1[3]
    (cx, cy, dx, dy) = s2[0], s2[1], s2[2], s2[3]
    dmin = 1e9
    for (px, py) in ((ax, ay), (bx, by)):
        qx, qy = proj(px, py, cx, cy, dx, dy)
        dmin = min(dmin, math.hypot(px - qx, py - qy))
    for (px, py) in ((cx, cy), (dx, dy)):
        qx, qy = proj(px, py, ax, ay, bx, by)
        dmin = min(dmin, math.hypot(px - qx, py - qy))
    # segment-segment (non-parallel)
    abx, aby = bx - ax, by - ay
    cdx, cdy = dx - cx, dy - cy
    denom = abx * cdy - aby * cdx
    if abs(denom) > 1e-12:
        t = ((cx - ax) * cdy - (cy - ay) * cdx) / denom
        u = ((cx - ax) * aby - (cy - ay) * abx) / denom
        if -1e-9 <= t <= 1 + 1e-9 and -1e-9 <= u <= 1 + 1e-9:
            px, py = ax + t * abx, ay + t * aby
            dmin = min(dmin, math.hypot(px - (cx + u * cdx), py - (cy + u * cdy)))
    return dmin

def min_gap(segsA, segsB):
    """Return (overall_best, same_layer_best) with pair details."""
    best, bestpair = 1e9, None
    sl, slpair = 1e9, None
    for sa in segsA:
        for sb in segsB:
            d = seg_dist(sa, sb) - (sa[4] + sb[4]) / 2.0  # edge-to-edge
            if d < best:
                best, bestpair = d, (sa, sb)
            if sa[5] == sb[5] and d < sl:
                sl, slpair = d, (sa, sb)
    return (best, bestpair, sl, slpair)

def fmt(s):
    return f"{s[6]} [{s[5]}] ({s[0]:.3f},{s[1]:.3f})->({s[2]:.3f},{s[3]:.3f}) w={s[4]}"

def main(board, pairs):
    segs = parse(board)
    bynet = {}
    for s in segs:
        bynet.setdefault(s[6], []).append(s)
    for label, netsA, netsB, expect in pairs:
        A = [s for n in netsA for s in bynet.get(n, [])]
        B = [s for n in netsB for s in bynet.get(n, [])]
        if not A or not B:
            print(f"{label}: MISSING net data A={len(A)} B={len(B)}")
            continue
        best, bestpair, sl, slpair = min_gap(A, B)
        print(f"{label}: overall {best:.3f} mm ({fmt(bestpair[0])} | {fmt(bestpair[1])})")
        if slpair:
            print(f"   same-layer {sl:.3f} mm (expect ~{expect}) ({fmt(slpair[0])} | {fmt(slpair[1])})")
        else:
            print(f"   same-layer: no same-layer pairs")

if __name__ == '__main__':
    board = sys.argv[1]
    pairs = [
        ('CH-lanes vs CLK_SEL', ['_PULSE_OUT_CH1', '_PULSE_OUT_CH2'], ['CLK_SEL'], 0.538),
        ('CH-lanes vs PWM_1MHz+SYNC_N', ['_PULSE_OUT_CH1', '_PULSE_OUT_CH2'], ['PWM_1MHz', 'SYNC_N'], 21.700),
        ('CH-lanes vs ALL-other (sanity, excl CH1_J10/GND/lane-group)', None, None, None),
    ]
    main(board, pairs[:2])
