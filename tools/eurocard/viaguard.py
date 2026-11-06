# Via obstacle guard (residual R1): every via in a board file must be a via that KiCadRoutingTools models
# (an obstacle for route.py / route_planes.py). Run with the KRT python (it imports KRT's own parser).
# Count A: top-level (via ...) blocks of the file, string-aware scan (a "(via" inside a quoted string is text).
# Count B: len(parse_kicad_pcb(board).vias), the list the router reads as obstacles.
# A != B -> exit 1 (a real via that the router would plan copper through, or a phantom via).
# KRT's block scan (_via_blocks) matches "(via" also inside quoted strings: on this board the three
# Description properties "... shunt ... (via J18 2-3) / (via J19 2-3) / (via J21 2-3) ..." give KRT's
# "3 via block(s) could not be read" warning. Those are text, not copper; they are listed here as such.
# usage: KRT_PY viaguard.py KRT_DIR board.kicad_pcb [board2 ...]
import os, sys

def top_level_vias(text):
    # -> (count of depth-1 "(via" blocks, [(line, snippet) of "(via" inside quoted strings])
    n, depth, i, in_str, s0, quoted = len(text), 0, 0, False, 0, []
    vias = 0
    while i < n:
        c = text[i]
        if in_str:
            if c == '\\': i += 2; continue
            if c == '"':
                in_str = False
                k = text.find('(via', s0, i)
                while k != -1:
                    if k + 4 < i and text[k + 4] in ' \t\n(':
                        quoted.append((text.count('\n', 0, k) + 1, text[max(s0, k - 30):k + 20].replace('\n', ' ')))
                    k = text.find('(via', k + 4, i)
        elif c == '"': in_str, s0 = True, i
        elif c == '(':
            depth += 1
            if depth == 2 and text.startswith('via', i + 1) and text[i + 4] in ' \t\n(': vias += 1
        elif c == ')': depth -= 1
        i += 1
    return vias, quoted

krt, boards = sys.argv[1], sys.argv[2:]
sys.path.insert(0, os.path.join(krt, 'py_router'))
from kicad_parser import parse_kicad_pcb, read_board_text
bad = 0
for b in boards:
    a, quoted = top_level_vias(read_board_text(b))
    m = len(parse_kicad_pcb(b).vias)
    ok = a == m; bad += not ok
    print('viaguard: %s: %d vias in file, %d modelled by KRT%s' % (os.path.basename(b), a, m, '' if ok else '  MISMATCH'))
    for ln, s in quoted:
        print('  "(via" in a quoted string (text, not copper), line %d: ...%s...' % (ln, s))
if bad:
    print('viaguard: FAIL: KRT does not model every via as an obstacle (fix the via block syntax)'); sys.exit(1)
