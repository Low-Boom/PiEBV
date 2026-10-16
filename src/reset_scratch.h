#pragma once
// Watchdog SCRATCH registers used by the firmware. They survive the watchdog's PSM reset
// and are cleared by POR/BOR/RUN. The SDK uses SCRATCH4-7 and the bootrom SCRATCH2-3.
//
// SCRATCH0 counts watchdog timeouts since the last POR/BOR/RUN; it is valid only while
// SCRATCH1 holds kWdtCountMagic. main.cpp (captureResetInfo()) keeps the count and shows
// it as WDT_RESETS; clock_mode.cpp reads it to keep the clock at 150 MHz after a timeout.

#include <cstdint>

constexpr unsigned kWdtCountScratch = 0;
constexpr unsigned kWdtCountMagicScratch = 1;
constexpr uint32_t kWdtCountMagic = 0x50494447;  // 'PIDG'
