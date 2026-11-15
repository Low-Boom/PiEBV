# First-board checks

Do these checks on the first boards, before you connect a laser driver or a camera. The
circuit description is in the [hardware reference](../Hardware.md). The check numbers are
fixed: other pages refer to them.

Ordered by what would bite hardest.

1. **Bench-verify the laser outputs before connecting a laser driver.** With J17 on a 15 V PD
   charger, check +12V at C17 (11.54–12.05 V, typically 11.8 V) and that `LASER_PWR_OK` (U13 pins
   1/8) is high (~12 V). Fit J11 on 1-2 and J18/J19 on 1-2 (50 Ω mode), send `ARM`, then scope J7
   and J8 through a **50 Ω-terminated** input:
   - amplitude 0 V to 4.53–5.14 V (typically ~4.79 V); the budget rests on datasheet corners for
     U17's reference and U13's output resistance, so a measurement closes it;
   - CH2 rising exactly DELAY after CH1 (e.g. `DELAY 10000` → 10.000 µs, `DELAY 13` → 13.3 ns),
     and MARKER rising with every CH1 pulse for minutes at `FREQ 3000`;
   - MARKER rising with every CH1 pulse at a FREQ whose period is not a whole number of cycles,
     e.g. `FREQ 7000`;
   - the first pulse after `ARM` full width, and no two CH1 pulses closer than 1/FREQ while a host
     loops `ARM`/`DISARM` as fast as it can;
   - J7/J8 at 0 V after `DISARM`; after a reset (a power cycle of both J17 and the Pico USB, since
     neither the board nor the Pico 2 W has a reset button, and a watchdog timeout forced over SWD
     as described under [Boot and arming](design/FIRMWARE_HW.md#boot-and-arming)); and, while ARMED with pulses running,
     with J17 unplugged and while it is plugged back in;
   - Hi-Z mode: J18/J19 on 2-3 and the scope at 1 MΩ, 0 V to 4.55–5.08 V, with at most ~5 %
     overshoot (≤ ~5.3 V) at the far end of a 2 m cable (the source is ~49 Ω);
   - the shortest pulse: `WIDTH 20` reaches full height at J7/J8 (U13's minimum input pulse is
     15 ns maximum for the current die, 25 ns for the older one; see [Amplitude budget](design/SIGNALS.md#amplitude-budget));
2. **Check the charger's PD behaviour.** The CH224A datasheet does not say what it does when the
   charger lacks the requested 15 V. The board is safe either way (U18 keeps the lasers disabled
   below ~11 V), but a small charger may leave them disabled. Measure VBUS_PD (C12) with the charger
   you will deploy. This also confirms that the CH224A completes the PD contract with DP/DM shorted
   at the chip (a connection carried over from the CH224K; WCH documents it only for the CH224K).
   If it does not, VBUS_PD stays at 5 V: lasers off, logic still running.
3. **Bench-confirm the camera I/O before plugging in six cameras.** First do check 7 (`+VCAM`).
   Then, with a fast probe and a short ground at the camera end of the harness, look at the
   overshoot of each edge. The series resistors (R52–R69, 47 Ω) are on the board, so this check
   is a measurement only: there is no resistor to fit. The simulation predicts a peak of 2.18 V
   and −0.34 V after a falling edge on a 1.8 V line
   ([Camera line series resistors](design/SIGNALS.md#camera-line-series-resistors)). Compare the measured values with what the camera
   allows.
   IDS documents the pins as 1.8 V
   but publishes no VIH/VIL, input pull or absolute maximum. With one camera, measure TDRSTN,
   Trigger and Sync at the camera end of the harness, and confirm pin 5 is not being driven by the
   camera (i.e. that it is configured as a sync slave).
4. **External Sync Out (J12).** With J17 on the charger, J10 on 2-3 and J21 on 1-2, scope J12
   through a **50 Ω-terminated** input: 0 V to 4.53–5.14 V, one pulse of MARKERWIDTH with every CH1
   period, also while DISARMED, and rising with the camera trigger lines. **Measure the J12-to-camera
   offset** and write it in the `J12-TRIG OFFSET (MEASURED)` field on the silkscreen in the left area,
   below TP3 (RISE, FALL, and the J10/J21 setting it applies to): J12 through the 50 Ω-terminated input, Trigger1 at J1 pin 4
   with a 10× probe and a short ground spring, both edges, at the 50 % points (J12 ~2.4 V, Trigger1
   0.9 V). Deskew the two scope channels first, and subtract the delay of J12's cable (RG-58
   ~5.05 ns/m). Repeat for each J10/J21 setting you use. Expect −9 to +26 ns, typically about
   +10 ns (J12 later); see [External Sync Out](design/SIGNALS.md#external-sync-out-j12). These values are for
   `+VCAM` = 1.8 V. With J22 fitted (3.3 V) the camera buffers are faster and the camera edge is
   about 2.5 ns earlier (typical; `rev2_sim.py`, case 1), so expect about +13 ns. Measure the
   offset again after a change of J22. With J21 on 2-3 and the
   scope at 1 MΩ: 4.55–5.08 V, peak at most ~5.3 V at the end of a 2 m cable. With the Pico's USB
   alone (J17 unplugged), J12 must stay at 0 V. With
   `PIXGATE 0`, TDRSTN at every camera port must stay high (no other source of pixel reset).
5. **Before the first USB-C PD power-up, check the fine-pitch parts for solder bridges.** J17's pads are
   as little as 0.27 mm apart, U20's leads have 0.5 mm pitch (SOT-583) and U16's and U17's leads 0.65 mm pitch, on lead-free HASL. Look at U20 for bridges between adjacent pins (check 7 measures its function). With no power applied, check
   that VBUS_PD is not shorted to GND, CC1 or CC2 (at J17 and U14 pins), and that +5V_PD and +5V are
   not shorted to GND (at U16). U14's CC pins are rated to 32 V, but a VBUS-to-CC bridge would put
   VBUS_PD on the cable's CC line. U14 pins 1 (VHV) and 8 (VBUS) sit directly on VBUS_PD, so also
   check U14 pin 1 against pin 2 (GND) and pin 8 against pin 9 (CFG1, rated
   only 3.8 V). U17's IN (pins 1-3) and OUT (pins 11-12) are on opposite sides of the package and cannot
   bridge; check OUT against ADJ (pin 10): a bridge there sets +12V to about 0.6 V (U18 then
   holds the outputs off). Also confirm that J17's four shell legs are
   soldered (they are through-hole with no paste).

6. **Clock jumper J20:** with no shunt, `STATUS` must show `CLK=150000000` and `CLKMODE=STANDARD`;
   with a shunt, after a power-cycle, `CLK=300000000` and `CLKMODE=OVERCLOCK (jumper fitted)`.
   Measure about 1 kΩ (R29) from J20.1 to Pico pin 14 (GP10) and continuity from J20.2 to GND,
   with no short between J20.1 and J20.2 when the shunt is off. Only if you use 300 MHz: do the soak
   test under
   [Clock jumper](../Hardware.md#clock-jumper-j20-300-mhz-overclock) for each Pico before you rely on it.

7. **Camera I/O level `+VCAM` (Rev 2), before any camera is connected.** With the Pico fitted and
   J22 **open**, measure TP8 (`VCAM`) with a meter: it must be 1.76–1.84 V, and D1 must be dark.
   TP7 (`1V8`) must be the same. TP6 (`3V3`) must be 3.2–3.4 V. Measure U20 pin 4 (PR1): it must
   be at the level of TP6 (R34 and R70 pull it up). Then fit J22: TP8 must go to TP6 less
   a few mV, D1 must light, PR1 must be about 0.55 V. Remove J22: TP8 must return to 1.8 V.
   If TP8 is not 1.8 V with J22 open,
   do not connect an IDS camera: check R34 and R70 (10 kΩ each, PR1 to +3V3) and U20 for solder bridges
   (0.5 mm pitch). Do this measurement again each time before you connect an IDS camera.
   Bench test of a failed U9 (the TPS2116 data sheet does not state this case): with J22 open
   and no camera connected, hold the U9 output (TP7) low and confirm that +VCAM (TP8) does not
   go to 3.3 V.
8. **Status LEDs (Rev 2).** With J17 on a 15 V charger, D2 (`12V OK`) must light when `LASER_PWR_OK`
   goes high, and stay dark on a 5 V-only supply. D3 (`ARMED`) must light only with all three of:
   `ARM` sent, J11 on 1-2, D2 lit. Check each one alone: `DISARM`, J11 on 2-3, J17 unplugged must
   each turn D3 off. With the outputs into 50 Ω: D4 and D5 must flash once for each pulse pair at
   `FREQ 1` and be on continuously at `FREQ 1000`, and be dark when DISARMED; D6 must follow the
   marker. Send `WIDTH 20` and check that D4 and D5 still light. The levels at J7 and J8 (check 1)
   must be inside 4.53–5.14 V with the sense dividers fitted.
9. **EVK4 harness (Rev 2), if you use EVK4 cameras.** Do the continuity table and the powered
   check of [docs/EVK4_HARNESS.md](EVK4_HARNESS.md) before you connect a camera. With the
   camera connected, the level between SYNC_IN_P and SYNC_IN_N must be 2.5 V or more when high.
   The harness has no resistors: the series resistors are on the board (R52–R63).

10. **Cooling fan supply (U24, J23), if you use a fan.** The board is specified for one 12 V,
    40 mm fan. With J17 on a 15 V charger and no fan
    connected, measure J23 pin 1 (`+`) against pin 2: it must be 11.5–12.5 V. Then connect the
    fan (`+` = pin 1; the header has no key). Confirm that the fan starts at the lowest and the
    highest input (about 14.2 V and 15.75 V on VBUS_PD), cold and warm. A fan near the 200 mA
    limit can need more current to start than it draws when it runs; if it does not start, use
    a fan with a lower rated current. Feel or measure the temperature of U24 after 10 minutes
    with the fan running: the junction temperature was not measured in the design. Do not fit
    a shunt on J23: it shorts the fan supply to GND.

**Not an open item: Wi-Fi / Bluetooth.** The firmware doesn't use the radio; the Pico 2 W is fitted
only because it is easier to buy than the plain Pico 2. The In1 GND plane and the In2 +5V and +3V3 islands run
under the whole module, including its antenna, and F.Cu and B.Cu carry GND fill and some tracks
there; this copper shortens the radio's range. That is acceptable even for a
future wireless firmware, which would aim for short, Bluetooth-like range (a few metres), so no
antenna keep-out is needed.
