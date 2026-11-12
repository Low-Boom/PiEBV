# Rev 2 board tools

These tools make the Rev 2 board from the Rev 1 EuroCard board. Rev 2 adds:

- the selectable camera I/O supply `+VCAM` (U20, J22, D1): 1.8 V for IDS cameras, 3.3 V for
  Prophesee EVK4 cameras;
- a 47 Ω series resistor in each camera line (R52–R69), at the camera headers;
- status LEDs: 12 V good (D2), ARMED (D3), output activity (D4–D6, U21–U23);
- rail test pads TP4–TP9;
- power islands on In2.Cu (`+5V`, `+3V3`, `+1V8`, `+VCAM`, `+12V`) in a GND fill.

The Rev 1 board was made by an autorouter (`tools/eurocard/build.sh`). The Rev 2 build removes
the Rev 1 camera copper and routes the camera lines again with the same autorouter
(KiCadRoutingTools, commit 8759686). All other copper is locked during that step, so the laser
pulse lanes and the output block keep their Rev 1 copper.

## Files

| File | What it does |
|---|---|
| `sch_edit.py` | One-shot generator of the Rev 2 schematic from the Rev 1 schematic (text level). It is kept as the record of the schematic change. It is not part of the build. Do not run it on the Rev 2 schematic. |
| `build.sh` | The board build: netlist, `pcb_edit.py`, `uuidfix.py`, camera routing (KiCadRoutingTools), `jogs.py`, `tidy.py`, `trim.py`, `spokes.py`, `uuidfix.py`, then the checks. Writes `PiEBV_Pico.kicad_pcb` in the repository root. |
| `pcb_edit.py` | Rev 1 board + Rev 2 netlist to Rev 2 board: new nets, moved parts (U9, C6, C7), new parts and their copper (coordinates in the script), In2 islands, silkscreen, title block. It removes the Rev 1 camera copper, places R52–R69 with their header stubs and draws `Trigger3`. |
| `uuidfix.py` | Gives a board file deterministic item IDs and a fixed item order. pcbnew writes random item IDs, and the router result depends on the item order. |
| `jogs.py` | Merges router staircases. The track length does not change (see the script header). It reads the choice for each staircase from `jog_choices.json`. |
| `jog_choices.json` | For each staircase: `"B"` = merge at the other end, `"skip"` = leave it. No entry = merge at the first end. |
| `jogfit.py` | Fits `jog_choices.json` to a new routing. Run it by hand after the camera routing changes. It runs `jogs.py` and DRC in a loop: a merge with a DRC violation goes to `"B"`, then to `"skip"`. |
| `tidy.py` | Hand clean-up of three router squiggles after `jogs.py`: the `Sync1` pad entry at U2, `+5V_PD`, and `+12V` at U19. |
| `trim.py` | Fine length trim of the camera lines by KiCad's own length reading. It moves meander caps; a line with no meander gets one square bump. |
| `spokes.py` | Adds a small pour cut-out at each pad that DRC reports with too few thermal spokes (header GND pins beside a camera track). The In1.Cu connection of the pad does not change. |
| `plane_check.py` | Lists the In2 island under each B.Cu track, the points where a track changes island, and the plane taps of each rail. |
| `stats.py` | Board numbers for the documentation (segments, lengths, vias per net, parts, fingerprint). |
| `cpl.py` | JLC placement file for Rev 2 from the Rev 1 placement file. |
| `fab.sh` | DRC gate, plane check, gerbers, drill files, job file and zip in `fab/`. It does not write the board file. |
| `images.sh` | Layer SVG files, the top silkscreen view, 3-D renders and the island map for `docs/img/`. |
| `svg2png.js` | Converts an SVG file to a PNG file with a headless browser. |
| `island_map.py` | Coloured map of the In2.Cu power islands with the B.Cu tracks (`docs/img/in2_islands.png`). |

## Requirements

- KiCad 10 (10.0.6 was used): `kicad-cli` and the Python that has `pcbnew`.
- The Python packages `shapely` (island outlines in `pcb_edit.py`) and `matplotlib`
  (`island_map.py`) in that Python.
- `git` and Node. `svg2png.js` also needs the Node package Playwright.
- For `build.sh`: KiCadRoutingTools at commit 8759686, built, with its Python. The setup is in
  `tools/eurocard/README.md`. Set `KRT_DIR` to the checkout and `KRT_PY` to its Python. The
  defaults are `tools/eurocard/KiCadRoutingTools` and `tools/eurocard/.venv/bin/python`.

## Run

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

```bash
bash tools/rev2/images.sh OUTDIR
```

Set `KICAD_CLI` and `KICAD_PY` if the KiCad 10 programs are not on the path. On Windows, set
`KICAD_CLI`, `KICAD_PY` and `KICAD_FOOTPRINT_DIR` to the KiCad 10 programs and footprint folder,
as in `tools/eurocard/build.sh`.

## Steps of `build.sh`

1. `pcb_edit.py` makes the Rev 2 parts, hand-drawn copper and In2 islands. It removes the Rev 1
   camera copper, places R52–R69 with their stubs and draws `Trigger3` (F.Cu, four teeth,
   45.8 mm as drawn). The resistor of `Trigger3` is about 12 mm from its buffer pin, and the
   router cannot make that line longer.
2. `uuidfix.py` gives the board file a fixed item order.
3. KiCadRoutingTools routes the other 17 camera lines from the buffer to the resistor. All other
   copper is locked. The lines are length-matched in each group. The net order in the script was
   found by a search of about 200 trials.
4. A check confirms that the router changed no other copper (91 other nets).
5. `jogs.py` merges 59 router staircases on 14 nets. The length of each line stays the same.
6. `tidy.py` makes 3 hand edits.
7. `trim.py` makes the lines of each group equal by KiCad's own length reading (two passes).
8. `spokes.py` adds 4 pour cut-outs at header GND pins where a camera track leaves only one
   thermal spoke on F.Cu or B.Cu. These pins keep their full connection to the In1 GND plane.
9. `uuidfix.py` runs again. Then the checks below run.

The build is repeatable: two runs gave the same router output.

## Checks in `build.sh`

The build stops if a check fails.

| Check | Limit |
|---|---|
| Camera routing | No failed net; the copper of all other nets not changed |
| KiCad DRC with the project rules, zones refilled | 0 errors, 0 unconnected items (warnings are printed) |
| Camera line lengths, KiCad's own length reading, buffer pad to resistor pad | Spread in each group (Sync, Trigger, TDRSTN) 0.1 mm or less |
| `tools/eurocard/meander_check.js` | Parts of one camera line at least 0.3 mm apart |
| `plane_check.py` | Each via and through-hole pad of a plane net is over the island of its net, or is listed as fed by tracks |

Result on the committed board:

- DRC: 0 errors, 0 unconnected items, 1 warning (the U14 footprint differs from its library
  copy; Rev 1 has this warning also).
- Schematic parity: 225 notes (199 net-name notes, 22 field notes, 4 mounting holes that are not
  in the schematic). `Hardware.md`, section Files, explains them.
- `Sync1`–`Sync6` 78.142–78.168 mm (spread 0.025 mm); `Trigger1`–`Trigger6` 45.144 mm (spread
  0.000 mm); `TDRSTN1`–`TDRSTN6` 53.924 mm (spread 0.000 mm). The Rev 1 spreads were 1.18 / 2.47 /
  1.37 mm.
- The stubs from the resistors to the header pins are the same for all six headers: Sync
  4.43 mm, TDRSTN 5.09 mm, Trigger 9.77 mm.
- 1496 track segments, 2998.5 mm of track (F.Cu 2108.0 mm, B.Cu 890.6 mm), 223 vias, no
  duplicate segments. Copper fingerprint (`stats.py`): `e49b4e784743a369`.

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
- **Plane check and DRC.** `plane_check.py` tests the zone outlines. DRC (0 unconnected items)
  covers the fill connections.
- **Gerber check sum.** The gerber files contain their creation date. A new run of `fab.sh`
  gives a zip with another check sum for the same board.
- **JLC rotations.** `cpl.py` does not have the JLC footprints of the new polarised parts
  (D1–D6, Q1, Q2, U20–U23). Their rows have the KiCad rotation, which is not verified against
  JLC's footprints. Check them in JLC's placement preview, or run `tools/jlc_cpl`, before an
  order. R51–R69 are two-pad parts and need no rotation check.
