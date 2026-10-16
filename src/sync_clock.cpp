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
    // If it runs (a restart, or a warm reset that kept the clock block), stop it with
    // ENABLE alone and wait 3 of its output cycles for the stop to take effect, as the
    // SDK's clock_configure() does. DIV INT 0 divides by 65536.
    if (gen->ctrl & CLOCKS_CLK_GPOUT0_CTRL_ENABLE_BITS) {
        const uint32_t divInt = gen->div >> CLOCKS_CLK_GPOUT0_DIV_INT_LSB;
        hw_clear_bits(&gen->ctrl, CLOCKS_CLK_GPOUT0_CTRL_ENABLE_BITS);
        busy_wait_at_least_cycles(3u * ((divInt ? divInt : 0x10000u) + 1u));
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
