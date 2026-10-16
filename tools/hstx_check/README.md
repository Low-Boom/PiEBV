# Host check for the HSTX bench test

`hstx_check.cpp` tests `src/bench/hstx_pattern.h`, the pattern math of the HSTX bench test
(`src/bench/hstx_bench.cpp`). Run it after any change to that header.

| Part | What it checks |
|---|---|
| DMA mode | Every command list the bench would send is decoded with a model of the HSTX command expander and output shifter as the bench sets them up (`RAW n`: n data words follow; `RAW_REPEAT n`: the next word is used n times; one word = 8 clk_hstx cycles, lowest nibble first; per pin, `SEL_P` = first half of a cycle, `SEL_N` = second half). Both pins are compared step by step with an independent model of the ideal waveform. Long repeated stretches are checked run by run, so periods up to 1 s are covered. It also checks that any 8 consecutive FIFO entries cover at least 32 HSTX cycles, so the DMA stays ahead, and that a 1 Hz period fits the bench's list buffer. |
| Coupled mode | Each pin is rebuilt from its P and N lines (first and second half of each clk_sys cycle) and compared step by step with the ideal waveform. Every accept/reject decision is compared with an independent model of the rules. |

The model follows the RP2350 HSTX register descriptions in the Pico SDK and Raspberry Pi's
`pico-examples` DVI code. The bench test measures whether the hardware behaves the same.

## Running

Any C++17 compiler works:

```
cd tools/hstx_check
g++ -std=c++17 -O2 -Wall -Wextra -o hstx_check hstx_check.cpp
./hstx_check
```

Expected output:

```
1 Hz at clk_hstx 150 MHz: 9167 list entries of 20480
1 Hz at clk_hstx 300 MHz: 18325 list entries of 20480
dma: 67948 configurations, worst 8-entry window 40 cycles
coupled: 203760 configurations
all checks passed (0 failures)
```
