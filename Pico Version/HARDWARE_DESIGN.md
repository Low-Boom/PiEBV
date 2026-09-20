# PiDG Pico Version — Hardware Design Spec

Baseline: `Chris Teensy Version/IDS_EVS_Synchronizer.kicad_sch` (Teensy 4.1). This
document specifies the Raspberry Pi Pico (RP2040) redesign: MCU swap, a new
50Ω-matched laser driver stage, and an SWD debug header. The camera-side
buffering (Sync/Trigger/TDRSTN to the six `J1`-`J6` headers, the 1.8V LDO, the
`J10`/`J11` selector jumpers) is carried forward unchanged, per direction —
only re-sourced from the new Pico GPIOs instead of the Teensy's.

All active components and passives are SMD; connectors (BNC, pin headers,
SWD) remain through-hole, which is standard fab practice even on
"SMD" boards — call this out if an all-THT-free board is actually required.

## 1. Kept unchanged from the Teensy schematic

| Ref (Teensy sch) | Part | Role |
|---|---|---|
| U1, U3, U5 | 74LVC1G04 (SOT-23-5) | single inverters: sync, trigger-select, pixel-reset paths |
| U2, U4, U6 | SN74LVC04AD hex inverter (SOIC-14) — substitute KiCad stock `74xx:74LVC04` if the original custom symbol/footprint isn't available | fan out Sync/TDRSTN/Trigger to all 6 camera headers |
| U9 | NCP718xSN180 (SOT-23-5), 3.3V→1.8V LDO | powers the camera-side logic at 1.8V |
| U10 | 74LVC1G08 AND gate | laser safety-interlock gate (jumper `J11` AND permanent pull-up `TP2` node) |
| U12 | 74LVC1G08 AND gate | pixel-reset coax input buffer |
| R2-R5 | 3.3kΩ 0805 | pull-ups on jumper/interlock nodes (unchanged values/roles) |
| J1-J6 | Conn_02x05_Odd_Even | camera Sync/Trigger/TDRSTN headers, pinout unchanged |
| J10 | Conn_01x03_Pin | "Trig" source-select jumper (CH1 pulse vs. marker) |
| J11 | Conn_01x03_Pin | "Laser Enable" interlock jumper |
| J12 | Conn_Coaxial | "Pixel Reset" input (external, idle-high) |
| TP2, TP3, TP4 | TestPoint | interlock / sync / trigger-select test points |
| C1-C8 | 0.1µF 0805 | rail decoupling, unchanged |

## 2. Replaced

### 2.1 MCU
Teensy 4.1 module (`U11`) + breakout headers `J16`/`J17` → **Raspberry Pi
Pico**, mounted SMD (soldered directly by its 40 castellated edge pads +
3 castellated debug pads, reflow — no pin headers/socket). **Verify the
castellation footprint's pad pitch/offsets against the official Raspberry Pi
Pico datasheet mechanical drawing before fab** — getting this wrong means the
Pico physically won't solder to the board correctly.

Pico power: `VSYS`/`VBUS` → board `+5V` net (was Teensy `VIN`); Pico's
`3V3(OUT)` → board `+3V3` net, feeding `U9`'s LDO input/enable exactly as the
Teensy's `3V3` pin did. Pico's own micro-USB port (board-edge overhang)
remains the sole power/serial connection, same as the Teensy version.

### 2.2 Laser output stage (CH1/CH2) — new 50Ω-matched drive
The Teensy board drove `J7`/`J8` (the two laser-trigger BNCs) directly from a
74LVC1G08 AND-gate output with **no series or termination resistor at all**.
New stage, added *after* the existing AND-gate/interlock logic (so the safety
interlock behavior is unchanged) and *before* the coax connector:

- **U13 — TI UCC27524** (dual 5A low-side gate driver, SOIC-8), repurposed as
  a fast, low-impedance push-pull line driver (a common technique — these
  parts have <20ns propagation delay and much lower output impedance than a
  logic gate). Non-inverting, 2 independent channels.
  - Pin 1 `ENA`, Pin 8 `ENB` → tied to `VDD` (always enabled; the interlock
    already happens upstream at U7/U8).
  - Pin 2 `INA` ← U7 output (CH1, gated pulse from Pico GP2).
  - Pin 4 `INB` ← U8 output (CH2, gated pulse from Pico GP3).
  - Pin 7 `OUTA` → **R6** → `J7` center pin (CH1 coax).
  - Pin 5 `OUTB` → **R7** → `J8` center pin (CH2 coax).
  - Pin 6 `VDD` → board `+5V` rail (4.5V–18V rated; USB VBUS is in-range but
    has little margin at the 4.5V floor — reuses the rail every other
    5V-side gate on this board already runs from, so this isn't a new risk,
    just worth a bench check with a scope on VDD under load).
  - Pin 3 `GND` → board GND.
  - **R6, R7**: 47Ω 0805, placeholder — pick to bring (driver output
    impedance + R) ≈ 50Ω once the actual driver's output impedance and the
    light sources' trigger-input impedance are measured/confirmed on the
    bench. This is the one piece of this design that should be verified
    empirically, not just trusted from the BOM.
  - C_new: 0.1µF + 1µF decoupling on U13 `VDD`, same footprint style as
    the existing 0805 decoupling caps.

### 2.3 Debug header (new)
The Teensy had no SWD (it's USB-bootloader-only). RP2040 benefits from SWD
for development. Add a 3-pin header wired to the Pico's dedicated debug
castellated pads: `SWCLK`, `GND`, `SWDIO` (these are separate, dedicated pads
on the Pico module, not shared with any GPIO). BOOTSEL + USB/UF2 remains the
primary, simpler programming path — this header is optional-but-cheap.

## 3. New Pico pin mapping

| Net | Pico pin | Destination | Was (Teensy) |
|---|---|---|---|
| `_PULSE_OUT_CH1` | GP2 | U7 pin2 (AND gate B input) | D2 |
| `_PULSE_OUT_CH2` | GP3 | U8 pin2 (AND gate B input) | D3 |
| `MARKER_OUT` (was `PWM_Trig`) | GP4 | U5 pin2 (74LVC1G04 input) | D5 |
| `SYNC_OUT` (was `PWM_1MHz`) | GP5 | U1 pin2 (74LVC1G04 input) | D4 |
| `SWCLK` / `SWDIO` | dedicated debug pads | new 3-pin debug header | n/a (Teensy has none) |
| Serial console | USB CDC (onboard) | Pico's own USB connector | Teensy USB |

Only 4 GPIOs are load-bearing; the Pico's other ~22 GPIOs are unused, leaving
headroom for anything found missing during bring-up.

## 4. Net-by-net wiring list (for schematic capture)

```
+5V      : Pico VSYS/VBUS -- U7.VCC -- U8.VCC -- U10.VCC -- U12.VCC -- U13.VDD -- R2/R3(pull side)
+3V3     : Pico 3V3(OUT)  -- U9.IN -- U9.EN
+1V8     : U9.OUT -- U1.VCC -- U3.VCC -- U5.VCC -- U2.VCC -- U4.VCC -- U6.VCC
GND      : common
_PULSE_OUT_CH1 : Pico GP2 -- U7.pin2
_PULSE_OUT_CH2 : Pico GP3 -- U8.pin2
MARKER_OUT     : Pico GP4 -- U5.pin2
SYNC_OUT       : Pico GP5 -- U1.pin2
CH1_GATED      : U7.pin4 (out) -- U13.INA (pin2)
CH2_GATED      : U8.pin4 (out) -- U13.INB (pin4)
CH1_DRIVE      : U13.OUTA (pin7) -- R6 -- J7.center
CH2_DRIVE      : U13.OUTB (pin5) -- R7 -- J8.center
(all other nets: unchanged from Chris Teensy Version/IDS_EVS_Synchronizer.kicad_sch
 -- see that file for U1-U6, U9, U10-U12, J1-J6, J10-J12, R2-R5, TP2-TP4, C1-C8)
```

## 5. BOM additions/changes vs. the Teensy version

| Ref | Part | Package | Notes |
|---|---|---|---|
| U11 (replaces Teensy) | Raspberry Pi Pico | SMD module, castellated edge | verify footprint against official mechanical drawing |
| U13 (new) | TI UCC27524 | SOIC-8 | dual 50Ω-drive stage for CH1/CH2 |
| R6, R7 (new) | 47Ω, 0805 | placeholder, tune on bench | CH1/CH2 back-match resistors |
| C9, C10 (new) | 0.1µF / 1µF, 0805 | U13 VDD decoupling |
| Debug header (new) | 3-pin, 2.54mm | SWCLK/GND/SWDIO |
| U2, U4, U6 (if custom lib unavailable) | `74xx:74LVC04` (KiCad stock) | SOIC-14 | functional substitute for the missing custom `SN74LVC04AD` symbol/footprint |

## 6. What still needs a KiCad-GUI pass before fab
- PCB copper routing and DRC — this design work stops at schematic capture;
  actual footprint placement and routing needs to be done in KiCad, which
  isn't possible in this environment (see §7: `PiDG_Pico.kicad_pcb` was left
  untouched, so it still has the old Teensy-era footprints).
- **Get a verified Pico footprint.** `PiDG_Pico.kicad_sch` intentionally
  leaves U11's Footprint field blank rather than shipping a hand-derived
  castellation footprint under false confidence — pull one from Raspberry
  Pi's own official KiCad design files or a vetted community library (e.g.
  the ones found under "KiCad Raspberry Pi Pico" — several exist on GitHub),
  add it to `libs/`, and assign it to U11 before running Update PCB from
  Schematic.
- Confirming R6/R7 values against the real light sources' trigger-input spec
  and a bench measurement of U13's actual output impedance.
- Confirming VBUS headroom for U13's 4.5V VDD minimum under real USB load.

## 7. As-built: what's actually in `PiDG_Pico.kicad_sch`

This schematic is a direct, programmatically-verified edit of the Teensy
baseline (parsed and re-serialized through a small S-expression tool so the
diff is exactly: remove 3 symbols, relocate 2, add N new ones — nothing else
in the original 15,000+ lines was touched). Concretely:

- **Removed:** Teensy 4.1 (`U11`) and its two raw breakout headers `J16`/`J17`.
- **Relocated:** `J7`/`J8` (the laser BNCs), shifted 60mm to the right, so the
  new driver stage sits between the existing AND-gate outputs and the
  connectors instead of them being pin-coincident as before.
- **Added:** Pico (`U11`, reusing the freed reference), `UCC27524` (`U13`),
  back-match resistors `R6`/`R7`, `U13` decoupling `C9`/`C10`, and a 3-pin SWD
  header `J13`. New schematic-only symbols live in `libs/PiDG_Local.kicad_sym`
  (registered in this folder's `sym-lib-table`) and are also cached inline in
  the `.kicad_sch` itself, so the file opens correctly even before KiCad
  resolves that library.
- **Net names used in the schematic** (for anyone tracing it in the KiCad
  GUI): the Pico's GP2/GP3/GP4/GP5 keep the **existing** label text
  `_PULSE_OUT_CH1` / `_PULSE_OUT_CH2` / `PWM_Trig` / `PWM_1MHz` (not the
  friendlier `MARKER_OUT`/`SYNC_OUT` names used earlier in this doc) —
  matching the pre-existing labels is what actually ties the Pico into the
  unchanged downstream buffer chain; renaming them would have silently
  created new, disconnected nets instead. `U7`/`U8`'s gated outputs feed the
  driver via new `CH1_GATED`/`CH2_GATED` labels; the driver's outputs reach
  `R6`/`R7` via `CH1_DRIVE_RAW`/`CH2_DRIVE_RAW`; and the resistors' far side
  reaches the relocated `J7`/`J8` via `CH1_DRIVE`/`CH2_DRIVE`.
- **ERC-clean by construction:** every one of the Pico's 33 unused pins gets
  an explicit `no_connect` flag (mirroring how the Teensy's unused pins were
  already handled in the baseline), and every power/ground pin on the new
  parts is tied to the existing `power:+5V`/`power:+3V3`/`power:GND` nets via
  freshly-placed power-flag symbols, the same idiom used throughout the rest
  of the sheet.
- **Verified before writing the file:** parse → re-serialize round-trips
  byte-for-byte (catches any structural corruption), zero duplicate UUIDs,
  zero duplicate reference designators, and every new/existing net label this
  edit relies on has exactly the expected number of occurrences (2 for a
  fresh net, ≥2 for one joining pre-existing wiring). This does **not**
  substitute for opening the file in KiCad and running ERC/DRC for real —
  it's the strongest check achievable without a KiCad GUI in this
  environment, not a replacement for one.
- Component **placement is cosmetic-only** (Pico placed in open space around
  (100, 280), driver stage around (378, 44)) — expect to rearrange for
  readability once you're in the GUI; nothing depends on these exact spots.
- Cosmetic leftovers to expect: a few `no_connect` flags now float where the
  old Teensy pins used to be (harmless — they were independent schematic
  elements, never part of the Teensy symbol itself) and can be deleted
  during your first cleanup pass.
