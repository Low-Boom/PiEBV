#pragma once
// PIO-based precision pulse/clock generation for the PiDG delay generator.
//
// Two PIO program shapes cover everything this board needs:
//  - PulseChannel: free-running "delay, then pulse-high, then idle-low" loop.
//    Used for the two laser outputs (CH1/CH2) and the low-rate marker/alt
//    trigger output. All PulseChannels sharing a period relationship (e.g.
//    marker period = N * pulse period) stay phase-locked forever once
//    started together, because the counts are exact integer cycle counts on
//    a common clock -- no runtime synchronization is needed after start.
//  - SyncChannel: a bare 2-instruction toggle loop for the continuous camera
//    sync clock; frequency is set purely via the state machine clock divider.
//
// Both program bodies are hand-encoded with pico-sdk's pio_encode_*()
// functions instead of a .pio/pioasm build step, since PlatformIO does not
// natively assemble .pio files and the pioasm package is not reliably
// available (see project notes). The programs are tiny (13 and 2
// instructions), so hand encoding is straightforward and removes the extra
// build-tool dependency entirely.

#include <cstddef>
#include <cstdint>
#include "hardware/pio.h"

class PulseChannel {
public:
    // Claims `sm` on `pio`, routes `gpio` to it, and loads the shared pulse
    // program (only actually loaded into PIO instruction memory once per
    // `pio` instance; subsequent channels on the same block reuse the offset).
    void begin(PIO pio, uint sm, uint gpio);

    // Computes cycle counts for the requested timing at clk_hz and loads them
    // into the state machine, ready to run. Leaves the state machine disabled
    // -- call pio_enable_sm_mask_in_sync() (or start()) to begin, so multiple
    // channels can be released on the exact same clock cycle.
    // Returns false (and leaves the channel's previous configuration
    // untouched) if width+delay cannot fit inside period at this clock.
    bool configure(uint32_t period_ns, uint32_t delay_ns, uint32_t width_ns, uint32_t clk_hz);

    void start();
    void stop();

    PIO pio() const { return pio_; }
    uint sm() const { return sm_; }

private:
    PIO pio_ = nullptr;
    uint sm_ = 0;
    uint gpio_ = 0;
    uint offset_ = 0;
    pio_sm_config config_{};
    bool ready_ = false;
};

class SyncChannel {
public:
    void begin(PIO pio, uint sm, uint gpio);

    // Sets the free-running toggle frequency (the output square wave is at
    // freq_hz, i.e. one full period is 2 state-machine clock cycles).
    // Returns false if freq_hz cannot be reached (too high, or divider out
    // of range).
    bool configure(uint32_t freq_hz, uint32_t clk_hz);

    void start();
    void stop();

    PIO pio() const { return pio_; }
    uint sm() const { return sm_; }

private:
    PIO pio_ = nullptr;
    uint sm_ = 0;
    uint gpio_ = 0;
    uint offset_ = 0;
    pio_sm_config config_{};
    bool ready_ = false;
};

// Enables every listed channel's state machine on the same clock cycle, so
// their configured delays stay in exact relative phase. All channels must be
// on the same PIO block.
void startPulseChannelsInSync(PulseChannel *const *channels, size_t count);

// Returns true if the requested timing can be represented at clk_hz, without
// touching any hardware -- the same feasibility check PulseChannel::configure()
// uses internally. Callers reconfiguring several channels from one parameter
// set should validate all of them with this first and only call configure()
// once every one of them fits, so a rejected change never leaves some
// channels reconfigured while others keep their old (still valid) timing.
bool pulseTimingFits(uint32_t period_ns, uint32_t delay_ns, uint32_t width_ns, uint32_t clk_hz);
