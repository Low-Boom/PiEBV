# Rev 2 board tools

These tools make the Rev 2 board from the Rev 1 EuroCard board. Rev 2 adds:

- the selectable camera I/O supply `+VCAM` (U20, J22, D1): 1.8 V for IDS cameras, 3.3 V for
  Prophesee EVK4 cameras;
- status LEDs: 12 V good (D2), ARMED (D3), output activity (D4–D6, U21–U23);
- rail test pads TP4–TP9;
- power islands on In2.Cu (`+5V`, `+3V3`, `+1V8`, `+VCAM`, `+12V`) in a GND fill.

The Rev 1 board was made by an autorouter (`tools/eurocard/build.sh`). The Rev 2 tools do not
run the autorouter again. They change only the copper that Rev 2 needs, so the camera lines, the
laser pulse lanes and the output block keep their Rev 1 copper.

## Files

| File | What it does |
|---|---|
| `sch_edit.py` | One-time edit: Rev 1 schematic to Rev 2 schematic (text level). It is kept as the record of the schematic change. Do not run it on the Rev 2 schematic. |
| `build.sh` | The board build: netlist, `pcb_edit.py`, `jogs.py`, `tidy.py`, then the checks. Writes `PiEBV_Pico.kicad_pcb` in the repository root. |
| `pcb_edit.py` | Rev 1 board + Rev 2 netlist to Rev 2 board: new nets, moved parts (U9, C6, C7), new parts and their copper (coordinates in the script), In2 islands, silkscreen, title block. |
| `jogs.py` | Merges router staircases. The track length does not change (see the script header). |
| `jog_choices.json` | For each staircase: `"B"` = merge at the other end, `"skip"` = leave it. No entry = merge at the first end. |
| `tidy.py` | Replaces five squiggle runs with clean runs (list in the script). |
| `plane_check.py` | Lists the In2 island under each B.Cu track, the points where a track changes island, and the plane taps of each rail. |
| `stats.py` | Board numbers for the documentation (segments, lengths, vias, parts, fingerprint). |
| `fab.sh` | DRC gate, gerbers, drill files, job file and zip in `fab/`. |
| `cpl.py` | JLC placement file for Rev 2 from the Rev 1 placement file. |
| `images.sh`, `svg2png.js` | Layer images and 3-D renders for `docs/img/`. |

## Run

Use KiCad 10 (10.0.6 was used) and its Python. `build.sh` also needs `git`, `node` and the
Python package `shapely` (for the island outlines).

```bash
bash tools/rev2/build.sh
```

```bash
bash tools/rev2/fab.sh
```

```bash
python3 tools/rev2/cpl.py tools/rev2/work/rev1.kicad_pcb REV1_CPL.csv PiEBV_Pico.kicad_pcb fab/jlc/PiEBV_Pico_JLC_CPL.csv
```

`REV1_CPL.csv` is the Rev 1 placement file: `git show 4381eab:fab/jlc/PiEBV_Pico_JLC_CPL.csv`.

On Windows, set `KICAD_CLI`, `KICAD_PY` and `KICAD_FOOTPRINT_DIR` to the KiCad 10 programs and
footprint folder, as in `tools/eurocard/build.sh`.

## Checks in `build.sh`

The build stops if a check fails.

| Check | Limit |
|---|---|
| KiCad DRC with the project rules, zones refilled | 0 errors, 0 unconnected items (warnings are printed) |
| Camera line lengths, KiCad's own length reading, Rev 1 against Rev 2 | `Sync1`–`Sync6` unchanged; no group (Sync, Trigger, TDRSTN) with a larger spread |
| `meander_check.js` | Parts of one camera line at least 0.3 mm apart |
| `plane_check.py` | Each via and through-hole pad of a plane net is over the island of its net, or is listed as fed by tracks |

Result on the committed board: DRC 0 errors and 0 unconnected items (1 warning, the U14 footprint
difference that Rev 1 has also); Sync 81.87–83.04 mm (spread 1.18 mm, unchanged); Trigger
41.12–43.32 mm (spread 2.20 mm, was 2.47 mm); TDRSTN 51.69–53.05 mm (spread 1.37 mm, unchanged).

## Notes

- **Python save and the project file.** `pcbnew.Board.Save()` writes a `.kicad_pro` file with
  default design rules next to the board. The scripts use `pcbnew.SaveBoard(path, board, True)`,
  which does not write the project file. A DRC run after a plain `Save()` uses the default rules,
  not the project rules.
- **`BOARD.Tracks()` after `BOARD.Remove()`.** On the KiCad 10.0.6 Linux build, `Tracks()` stops
  returning a list after a few `Remove()` calls. The scripts read the track list once and keep the
  removed items referenced.
- **In2 island outlines** are in `pcb_edit.py` (section 4). The gap between two islands is 0.5 mm.
  The GND fill has a lower priority and KiCad cuts it back from the islands.
- **JLC rotations.** `cpl.py` does not have the JLC footprints of the new polarised parts
  (D1–D6, Q1, Q2, U20–U23). Their rows have the KiCad rotation. Run `tools/jlc_cpl` before an
  order.
