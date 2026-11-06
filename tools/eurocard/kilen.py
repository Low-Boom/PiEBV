# Camera-line lengths as KiCad 10 reads them (its DRC length constraint, the same reading as the length tuner):
# the board is copied to a temp folder with a length rule that every camera net fails (min 900 mm); kicad-cli DRC
# reports each actual length. Writes "NET length_mm" lines (4 decimals) to OUT.
# usage: python.exe kilen.py board.kicad_pcb project.kicad_pro OUT [KICAD_CLI]
import sys, os, re, json, shutil, tempfile, subprocess
board, pro, out = sys.argv[1:4]
cli = sys.argv[4] if len(sys.argv) > 4 else "C:/Users/Flow-Lab/AppData/Local/Programs/KiCad/10.0/bin/kicad-cli.exe"
d = tempfile.mkdtemp()
try:
    shutil.copy(board, os.path.join(d, "x.kicad_pcb")); shutil.copy(pro, os.path.join(d, "x.kicad_pro"))
    with open(os.path.join(d, "x.kicad_dru"), "w") as f:
        f.write('(version 1)\n')
        for g in ("Sync", "Trigger", "TDRSTN"):
            f.write(f'(rule "len_{g}" (condition "A.NetName == \'{g}?\'") (constraint length (min 900mm)))\n')
    subprocess.run([cli, "pcb", "drc", "--format", "json", "-o", os.path.join(d, "d.json"), os.path.join(d, "x.kicad_pcb")],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    L = {}
    for v in json.load(open(os.path.join(d, "d.json"), encoding="utf-8"))["violations"]:
        if v["type"] != "length_out_of_range": continue
        m = re.search(r"actual ([\d.]+) mm", v["description"]); n = re.search(r"\[([^\]]+)\]", v["items"][0]["description"])
        if m and n: L[n.group(1)] = float(m.group(1))
finally:
    shutil.rmtree(d, ignore_errors=True)
if len(L) != 18: sys.exit(f"kilen: {len(L)} camera lengths read, expected 18")
with open(out, "w") as f:
    for n in sorted(L): f.write(f"{n} {L[n]:.4f}\n")
print(f"kilen: {len(L)} lengths -> {out}")
