#!/usr/bin/env python3
"""Deterministic item IDs for a board file.

pcbnew gives every new item a random UUID, and KiCad writes the items of a board sorted by
UUID. Two runs of the same script thus write the same copper in another order, and the
autorouter (which reads the items in file order) then gives another result. This tool replaces
every UUID by one derived from the content of its top-level block (footprint, segment, via,
zone, text ...): MD5 of the block text without its UUIDs, plus a counter for equal blocks and
the position of the UUID in the block. The blocks of each kind (footprint, segment, via ...) are
then written in sorted order in the places that kind had in the file, because pcbnew does not
write the tracks in a fixed order.

usage: uuidfix.py IN.kicad_pcb OUT.kicad_pcb
"""
import collections
import hashlib
import re
import sys

text = open(sys.argv[1], encoding="utf-8").read()
assert "\n\t(group" not in text, "groups refer to item UUIDs: not handled"
UU = re.compile(r'\(uuid "[0-9a-f-]{36}"\)')
seen = collections.Counter()
parts, kinds, pos = [], [], 0                           # text between blocks / blocks, with the kind of each block
for m in re.finditer(r"\n\t\((?:[^\n]*\n)*?\t\)(?=\n)|\n\t\([^\n]*\)(?=\n)", text):   # top-level blocks (one tab deep)
    block = m.group(0)
    if not UU.search(block):
        continue
    key = hashlib.md5(UU.sub("", block).encode()).hexdigest()
    seen[key] += 1
    k = [0]

    def new(_):
        h = hashlib.md5(("%s/%d/%d" % (key, seen[key], k[0])).encode()).hexdigest()
        k[0] += 1
        return '(uuid "%s-%s-%s-%s-%s")' % (h[:8], h[8:12], h[12:16], h[16:20], h[20:32])

    parts.append(text[pos:m.start()])
    parts.append(UU.sub(new, block))
    kinds.append(re.match(r"\n\t\((\w+)", block).group(1))
    pos = m.end()
tail = text[pos:]
blocks = parts[1::2]
for kind in set(kinds):                                 # sorted blocks go back into the slots of their kind
    idx = [i for i, kd in enumerate(kinds) if kd == kind]
    for i, blk in zip(idx, sorted(blocks[i] for i in idx)):
        parts[2 * i + 1] = blk
open(sys.argv[2], "w", encoding="utf-8").write("".join(parts) + tail)
print("uuidfix: %d blocks" % sum(seen.values()))
