# PiEBV — JLCPCB order checklist (full assembly)

**Board revision 2 (2026-11-12).** The Rev 2 items are marked. Before an order, do the three
Rev 2 actions under [Rev 2: do before ordering](#rev-2-do-before-ordering).

Goal: boards that arrive fully assembled, with every surface-mount (SMD) **and** through-hole part
fitted by JLCPCB, so nothing needs soldering on delivery. Part numbers and stock were checked
against JLC's parts library on 2026-09-25 (R25–R28 on 2026-10-01). Check stock again on the day you
order.

## Files to upload

| Step | File |
|---|---|
| PCB | `../PiEBV_Pico_Gerbers.zip` (the 14 files of `../gerbers/` without the drill-map PDFs; made by `tools/rev2/fab.sh` from the Rev 2 board) |
| BOM (parts list) | `PiEBV_Pico_JLC_BOM.csv`: 52 lines (the header line and 51 part lines), every part line with an LCSC part number |
| CPL (placement file) | `PiEBV_Pico_JLC_CPL.csv`: 148 rows, all 148 placed parts. The 84 Rev 1 parts have the rotation and centre corrections of `tools/jlc_cpl`, carried to their Rev 2 positions by `tools/rev2/cpl.py`. **The 12 new polarised parts (D1–D6, Q1, Q2, U20–U23) have the KiCad rotation: not verified against JLC's footprints. Check them in JLC's placement preview, or with `tools/jlc_cpl`, before an order.** The new two-pad parts (R33–R69, C23–C36) need no rotation check. The bare test pads TP4–TP9 are not in the file. |

## PCB options

| Option | Setting |
|---|---|
| Layers / size / qty | 4 layers, 160 × 100 mm EuroCard (read from the gerbers; the job file reports 160.1 × 100.1 mm because of the 0.1 mm outline line), 5 pcs |
| Thickness / material | 1.6 mm, FR-4 standard |
| Stackup | JLC04161H-7628 (the design's documented stackup; "no requirement" is also fine) |
| Impedance control | No |
| Surface finish | **LeadFree HASL** (the form defaults to leaded HASL: change it) |
| Copper | 1 oz outer, 0.5 oz inner |
| Mask / silk | Green / white |
| Via covering | **Tented** (not Plugged, not epoxy-filled) |
| Remove order number | **Specify a location**: the back silkscreen carries the `JLCJLCJLCJLC` placeholder |

## Assembly options

| Option | Setting |
|---|---|
| PCBA type | Economic (the cheaper service; a 4-layer, one-sided board; Rev 1 had 0.65 mm finest pitch and qualified. Rev 2 has one 0.5 mm part (U20, SOT-583): confirm in the order form that Economic still accepts the board). Economic covers the through-hole parts (hand-soldered); decline Standard if JLC suggests it (it costs more and needs edge rails, which J17, TP3 and the BNCs block). Every BOM line is "economic-and-standard" (checked 2026-10-05). |
| Side | Top |
| Assembled quantity | 5 (or fewer) |
| Edge rails | None requested (see the remarks below) |
| Confirm parts placement | Yes |

**Paste into the order remarks:**

> J17 (USB-C) is flush with the left board edge, at the bottom, by design. J7, J8, J12 (BNC, KH-BNC50-3511 50 ohm
> only, do not substitute KH-BNC75-3511) overhang the right edge by about 21 mm, by design — please
> hand-solder these, no wave fixture. J14/J15 are sockets for a plug-in module: seat them flat and
> perpendicular. Do not substitute U3 (74LVC1G00), U9, U13/U19,
> U14 (CH224A only, not CH224K), U15, U17 (adjustable LT3065 only), U18,
> U7/U8/U10, R6/R7/R30 (68 ohm 2 W 2512), R25-R28, R31, R32 (47 / 82 ohm 2 W 2512) or R12/R13 (0.1 %).

## Rev 2: do before ordering

0. **Vias.** Ten vias on the camera lines are 0.5 mm with a 0.3 mm hole (0.1 mm annular ring).
   All other vias are 0.6 mm with a 0.3 mm hole. Before the order, make sure that JLCPCB's
   current capability for a 4-layer board permits a 0.5 mm via with a 0.3 mm hole. This was not
   checked (no access to jlcpcb.com from the build machine).

1. **Run `tools/jlc_cpl`** (it needs internet access to JLC's footprint library) on the Rev 2
   board and copy its `cpl_new.csv` over `PiEBV_Pico_JLC_CPL.csv`. Until then the rotations of
   D1–D6, Q1, Q2 and U20–U23 are the KiCad rotations. A wrong rotation puts an LED in backwards
   or an IC on the wrong pins. Then check these parts one by one in JLC's placement preview:
   the cathode marks of D1–D6 (seen from the top side with the BNCs on the right: the cathode of
   D3, D4, D5 and D6 is the left pad, the cathode of D2 is the right pad, the cathode of D1 is the
   top pad), pin 1 of U20 (lower right of the part) and of U21–U23 (lower right), and the
   single-pad side of Q1 and Q2 (toward the top edge).
2. **Check stock and part type** of the new lines (table below; numbers from a web search on
   2026-11-12, not from JLC's live library).
3. **Remark for the order:** add `D1 must be the blue LED C2293 (do not substitute another
   colour). U20 is TPS2116DRLR in SOT-583 (0.5 mm pitch): check for solder bridges.`

| Ref | Part | LCSC | Type (2026-11-12) | Notes |
|---|---|---|---|---|
| U20 | TI TPS2116DRLR, SOT-583-8 | C3235557 | extended | Power mux for the camera signal level. LCSC stock 9,800–79,000 in different snapshots. |
| U21–U23 | TI SN74LVC1G123DCTR, SSOP-8 (SM8) | C123302 | extended | Pulse stretchers of the activity LEDs. LCSC stock about 16,600–18,800. Not C26159249 (another maker, out of stock). |
| Q1, Q2 | 2N7002, SOT-23 | C8545 | basic | |
| D1 | blue LED 0805, KT-0805B | C2293 | not in the current basic list (it was basic earlier): extended fee likely | Must be blue (or white): see the BOM note. |
| D2 | green LED 0805, KT-0805G | C2297 | basic | |
| D3, D4, D5 | red LED 0805, NCD0805R1 | C84256 | basic | |
| D6 | yellow LED 0805 | C2296 | basic | |
| C31, C33, C35 | 12 pF 50 V C0G 0805 | C1792 | basic | |
| C32, C34, C36 | 22 pF 50 V C0G 0805 (was 18 pF, C1797) | C1804 | not checked | Lower capacitor of the sense dividers. |
| R52–R69 | 47 Ω 1 % 0805 | C17714 | basic | Series resistors in the camera lines: R52–R57 Sync, R58–R63 Trigger, R64–R69 TDRSTN. 18 parts. |
| R51 | 4.7 kΩ 1 % 0805 | C17673 | – | Discharge resistor of `+VCAM`. Same BOM line as the other 4.7 kΩ resistors (R23, R40, R44, R48). |
| C23–C30, R33–R50, J22 | same LCSC parts as the Rev 1 lines with these values | – | – | 0.1 µF, 1 µF, 100 Ω, 750 Ω, 1 kΩ, 4.7 kΩ, 10 kΩ, 100 kΩ, 150 kΩ, 1×2 header |

"Basic" was checked against a public copy of JLC's basic and preferred parts list dated
2026-11-12. JLC's own parts library could not be opened from the machine that made Rev 2.

## Parts that need action before ordering

**J7/J8/J12 BNC:** Kinghelm KH-BNC50-3511 (C2837587, 5,636 in stock, ~$0.93). Before
releasing the order, buy two loose parts from LCSC and (1) test-fit them: the board's holes are 1.0 mm
(centre and ground pins) and 2.2 mm (posts), the sizes of JLC's own KH-BNC50-3511 footprint, which
gives clearance over Kinghelm's 0.90 / 2.00 mm drawing values after plating tolerance; (2) check continuity from the shell to the ground lead (pad 2): the shell bond is one iron lead,
and the mounting posts sit in a PBT (plastic) housing.

**Pre-order these thin-stock parts** in the Parts Manager (Order Parts → JLC stock) before placing the
PCBA order; the order then uses them from your parts inventory. Stock on 2026-10-05:

| Ref | Part | LCSC | Stock | Pre-order |
|---|---|---|---|---|
| U9 | onsemi NCP718BSN180T1G | C892792 | 162 | 6 pcs. Replaces NCP718ASN180T1G (C513024, 0 in stock): same datasheet, ±2 % 1.8 V output and TSOT-23-5 pinout, without the active output discharge (unused here). The TECH PUBLIC copy (C18212639) is not the specified part. |
| U17 | Analog Devices LT3065EMSE#PBF (MSOP-12-EP, adjustable) | C670156 | 36 (2026-11-02) | 6 pcs. Same part on tape: LT3065EMSE#TRPBF (C670157, 50). Not a fixed-voltage LT3065-x. |
| J7/J8/J12 | Kinghelm KH-BNC50-3511 | C2837587 | 5,636 | 18 pcs (single listing). |
| U2/U4/U6 | TI SN74LVC04ADR | C485074 | 3,115 | 18 pcs, optional (no in-stock substitute with Ioff). |

**U14** is the **WCH CH224A** (C42459160). As WCH's CH224K-to-CH224A guide (datasheet §7.2.1)
requires, U14's VHV and VBUS pins connect directly to VBUS_PD, with no resistors. R10 is 56 kΩ: the
CH224A table also gives 15 V. Check U14's rotation in the placement preview — JLC's CH224A library
model may differ from other CH224 variants.

Everything else was in stock in quantity on 2026-09-25 (J17 TYPE-C-31-M-17, C283540: 11,333 on 2026-11-02).
Thirteen lines are JLC basic parts and two preferred extended (no loading fee); the other 26 are
extended (about $3 loading fee each in Economic). Rev 2 adds 10 lines: 6 basic (2N7002, green,
red and yellow LED, 12 pF, 47 Ω), 3 extended (TPS2116, SN74LVC1G123, blue LED) and the 22 pF
line (C1804), whose type was not checked.

## Placement preview — check before approving

The CPL rotations and centres of the 84 Rev 1 parts are corrected to JLC's own LCSC footprints (`tools/jlc_cpl`,
see its README; re-run it after any layout change). For the EuroCard layout the CPL was regenerated
by carrying each part's correction to its new position; `tools/jlc_cpl` run on the Rev 1 EuroCard board gave
the same CPL for all 84 Rev 1 parts. The rotations of the new polarised parts (D1–D6, Q1, Q2, U20–U23) are KiCad
rotations. They are not verified against JLC's footprints: check them in the placement preview
(or with `tools/jlc_cpl`) before an order. R51–R69 are two-pad parts and need no rotation check. Check these in the preview against the
board's pin-1 marks before approving:

- SOT-23-5: U1, U3, U5, U7, U8, U9, U10 · TSOT-23-6: U15 · SOT-23-6: U18 · SC-70-6: U16
- SOIC-8: U13, U19 · SOIC-14: U2, U4, U6 · ESSOP-10 with exposed pad: U14 · MSOP-12 with exposed pad: U17
- J17 USB-C (opening toward the left edge) · J1–J6 IDC headers (key notch as on the silkscreen)
- J7/J8/J12 BNCs (barrels past the right edge) · TP3 (pins pointing toward the left edge, ending inside it)
- Rev 2: D1–D6, Q1, Q2, U20, U21–U23 (see [Rev 2: do before ordering](#rev-2-do-before-ordering)) · J22 (as J20) · C6, C7 and U9 at their new place at the top centre

## Cost estimate (5 boards, before shipping and Japanese consumption tax)

| Item | Estimate |
|---|---|
| 5 bare boards | ≈ $26 (estimate for the old 126 × 126 mm board; JLC's calculator needs a login: re-quote there at 160 × 100 mm) |
| Assembly fees | ≈ $87 (setup + stencil ≈ $10, 20 extended SMT loading fees × $3.07 ≈ $61, joints and through-hole hand soldering ≈ $17) |
| Components | ≈ $85 (with JLC attrition; the 0.1 % resistors, LT3065 and BNCs are the largest lines; not re-priced after the 2026-10-31 change, which adds a UCC27524, three 2512 resistors, two capacitors and a header and removes U12, R5, C8 and J16) |
| Rev 2 additions | not priced: 64 more placed parts, 3 more extended lines (about $9 of loading fees; more if the 22 pF line is an extended part) |
| **Total** | **≈ $200** (cost-down review model, 2026-10-05, for the 126 × 126 mm board; re-quote at 160 × 100 mm), plus shipping (≈ $10–35 to Tokyo, 2–7 days); confirm in JLC's quote |

## On delivery (no soldering)

JLC doesn't supply these:

1. **Pico module:** buy a **Raspberry Pi Pico 2 WH** (the version with pin headers already fitted)
   and plug it in, components up, USB toward the left edge (see the outline on the board). JLC's
   Pico 2 W (C42394205) comes without headers.
2. **Load the firmware** (see the top-level README, Quick start).
3. **Jumpers:** fit a shunt on **J10 2-3** (LCSC C100114, or any 2.54 mm shunt), and on **J18**,
   **J19** and **J21 1-2** (50 Ω outputs: Laser 1, Laser 2 and External Sync Out; 2-3 for a
   high-impedance load). On **J11**, wire the normally-closed E-stop switch across pins 1-2, or fit
   a shunt on 1-2 for bench work. Leave **J20** (clock jumper, right of the Pico) **open** (150 MHz)
   unless that Pico has passed the soak test in `Hardware.md` ("Clock jumper (J20)"); keep the
   sixth shunt loose for it. Leave **J22** (camera signal level, top centre) **open** for IDS cameras
   (1.8 V). Fit a seventh shunt on J22 only for Prophesee EVK4 cameras (3.3 V), and never with an
   IDS camera connected.
4. **Before the first power-up on J17:** the solder-bridge checks in the README (First-board
   checks).
5. **Before the first camera:** the camera signal level check (README, First-board checks, step 4):
   measure `+VCAM` at TP8 with a meter. It must be 1.8 V with J22 open before you connect an IDS
   camera.

## Enclosure notes

Positions are as seen from the top side, with the board landscape (160 mm wide, 100 mm tall).

- **EuroCard, 160 × 100 mm.** The two 160 mm edges have no parts within 2.5 mm (the IEC 60297-3
  card-guide border), so the board fits card guides and extruded enclosures whose slots take the
  160 mm edges, such as the Hammond 1455N1601. Zone copper goes to 0.5 mm from these edges, under
  solder mask. All external connectors are on the two 100 mm edges.
- **Mounting:** 4 × M3 unplated holes, in the corners, 4 mm in from the 100 mm edges and 6 mm in
  from the 160 mm edges: centres 152 × 88 mm apart. An M3 washer (7 mm) at MH2 clears the J7 BNC
  body. Copper is kept 3 mm clear of each hole. In card guides or the 1455N1601 slots, fit no
  hardware at MH1–MH4 (a 7 mm washer reaches the 2.5 mm guide border).
- **Hammond 1455N1601 data and cut-out positions** (slots, headroom, bezel window, edge dressing
  ≤ 0.2 mm, and a table of every end-panel cut-out measured from the top 160 mm edge):
  `Hardware.md`, *EuroCard mechanics*.
- **Right edge:** the three BNC barrels stand about 20.6 mm past the board edge (20.58 mm from the
  Kinghelm KH-BNC50-3511 drawing), with the axis about 6.6 mm
  above the board. Laser 1, Laser 2, External Sync Out from top to bottom, for a
  panel with matching holes (1/2-28UNEF thread, D-hole). Measure both on the first board before
  cutting a panel. The housing is plastic, so fit the panel nuts to take the bayonet torque. The
  housing front is 0.32 mm behind the board edge: with the panel against the board edge, fit a
  0.3 mm shim washer on each barrel between the housing and the panel, so that the nut does not
  pull the BNC forward and load its solder joints. The right edge has only the three BNCs.
- **Left edge:**
  - **Pico micro-USB, `CONTROL / PROGRAM`** (commands and firmware): the Pico sits top-left with
    its USB end at the left edge, raised about 13 mm above the board surface on the sockets (8.5 mm
    socket + 2.5 mm header spacer + module). Its receptacle face is 0.285 mm past the board edge,
    centre 20.50 mm below the top edge. Needs a cut-out at that height, sized for the cable plug's
    overmould (the plug must pass through the panel to seat); confirm the position and height on
    the first assembled board.
  - TP3 (right-angle 2-pin header) below the Pico, its pins pointing at the left edge and ending
    0.96 mm inside it: no cut-out, reach it from above.
  - **J17 USB-C, `POWER ONLY`:** below TP3, at the bottom of the left edge, flush with the edge,
    sitting on the board surface, centre 76.00 mm below the top edge. Needs a cut-out sized for
    the plug overmould (USB-C: up to 12.35 × 6.5 mm).
- **Inside the enclosure, reached from above:**
  - The six camera IDC headers stand upright in one row along the bottom of the board (12 mm
    pitch), not on an edge, so the ribbons leave upward.
  - J10, J11 (the E-stop wiring), and the output-mode jumpers J18/J19/J21 (between the 2512
    resistors and the BNCs).
  - J20 (clock jumper): vertical 2-pin header right of the Pico's GPIO end, below the J14 row.
- **Cable exits:** the camera harnesses and the J11 E-stop wires must leave through an end panel.
  Two strips of the short edges have no connector (measured between courtyards):
  - left edge: 31.8 mm between TP3 and J17 (38.8–70.6 mm below the top edge). J11 (47.5 mm below
    the top edge) is level with it: run the E-stop pair straight left and mount the
    normally-closed switch in the left panel there, or pass its cable through a grommet.
  - right edge: the lowest 31.7 mm, below J12 (MH4 is in its bottom corner).

  The camera ribbons rise from J1–J6 and go to a slot in either strip (J1 is 58 mm from the left
  edge, J6 31 mm from the right edge). A 10-way ribbon (1.27 mm pitch) is 12.7 mm wide, so the
  slot is one ribbon wide with the ribbons stacked flat; a harness with only the five used wires
  (pins 2, 3, 4, 5 and 7) makes a smaller bundle.
