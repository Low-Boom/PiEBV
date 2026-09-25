#include "pio_pulse.h"
#include "hardware/pio_instructions.h"
#include "hardware/sync.h"

namespace {

// Instruction addresses within the pulse program: a 5-instruction preamble
// loads three FIFO words into persistent registers (ISR=delay, Y=width,
// OSR=tail), then an 8-instruction loop spends `delay` cycles low, `width`
// cycles high, `tail` cycles low. Cycle model (see pulse_timing.h):
//   SET PINS,1 on cycle 7 + delay_loaded after the in-sync enable
//   high time = width_loaded + 3 cycles
//   period    = delay_loaded + width_loaded + tail_loaded + 8 cycles
// The 7-cycle offset is the same for every channel, so it cancels between
// CH1, CH2 and the marker.
constexpr uint kPulseWrapTarget = 5;
constexpr uint kPulseWrap = 12;

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
    0,  // pio_version: runs on any PIO
#if PICO_PIO_VERSION > 0
    0,  // used_gpio_ranges: no constraint (pins are chosen at run time)
#endif
};

// The same program for COMBINE mode, driving TWO consecutive pins: the rising edge
// is `SET PINS, 3` (both pins high) instead of `SET PINS, 1`. Every instruction and
// every cycle is otherwise identical, so the cycle model and FIFO words are shared.
// CH1 and CH2 both run it on the two laser pins; the PIO output level of a pin is
// the last value any state machine wrote (RP2350 datasheet 11.5.6), and the laser
// timing check requires DELAY >= WIDTH + 1 cycle so the pulses never touch, so each laser
// pin carries CH1's pulse and then CH2's pulse, exactly DELAY later.
const uint16_t kPulseDualInstructions[] = {
    (uint16_t)pio_encode_pull(false, true),      // 0: delay word -> OSR
    (uint16_t)pio_encode_mov(pio_isr, pio_osr),  // 1: ISR = delay
    (uint16_t)pio_encode_pull(false, true),      // 2: width word -> OSR
    (uint16_t)pio_encode_mov(pio_y, pio_osr),    // 3: Y = width
    (uint16_t)pio_encode_pull(false, true),      // 4: tail word -> OSR (kept)
    (uint16_t)pio_encode_mov(pio_x, pio_isr),    // 5: <-- wrap_target; X = delay
    (uint16_t)pio_encode_jmp_x_dec(6),           // 6: delay loop
    (uint16_t)pio_encode_set(pio_pins, 3),       // 7: rising edge on both pins
    (uint16_t)pio_encode_mov(pio_x, pio_y),      // 8: X = width
    (uint16_t)pio_encode_jmp_x_dec(9),           // 9: width loop
    (uint16_t)pio_encode_set(pio_pins, 0),       // 10: falling edge on both pins
    (uint16_t)pio_encode_mov(pio_x, pio_osr),    // 11: X = tail
    (uint16_t)pio_encode_jmp_x_dec(12),          // 12: <-- wrap; tail loop
};

const pio_program_t kPulseDualProgram = {
    kPulseDualInstructions,
    13,
    -1,
    0,  // pio_version: runs on any PIO
#if PICO_PIO_VERSION > 0
    0,  // used_gpio_ranges: no constraint (pins are chosen at run time)
#endif
};

const uint16_t kToggleInstructions[] = {
    (uint16_t)pio_encode_set(pio_pins, 1),  // 0: <-- wrap_target
    (uint16_t)pio_encode_set(pio_pins, 0),  // 1: <-- wrap
};

const pio_program_t kToggleProgram = {
    kToggleInstructions,
    2,
    -1,
    0,  // pio_version: runs on any PIO
#if PICO_PIO_VERSION > 0
    0,  // used_gpio_ranges: no constraint (pins are chosen at run time)
#endif
};

// The pulse program is shared by every PulseChannel on a given PIO block
// (each state machine gets its own PC/registers, so several SMs can run the
// same physical instruction memory concurrently) -- it must only be loaded
// into that block's instruction memory once, or repeated loads would exceed
// the block's 32-instruction memory. Returns the offset, or a negative
// PICO_ERROR_* if pio_add_program() found no room.
int programOffset(PIO pio, const pio_program_t *prog, bool *loaded, int *loadedOffset) {
    const uint idx = pio_get_index(pio);
    if (!loaded[idx]) {
        const int off = pio_add_program(pio, prog);
        if (off < 0) {
            return off;
        }
        loadedOffset[idx] = off;
        loaded[idx] = true;
    }
    return loadedOffset[idx];
}

int pulseProgramOffset(PIO pio, bool dual) {
    static bool loaded[2][NUM_PIOS] = {};
    static int loadedOffset[2][NUM_PIOS] = {};
    return programOffset(pio, dual ? &kPulseDualProgram : &kPulseProgram, loaded[dual], loadedOffset[dual]);
}

}  // namespace

bool pulseReserveDualProgram(PIO pio) {
    return pulseProgramOffset(pio, true) >= 0;
}

void PulseChannel::loadConfig() {
    config_ = pio_get_default_sm_config();
    sm_config_set_set_pins(&config_, gpio_, pinCount_);
    sm_config_set_wrap(&config_, offset_ + kPulseWrapTarget, offset_ + kPulseWrap);
    sm_config_set_clkdiv_int_frac8(&config_, 1, 0);
    // Load PINCTRL now, so a forced `SET PINS, 0` on this SM (stopPulseChannelsLow)
    // targets this channel's own pin(s) even before the next configure().
    pio_sm_set_config(pio_, sm_, &config_);
}

bool PulseChannel::begin(PIO pio, uint sm, uint gpio, bool connectPin) {
    pio_ = pio;
    sm_ = sm;
    gpio_ = gpio;
    pinCount_ = 1;

    const int off = pulseProgramOffset(pio_, false);
    if (off < 0) {
        return false;
    }
    offset_ = (uint)off;
    loadConfig();

    if (connectPin) {
        pio_gpio_init(pio_, gpio_);  // the PIO output latch is LOW after the boot-time PIO reset
        pio_sm_set_consecutive_pindirs(pio_, sm_, gpio_, 1, true);
    }
    return true;
}

bool PulseChannel::setOutputs(uint gpio, uint count) {
    if (count != 1 && count != 2) {
        return false;
    }
    const int off = pulseProgramOffset(pio_, count == 2);
    if (off < 0) {
        return false;
    }
    pio_sm_set_enabled(pio_, sm_, false);  // already stopped; harmless
    offset_ = (uint)off;
    gpio_ = gpio;
    pinCount_ = count;
    loadConfig();
    return true;
}

bool PulseChannel::configure(const PulseCycles &t) {
    PulseWords w;
    if (computePulseCounts(t, &w) != PulseFit::Ok) {
        return false;
    }
    pio_sm_set_enabled(pio_, sm_, false);  // already stopped; harmless
    pio_sm_set_consecutive_pindirs(pio_, sm_, gpio_, pinCount_, true);
    pio_sm_init(pio_, sm_, offset_, &config_);  // stays disabled; FIFOs cleared; PC = offset_
    pio_sm_put_blocking(pio_, sm_, w.delay);    // 3 words into a 4-deep TX FIFO: never blocks
    pio_sm_put_blocking(pio_, sm_, w.width);
    pio_sm_put_blocking(pio_, sm_, w.tail);
    return true;
}

bool SyncChannel::begin(PIO pio, uint sm, uint gpio) {
    pio_ = pio;
    sm_ = sm;
    gpio_ = gpio;

    const int off = pio_add_program(pio_, &kToggleProgram);
    if (off < 0) {
        return false;
    }
    offset_ = (uint)off;

    pio_gpio_init(pio_, gpio_);  // the PIO output latch is LOW after the boot-time PIO reset
    pio_sm_set_consecutive_pindirs(pio_, sm_, gpio_, 1, true);

    config_ = pio_get_default_sm_config();
    sm_config_set_set_pins(&config_, gpio_, 1);
    sm_config_set_wrap(&config_, offset_ + 0, offset_ + 1);
    return true;
}

void SyncChannel::start(uint32_t div256) {
    pio_sm_set_enabled(pio_, sm_, false);
    sm_config_set_clkdiv_int_frac8(&config_, div256 >> 8, (uint8_t)(div256 & 0xFFu));
    pio_sm_init(pio_, sm_, offset_, &config_);
    pio_sm_set_enabled(pio_, sm_, true);
}

// In RAM, so no flash (XIP) cache miss can sit between the halt and the forced LOWs.
void __not_in_flash_func(stopPulseChannelsLow)(PulseChannel *const *channels, size_t count) {
    if (count == 0) {
        return;
    }
    // Read everything first: the channel list may live in flash, and nothing between
    // the halt and the forced LOWs should touch flash.
    PIO pio = channels[0]->pio();
    uint sms[NUM_PIO_STATE_MACHINES];
    const size_t n = count < NUM_PIO_STATE_MACHINES ? count : NUM_PIO_STATE_MACHINES;
    uint32_t smMask = 0;
    for (size_t i = 0; i < n; ++i) {
        sms[i] = channels[i]->sm();
        smMask |= 1u << sms[i];
    }
    const uint32_t irq = save_and_disable_interrupts();
    pio_set_sm_mask_enabled(pio, smMask, false);  // one CTRL write halts them all
    // The output latch is PIO-block state (RP2350 datasheet 11.5.6): a halted SM
    // leaves it wherever it was. `SET PINS, 0` written to each SM's own SMx_INSTR
    // runs on the disabled SM, drives that SM's own pin (PINCTRL is loaded at
    // begin()) and leaves its PC alone -- one store per channel, no PINCTRL swap.
    for (size_t i = 0; i < n; ++i) {
        pio_sm_exec(pio, sms[i], pio_encode_set(pio_pins, 0));
    }
    restore_interrupts(irq);
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
