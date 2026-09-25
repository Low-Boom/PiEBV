#pragma once
// PIO-based precision pulse/clock generation for the PiDG delay generator.
//
// Two PIO program shapes cover everything this board needs:
//  - PulseChannel: free-running "delay, then pulse-high, then idle-low" loop.
//    Used for the two laser outputs (CH1/CH2) and the low-rate marker/alt
//    trigger output. Channels started together stay phase-locked forever,
//    because their periods are exact integer cycle counts on a common clock
//    (the marker period is exactly MARKERDIV x the laser period in cycles).
//  - SyncChannel: a bare 2-instruction toggle loop for the continuous camera
//    sync clock; frequency is set purely via the state machine clock divider.
//
// Both program bodies are hand-encoded with pico-sdk's pio_encode_*()
// functions. (The pinned PlatformIO fork can assemble .pio files too; the
// hand encoding is kept because the cycle model in pulse_timing.h is written
// against these exact instructions.)
//
// Timing math (cycle counts, feasibility, realized values) lives in
// pulse_timing.h, which has no hardware dependency. This file only loads
// those numbers into the state machines.
//
// Pin ownership: the laser pins (CH1/CH2) are routed to PIO only by
// laser_gate's gateOpen(), so PulseChannel::begin() leaves them alone; the
// marker and sync pins are routed to PIO at begin().

#include <cstddef>
#include <cstdint>
#include "hardware/pio.h"
#include "pulse_timing.h"

class PulseChannel {
public:
    // Records pio/sm/gpio and loads the shared pulse program (loaded into a
    // block's instruction memory only once; later channels on the same block
    // reuse the offset). Routes the pin to PIO only if connectPin is true.
    // The caller must already have claimed `sm`.
    // Returns false if the program cannot be loaded (instruction memory full).
    bool begin(PIO pio, uint sm, uint gpio, bool connectPin);

    // Loads one channel's cycle counts: pin direction output, pio_sm_init()
    // (disabled, FIFOs cleared, PC at the program start), then the three
    // timing words into the TX FIFO. Leaves the state machine disabled -- start
    // it with startPulseChannelsInSync().
    // PRECONDITION: the state machine is stopped and its output latch is LOW,
    // i.e. stopPulseChannelsLow() has run.
    // Returns false (and touches no hardware) if the timing does not fit.
    bool configure(const PulseCycles &t);

    // Switches which pin(s) the channel drives: count 1 = `gpio` only (the normal
    // program), count 2 = `gpio` and `gpio + 1` together (the dual-pin program, same
    // cycle timing). Used for COMBINE mode on the two laser pins. PRECONDITION: the
    // state machine is stopped; call configure() afterwards. Returns false if the
    // program cannot be loaded.
    bool setOutputs(uint gpio, uint count);

    PIO pio() const { return pio_; }
    uint sm() const { return sm_; }
    uint gpio() const { return gpio_; }

private:
    void loadConfig();

    PIO pio_ = nullptr;
    uint sm_ = 0;
    uint gpio_ = 0;
    uint pinCount_ = 1;
    uint offset_ = 0;
    pio_sm_config config_{};
};

// Loads the dual-pin pulse program into `pio` now, so COMBINE mode can never fail
// later for lack of instruction memory. Returns false if it does not fit.
bool pulseReserveDualProgram(PIO pio);

class SyncChannel {
public:
    // Loads the toggle program and routes `gpio` to PIO. The caller must
    // already have claimed `sm`. Returns false if the program cannot be loaded.
    bool begin(PIO pio, uint sm, uint gpio);

    // (Re)starts the toggle loop with a clock divider of div256/256 (see
    // syncDiv256For() in pulse_timing.h). div256 must already be in range.
    void start(uint32_t div256);

private:
    PIO pio_ = nullptr;
    uint sm_ = 0;
    uint gpio_ = 0;
    uint offset_ = 0;
    pio_sm_config config_{};
};

// Halts every listed channel's state machine with a single CTRL write, then
// forces each pin's PIO output latch LOW through its own state machine. Runs from
// RAM with interrupts masked, so a pulse in flight is stretched by at most the
// few instructions between the halt and its SET (a few tens of ns) -- which is
// why callers gate the laser pads closed (laser_gate) BEFORE calling this; only
// the MARKER output sees that tiny stretch. All channels must be on the same
// PIO block.
void stopPulseChannelsLow(PulseChannel *const *channels, size_t count);

// Enables every listed channel's state machine on the same clock cycle, so
// their configured delays stay in exact relative phase. All channels must be
// on the same PIO block.
void startPulseChannelsInSync(PulseChannel *const *channels, size_t count);
