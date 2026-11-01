# PiDG — JLCPCB order checklist (full assembly)

Goal: boards that arrive fully assembled, with every surface-mount (SMD) **and** through-hole part
fitted by JLCPCB, so nothing needs soldering on delivery. Part numbers and stock were checked
against JLC's parts library on 2026-09-25 (R25–R28 on 2026-10-01). Check stock again on the day you
order.

## Files to upload

| Step | File |
|---|---|
| PCB | `../PiDG_Pico_Gerbers.zip` |
| BOM (parts list) | `PiDG_Pico_JLC_BOM.csv`: 41 lines, every one with an LCSC part number |
| CPL (placement file) | `PiDG_Pico_JLC_CPL.csv`: all 85 placed parts; rotations and centres corrected to JLC's own footprints by `tools/jlc_cpl` |

## PCB options

| Option | Setting |
|---|---|
| Layers / size / qty | 4 layers, 126 × 126 mm (read from the gerbers), 5 pcs |
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
| PCBA type | Economic (the cheaper service; a 4-layer, one-sided board with 0.5 mm finest pitch qualifies). Economic covers the through-hole parts (hand-soldered); decline Standard if JLC suggests it (it costs more and needs edge rails, which J17, TP3 and the BNCs block). Every BOM line is "economic-and-standard" (checked 2026-10-05). |
| Side | Top |
| Assembled quantity | 5 (or fewer) |
| Edge rails | None requested (see the remarks below) |
| Confirm parts placement | Yes |

**Paste into the order remarks:**

> J17 (USB-C) is flush with the top board edge by design. J7, J8, J12 (BNC, KH-BNC50-3511 50 ohm
> only, do not substitute KH-BNC75-3511) overhang the right edge by about 21 mm, and TP3 (right-angle header) overhangs the top edge, all by design — please
> hand-solder these, no wave fixture. J14/J15 are sockets for a plug-in module: seat them flat and
> perpendicular. Do not substitute U3 (74LVC1G00), U9, U13/U19,
> U14 (CH224A only, not CH224K), U15, U17 (adjustable LT3065 only), U18,
> U7/U8/U10, R6/R7/R30 (68 ohm 2 W 2512), R25-R28, R31, R32 (47 / 82 ohm 2 W 2512) or R12/R13 (0.1 %).

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
| U17 | Analog Devices LT3065EDD#TRPBF | C670143 | 684, falling | 6 pcs. No drop-in alternative. |
| J7/J8/J12 | Kinghelm KH-BNC50-3511 | C2837587 | 5,636 | 18 pcs (single listing). |
| U2/U4/U6 | TI SN74LVC04ADR | C485074 | 3,115 | 18 pcs, optional (no in-stock substitute with Ioff). |

**U14** is the **WCH CH224A** (C42459160). As WCH's CH224K-to-CH224A guide (datasheet §7.2.1)
requires, U14's VHV and VBUS pins connect directly to VBUS_PD, with no resistors. R10 is 56 kΩ: the
CH224A table also gives 15 V. Check U14's rotation in the placement preview — JLC's CH224A library
model may differ from other CH224 variants.

Everything else was in stock in quantity on 2026-09-25 (U17 LT3065: 799, enough for 5 boards).
Thirteen lines are JLC basic parts and two preferred extended (no loading fee); the other 26 are
extended (about $3 loading fee each in Economic).

## Placement preview — check before approving

The CPL rotations and centres are already corrected to JLC's own LCSC footprints (`tools/jlc_cpl`,
see its README; re-run it after any layout change). Still check these in the preview against the
board's pin-1 marks before approving:

- SOT-23-5: U1, U3, U5, U7, U8, U9, U10 · TSOT-23-6: U15 · SOT-23-6: U18 · SC-70-6: U16
- SOIC-8: U13, U19 · SOIC-14: U2, U4, U6 · ESSOP-10 with exposed pad: U14 · DFN-10 with exposed pad: U17
- J17 USB-C (opening toward the top edge) · J1–J6 IDC headers (key notch as on the silkscreen)
- J7/J8/J12 BNCs (barrels past the right edge) · TP3 (pins pointing off the board edge)

## Cost estimate (5 boards, before shipping and Japanese consumption tax)

| Item | Estimate |
|---|---|
| 5 bare boards | ≈ $26 (estimate; JLC's calculator needs a login: confirm there) |
| Assembly fees | ≈ $87 (setup + stencil ≈ $10, 20 extended SMT loading fees × $3.07 ≈ $61, joints and through-hole hand soldering ≈ $17) |
| Components | ≈ $85 (with JLC attrition; the 0.1 % resistors, LT3065 and BNCs are the largest lines; not re-priced after the 2026-10-31 change, which adds a UCC27524, three 2512 resistors, two capacitors and a header and removes U12, R5, C8 and J16) |
| **Total** | **≈ $200** (cost-down review model, 2026-10-05), plus shipping (≈ $10–35 to Tokyo, 2–7 days); confirm in JLC's quote |

## On delivery (no soldering)

JLC doesn't supply these:

1. **Pico module:** buy a **Raspberry Pi Pico 2 WH** (the version with pin headers already fitted)
   and plug it in, components up, USB toward the top edge (see the outline on the board). JLC's
   Pico 2 W (C42394205) comes without headers.
2. **Load the firmware** (see the top-level README, Quick start).
3. **Jumpers:** fit a shunt on **J10 2-3** (LCSC C100114, or any 2.54 mm shunt), and on **J18**,
   **J19** and **J21 1-2** (50 Ω outputs: Laser 1, Laser 2 and External Sync Out; 2-3 for a
   high-impedance load). On **J11**, wire the normally-closed E-stop switch across pins 1-2, or fit
   a shunt on 1-2 for bench work. Leave **J20** (clock jumper, left of the Pico) **open** (150 MHz)
   unless that Pico has passed the soak test in `Hardware.md` ("Clock jumper (J20)"); keep the
   sixth shunt loose for it.
4. **Before the first power-up on J17:** the solder-bridge checks in the README (First-board
   checks).

## Enclosure notes

- **Mounting:** 4 × M3 holes on a 114 × 114 mm square, 6 mm in from each edge of the
  126 × 126 mm board. Copper is kept 3 mm clear of each hole.
- **Right edge:** the three BNC barrels stand about 20.6 mm past the board edge (20.58 mm from the
  Kinghelm KH-BNC50-3511 drawing), with the axis about 6.6 mm
  above the board. Laser 1, Laser 2, External Sync Out from top to bottom, for a
  panel with matching holes (1/2-28UNEF thread, D-hole). Measure both on the first board before
  cutting a panel. The housing is plastic, so fit the panel nuts to take the bayonet torque.
- **Top edge: two USB ports, labelled on the silkscreen:**
  - **J17 USB-C, `POWER ONLY`:** centred 82 mm from the board's left edge, flush with the top edge,
    sitting on the board surface. Needs a cut-out.
  - **Pico micro-USB, `CONTROL / PROGRAM`** (commands and firmware): centred about 37 mm from the
    left edge, at the top edge, raised about 13 mm above the board surface on the sockets (8.5 mm
    socket + 2.5 mm header spacer + module). Needs a cut-out at that height; confirm the height on
    the first assembled board.
  - TP3's pins stick out 2.1 mm past the top edge, left of the Pico.
- **Inside the enclosure, reached from above:**
  - The six camera IDC headers stand upright between about 17 and 30 mm in from the bottom edge, so
    the ribbons leave upward.
  - J10, J11 (the E-stop wiring), and the output-mode jumpers J18/J19/J21 (between the 2512
    resistors and the BNCs).
  - J20 (clock jumper): vertical 2-pin header 7.6 mm left of the Pico socket J14, level with Pico
    pins 13-14. Its shunt is reached beside the seated Pico (pin centres 6 mm from the module edge).
