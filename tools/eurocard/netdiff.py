#!/usr/bin/env python
# Per-net track census: segment count + total length, for whole-board diff between two files.
import re, sys
from collections import defaultdict

def parse(path):
    text = open(path, encoding='utf-8').read()
    pat = re.compile(r'\(segment\s+\(start\s+(-?[\d.]+)\s+(-?[\d.]+)\)\s+\(end\s+(-?[\d.]+)\s+(-?[\d.]+)\)\s+\(width\s+([\d.]+)\)\s+\(layer\s+"([^"]+)"\)\s+\(net\s+"([^"]+)"\)')
    per = defaultdict(lambda: [0, 0.0])
    for m in pat.finditer(text):
        x1, y1, x2, y2 = map(float, m.groups()[:4])
        net = m.group(7)
        per[net][0] += 1
        per[net][1] += ((x2-x1)**2 + (y2-y1)**2) ** 0.5
    return per

def main():
    a, b = parse(sys.argv[1]), parse(sys.argv[2])
    nets = sorted(set(a) | set(b))
    print(f"{'net':28s} {'pre_segs':>9s} {'pre_mm':>10s} {'post_segs':>10s} {'post_mm':>10s} {'d_segs':>7s} {'d_mm':>9s}")
    for n in nets:
        ps, pl = a.get(n, [0, 0.0])
        qs, ql = b.get(n, [0, 0.0])
        ds, dl = qs - ps, ql - pl
        if ds or abs(dl) > 1e-6:
            print(f"{n:28s} {ps:9d} {pl:10.3f} {qs:10d} {ql:10.3f} {ds:+7d} {dl:+9.3f}")
    print(f"{'TOTAL':28s} {sum(v[0] for v in a.values()):9d} {sum(v[1] for v in a.values()):10.3f} {sum(v[0] for v in b.values()):10d} {sum(v[1] for v in b.values()):10.3f}")

if __name__ == '__main__':
    main()
