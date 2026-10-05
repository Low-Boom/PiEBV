# Step 1 of the JLC CPL fix (run with KiCad's python.exe). Export each placed footprint: board position/orientation and its pads at orientation 0 relative to the origin (mm, y down).
import pcbnew, json, sys, os
HERE = os.path.dirname(os.path.abspath(__file__))
b = pcbnew.LoadBoard(os.path.join(HERE, "..", "..", "Pico Version 4Layer", "PiDG_Pico.kicad_pcb"))
out = {}
for fp in b.GetFootprints():
    c = pcbnew.FOOTPRINT(fp)
    c.SetOrientationDegrees(0); c.SetPosition(pcbnew.VECTOR2I(0, 0))
    pads = [{"n": p.GetNumber(), "x": pcbnew.ToMM(p.GetPosition().x), "y": pcbnew.ToMM(p.GetPosition().y),
             "w": pcbnew.ToMM(p.GetSize().x), "h": pcbnew.ToMM(p.GetSize().y), "tht": p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH}
            for p in c.Pads()]
    out[fp.GetReference()] = {"fp": str(fp.GetFPID().GetLibItemName()), "x": pcbnew.ToMM(fp.GetPosition().x),
                              "y": pcbnew.ToMM(fp.GetPosition().y), "rot": fp.GetOrientationDegrees() % 360,
                              "side": fp.GetLayerName(), "pads": pads}
json.dump(out, open(os.path.join(HERE, "kpads.json"), "w"), indent=0)
print(len(out), "footprints")
