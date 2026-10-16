// PiDG HSTX bench test. This is NOT the delay-generator firmware.
//
// Measures, on a bare Pico 2 / Pico 2 W and a scope, the step the RP2350 HSTX gives the
// laser pins: 3.333 ns (half a 150 MHz clk_hstx cycle) and, with the HSTX alone at
// 300 MHz, 1.667 ns. src/bench/README.md has the procedure; hstx_pattern.h the math.
//
// Pins: CH2 = GP12 (HSTX output 0), CH1 = GP13 (HSTX output 1), REF = GP11.
// MODE COUPLED (default): pio0 SM0-3 run the PiDG pulse program as the half-cycle lines
//   of CH1 and CH2 (coupledPlan()); HSTX coupled mode puts the P line on the pin in the
//   first half of each clk_sys cycle and the N line in the second half. pio1 SM0 drives
//   REF on GP11 directly and is enabled on the same clock cycle, so REF's edge against
//   CH1's shows the delay of the HSTX path. Needs clk_hstx = clk_sys (HSTXCLK 150).
//   KEEPALIVE 1 (default) feeds the HSTX FIFO with filler words, in case the coupled
//   output only updates while the shifter runs; KEEPALIVE 0 tests whether it must.
// MODE DMA: DMA plays a command list for the HSTX command expander that holds one
//   period (dmaRender()); no PIO. HSTXCLK 300 runs pll_sys at 300 MHz with clk_sys =
//   pll_sys / 2 = 150 MHz (CPU, flash, buses and PIO unchanged) and clk_hstx = pll_sys,
//   so only the HSTX runs above its 150 MHz rating.
//
// Bench only: no arming, no restart hold-off, no watchdog. Do not connect laser drivers.
// The laser pins boot LOW (laser_gate.cpp pre-init hook) and stay LOW until RUN.

#include <Arduino.h>
#include <cctype>
#include <cerrno>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <strings.h>
#include "../board.h"
#include "../laser_gate.h"
#include "../pio_pulse.h"
#include "../pulse_timing.h"
#include "hardware/clocks.h"
#include "hardware/dma.h"
#include "hardware/gpio.h"
#include "hardware/pio.h"
#include "hardware/pll.h"
#include "hardware/resets.h"
#include "hardware/structs/busctrl.h"
#include "hardware/structs/hstx_ctrl.h"
#include "hardware/structs/hstx_fifo.h"
#include "hstx_pattern.h"

#ifndef PIDG_FIRMWARE_VERSION
#define PIDG_FIRMWARE_VERSION "unknown"
#endif

namespace {

// ---------------------------------------------------------------- pins and resources
constexpr uint kHstxFirstPin = 12;  // HSTX output n drives GPIO 12 + n
static_assert(kPinCh2 >= kHstxFirstPin && kPinCh2 < kHstxFirstPin + 8 && kPinCh1 >= kHstxFirstPin &&
                  kPinCh1 < kHstxFirstPin + 8,
              "the laser pins must be HSTX pins (GP12-GP19)");
constexpr uint kPinRef = 11;  // not an HSTX pin: shows the direct PIO timing

// Coupled mode: pio0 outputs 12-19 form the PIO-to-HSTX bus, selected by BITx.SEL_P/SEL_N
// indices 24-31. Lines 14 and 15 stay internal: their pads are never routed to PIO.
constexpr uint kLineCh2P = 12;
constexpr uint kLineCh1P = 13;
constexpr uint kLineCh2N = 14;
constexpr uint kLineCh1N = 15;
static_assert(kLineCh1P == kLineCh2P + 1 && kLineCh1N == kLineCh2N + 1,
              "COMBINE drives each line pair with one 2-pin SET");
constexpr uint kCoupledSelBase = 24;
static_assert(4 * kDmaCyclesPerWord == 32, "DMA mode: 8 cycles of 4 bits fill one word");

PIO const kLinePio = pio0;  // the coupled PIO (CSR COUPLED_SEL)
PIO const kRefPio = pio1;   // the next PIO, so one CTRL write starts both
constexpr uint kSmCh1P = 0;
constexpr uint kSmCh1N = 1;
constexpr uint kSmCh2P = 2;
constexpr uint kSmCh2N = 3;
constexpr uint32_t kLineSmMask = 0xFu;
constexpr uint kSmRef = 0;

PulseChannel g_ch1p, g_ch1n, g_ch2p, g_ch2n, g_ref;
PulseChannel *const g_lines[] = {&g_ch1p, &g_ch1n, &g_ch2p, &g_ch2n};
PulseChannel *const g_refOnly[] = {&g_ref};

int g_dmaData = -1;  // streams a command list into the HSTX FIFO
int g_dmaCtrl = -1;  // restarts the data channel at the list start
const uint32_t *g_dmaListAddr = nullptr;  // read by the control channel
uint32_t g_list[kDmaListCap];             // DMA mode: one period
uint32_t g_keepAlive[2] = {kHstxCmdRawRepeat | kHstxCmdMaxCount, 0};  // coupled mode filler

bool g_hwOk = false;
uint32_t g_hstxMhz = 150;  // 150: clk_hstx = clk_sys; 300: clk_hstx = pll_sys, clk_sys = pll_sys / 2

// ---------------------------------------------------------------- settings
enum class Mode : uint8_t { Coupled, Dma };

struct Settings {
    Mode mode = Mode::Coupled;
    uint32_t freqHz = 1000;
    uint32_t widthSteps = 30;    // 100 ns at 3.333 ns per step
    uint32_t delaySteps = 3000;  // 10 us
    bool combine = false;
    uint32_t refCycles = 15;     // REF width, clk_sys cycles (100 ns)
    bool keepAlive = true;
};

struct Plan {
    uint32_t periodCycles = 0;  // coupled mode
    CoupledPlan lines{};
    PulseCycles ref{};
    BenchPulses dma{};          // DMA mode
    size_t listLen = 0;
};

Settings g_set;
bool g_running = false;
uint32_t g_emptySeen = 0;  // loop() saw the HSTX FIFO empty while it should be fed
uint32_t g_wofSeen = 0;    // the FIFO was written while full (WOF)

struct Sweep {
    bool on = false;
    uint32_t from = 0, to = 0, everyMs = 0, nextMs = 0;
} g_sweep;

// ---------------------------------------------------------------- output helpers
void out(const char *fmt, ...) {
    char buf[200];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    Serial.print(buf);
    Serial.print("\r\n");
}

// Duration of `steps` in ns, 3 decimals. A step is half a clk_hstx cycle.
const char *stepsNs(uint32_t steps, char *buf, size_t len) {
    pulseFormatFixed3((uint64_t)steps * 1000000000ULL, 2ULL * clock_get_hz(clk_hstx), buf, len);
    return buf;
}

const char *cyclesNs(uint32_t cycles, char *buf, size_t len) {
    pulseFormatNs(cycles, clock_get_hz(clk_sys), buf, len);
    return buf;
}

// ---------------------------------------------------------------- clocks
// 150: the SDK default. pll_sys 150 MHz (VCO 1500 / 5 / 2), clk_sys = clk_hstx = pll_sys.
// 300: pll_sys 300 MHz (VCO 1500 / 5 / 1), clk_sys = pll_sys / 2 = 150 MHz,
//      clk_hstx = pll_sys = 300 MHz. Only call while stopped.
void setHstxClock(uint32_t mhz) {
    const bool fast = mhz == 300;
    // As the SDK's set_sys_clock_pll(): run clk_sys from pll_usb (48 MHz) while pll_sys
    // re-locks. USB has its own PLL; the timer and watchdog ticks come from clk_ref.
    clock_configure_undivided(clk_sys, CLOCKS_CLK_SYS_CTRL_SRC_VALUE_CLKSRC_CLK_SYS_AUX,
                              CLOCKS_CLK_SYS_CTRL_AUXSRC_VALUE_CLKSRC_PLL_USB, USB_CLK_HZ);
    pll_init(pll_sys, 1, 1500 * MHZ, 5, fast ? 1 : 2);
    clock_configure_int_divider(clk_sys, CLOCKS_CLK_SYS_CTRL_SRC_VALUE_CLKSRC_CLK_SYS_AUX,
                                CLOCKS_CLK_SYS_CTRL_AUXSRC_VALUE_CLKSRC_PLL_SYS, (fast ? 300 : 150) * MHZ,
                                fast ? 2 : 1);
    clock_configure_undivided(clk_peri, 0, CLOCKS_CLK_PERI_CTRL_AUXSRC_VALUE_CLK_SYS, 150 * MHZ);
    clock_configure_undivided(clk_hstx, 0,
                              fast ? CLOCKS_CLK_HSTX_CTRL_AUXSRC_VALUE_CLKSRC_PLL_SYS
                                   : CLOCKS_CLK_HSTX_CTRL_AUXSRC_VALUE_CLK_SYS,
                              (fast ? 300 : 150) * MHZ);
    g_hstxMhz = mhz;
}

// ---------------------------------------------------------------- DMA
// The data channel streams `list` into the HSTX FIFO, paced by the FIFO's DREQ, then
// chains to the control channel. That writes the list address into the data channel's
// read-address trigger register, which restarts it with the same count: the list
// repeats without the CPU.
void dmaPlay(const uint32_t *list, uint32_t count) {
    g_dmaListAddr = list;
    dma_channel_config c = dma_channel_get_default_config((uint)g_dmaCtrl);
    channel_config_set_transfer_data_size(&c, DMA_SIZE_32);
    channel_config_set_read_increment(&c, false);
    channel_config_set_write_increment(&c, false);
    channel_config_set_high_priority(&c, true);
    dma_channel_configure((uint)g_dmaCtrl, &c, &dma_hw->ch[g_dmaData].al3_read_addr_trig, &g_dmaListAddr, 1, false);

    dma_channel_config d = dma_channel_get_default_config((uint)g_dmaData);
    channel_config_set_transfer_data_size(&d, DMA_SIZE_32);
    channel_config_set_read_increment(&d, true);
    channel_config_set_write_increment(&d, false);
    channel_config_set_dreq(&d, DREQ_HSTX);
    channel_config_set_chain_to(&d, (uint)g_dmaCtrl);
    channel_config_set_high_priority(&d, true);
    dma_channel_configure((uint)g_dmaData, &d, &hstx_fifo_hw->fifo, list, count, true);
}

void dmaStop() {
    const uint32_t mask = 1u << g_dmaData | 1u << g_dmaCtrl;
    // Disable both first, so a channel that finishes now cannot trigger the other.
    hw_clear_bits(&dma_hw->ch[g_dmaData].al1_ctrl, DMA_CH0_CTRL_TRIG_EN_BITS);
    hw_clear_bits(&dma_hw->ch[g_dmaCtrl].al1_ctrl, DMA_CH0_CTRL_TRIG_EN_BITS);
    dma_hw->abort = mask;
    while (dma_hw->abort & mask) {
        tight_loop_contents();
    }
}

// ---------------------------------------------------------------- HSTX
// A block reset clears the FIFO, the command expander and the shifter, so every start
// begins at the first word of the list.
void hstxReset() {
    reset_unreset_block_num_wait_blocking(RESET_HSTX);
}

uint32_t hstxBitSel(uint firstHalf, uint secondHalf) {
    return firstHalf << HSTX_CTRL_BIT0_SEL_P_LSB | secondHalf << HSTX_CTRL_BIT0_SEL_N_LSB;
}

// Configures the HSTX and leaves it halted (CSR EN = 0); hstxEnable() starts it.
void hstxConfigure(bool coupled) {
    hstxReset();
    // Each raw data word goes to the output shifter whole (as in the pico-examples DVI code).
    hstx_ctrl_hw->expand_shift = 1u << HSTX_CTRL_EXPAND_SHIFT_RAW_N_SHIFTS_LSB | 0u << HSTX_CTRL_EXPAND_SHIFT_RAW_SHIFT_LSB;
    if (coupled) {
        hstx_ctrl_hw->bit[kPinCh2 - kHstxFirstPin] = hstxBitSel(kCoupledSelBase + kLineCh2P - kHstxFirstPin,
                                                               kCoupledSelBase + kLineCh2N - kHstxFirstPin);
        hstx_ctrl_hw->bit[kPinCh1 - kHstxFirstPin] = hstxBitSel(kCoupledSelBase + kLineCh1P - kHstxFirstPin,
                                                               kCoupledSelBase + kLineCh1N - kHstxFirstPin);
        // The shifter data is unused (filler words): N_SHIFTS 0 = 32 cycles per word.
        hstx_ctrl_hw->csr = HSTX_CTRL_CSR_EXPAND_EN_BITS | HSTX_CTRL_CSR_COUPLED_MODE_BITS |
                            pio_get_index(kLinePio) << HSTX_CTRL_CSR_COUPLED_SEL_LSB |
                            0u << HSTX_CTRL_CSR_N_SHIFTS_LSB | 0u << HSTX_CTRL_CSR_SHIFT_LSB;
    } else {
        hstx_ctrl_hw->bit[kPinCh2 - kHstxFirstPin] = hstxBitSel(kDmaBitCh2P, kDmaBitCh2N);
        hstx_ctrl_hw->bit[kPinCh1 - kHstxFirstPin] = hstxBitSel(kDmaBitCh1P, kDmaBitCh1N);
        hstx_ctrl_hw->csr = HSTX_CTRL_CSR_EXPAND_EN_BITS | kDmaCyclesPerWord << HSTX_CTRL_CSR_N_SHIFTS_LSB |
                            4u << HSTX_CTRL_CSR_SHIFT_LSB;
    }
}

void hstxEnable() {
    hw_set_bits(&hstx_ctrl_hw->csr, HSTX_CTRL_CSR_EN_BITS);  // EXPAND_EN is already set: allowed
}

// ---------------------------------------------------------------- start / stop
void stopAll() {
    laser::gateClose();  // pads LOW first: a pulse in flight is cut short, never stretched
    g_running = false;
    if (!g_hwOk) {
        return;  // nothing was claimed or started
    }
    stopPulseChannelsLow(g_lines, 4);
    stopPulseChannelsLow(g_refOnly, 1);
    dmaStop();
    hstxReset();
}

// Checks `s` without touching the hardware; fills *pl. Returns nullptr or the reason.
const char *makePlan(const Settings &s, Plan *pl) {
    if (s.freqHz == 0) {
        return "FREQ must be > 0";
    }
    if (s.mode == Mode::Coupled) {
        if (g_hstxMhz != 150) {
            return "COUPLED mode needs HSTXCLK 150 (clk_hstx must be clk_sys)";
        }
        const uint64_t c = pulseHzToCycles(s.freqHz, clock_get_hz(clk_sys));
        if (c == 0 || c > 0xFFFFFFFFULL) {
            return "FREQ out of range";
        }
        if (const char *why = coupledPlan((uint32_t)c, s.widthSteps, s.delaySteps, s.combine, &pl->lines)) {
            return why;
        }
        pl->ref = PulseCycles{(uint32_t)c, 0, s.refCycles};
        if (computePulseCounts(pl->ref, nullptr) != PulseFit::Ok) {
            return "REFWIDTH must be >= 3 cycles and <= period - 5 cycles";
        }
        pl->periodCycles = (uint32_t)c;
        return nullptr;
    }
    // DMA mode: the nearest whole number of 16-step words per period.
    const uint64_t stepsPerSecond = 2ULL * clock_get_hz(clk_hstx);
    const uint64_t words = (stepsPerSecond + 8ULL * s.freqHz) / (16ULL * s.freqHz);
    if (words == 0 || words * kDmaStepsPerWord > 0xFFFFFFFFULL) {
        return "FREQ out of range";
    }
    pl->dma = BenchPulses{(uint32_t)(words * kDmaStepsPerWord), s.widthSteps, s.delaySteps, s.combine};
    if (const char *why = dmaCheck(pl->dma)) {
        return why;
    }
    pl->listLen = dmaRender(pl->dma, nullptr, 0);
    if (pl->listLen > kDmaListCap) {
        return "the period needs more DMA list entries than the buffer holds: raise FREQ";
    }
    return nullptr;
}

const char *startCoupled(const Plan &pl) {
    hstxConfigure(true);
    if (g_set.keepAlive) {
        dmaPlay(g_keepAlive, 2);
    }
    hstxEnable();
    // Line SMs: split mode drives one line each; COMBINE drives both pins' line of the
    // same half with each SM (last write wins, as in the firmware's COMBINE mode).
    const uint pair = g_set.combine ? 2u : 1u;
    const bool loaded = g_ch1p.setOutputs(g_set.combine ? kLineCh2P : kLineCh1P, pair) &&
                        g_ch2p.setOutputs(kLineCh2P, pair) &&
                        g_ch1n.setOutputs(g_set.combine ? kLineCh2N : kLineCh1N, pair) &&
                        g_ch2n.setOutputs(kLineCh2N, pair) && g_ch1p.configure(pl.lines.ch1p) &&
                        g_ch1n.configure(pl.lines.ch1n) && g_ch2p.configure(pl.lines.ch2p) &&
                        g_ch2n.configure(pl.lines.ch2n) && g_ref.configure(pl.ref);
    if (!loaded) {
        stopAll();
        return "PIO load failed";
    }
    gpio_set_function(kPinCh2, GPIO_FUNC_HSTX);  // the PIO lines are LOW: no edge
    gpio_set_function(kPinCh1, GPIO_FUNC_HSTX);
    // pio0 SM0-3 and pio1 SM0 start on the same clk_sys cycle.
    pio_enable_sm_multi_mask_in_sync(kLinePio, 0, kLineSmMask, 1u << kSmRef);
    return nullptr;
}

const char *startDma(const Plan &pl) {
    const size_t n = dmaRender(pl.dma, g_list, kDmaListCap);
    if (n == 0) {
        return "DMA list render failed";
    }
    hstxConfigure(false);
    dmaPlay(g_list, (uint32_t)n);  // fills the FIFO while the HSTX is halted
    gpio_set_function(kPinCh2, GPIO_FUNC_HSTX);  // the halted shifter outputs LOW
    gpio_set_function(kPinCh1, GPIO_FUNC_HSTX);
    hstxEnable();  // the list starts with step 0 of a period: CH1 rises now
    return nullptr;
}

// (Re)starts the outputs with g_set. On failure everything stays stopped.
const char *start() {
    if (!g_hwOk) {
        return "hardware setup failed at boot";
    }
    Plan pl;
    if (const char *why = makePlan(g_set, &pl)) {
        return why;
    }
    stopAll();
    g_emptySeen = 0;
    g_wofSeen = 0;
    hstx_fifo_hw->stat = HSTX_FIFO_STAT_WOF_BITS;
    const char *why = g_set.mode == Mode::Coupled ? startCoupled(pl) : startDma(pl);
    if (why) {
        stopAll();
        return why;
    }
    g_running = true;
    return nullptr;
}

// Takes a new setting: checked first, then applied (with a restart if running).
const char *apply(const Settings &s) {
    Plan pl;
    if (const char *why = makePlan(s, &pl)) {
        return why;
    }
    g_set = s;
    return g_running ? start() : nullptr;
}

// ---------------------------------------------------------------- status
void printStatus() {
    char a[32];
    Plan pl;
    const char *planWhy = makePlan(g_set, &pl);
    out("MODE=%s", g_set.mode == Mode::Coupled ? "COUPLED" : "DMA");
    out("RUN=%d", g_running ? 1 : 0);
    out("CLK_SYS=%lu", (unsigned long)clock_get_hz(clk_sys));
    out("CLK_HSTX=%lu (HSTXCLK %lu, step %s ns)", (unsigned long)clock_get_hz(clk_hstx), (unsigned long)g_hstxMhz,
        stepsNs(1, a, sizeof(a)));
    if (planWhy) {
        out("FREQ=%lu (not realizable: %s)", (unsigned long)g_set.freqHz, planWhy);
    } else if (g_set.mode == Mode::Coupled) {
        pulseFormatHz(pl.periodCycles, clock_get_hz(clk_sys), a, sizeof(a));
        out("FREQ=%lu (actual %s Hz, period %lu cycles = %lu steps)", (unsigned long)g_set.freqHz, a,
            (unsigned long)pl.periodCycles, (unsigned long)(2ULL * pl.periodCycles));
    } else {
        pulseFormatFixed3(2ULL * clock_get_hz(clk_hstx), pl.dma.periodSteps, a, sizeof(a));
        out("FREQ=%lu (actual %s Hz, period %lu steps = %lu words)", (unsigned long)g_set.freqHz, a,
            (unsigned long)pl.dma.periodSteps, (unsigned long)(pl.dma.periodSteps / kDmaStepsPerWord));
    }
    out("WIDTH=%lu steps (%s ns)", (unsigned long)g_set.widthSteps, stepsNs(g_set.widthSteps, a, sizeof(a)));
    out("DELAY=%lu steps (%s ns)", (unsigned long)g_set.delaySteps, stepsNs(g_set.delaySteps, a, sizeof(a)));
    out("COMBINE=%d", g_set.combine ? 1 : 0);
    if (g_set.mode == Mode::Coupled) {
        out("REFWIDTH=%lu cycles (%s ns)", (unsigned long)g_set.refCycles, cyclesNs(g_set.refCycles, a, sizeof(a)));
        out("KEEPALIVE=%d", g_set.keepAlive ? 1 : 0);
        if (!planWhy) {
            const CoupledPlan &l = pl.lines;
            out("LINES=CH1 P %lu+%lu N %lu+%lu, CH2 P %lu+%lu N %lu+%lu (start+width, cycles)",
                (unsigned long)l.ch1p.delay, (unsigned long)l.ch1p.width, (unsigned long)l.ch1n.delay,
                (unsigned long)l.ch1n.width, (unsigned long)l.ch2p.delay, (unsigned long)l.ch2p.width,
                (unsigned long)l.ch2n.delay, (unsigned long)l.ch2n.width);
        }
    } else if (!planWhy) {
        out("LIST=%lu entries of %lu", (unsigned long)pl.listLen, (unsigned long)kDmaListCap);
    }
    if (g_sweep.on) {
        out("SWEEP=DELAY %lu..%lu every %lu ms", (unsigned long)g_sweep.from, (unsigned long)g_sweep.to,
            (unsigned long)g_sweep.everyMs);
    } else {
        out("SWEEP=OFF");
    }
    out("FIFO_EMPTY_SEEN=%lu", (unsigned long)g_emptySeen);
    out("FIFO_WOF=%lu", (unsigned long)g_wofSeen);
}

void printHelp() {
    out("PiDG HSTX bench. Times in steps: 1 step = half a clk_hstx cycle (3.333 ns at 150 MHz).");
    out("RUN | STOP                start / stop the outputs (CH1 GP13, CH2 GP12, REF GP11)");
    out("MODE COUPLED|DMA          COUPLED: PIO lines through HSTX coupled mode; DMA: command list");
    out("HSTXCLK 150|300           clk_hstx (300: DMA mode only, clk_sys stays 150 MHz); STOP first");
    out("FREQ <Hz>                 pulse-pair rate (DMA mode: period rounds to 16 steps)");
    out("WIDTH <steps>             pulse width (COUPLED: >= 6 steps)");
    out("DELAY <steps>             CH2 rising edge after CH1 rising edge");
    out("COMBINE 0|1               1 = both pulses on both pins");
    out("REFWIDTH <cycles>         REF pulse width on GP11 (COUPLED mode)");
    out("KEEPALIVE 0|1             COUPLED: feed the HSTX FIFO with filler words (default 1)");
    out("SWEEP <from> <to> <ms>    step DELAY by 1 every <ms>, from..to, repeating; SWEEP OFF");
    out("STATUS | HELP");
    out("Bench only: no arming, no hold-off, no watchdog. Do not connect laser drivers.");
}

// ---------------------------------------------------------------- commands
bool parseU32(const char *s, uint32_t *v) {
    if (!s || !isdigit((unsigned char)s[0])) {
        return false;
    }
    char *end = nullptr;
    errno = 0;
    const unsigned long x = strtoul(s, &end, 10);
    if (*end != '\0' || errno == ERANGE || x > 0xFFFFFFFFUL) {
        return false;
    }
    *v = (uint32_t)x;
    return true;
}

void replyApply(const char *name, const Settings &cand) {
    if (const char *why = apply(cand)) {
        out("ERR %s: %s", name, why);
    } else {
        out("OK %s", name);
    }
}

void dispatch(char *line) {
    char *cmd = strtok(line, " \t");
    if (!cmd) {
        return;
    }
    char *arg = strtok(nullptr, " \t");
    char *arg2 = strtok(nullptr, " \t");
    char *arg3 = strtok(nullptr, " \t");
    uint32_t v = 0;
    Settings cand = g_set;

    if (!strcasecmp(cmd, "HELP")) {
        printHelp();
    } else if (!strcasecmp(cmd, "STATUS")) {
        printStatus();
    } else if (!strcasecmp(cmd, "RUN")) {
        const char *why = start();
        out(why ? "ERR RUN: %s" : "OK RUN", why);
    } else if (!strcasecmp(cmd, "STOP")) {
        stopAll();
        g_sweep.on = false;
        out("OK STOP");
    } else if (!strcasecmp(cmd, "MODE") && arg && (!strcasecmp(arg, "COUPLED") || !strcasecmp(arg, "DMA"))) {
        cand.mode = !strcasecmp(arg, "DMA") ? Mode::Dma : Mode::Coupled;
        replyApply("MODE", cand);
    } else if (!strcasecmp(cmd, "HSTXCLK") && parseU32(arg, &v) && (v == 150 || v == 300)) {
        if (g_running) {
            out("ERR HSTXCLK: STOP first");
            return;
        }
        setHstxClock(v);
        Plan pl;
        const char *why = makePlan(g_set, &pl);
        out(why ? "OK HSTXCLK (note: current settings not realizable: %s)" : "OK HSTXCLK", why);
    } else if (!strcasecmp(cmd, "FREQ") && parseU32(arg, &v)) {
        cand.freqHz = v;
        replyApply("FREQ", cand);
    } else if (!strcasecmp(cmd, "WIDTH") && parseU32(arg, &v)) {
        cand.widthSteps = v;
        replyApply("WIDTH", cand);
    } else if (!strcasecmp(cmd, "DELAY") && parseU32(arg, &v)) {
        cand.delaySteps = v;
        replyApply("DELAY", cand);
    } else if (!strcasecmp(cmd, "COMBINE") && parseU32(arg, &v) && v <= 1) {
        cand.combine = v == 1;
        replyApply("COMBINE", cand);
    } else if (!strcasecmp(cmd, "REFWIDTH") && parseU32(arg, &v)) {
        cand.refCycles = v;
        replyApply("REFWIDTH", cand);
    } else if (!strcasecmp(cmd, "KEEPALIVE") && parseU32(arg, &v) && v <= 1) {
        cand.keepAlive = v == 1;
        replyApply("KEEPALIVE", cand);
    } else if (!strcasecmp(cmd, "SWEEP") && arg && !strcasecmp(arg, "OFF")) {
        g_sweep.on = false;
        out("OK SWEEP OFF");
    } else if (!strcasecmp(cmd, "SWEEP")) {
        uint32_t from = 0, to = 0, ms = 0;
        if (!parseU32(arg, &from) || !parseU32(arg2, &to) || !parseU32(arg3, &ms) || from > to || ms < 10) {
            out("ERR SWEEP: SWEEP <from> <to> <ms>, from <= to, ms >= 10");
            return;
        }
        // The rules on DELAY are intervals, so both ends valid means every step is.
        Plan pl;
        Settings end = g_set;
        end.delaySteps = to;
        const char *whyTo = makePlan(end, &pl);
        cand.delaySteps = from;
        if (whyTo || makePlan(cand, &pl)) {
            out("ERR SWEEP: %s", whyTo ? whyTo : "the start value is not realizable");
            return;
        }
        g_sweep = Sweep{true, from, to, ms, millis() + ms};
        replyApply("SWEEP", cand);
        if (!g_running) {
            out("(SWEEP steps while running: send RUN)");
        }
    } else {
        out("ERR unknown command or bad value: %s (HELP lists the commands)", cmd);
    }
}

void feedChar(char c) {
    static char line[96];
    static size_t len = 0;
    if (c == '\r' || c == '\n') {
        line[len] = '\0';
        if (len > 0) {
            dispatch(line);
        }
        len = 0;
    } else if (len + 1 < sizeof(line)) {
        line[len++] = c;
    }
}

void serviceSweep() {
    if (!g_sweep.on || !g_running || (int32_t)(millis() - g_sweep.nextMs) < 0) {
        return;
    }
    g_sweep.nextMs = millis() + g_sweep.everyMs;
    Settings cand = g_set;
    cand.delaySteps = (g_set.delaySteps >= g_sweep.to || g_set.delaySteps < g_sweep.from) ? g_sweep.from
                                                                                             : g_set.delaySteps + 1;
    if (const char *why = apply(cand)) {
        g_sweep.on = false;
        out("ERR SWEEP stopped: %s", why);
        return;
    }
    char a[32];
    out("DELAY=%lu steps (%s ns)", (unsigned long)g_set.delaySteps, stepsNs(g_set.delaySteps, a, sizeof(a)));
}

// While the FIFO should be fed (DMA mode, or coupled mode with KEEPALIVE 1), an empty
// FIFO means the DMA fell behind and the output timing slipped. This is a spot check
// once per loop(), not a guarantee: the hardware has no underflow flag.
void monitorFifo() {
    if (!g_running || (g_set.mode == Mode::Coupled && !g_set.keepAlive)) {
        return;
    }
    const uint32_t st = hstx_fifo_hw->stat;
    if (st & HSTX_FIFO_STAT_EMPTY_BITS) {
        ++g_emptySeen;
    }
    if (st & HSTX_FIFO_STAT_WOF_BITS) {
        ++g_wofSeen;
        hstx_fifo_hw->stat = HSTX_FIFO_STAT_WOF_BITS;
    }
}

bool claimHardware() {
    for (uint sm = 0; sm < 4; ++sm) {
        if (pio_sm_is_claimed(kLinePio, sm)) {
            return false;
        }
    }
    if (pio_sm_is_claimed(kRefPio, kSmRef) || pio_get_index(kRefPio) != pio_get_index(kLinePio) + 1) {
        return false;
    }
    pio_claim_sm_mask(kLinePio, kLineSmMask);
    pio_claim_sm_mask(kRefPio, 1u << kSmRef);
    g_dmaData = dma_claim_unused_channel(false);
    g_dmaCtrl = dma_claim_unused_channel(false);
    return g_dmaData >= 0 && g_dmaCtrl >= 0;
}

}  // namespace

void setup() {
    laser::gateClose();  // already LOW from the pre-init hook; re-asserted
    for (uint pin : {kPinRef, kPinCh2, kPinCh1}) {
        gpio_set_slew_rate(pin, GPIO_SLEW_RATE_FAST);  // fast edges for the scope
        gpio_set_drive_strength(pin, GPIO_DRIVE_STRENGTH_8MA);
    }
    // The line SMs only feed the PIO-to-HSTX bus, so their pins are not routed (false).
    g_hwOk = claimHardware() && g_ch1p.begin(kLinePio, kSmCh1P, kLineCh1P, false) &&
             g_ch1n.begin(kLinePio, kSmCh1N, kLineCh1N, false) && g_ch2p.begin(kLinePio, kSmCh2P, kLineCh2P, false) &&
             g_ch2n.begin(kLinePio, kSmCh2N, kLineCh2N, false) && pulseReserveDualProgram(kLinePio) &&
             g_ref.begin(kRefPio, kSmRef, kPinRef, true);
    // DMA reads and writes win bus arbitration, so the HSTX FIFO is refilled promptly.
    busctrl_hw->priority = BUSCTRL_BUS_PRIORITY_DMA_W_BITS | BUSCTRL_BUS_PRIORITY_DMA_R_BITS;
    if (g_hwOk) {
        hstxReset();
    }

    Serial.begin(115200);
    const unsigned long t0 = millis();
    while (!Serial && millis() - t0 < 1500) {
    }
    out("PiDG HSTX bench, firmware " PIDG_FIRMWARE_VERSION ". Bench test only: no arming, no hold-off, no watchdog;");
    out("do not connect laser drivers. Outputs stopped. Type HELP.");
    if (!g_hwOk) {
        out("ERR hardware setup failed (PIO state machine or DMA channel not available)");
    }
}

void loop() {
    for (int c; (c = Serial.read()) >= 0;) {
        feedChar((char)c);
    }
    monitorFifo();
    serviceSweep();
}
