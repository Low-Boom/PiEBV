# Remove router stubs that KiCad DRC reports as track_dangling (e.g. the 0.5 mm +5V_PD stub that the router
# leaves near U15), one at a time, and only if the board stays as connected as before.
# usage: python.exe dangling.py <drc.json> <board.kicad_pcb>   (board is rewritten in place)
import sys, json, pcbnew
rep, brd = sys.argv[1], sys.argv[2]
ids = {it["uuid"] for v in json.load(open(rep))["violations"] if v["type"] == "track_dangling" for it in v["items"]}
b = pcbnew.LoadBoard(brd); b.BuildConnectivity(); base = b.GetConnectivity().GetUnconnectedCount(True)
for t in list(b.GetTracks()):
    if t.m_Uuid.AsString() not in ids or t.GetClass() != "PCB_TRACK": continue
    desc = (t.GetNetname(), round(pcbnew.ToMM(t.GetStart().x), 3), round(pcbnew.ToMM(t.GetStart().y), 3), round(pcbnew.ToMM(t.GetLength()), 2))
    b.Remove(t); b.BuildConnectivity()             # (net name read before Remove: the wrapper loses it after)
    if b.GetConnectivity().GetUnconnectedCount(True) > base: b.Add(t); b.BuildConnectivity(); print("dangling stub kept (needed):", *desc)
    else: print("dangling stub removed:", *desc, "mm")
pcbnew.SaveBoard(brd, b)
