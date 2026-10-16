#include "sync_clock.h"

#include "hardware/clocks.h"
#include "hardware/gpio.h"
#include "hardware/structs/clocks.h"

bool SyncClock::begin(unsigned gpio) {
    // CLK_COUNT is no clock generator: it marks a pin without a clk_gpout function.
    const clock_handle_t gpout = GPIO_TO_GPOUT_CLOCK_HANDLE(gpio, CLK_COUNT);
    if (gpout == CLK_COUNT) {
        return false;
    }
    gpio_ = gpio;
    gpout_ = (unsigned)gpout;
    gpio_init(gpio_);  // SIO, output latch 0
    gpio_put(gpio_, false);
    gpio_set_dir(gpio_, GPIO_OUT);
    ready_ = true;
    return true;
}

void SyncClock::start(uint32_t div) {
    if (!ready_ || div == runningDiv_) {
        return;
    }
    clock_hw_t *const gen = &clocks_hw->clk[gpout_];
    // AUXSRC is not glitch-free, so it may only change while the generator is stopped.
    // If it runs (a restart, or a warm reset that kept the clock block, possibly with
    // another image's source and divider), stop it with ENABLE alone and wait until its
    // read-only ENABLED bit shows that the stop has taken effect. Bounded (150000 polls,
    // a few ms), so a generator whose source clock has stopped cannot hang the boot.
    if (gen->ctrl & CLOCKS_CLK_GPOUT0_CTRL_ENABLE_BITS) {
        hw_clear_bits(&gen->ctrl, CLOCKS_CLK_GPOUT0_CTRL_ENABLE_BITS);
        for (uint32_t guard = 150000; (gen->ctrl & CLOCKS_CLK_GPOUT0_CTRL_ENABLED_BITS) && guard; --guard) {
            tight_loop_contents();
        }
    }
    // Stopped: set the source and duty correction, then DIV (INT in bits 31:16, FRAC in
    // 15:0, the same layout as syncDiv), and only then start it.
    gen->ctrl = (CLOCKS_CLK_GPOUT0_CTRL_AUXSRC_VALUE_CLK_SYS << CLOCKS_CLK_GPOUT0_CTRL_AUXSRC_LSB) |
                CLOCKS_CLK_GPOUT0_CTRL_DC50_BITS;
    gen->div = div;
    hw_set_bits(&gen->ctrl, CLOCKS_CLK_GPOUT0_CTRL_ENABLE_BITS);
    gpio_set_function(gpio_, GPIO_FUNC_GPCK);
    runningDiv_ = div;
}
