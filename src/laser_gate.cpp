#include "laser_gate.h"

#include "board.h"
#include "hardware/gpio.h"
#include "hardware/structs/sio.h"
#include "hardware/sync.h"

namespace laser {
namespace {
// Zeroed by crt0 (.bss clear) before runtime_init() runs the pre-init hook below.
volatile bool g_open = false;
constexpr uint kPins[] = {kPinCh1, kPinCh2};
}  // namespace

void gateClose() {
    const uint32_t irq = save_and_disable_interrupts();  // close both pads together
    // (1) Stage the SIO side first: level LOW, output enabled. This is invisible at
    //     the pad until FUNCSEL selects SIO.
    sio_hw->gpio_clr = kLaserPinMask;
    sio_hw->gpio_oe_set = kLaserPinMask;

    // (2) Per pin: keep the pad pull-down (the PADS reset default, and it agrees with
    //     R17/R18 on the board), then gpio_set_function(SIO). In the installed SDK
    //     (hardware_gpio/gpio.c) that writes PADS IE=1/OD=0, then IO_BANK0 CTRL =
    //     FUNCSEL (clearing every override), and clears PADS ISO last. So the pad
    //     moves straight from its current state (reset, isolated or PIO) to "driven
    //     LOW". No step ever presents OUT=1.
    for (uint pin : kPins) {
        gpio_set_pulls(pin, false, true);
        gpio_set_function(pin, GPIO_FUNC_SIO);
    }
    g_open = false;
    restore_interrupts(irq);
}

void gateOpen(PIO pio, uint anySm) {
    // PIO keeps one output-level register per GPIO (RP2350 datasheet 11.5.6). Disabling
    // a state machine does not clear it, so a laser pin could still be HIGH there from
    // a pulse cut short earlier. Force both levels LOW and set them as outputs, then
    // switch FUNCSEL. (pio_sm_set_pins_with_mask() uses SM exec, which runs even on a
    // disabled SM, and restores that SM's PINCTRL afterwards.)
    pio_sm_set_pins_with_mask(pio, anySm, 0, kLaserPinMask);
    pio_sm_set_pindirs_with_mask(pio, anySm, kLaserPinMask, kLaserPinMask);
    for (uint pin : kPins) {
        pio_gpio_init(pio, pin);  // == gpio_set_function(pin, PIOx); ISO is already clear
    }
    g_open = true;
}

bool gateIsOpen() {
    return g_open;
}

}  // namespace laser

// ---------------------------------------------------------------------------------
// Earliest hook in the application image.
//
// runtime_init() (called from crt0, before main()) walks the SDK's sorted
// __preinit_array. The SDK's runtime_init_early_resets sits at priority "00100": it
// resets and releases IO_BANK0, PADS_BANK0 and PIO0. The next SDK entry is "00101"
// (USB power-down), then "00200" and up, with clocks at "00500". Priority "00110"
// therefore runs right after the peripheral reset, and before clock setup, C++
// constructors, main(), initVariant() (CYW43 on a Pico 2 W), USB, and setup(). Only
// raw SIO/IO_BANK0/PADS register writes happen here: no timers, heap, or Serial.
//
// The laser pads are already LOW at this point after any watchdog/PSM reset (the
// peripheral resets leave them undriven with a pull-down, plus R17/R18). The hook
// shortens the window in the one case that is not: a processor-only warm reset
// (SYSRESETREQ, e.g. some debugger "reset" commands), where the bootrom latches the
// pads through ISO until the application releases them.
//
// A pointer to a function is a constant initializer in C++, so this is emitted as
// static data in .preinit_array.00110. It is not a dynamic initializer.
// ---------------------------------------------------------------------------------
extern "C" {
static void pidg_preinit_laser_gate_close(void) {
    laser::gateClose();
}
__attribute__((used, section(".preinit_array.00110")))
void (*const pidg_preinit_laser_gate_close_ptr)(void) = pidg_preinit_laser_gate_close;
}
