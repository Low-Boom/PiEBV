#pragma once
// GPIO assignments of the PiEBV 4-layer board. These MUST match
// "PiEBV_Pico.kicad_sch" (repo root). The Pico plugs into sockets
// J14/J15; J14 pad n = Pico physical pin n.
//
//   constant     GPIO   Pico pin   J14 pad   board net         drives
//   ----------   ----   --------   -------   ---------------   ---------------------------------
//   kPinMarker   GP11      15         15     PWM_Trig          J10.3 -> U5 -> U6 -> Trigger1..6, and
//                                                                U19 -> J12 (External Sync Out)
//   kPinCh2      GP12      16         16     _PULSE_OUT_CH2    U8 -> U13 -> J8 (Laser 2); R18 10k to GND
//   kPinCh1      GP13      17         17     _PULSE_OUT_CH1    U7 -> U13 -> J7 (Laser 1); R17 10k to GND
//   kPinSync     GP15      20         20     PWM_1MHz          U1 -> U2 -> Sync1..6, TP3. clk_gpout1, not PIO:
//                                                                only GP13/15/21 (23-25 internal) have a clock
//                                                                output, and GP13 is CH1 (sync_clock.h).
//   kPinPixGate  GP16      21    J15 pad 20 PIXRST_GATE       U3 pins 1+2 (NAND as inverter) -> U4 ->
//                                                                TDRSTN1..6; R24 10k to +3V3. Driven INVERTED
//                                                                (main.cpp): PIO latch high = pixels in reset.
//   kPinClockSel GP10      14         14     CLK_SEL           R29 1k -> J20.1 (J20.2 = GND). Clock jumper, read once
//                                                                at boot (clock_mode.cpp): fitted = 300 MHz, open = 150 MHz.
//                                                                Internal pull-up only; no capacitor on the net. R29
//                                                                limits the current if GP10 is driven with the shunt fitted.
//   kPinArmedLed GP17      22    J15 pad 19 ARMED_LED         Q2 gate (R38 100k to GND) -> D3 "ARMED" (Rev 2 board). HIGH while
//                                                                ARMED. D3 lights only if J11 is closed and +12 V is good as
//                                                                well (LASER_EN -> D3 -> Q2 -> Q1). Status only: it gates nothing.
//
// CH1 is the HIGHER GPIO and CH2 the lower. The order is deliberate, so do not
// "tidy" these into ascending order.
// GP2-GP5 are not connected on this board. GP17 is not connected on the Rev 1 board (driving it there is harmless). GP10 (SYNC before it moved to the clock generator)
// is now the clock jumper input.

constexpr unsigned kPinMarker = 11;
constexpr unsigned kPinCh2 = 12;
constexpr unsigned kPinCh1 = 13;
constexpr unsigned kPinSync = 15;
constexpr unsigned kPinPixGate = 16;
constexpr unsigned kPinClockSel = 10;
constexpr unsigned kPinArmedLed = 17;

constexpr unsigned kLaserPinMask = (1u << kPinCh1) | (1u << kPinCh2);
