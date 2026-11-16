# Safety

This page gives the safety rules of the PiEBV board in detail. Read the short version in the
[README](../README.md#the-short-version) first. This page is part of the PiEBV documentation. The
overview and the list of all pages are in the [README](../README.md).

## In detail

**Starting and stopping**

- **`DISARM` always works, immediately.** The six letters D-I-S-A-R-M, in any case and anywhere in
  what you type, disarm the outputs as soon as the last letter reaches the board. You don't need to
  press Enter, as long as your terminal sends each key as you type it (all the terminals listed
  under [USB serial](CONNECTING.md#usb-serial) do). A monitor with a separate input box, such as the Arduino
  IDE's, sends nothing until you press Enter.
- **The three gates are independent.** Each one on its own holds both outputs at 0 V. The firmware
  can only see the first one, so `ARMED=1` does not by itself mean the outputs are live. The third
  gate (U18) checks that the board's 12 V laser-driver supply is between 10.6 and 13.3 V, which needs
  the 15 V charger.
- **Losing the USB link does not disarm.** If the Pico's USB cable is pulled, the PC goes to sleep
  or a script is killed while ARMED, the board keeps running from J17 and the lasers keep pulsing,
  with no way to send `DISARM`. Stop them in hardware: take the J11 shunt off 1-2, or unplug J17.
- **With Wi-Fi on, `ARM` can come from the network.** The network link has no password and no
  encryption: every computer that can reach the board can arm it. Losing the network link does not
  disarm. `DISARM` over USB stays available, but the network link can delay it: by design up to
  about 0.5 s, and about 1 s if the radio chip stops answering. The network link was not yet
  tested on a board. See [Network (Wi-Fi)](CONNECTING.md#network-wi-fi). The link is off until it
  is set up over USB.
- **Before uploading new firmware, send `DISARM`.** The upload restarts the Pico, and a restart in
  the middle of a pulse can stretch that one pulse by an estimated 70–150 ns.
- **Before using a debugger (SWD), send `DISARM` and remove the J11 shunt** (or unplug J17). A
  debugger reset can leave a laser output high for milliseconds.

**Laser outputs**

- **Match the output mode to what you connect.** J18 sets the mode for J7 (Laser 1), J19 for J8
  (Laser 2) and J21 for J12 (External Sync Out) ([details](SETUP.md#jumpers)):

  | Shunt | Mode | Use it for | Into a 50 Ω input | Into a Hi-Z input |
  |---|---|---|---|---|
  | **1-2** | 50 Ω | The LDP-V, or any 50 Ω input | **about 4.8 V** (correct) | about 12 V (too high for 5 V logic) |
  | **2-3** | Hi-Z | TTL or 5 V CMOS inputs, a scope at 1 MΩ | about 2.5 V (too low to fire an LDP-V) | **about 4.8 V** (correct) |
  | none | — | nothing: always fit a shunt | about 3.5 V | about 12 V |

  To fire **one light source with both pulses**, or **two light sources together with the same
  double pulse**, use `COMBINE 1` instead ([Combined mode](COMMANDS.md#combined-mode-combine)): each output
  then carries both pulses, still one driver per output.

**Cameras and jumpers**

- **Camera pins 1, 6 and 8 are not connected on the board,** so a straight-through ribbon can't
  short the camera's own supplies at the board (pin 1 is the camera's 1.8 V output, pin 8 its USB
  5 V). The remaining risk is in the harness: fit only wires 2, 3, 4, 5 and 7 (or cut 1, 6 and 8),
  and never join pin 1 or 8 to a ground wire. Pin 6 is undocumented: don't assume it is a ground.
- **Set every camera to sync slave.** PiEBV drives the sync pin, so a camera set as sync master would
  fight it.
- **Never fit a shunt across all three pins of J10.**
- **Don't short J12.** External Sync Out can be high for up to half the period (`MARKERWIDTH` is
  limited to 50 % for this reason); into a short its 2 W, 68 Ω resistor then takes up to 1.1 W on
  average (1.45 W with J10 on 1-2 and `COMBINE 1`).

More detail: [Hardware.md](../Hardware.md), sections Boot and arming, Laser
interlock and Connectors.
