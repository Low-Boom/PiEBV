# PiDG — JLCPCB order checklist (full assembly)

Goal: boards that arrive fully assembled — every SMD **and** through-hole part fitted by JLCPCB —
so nothing needs soldering on delivery. Part numbers and stock were checked against JLC's parts
library on 2026-09-25; re-check stock on the day you order.

## Files to upload

| Step | File |
|---|---|
| PCB | `../PiDG_Pico_Gerbers.zip` |
| BOM | `PiDG_Pico_JLC_BOM.csv` — 40 lines, every one with an LCSC part number |
| CPL | `PiDG_Pico_JLC_CPL.csv` — all 75 placed parts (through-hole parts at their pad centre) |

## PCB options

| Option | Setting |
|---|---|
| Layers / size / qty | 4 layers, 126 × 126 mm (from the gerbers), 5 pcs |
| Thickness / material | 1.6 mm, FR-4 standard |
| Stackup | JLC04161H-7628 (the design's documented stackup; "no requirement" is also fine) |
| Impedance control | No |
| Surface finish | **LeadFree HASL** (the form defaults to leaded HASL — change it) |
| Copper | 1 oz outer, 0.5 oz inner |
| Mask / silk | Green / white |
| Via covering | **Tented** (not Plugged, not epoxy-filled) |
| Remove order number | **Specify a location** — the back silkscreen carries the `JLCJLCJLCJLC` placeholder |

## Assembly options

| Option | Setting |
|---|---|
| PCBA type | Economic (4-layer, single-sided, finest pitch 0.5 mm all qualify). Accept Standard if JLC asks for it because of the through-hole parts. |
| Side | Top |
| Assembled quantity | 5 (or fewer) |
| Edge rails | None requested — see the remarks below |
| Confirm parts placement | Yes |

**Paste into the order remarks:**

> J17 (USB-C) is flush with the top board edge by design. J7, J8, J12 (BNC) overhang the right edge
> by about 21 mm, and J16 / TP3 (right-angle headers) overhang their edges, all by design — please
> hand-solder these, no wave fixture. J14/J15 are sockets for a plug-in module: seat them flat and
> perpendicular. Do not substitute U9, U12, U13, U14, U15, U17 (adjustable LT3065 only), U18,
> U7/U8/U10, R6/R7 (68 ohm 2 W 2512) or R12/R13 (0.1 %).

## Parts that need action before ordering

| Ref | Part | LCSC | Stock on 2026-09-25 | Action |
|---|---|---|---|---|
| U14 | WCH CH224K | C970725 | **0** | Pre-stock it through JLC Global Sourcing (Parts Manager), or buy and consign it. Do **not** accept CH224A: different CFG1 rating and resistor table. |
| U9 | onsemi NCP718ASN180T1G | C513024 | **0** | Global Sourcing (Digi-Key/Mouser stock it) or consign. The TECH PUBLIC copy (C18212639) is not the specified part. |

Everything else was in stock in quantity (U17 LT3065: 799, enough for 5 boards). Eleven lines are
JLC basic parts; the rest are extended (about $3 loading fee each in Economic).

## Placement preview — check before approving

Pin 1 is top-left in every KiCad footprint, but JLC's library orientation varies. Check each of
these in the preview against the board's pin-1 marks and correct the rotation there if needed:

- SOT-23-5: U1, U3, U5, U7, U8, U9, U10, U12 · TSOT-23-6: U15 · SOT-23-6: U18 · SC-70-6: U16
- SOIC-8: U13 · SOIC-14: U2, U4, U6 · ESSOP-10 with exposed pad: U14 · DFN-10 with exposed pad: U17
- J17 USB-C (opening toward the top edge) · J1–J6 IDC headers (key notch as on the silkscreen)
- J7/J8/J12 BNCs (barrels past the right edge) · J16/TP3 (pins pointing off the board edge)

## Cost estimate (2026-09-25, before shipping and Japanese consumption tax)

| Item | Estimate |
|---|---|
| 5 bare boards | ≈ $25–45 (JLC's calculator needs a login — confirm there) |
| Assembly fees, 5 boards | ≈ $115 (setup + stencil ≈ $10, ≈ 28 extended-part loading fees ≈ $86, joints and hand soldering ≈ $19) |
| Components, 5 boards | ≈ $120–140 (SMD ≈ $12 per board, through-hole ≈ $12 per board, plus attrition) |
| **Total** | **≈ $260–300**, plus shipping (≈ $10–35 to Tokyo, 2–7 days) and Global Sourcing premiums |

## Not supplied by JLC — do on delivery (no soldering)

1. **Pico module:** buy a **Raspberry Pi Pico 2 WH** (the version with headers already fitted) and
   plug it in, component side up, USB toward the top edge (see the silkscreen outline). JLC's
   Pico 2 W (C42394205) comes without headers.
2. **Flash the firmware** (see the top-level README, Quick start).
3. **Jumpers:** fit a shunt on **J10 2-3** (LCSC C100114, or any 2.54 mm shunt). On **J11**, wire the
   normally-closed E-stop switch across pins 1-2, or fit a shunt on 1-2 for bench work.
4. **Before the first power-up on J17:** the continuity checks in the README (Before connecting
   lasers or cameras).

## Enclosure notes

- **Mounting:** 4 × M3 holes on a 114 × 114 mm square, 6 mm in from each edge of the 126 × 126 mm
  board. Copper is kept 3 mm clear of each hole.
- **Right edge:** the three BNC barrels stand 20.8 mm past the board edge (Laser 1, Laser 2, Pixel
  reset from top to bottom), for a panel with matching holes. J16's pins stick out 2.1 mm past the
  right edge.
- **Top edge — two USB ports, labelled on the silkscreen:**
  - **J17 USB-C, `POWER ONLY`**: centred 82 mm from the board's left edge, flush with the top edge,
    sitting on the board surface. Needs a cut-out.
  - **Pico micro-USB, `CONTROL / PROGRAM`** (serial commands and firmware): centred about 37 mm
    from the left edge, at the top edge, raised about 13 mm above the board surface on the sockets
    (8.5 mm socket + 2.5 mm header spacer + module). Needs a cut-out at that height; confirm the
    height on the first assembled board.
  - TP3's pins stick out 2.1 mm past the top edge, to the left of the Pico (the same overhang as J16).
- **Inside the enclosure, reached from above:**
  - The six camera IDC headers stand vertically between about 17 and 30 mm in from the bottom edge, so the
    ribbons leave upward.
  - J10 and J11 (the E-stop wiring) are inside as well.
