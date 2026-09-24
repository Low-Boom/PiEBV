#pragma once
// Laser-output gate for CH1 / CH2 (see board.h for the pins).
//
// Each laser trigger pad is in exactly one of two states:
//   CLOSED: IO_BANK0 FUNCSEL = SIO, SIO OUT = 0, SIO OE = 1  -> pad actively driven LOW
//   OPEN  : IO_BANK0 FUNCSEL = PIO0                           -> pad follows the pulse SMs
// The pulse state machines may keep running while the gate is closed; their output
// never reaches the pad. Power-up, every reset and DISARM leave the gate CLOSED. It
// is opened only while ARMED: at the end of the restart hold-off that follows ARM,
// and again after each pulse change while armed. restartPulses() in main.cpp closes
// it and reloads the state machines; servicePendingStart(), called from loop(),
// reopens it when the hold-off is over (a DISARM before then cancels that). A
// pre-init hook closes it before clocks, C++ constructors, the Pico 2 W's
// initVariant() or setup() run.

#include "hardware/pio.h"

namespace laser {

// Drive both laser pads LOW from SIO. Glitch-free (a pulse in flight is cut short,
// never lengthened), idempotent, and safe from any state -- including from the
// pre-init hook, before clocks are configured.
void gateClose();

// Hand both laser pads to `pio`. PRECONDITION: every state machine that can drive
// the laser pins is DISABLED. Forces the PIO output level of both pins LOW before
// switching FUNCSEL, so each pad goes SIO-LOW -> PIO-LOW with no edge. `anySm` is
// used only to execute the forced SET.
void gateOpen(PIO pio, uint anySm);

bool gateIsOpen();

}  // namespace laser
