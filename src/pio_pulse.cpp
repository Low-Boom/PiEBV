#include "pio_pulse.h"
#include "hardware/pio_instructions.h"

namespace {

// Instruction addresses within the pulse program (see pio_pulse.h for the
// timing derivation): a 5-instruction preamble loads three FIFO words into
// persistent registers (ISR=delay, Y=width, OSR=tail), then an 8-instruction
// loop spends `delay` cycles low, `width` cycles high, `tail` cycles low.
//   cycles-to-rising-edge   = delay_loaded + 2
//   cycles-pin-stays-high   = width_loaded + 3
//   cycles-pin-stays-low    = tail_loaded + 3
//   total period (cycles)   = delay_loaded + width_loaded + tail_loaded + 8
constexpr uint kPulseWrapTarget = 5;
constexpr uint kPulseWrap = 12;
constexpr uint32_t kPulseFixedOverheadCycles = 8;
constexpr uint32_t kPulseMinDelayCycles = 2;
constexpr uint32_t kPulseMinWidthCycles = 3;

const uint16_t kPulseInstructions[] = {
    (uint16_t)pio_encode_pull(false, true),      // 0: delay word -> OSR
    (uint16_t)pio_encode_mov(pio_isr, pio_osr),  // 1: ISR = delay
    (uint16_t)pio_encode_pull(false, true),      // 2: width word -> OSR
    (uint16_t)pio_encode_mov(pio_y, pio_osr),    // 3: Y = width
    (uint16_t)pio_encode_pull(false, true),      // 4: tail word -> OSR (kept)
    (uint16_t)pio_encode_mov(pio_x, pio_isr),    // 5: <-- wrap_target; X = delay
    (uint16_t)pio_encode_jmp_x_dec(6),           // 6: delay loop
    (uint16_t)pio_encode_set(pio_pins, 1),       // 7: rising edge
    (uint16_t)pio_encode_mov(pio_x, pio_y),      // 8: X = width
    (uint16_t)pio_encode_jmp_x_dec(9),           // 9: width loop
    (uint16_t)pio_encode_set(pio_pins, 0),       // 10: falling edge
    (uint16_t)pio_encode_mov(pio_x, pio_osr),    // 11: X = tail
    (uint16_t)pio_encode_jmp_x_dec(12),          // 12: <-- wrap; tail loop
};

const pio_program_t kPulseProgram = {
    kPulseInstructions,
    13,
    -1,
};

const uint16_t kToggleInstructions[] = {
    (uint16_t)pio_encode_set(pio_pins, 1),  // 0: <-- wrap_target
    (uint16_t)pio_encode_set(pio_pins, 0),  // 1: <-- wrap
};

const pio_program_t kToggleProgram = {
    kToggleInstructions,
    2,
    -1,
};

// The pulse program is shared by every PulseChannel on a given PIO block
// (each state machine gets its own PC/registers, so several SMs can run the
// same physical instruction memory concurrently) -- it must only be loaded
// into that block's instruction memory once, or repeated loads would exceed
// the block's 32-instruction memory.
uint pulseProgramOffset(PIO pio) {
    static PIO loadedOn[2] = {nullptr, nullptr};
    static uint loadedOffset[2] = {0, 0};
    int idx = (pio == pio0) ? 0 : 1;
    if (loadedOn[idx] != pio) {
        loadedOffset[idx] = pio_add_program(pio, &kPulseProgram);
        loadedOn[idx] = pio;
    }
    return loadedOffset[idx];
}

// Shared by pulseTimingFits() and PulseChannel::configure() so both agree on
// exactly the same feasibility check and cycle-count math.
bool computePulseCounts(uint32_t period_ns, uint32_t delay_ns, uint32_t width_ns, uint32_t clk_hz,
                         uint32_t *delayLoaded, uint32_t *widthLoaded, uint32_t *tailLoaded) {
    auto nsToCycles = [clk_hz](uint32_t ns) -> uint64_t {
        return ((uint64_t)ns * clk_hz + 500000000ULL) / 1000000000ULL;
    };

    const uint64_t delayCycles = nsToCycles(delay_ns);
    const uint64_t widthCycles = nsToCycles(width_ns);
    const uint64_t periodCycles = nsToCycles(period_ns);

    const uint32_t dl =
        (delayCycles >= kPulseMinDelayCycles) ? (uint32_t)(delayCycles - kPulseMinDelayCycles) : 0;
    const uint32_t wl =
        (widthCycles >= kPulseMinWidthCycles) ? (uint32_t)(widthCycles - kPulseMinWidthCycles) : 0;

    const uint64_t used = (uint64_t)dl + wl + kPulseFixedOverheadCycles;
    if (periodCycles <= used) {
        return false;  // requested width+delay does not fit inside period at this clock
    }

    if (delayLoaded) *delayLoaded = dl;
    if (widthLoaded) *widthLoaded = wl;
    if (tailLoaded) *tailLoaded = (uint32_t)(periodCycles - used);
    return true;
}

}  // namespace

bool pulseTimingFits(uint32_t period_ns, uint32_t delay_ns, uint32_t width_ns, uint32_t clk_hz) {
    return computePulseCounts(period_ns, delay_ns, width_ns, clk_hz, nullptr, nullptr, nullptr);
}

void PulseChannel::begin(PIO pio, uint sm, uint gpio) {
    pio_ = pio;
    sm_ = sm;
    gpio_ = gpio;
    offset_ = pulseProgramOffset(pio_);

    pio_gpio_init(pio_, gpio_);
    pio_sm_set_consecutive_pindirs(pio_, sm_, gpio_, 1, true);

    config_ = pio_get_default_sm_config();
    sm_config_set_set_pins(&config_, gpio_, 1);
    sm_config_set_wrap(&config_, offset_ + kPulseWrapTarget, offset_ + kPulseWrap);
    sm_config_set_clkdiv_int_frac(&config_, 1, 0);
}

bool PulseChannel::configure(uint32_t period_ns, uint32_t delay_ns, uint32_t width_ns, uint32_t clk_hz) {
    uint32_t delayLoaded, widthLoaded, tailLoaded;
    if (!computePulseCounts(period_ns, delay_ns, width_ns, clk_hz, &delayLoaded, &widthLoaded, &tailLoaded)) {
        return false;
    }

    pio_sm_set_enabled(pio_, sm_, false);
    pio_sm_init(pio_, sm_, offset_, &config_);
    pio_sm_put_blocking(pio_, sm_, delayLoaded);
    pio_sm_put_blocking(pio_, sm_, widthLoaded);
    pio_sm_put_blocking(pio_, sm_, tailLoaded);
    ready_ = true;
    return true;
}

void PulseChannel::start() {
    if (ready_) {
        pio_sm_set_enabled(pio_, sm_, true);
    }
}

void PulseChannel::stop() {
    pio_sm_set_enabled(pio_, sm_, false);
}

void SyncChannel::begin(PIO pio, uint sm, uint gpio) {
    pio_ = pio;
    sm_ = sm;
    gpio_ = gpio;
    offset_ = pio_add_program(pio_, &kToggleProgram);

    pio_gpio_init(pio_, gpio_);
    pio_sm_set_consecutive_pindirs(pio_, sm_, gpio_, 1, true);

    config_ = pio_get_default_sm_config();
    sm_config_set_set_pins(&config_, gpio_, 1);
    sm_config_set_wrap(&config_, offset_ + 0, offset_ + 1);
}

bool SyncChannel::configure(uint32_t freq_hz, uint32_t clk_hz) {
    if (freq_hz == 0) {
        return false;
    }
    // One output period is 2 state-machine clock cycles (set high, set low).
    const double divider = (double)clk_hz / (2.0 * (double)freq_hz);
    if (divider < 1.0 || divider >= 65536.0) {
        return false;  // outside the PIO clock divider's representable range
    }

    pio_sm_set_enabled(pio_, sm_, false);
    sm_config_set_clkdiv(&config_, (float)divider);
    pio_sm_init(pio_, sm_, offset_, &config_);
    ready_ = true;
    return true;
}

void SyncChannel::start() {
    if (ready_) {
        pio_sm_set_enabled(pio_, sm_, true);
    }
}

void SyncChannel::stop() {
    pio_sm_set_enabled(pio_, sm_, false);
}

void startPulseChannelsInSync(PulseChannel *const *channels, size_t count) {
    if (count == 0) {
        return;
    }
    PIO pio = channels[0]->pio();
    uint32_t mask = 0;
    for (size_t i = 0; i < count; ++i) {
        mask |= 1u << channels[i]->sm();
    }
    pio_enable_sm_mask_in_sync(pio, mask);
}
