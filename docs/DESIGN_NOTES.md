# PiEBV design notes

This page is the index of the design documentation of the PiEBV board. The design pages give the
reasons, the analysis, the history and the verification data. The pins, the limits and the
operating rules are in the [hardware reference](../Hardware.md).

| Page | Contents |
|---|---|
| [design/LAYOUT.md](design/LAYOUT.md) | Board images of the layers, stackup, finish and footprints, EuroCard mechanics, routing, power islands (In2.Cu), reference planes, KiCad checks |
| [design/POWER.md](design/POWER.md) | USB-C PD input, +5 V, +12 V supply and power-good gate, +VCAM mux and data-sheet values, camera supply budget, +3.3 V, board output rating |
| [design/SIGNALS.md](design/SIGNALS.md) | Camera signal chains, trigger source and CH1/CH2 skew, pixel reset, laser outputs, amplitude budget, output mode, External Sync Out timing, camera line series resistors, laser interlock, status LED circuits |
| [design/FIRMWARE_HW.md](design/FIRMWARE_HW.md) | Firmware pin map, timing limit derivations, combined mode, pixel-reset gate, boot and arming, clock jumper (300 MHz overclock) |
| [Rev 2 changes](#rev-2-changes) | The differences between Rev 1 and Rev 2 (below) |

---

## Rev 2 changes

| Item | Rev 1 | Rev 2 |
|---|---|---|
| Camera I/O level | 1.8 V only (U9) | `+VCAM`: 1.8 V with J22 open (default), 3.3 V with J22 fitted. U20 (TPS2116 power mux) selects the rail: VIN1 = +1V8, VIN2 = +3V3. R34 and R70 (10 kΩ each, in parallel) pull the select pin PR1 up to +3V3 (1.8 V); a shunt on J22 pulls it low through R35 (3.3 V). R51 discharges `+VCAM`. D1 (blue) shows 3.3 V. See [+VCAM](design/POWER.md#vcam-the-camera-signal-supply). |
| Cameras | IDS uEye EVS | IDS uEye EVS (1.8 V), or Prophesee EVK4 (3.3 V) with the harness of [docs/EVK4_HARNESS.md](EVK4_HARNESS.md) |
| Series resistors in the camera lines | none | R52–R69, 47 Ω 1 %, 0805: one in each Sync, Trigger and TDRSTN line, between the buffer output and the camera header pin. They are the source termination of the camera cable. See [Camera line series resistors](design/SIGNALS.md#camera-line-series-resistors). |
| Status LEDs | none | D2 12 V good, D3 ARMED, D4/D5/D6 output activity of Laser 1 / Laser 2 / External Sync Out. See [Status LEDs](design/SIGNALS.md#status-leds). |
| Firmware pin | – | GP17 = `ARMED_LED` (output, high while ARMED) |
| Third copper layer (In2.Cu) | one +5 V plane | islands: +5V, +3V3, +1V8, +VCAM, +12V, in a GND fill. See [Power islands](design/LAYOUT.md#power-islands-in2cu). |
| Test pads | TP3 only | TP4–TP9: +12V, +5V, +3V3, +1V8, +VCAM, GND |
| U9, C6, C7 | beside the camera buffers | in the supply block at the top centre, beside U20 |
| Parts | 84 placed | 149 placed, plus 6 test pads |
| Finest pitch | 0.65 mm | 0.5 mm (U20, SOT-583) |
| Camera line lengths (buffer pad to resistor pad in Rev 2) | group spreads 1.18 / 2.47 / 1.37 mm (Sync / Trigger / TDRSTN, buffer pin to header pin) | `Sync1`–`Sync6` 74.082 mm, `Trigger1`–`Trigger6` 43.584 mm, `TDRSTN1`–`TDRSTN6` 51.472 mm. The spread in each group is 0.000 mm (below 0.001 mm). The stubs from the resistors to the header pins are equal in each group. |
| Routing | – | The Rev 1 camera copper is removed. The camera lines are routed again, from the buffer to the series resistor. See [Routing](design/LAYOUT.md#routing). |
| Copyright mark | – | Front silkscreen, lower left: `PiEBV Rev 2  (C) 2026 Louis M. Edelman, Chris Willert` and `GPL-3.0` (1 mm text). The licence of the repository is GPL v3 (`LICENSE`). |

Rev 2 is made from the Rev 1 board by `tools/rev2` (see its README). The laser pulse lanes and the
output block keep their Rev 1 copper. The camera lines do not: `tools/rev2/build.sh` removes the
Rev 1 camera copper and routes these lines again.
