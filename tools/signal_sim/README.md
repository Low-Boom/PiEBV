# Signal simulation of the timing nets

Transmission-line simulation of the PiDG trigger, laser and External Sync Out nets. It uses the
routed geometry from `PiDG_Pico.kicad_pcb` and datasheet device values. It calculates:

- the CH1-to-CH2 skew at U7/U8 and at J7/J8, for each J10 position, with and without R19;
- the delay from the GP11 edge to J12 and to the camera trigger pins (J1-J6 pin 4), and the
  J12-minus-camera offset at the min / typ / max corners;
- the J7/J8 and J12 levels, overshoot and settling, in both output modes;
- the power in R30, R31 and R32 (a check of the values in Hardware.md);
- the effect of a different U19 driver, of the GP11 drive strength and slew rate, and of a
  separate GPIO for U19 (option d).

Run it again after a change to the routing of these nets, to a part in these chains, or to a
value in `devices.json`. The last results are in `results.md`.

| File | What it does |
|---|---|
| `signal_sim.py` | The runner. Builds one ngspice netlist for each circuit stage and corner, runs it through KiCad's `ngspice.dll`, and writes `results.md` and `results.json`. |
| `geometry.json` | Input. Stackup, line values (Z0, delay, L and C per mm) and the routed tree of each net: branches, layers, widths, lengths and vias. Made by `extract_geometry.py`. |
| `devices.json` | Input. Device parameters for each corner, with the datasheet and table for each value. Keys that end in `_est`, and blocks with `"est": true`, are estimates. |
| `extract_geometry.py` | Makes `geometry.json` from `../../PiDG_Pico.kicad_pcb` (read only) with KiCad's `pcbnew`. |
| `fd_cache.json` | Cache of the field-solver results that `extract_geometry.py` uses. |
| `results.md` | Output. The tables for all cases, the hand-calculation checks and the gate calibration. |
| `results.json` | Output. The same results as numbers, for other scripts. |

## Run

Use KiCad 10's Python. It contains numpy and `pcbnew`. The tools need no other packages.

```
cd tools/signal_sim
"%LOCALAPPDATA%\Programs\KiCad\10.0\bin\python.exe" signal_sim.py
```

The run takes about 1.5 min (169 ngspice runs). The script prints `results.md` and then the number
of runs and the time. Set `KICAD_BIN` to use a KiCad `bin` folder in a different location. If ngspice
stops with an error, the script writes the netlist to `failed_netlist.cir` and stops.

### Make the geometry again

Do this after a change to the routing of a simulated net:

```
"%LOCALAPPDATA%\Programs\KiCad\10.0\bin\python.exe" extract_geometry.py
```

The script reads the board file and writes `geometry.json`. With `fd_cache.json` it takes about
1 s. The cache key holds the line parameters, so a new stackup, mask permittivity or trace width
gets a new field solve automatically (about 2.5 min for each new width). Delete `fd_cache.json` only
after a change to the solver code; a full solve takes about 8 min. The script prints each net: total length,
vias, loops, pads that it cannot reach, and track that lies fully inside a pad. A good net has
`comps 1 loops 0 unreached []`. To add a net, add it to `NETS` and its source pad to `ROOT`.

## Model

**Stages.** The circuit is divided at each gate input. A gate input loads its net only through
its input capacitance, so each stage is simulated alone and the delays are added:

| Stage | From | To |
|---|---|---|
| A | GP11, GP12, GP13 pads (and GP14 for option d) | U5.2, U19.2, U7.2, U8.2 through `PWM_Trig`, J10, `PWM_TRIG_TAP`, `CH1_J10`, `_PULSE_OUT_CH1/2`, R19, R9, R17, R18 and TP4 |
| B1, B2 | U5 output, then the U6 outputs | U6 inputs (`TRIG_N`), then J1-J6 pin 4 (`Trigger1..6`) |
| C | U19 output (or U13 outputs) | R30 (R6/R7), J21 (J18/J19), R31, R32, the BNC, RG-58 cable and the load |
| D1 | U7/U8 outputs | U13 inputs (`CH1_GATED`, `CH2_GATED`) |

**Board traces.** Each routed run is a lossless T line with the Z0 and delay of its layer and
width. A run shorter than 2 mm is a lumped LC section. A via is a lumped C-L-C section. All
simulated nets are on F.Cu or B.Cu, so they are microstrip: F.Cu over In1 (GND), B.Cu over In2
(+5V plane, AC reference only). For a 0.3 mm trace, Z0 is 54.5 ohm and the delay is 6.06 ps/mm.

**GPIO.** The RP2350 pad is a current source with a tanh V-I shape, switched by an internal ramp.
The slope is from the typical V-I curves (RP2350 datasheet Figure 154). The "floor" corner puts the
pad on the Table 1683 VOH/VOL limits. The pad, the Pico 2 W trace, the pin and the J14 socket are
added as estimates.

**Gates and drivers.** Each gate is a threshold crossing, then an internal delay, then an output
ramp behind an output resistance. The internal delay is calibrated: the gate model, driven and
loaded as in the datasheet test circuit, gives the datasheet propagation delay. The calibration
table is at the end of `results.md`.

**Corners.** min = strong GPIO and every device at its fast corner. typ = all typical.
max = weak GPIO and every device at its slow corner. Output levels use the +12V and 1 % resistor
corners of Hardware.md "Amplitude budget". The J12-minus-camera offset takes the corners of the
two paths independently.

## Checks

`results.md` starts with a table of hand calculations against the simulation:

- levels into 50 ohm and into 1 Mohm in both J21 modes (voltage dividers);
- the cable delay (2 m x 5.05 ns/m);
- the first arrival of an ideal step through the routed geometry (sum of length x delay per mm);
- the U5 delay into its datasheet test load;
- the R30 power while high, into 50 ohm and into a short.

It also repeats the typical J12 and camera delays with half the time step. A difference larger
than a few ps shows a numerical problem.

## Limits

- Many device values are estimates: the RP2350 pad (no IBIS model is published), the Pico trace
  and socket, the UCC27524 input capacitance and output edge, the gate output resistances, the
  typical thresholds and the 2512 parasitics. `devices.json` marks each one. Use the typical
  results as a model result, not as a measurement. Measure the J12-to-camera offset on the board.
- The traces are lossless and have no coupling to other nets. The return path of B.Cu through the
  +5V plane is ideal.
- The GND pour beside most traces lowers Z0 to about 52 ohm and the delay to 5.94 ps/mm
  (`fd_masked_gcpw_gap0.30` in `geometry.json`). The runner uses the microstrip values. The
  difference in trace delay is about 2 %, which is small compared to the device spread.
- The camera input is 5 pF (estimate). The ribbon cable to the camera is not in the model.
- The UCC27524 peak-current limit is not in the model. The output edge is an estimate.

## Sources

- Raspberry Pi RP2350 datasheet, build 01/10/2026: Table 1680, Table 1683, Figure 154.
- TI SCES214AF (SN74LVC1G04): Tables 5.3, 5.5, 5.7.
- TI SCAS281T (SN74LVC04A): Tables 6.3, 6.7, 6.8.
- TI SCLS315S (SN74AHCT1G08): Tables 5.3, 5.5, 5.6.
- TI SLUSFA9, June 2024 (UCC27524, D package): sections 6.5, 6.6, 7.3.4.
- TI SLUSBP4C (UCC27524A and the older UCC27524 die): sections 5.5, 5.6.
- Infineon 2EDN752x datasheet Rev. 2.7: Tables 12, 13, 14.
- TI SLUSBQ0C (UCC27517A): sections 8.5, 8.6.
- E. Hammerstad and O. Jensen, microstrip formulas (1980); IPC-2141A; H. Johnson, High-Speed
  Digital Design (1993), section 7.3 (via L and C).
