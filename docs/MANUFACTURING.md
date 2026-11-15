# Manufacturing notes

This page gives the data for the board order and for assembly. The circuit description is in
the [hardware reference](../Hardware.md). The JLCPCB order checklist is
[fab/jlc/JLC_ORDER.md](../fab/jlc/JLC_ORDER.md).

- **No vias inside SMD pads,** apart from the two thermal vias in each of U14's and U17's exposed
  GND pads, which is normal practice. Every other via drill is at least 0.2 mm from any SMD pad
  edge, so the standard **tented** via option is correct, and filled-and-capped via-in-pad (a paid
  option on 4-layer boards) is not needed. On the JLC order form choose *Tented*, not *Plugged*.
- **No controlled impedance is needed.** The longest critical run (U13 to J7/J8 through the
  output-mode block, ~50 mm, Z0 ≈ 55 Ω; unchanged in the EuroCard re-layout) is electrically short
  compared with the driver's edges. The camera lines are 43.6–74.1 mm from the buffer output to the
  series resistor, equal in each group, and 4.4–9.8 mm from the resistor to the
  header. Order *Impedance control: No*.
- **Copper keep-outs:** zone copper stays 0.5 mm from the board edge on all four layers, and a
  3 mm-radius keep-out keeps all copper (including the In2 islands) away from each M3 hole, so a
  metal screw or standoff can't touch a plane in the hole wall. No parts are within 2.5 mm of the
  two 160 mm edges (card-guide border; see [EuroCard mechanics](design/LAYOUT.md#eurocard-mechanics)); zone copper
  there still goes to 0.5 mm from the edge, under solder mask.
- **Ground stitching:** edge-fence vias at 10 mm pitch (two gaps on the left edge where parts
  intrude), 1.5 mm in from the outline, plus a tap via at every SMD GND pad and at the pads of
  each power rail. The Rev 2 board has 228 vias in total: GND 139, +5V 13, +3V3 7, +1V8 2, +VCAM 5,
  +12V 9, other nets 53 (`tools/rev2/stats.py`). The Rev 1 EuroCard board had 173; the interior
  stitching lattice was removed on 2026-11-07, and the count of 194 in earlier text was from
  before that.
- **Silkscreen** shows the Pico outline, the `CONTROL / PROGRAM` and `POWER ONLY` port labels, and a
  pin-1 mark (a module fitted the other way round would put the board's +5 V on one of its GPIO
  pins). J10, J11, J18, J19, J20 and J21 are labelled as described in the [hardware reference](../Hardware.md). Rev 2 adds the LED names
  (`12V OK`, `ARMED`, `3V3`, `L1`, `L2`, `SYNC`), `J22` with `CAMERA I/O LEVEL (J22)` /
  `OPEN = 1V8  IDS` / `SHUNT = 3V3  EVK4`, the rail names at TP4–TP9, and the fan header text
  `J23  FAN 12V` / `0.2 A MAX` with `+` beside pin 1 and `-` beside pin 2. The reference
  designators of the new parts (R52–R69 included) are on F.Fab only, not on the silkscreen,
  except U9, C6, C7 and U24. The
  `J12-TRIG OFFSET (MEASURED)` write-in field is in the left area, below TP3. Board text is 0.7 mm high or more (the new Rev 2 text is 0.8 mm).

**JLCPCB order:** the board is set up for full assembly by JLCPCB, with every SMD and
through-hole part fitted, so nothing needs soldering on delivery. `fab/jlc/JLC_ORDER.md` is the
checklist: order-form settings, remarks to paste, rotations to
check in the placement preview, the cost estimate, what to do on delivery (plug in a Pico 2 WH,
flash the firmware, fit J10, wire the E-stop to J11), and enclosure notes. The JLC BOM carries an
LCSC number on every line; through-hole parts sit in the placement file at their pad centre,
because their footprint origins are on pin 1. The placement file was regenerated for the EuroCard
layout: each part's JLC rotation and centre correction was carried to its new position, so check
JLC's placement preview as before. Rev 2 adds 69 placed parts to the BOM and the placement file (153 rows; the JLC BOM has 53 lines: the header line and 52 part lines);
`tools/jlc_cpl` was run on the final Rev 2 board and its result is the committed placement file. It read JLC's footprint of every one of the 153 parts. It changed the rotation of D1 (270 to 90), D2 (180 to 0), D6 (0 to 180), Q1 and Q2 (90 to 270), U20 (180 to 90) and U21–U23 (180 to 0). D3, D4 and D5 need no correction. The rows of the 84 Rev 1 parts did not change. The pad fit of these parts is 0.10 mm or better (`tools/jlc_cpl/rot_report.txt`). The tool was run again after the fan supply was added: the rows of the 149 earlier parts did not change, and the new rows are C37, C38, J23 and U24. It changed the rotation of U24 (0 to 270). The tool flags the pad fit of U24 (0.65 mm, above its 0.2 mm limit) for a check, because the KiCad TO-252-2 footprint and JLC's footprint differ in pad shape. Check these parts in JLC's placement preview also (see `fab/jlc/JLC_ORDER.md`). Check U24 there: the tab must point toward the right (toward J23) and the two leads toward the left (toward C37 and C38). The JLC part class of U24 (C9072, basic or extended) is not confirmed: treat it as an extended part until checked. R51–R70 are two-pad parts and need no rotation check. The back silkscreen carries JLC's
`JLCJLCJLCJLC` order-number placeholder.

## Hot-plate assembly

The layout also lets you assemble the board by hand with a hot plate.

- **All SMD parts are on the top side.** Their pads span 133.4 mm of the board's 160 mm width, so
  the plate must be about 140 mm wide or more (e.g. a 200 × 200 mm plate).
- **Order:** apply paste and place all SMD parts, reflow on the plate, then hand-solder every
  through-hole part (sockets, headers, BNCs and J17's shell legs) with an iron. There are no parts on
  the bottom side, so the board lies flat on the plate. The exposed pads of U14 and U17 reflow on the
  plate; this flow needs no hot air. The tab of U24 (TO-252) is a large pad with a solid connection
  to the top-layer GND pour and four GND vias: with an iron, it needs more heat than the other pads. If you solder with an iron only, solder R52–R69 before the
  camera headers J1–J6: the header bodies then stand on both sides of each resistor column.
- **Paste: use a stencil.** U20 has 0.5 mm pitch (SOT-583, pads 0.3 mm wide). U16 and U17 have 0.65 mm pitch (pads 0.35 and 0.40 mm wide, so gaps of
  0.30 and 0.25 mm), and J17's pads are as little as 0.27 mm apart. Paste from a syringe is hard to meter
  for these gaps. Order a steel stencil, 0.12 mm thick, cut from
  `fab/gerbers/PiEBV_Pico-F_Paste.gbr` (apertures equal to the pads; at 0.12 mm every U16/U17 lead
  aperture has an area ratio of 1.09 or more, above the 0.66 minimum of IPC-7525; the area ratio of the U20 apertures was not calculated), and use type 4
  paste. Print the whole board in one pass. The exposed pads get reduced paste so that solder does not
  wick into their thermal vias: U14's paste is an "H" that keeps its two via holes clear,
  and U17's is four small windows (they still cover about 35 % of its via holes).
  Without a stencil, dispense paste only on the exposed pads of U14 and U17 and on the coarser
  parts, reflow, then drag-solder the U16, U17, U20 and J17 leads with an iron and flux, and remove
  bridges with braid.
- **Spacing for tweezers:** the Rev 1 layout put the parts at least 0.5 mm apart, courtyard to courtyard
  (pads at least 1 mm apart), with these exceptions. Five pairs in the carried output block stay as designed: U13–C9 and
  U19–C21 (0.03 mm, the VDD bypass capacitors right at the pins), and J18–R27, J19–R28 and J21–R32
  (0.23 mm). Two buck pairs keep their hand spacing for the shortest hot loop: C13–L1 (0.08 mm) and
  C12–U15 (0.36 mm). The parts around U17/U18 and C14/C15/U16 are spread out around their ICs.
  The Rev 2 additions (the status LED cells, the sense dividers, the resistor columns between
  the camera headers) are closer than 0.5 mm in places. The smallest courtyard gap is about
  0.15 mm (C31–C32). DRC shows no courtyard overlap.
- **Thermal relief** on the plane-connected pads (0.5 mm gap, 0.5 mm spokes), so you can
  hand-solder the through-hole GND pins. Exceptions: pins 1 and 4 (GND) of U21, U22 and U23 and the
  tab (GND) of U24 have a solid zone connection.
