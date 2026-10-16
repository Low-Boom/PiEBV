#include "clock_mode.h"

#include "board.h"
#include "reset_scratch.h"
#include "hardware/clocks.h"
#include "hardware/gpio.h"
#include "hardware/structs/qmi.h"
#include "hardware/structs/sio.h"
#include "hardware/structs/watchdog.h"
#include "hardware/sync.h"
#include "hardware/vreg.h"
#include "hardware/watchdog.h"
#include "pico/platform.h"

// The arduino-pico core calls set_sys_clock_khz(F_CPU) in main() when F_CPU is not
// 150 MHz. That runs AFTER the pre-init hook below and would undo it (keeping the raised
// VREG and the slowed flash), so the build must keep the 150 MHz boot clock.
static_assert(F_CPU == kStandardClockHz, "platformio.ini board_build.f_cpu must stay 150000000L (clock_mode.h)");

namespace {

// Core voltage for 300 MHz. 1.30 V is the highest the SDK allows without unlocking the
// regulator limit (vreg.h, VREG_VOLTAGE_MAX); the default is 1.10 V. The soak test may
// show that a lower value is stable on a given chip.
constexpr vreg_voltage kOverclockVreg = VREG_VOLTAGE_1_30;
// VSEL 0..15 = 0.55 V + 50 mV per step (vreg.h).
static_assert(kOverclockVreg <= VREG_VOLTAGE_1_30 && 550u + 50u * (uint32_t)kOverclockVreg == kOverclockVregMv,
              "kOverclockVregMv must match kOverclockVreg");
// Wait after a VREG change, as the SDK's runtime_init_clocks() does.
constexpr uint32_t kVregSettleUs = SYS_CLK_VREG_VOLTAGE_AUTO_ADJUST_DELAY_US;
// The pull-up charges the jumper trace well within this.
constexpr uint32_t kJumperSettleUs = 100;

ClockModeInfo g_info;  // .bss: zeroed by crt0 before the pre-init hook; no dynamic initializer

// CPU-cycle wait: does not depend on the timer.
void waitUs(uint32_t us) {
    busy_wait_at_least_cycles((uint32_t)((uint64_t)us * clock_get_hz(clk_sys) / 1000000u));
}

// Jumper fitted = pin held at GND. Internal pull-up (the pad default is a pull-down),
// read twice kJumperSettleUs apart: both LOW = fitted, anything else = open. The pin
// stays an input with the pull-up. It starts LOW (pull-down) and charges through the
// pull-up, so the board must not put a capacitor on it: with an RC of ~100 us or more,
// an open jumper would still read LOW here.
//
// Only register writes, as in laser_gate.cpp. Not gpio_init(): its gpio_put() and
// gpio_set_dir() use the RP2350 GPIO coprocessor, which the SDK enables only after this
// hook (runtime_init_per_core_enable_coprocessors is a per-core initializer, and those
// run after every core-0 one). gpio_get() reads sio_hw directly.
bool readJumper() {
    sio_hw->gpio_oe_clr = 1u << kPinClockSel;  // input
    sio_hw->gpio_clr = 1u << kPinClockSel;
    gpio_set_pulls(kPinClockSel, true, false);
    gpio_set_function(kPinClockSel, GPIO_FUNC_SIO);  // PADS IE=1, then FUNCSEL, then ISO cleared
    waitUs(kJumperSettleUs);
    const bool first = !gpio_get(kPinClockSel);
    waitUs(kJumperSettleUs);
    return first && !gpio_get(kPinClockSel);
}

// Any watchdog timeout since the last POR/BOR/RUN: this boot's reset (the core's
// getResetReason() test for WDT_RESET), or an earlier one in main.cpp's counter.
bool watchdogTimeoutSincePowerUp() {
    if (watchdog_caused_reboot() && watchdog_enable_caused_reboot()) {
        return true;
    }
    return watchdog_hw->scratch[kWdtCountMagicScratch] == kWdtCountMagic && watchdog_hw->scratch[kWdtCountScratch] != 0;
}

// Doubles the field `mask` of *t. False if the result does not fit.
bool doubleField(uint32_t *t, uint32_t mask, uint32_t lsb) {
    const uint32_t v = ((*t & mask) >> lsb) * 2u;
    if (v > (mask >> lsb)) {
        return false;
    }
    *t = (*t & ~mask) | (v << lsb);
    return true;
}

// QMI window 0 (flash) timing for twice the clk_sys, with the same flash timing in ns:
// every field counted in clk_sys cycles is doubled. CLKDIV keeps the SCK frequency (the
// boot ROM's 3 -> 6: 50 MHz at both clocks), RXDELAY the sample point (2 -> 4), and
// MIN_DESELECT, SELECT_HOLD, SELECT_SETUP and MAX_SELECT their times. COOLDOWN only
// trades power for speed, so it stays. False if a value does not fit (no overclock then).
bool qmiTimingForDoubleClock(uint32_t t, uint32_t *out) {
    if ((t & QMI_M0_TIMING_CLKDIV_BITS) == 0) {
        return false;  // CLKDIV 0 means 256
    }
    const bool ok = doubleField(&t, QMI_M0_TIMING_CLKDIV_BITS, QMI_M0_TIMING_CLKDIV_LSB) &&
                    doubleField(&t, QMI_M0_TIMING_RXDELAY_BITS, QMI_M0_TIMING_RXDELAY_LSB) &&
                    doubleField(&t, QMI_M0_TIMING_MIN_DESELECT_BITS, QMI_M0_TIMING_MIN_DESELECT_LSB) &&
                    doubleField(&t, QMI_M0_TIMING_SELECT_HOLD_BITS, QMI_M0_TIMING_SELECT_HOLD_LSB) &&
                    doubleField(&t, QMI_M0_TIMING_SELECT_SETUP_BITS, QMI_M0_TIMING_SELECT_SETUP_LSB) &&
                    doubleField(&t, QMI_M0_TIMING_MAX_SELECT_BITS, QMI_M0_TIMING_MAX_SELECT_LSB);
    *out = t;
    return ok;
}

// The QMI allows only CLKDIV to change during a transfer. As the SDK's PSRAM setup
// does: direct mode blocks new memory-mapped (XIP) transfers, and BUSY = 0 means the
// last one has finished. Runs from RAM with interrupts off, so no flash access can
// start in between; calls nothing (every helper used here is inline).
void __no_inline_not_in_flash_func(qmiSetM0Timing)(uint32_t timing) {
    const uint32_t irq = save_and_disable_interrupts();
    const uint32_t csr = qmi_hw->direct_csr;
    qmi_hw->direct_csr = csr | QMI_DIRECT_CSR_EN_BITS;
    while (qmi_hw->direct_csr & QMI_DIRECT_CSR_BUSY_BITS) {
        tight_loop_contents();
    }
    qmi_hw->m[0].timing = timing;
    qmi_hw->direct_csr = csr;  // direct mode off again
    __compiler_memory_barrier();
    restore_interrupts(irq);
}

// 150 -> 300 MHz. Every check comes first, so a refusal changes nothing. Then: VREG up
// and settled; flash timing doubled (flash at 25 MHz for the moment, back to 50 MHz
// once clk_sys doubles); clk_sys through the SDK, which runs it from pll_usb while
// pll_sys re-locks and moves clk_peri to pll_usb (48 MHz; UART/SPI are unused).
const char *raiseClock() {
    uint vco = 0, postDiv1 = 0, postDiv2 = 0;
    if (!check_sys_clock_hz(kOverclockHz, &vco, &postDiv1, &postDiv2)) {
        return "300 MHz is not an exact PLL setting";
    }
    uint32_t timing = 0;
    if (!qmiTimingForDoubleClock(qmi_hw->m[0].timing, &timing)) {
        return "flash timing cannot be scaled";
    }
    vreg_set_voltage(kOverclockVreg);
    waitUs(kVregSettleUs);
    qmiSetM0Timing(timing);
    set_sys_clock_pll(vco, postDiv1, postDiv2);
    // The firmware does not use the HSTX. Its clock follows clk_sys (runtime_init_clocks)
    // and would otherwise run at 300 MHz, above its 150 MHz rating.
    clock_stop(clk_hstx);
    return clock_get_hz(clk_sys) == kOverclockHz ? nullptr : "clk_sys did not reach 300 MHz";
}

void clockModeBoot() {
    g_info.jumperFitted = readJumper();
    if (!g_info.jumperFitted) {
        return;
    }
    if (watchdogTimeoutSincePowerUp()) {
        g_info.why = "watchdog reset since power-up; power-cycle to retry";
    } else if (clock_get_hz(clk_sys) != kStandardClockHz) {
        g_info.why = "boot clock is not 150 MHz";
    } else {
        g_info.why = raiseClock();
        g_info.overclocked = g_info.why == nullptr;
    }
}

}  // namespace

const ClockModeInfo &clockModeInfo() {
    return g_info;
}

// ---------------------------------------------------------------------------------
// Pre-init hook, after the SDK's clock setup.
//
// runtime_init() walks the sorted __preinit_array (laser_gate.cpp has the overview).
// The SDK sets the 150 MHz clocks at "00500" and releases the remaining peripheral
// resets at "00600"; the next SDK entries are "00650" and "01000". So "00700" runs with
// the clocks, GPIO and timer ticks up, and before C++ constructors, main(), the core's
// initVariant() (CYW43 on a Pico 2 W: it picks its SPI divider from clk_sys, and uses
// 4 at >= 250 MHz), USB, and setup(). Everything after it sees the final clock.
// ---------------------------------------------------------------------------------
extern "C" {
static void pidg_preinit_clock_mode(void) {
    clockModeBoot();
}
__attribute__((used, section(".preinit_array.00700")))
void (*const pidg_preinit_clock_mode_ptr)(void) = pidg_preinit_clock_mode;
}
