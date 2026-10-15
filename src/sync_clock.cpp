#include "sync_clock.h"

#include "hardware/clocks.h"
#include "hardware/gpio.h"
#include "hardware/structs/clocks.h"

namespace {

// clk_gpout index for an RP2350 GPIO, or -1 if the pin has no clock-output function
// (RP2350 datasheet, GPIO function table: F9 = CLOCK GPOUT).
int gpoutForGpio(unsigned gpio) {
    switch (gpio) {
        case 13:
        case 21:
            return 0;
        case 15:
        case 23:
            return 1;
        case 24:
            return 2;
        case 25:
            return 3;
        default:
            return -1;
    }
}

}  // namespace

bool SyncClock::begin(unsigned gpio) {
    const int gpout = gpoutForGpio(gpio);
    if (gpout < 0) {
        return false;
    }
    gpio_ = gpio;
    gpout_ = (unsigned)gpout;
    gpio_init(gpio_);  // SIO, output latch 0
    gpio_put(gpio_, false);
    gpio_set_dir(gpio_, GPIO_OUT);
    return true;
}

void SyncClock::start(uint32_t div) {
    clock_hw_t *const gen = &clocks_hw->clk[clk_gpout0 + gpout_];
    // ENABLE starts and stops the generator cleanly; the aux source is only switched
    // while it is stopped. DIV: INT in bits 31:16, FRAC in 15:0 (same layout as syncDiv).
    gen->ctrl = 0;
    gen->div = div;
    gen->ctrl = (CLOCKS_CLK_GPOUT0_CTRL_AUXSRC_VALUE_CLK_SYS << CLOCKS_CLK_GPOUT0_CTRL_AUXSRC_LSB) |
                CLOCKS_CLK_GPOUT0_CTRL_DC50_BITS | CLOCKS_CLK_GPOUT0_CTRL_ENABLE_BITS;
    gpio_set_function(gpio_, GPIO_FUNC_GPCK);
}
