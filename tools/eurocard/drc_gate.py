# DRC gate (review F21): the pipeline gate counts only non-warning severities as
# violations; warnings (e.g. the U14 lib_footprint_mismatch from the EP paste
# split) are printed so they stay visible in the build log.
# Exit 1 if any non-warning violation or unconnected item remains (stops build.sh).
# usage: python.exe drc_gate.py drc.json
import json, sys
d = json.load(open(sys.argv[1], encoding='utf-8'))
v = d.get('violations', [])
hard = [x for x in v if x.get('severity') != 'warning']
warn = [x for x in v if x.get('severity') == 'warning']
u = d.get('unconnected_items', [])
p = d.get('schematic_parity', [])
print('Found %d violations, %d unconnected items, %d schematic parity issues' % (len(hard), len(u), len(p)))
for w in warn:
    det = w.get('details') or ''
    print('  warning: %s%s' % (w.get('description', ''), (' ' + det) if det else ''))
for h in hard:
    print('  %s: %s' % (h.get('severity', ''), h.get('description', '')))
sys.exit(1 if hard or u else 0)
