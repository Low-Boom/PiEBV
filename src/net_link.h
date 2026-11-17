#pragma once
// Network link of the PiEBV firmware: the Pico 2 W's radio as a Wi-Fi station on an
// existing network, and a TCP server (tcp_link.h) that carries the command protocol
// (protocol.h) for one host at a time on port kNetPort. The image for a plain Pico 2
// has none of this (net::kAvailable is false, and every function here does nothing).
//
// The command loop must not be held up, because DISARM and the watchdog feed depend on
// it. What the link does about that:
//   * The core's own WiFi.begin() and WiFi.beginNoBlock() wait inside the join, so the
//     link does not use them. It starts the join through the same CYW43 driver and then
//     only polls (service()).
//   * The long call is the radio chip's power-up (it loads the chip's firmware), in
//     start() and in set(): the caller makes these calls only while DISARMED and with a
//     longer watchdog period (main.cpp). The chip is powered off whenever the link is
//     off, so every start is the same power-up, also after a fault.
//   * Replies to the TCP host never wait for the host inside lwIP (tcp_link.h).
// What remains, in the radio's driver (a compiled library), and was not measured:
//   * A radio chip that stops answering. The driver then waits for its time-outs
//     (about 1 s each) in every command and every frame. The link tests the chip with
//     one cheap command every 2 s while joined, before each join request, and at once
//     after a frame send that took long. No frame is handed to the driver during a
//     test, nor after a failed one, so a failed test holds the loop for the time-outs
//     of that one command (1 to 2 s). The second failed test in a row powers the chip
//     off (WIFI=FAULT, until WIFI ON). loop() feeds the watchdog right before each
//     test; a wait above the watchdog period restarts the board (DISARMED, radio held
//     off). A chip that fails between a passed test and the end of the join request
//     that follows it (more than ten commands) also ends in the watchdog restart.
//   * A bad radio link. The driver can wait about 1 s inside one frame send when the
//     chip withholds bus credits, also in lwIP's background work. After such a send
//     the link holds further frames back until the chip has passed a test. A chip that
//     is alive but withholds its credits through two tests is powered off like a dead
//     one.
//
// The pulse outputs do not depend on the link: they come from PIO and the clock
// generator. The radio's driver takes one PIO state machine (outside pio0, which
// main.cpp claims first) and two DMA channels.
//
// Flash. The set-up is one record (wifi_config.h) in the core's EEPROM sector. It is
// written only at the 150 MHz clock: after a flash write the SDK restores the flash
// interface timing of its start-up, which is too fast at 300 MHz (clock_mode.cpp sets
// its own timing there). With the clock jumper fitted, a new set-up holds until
// power-off.

#include <Arduino.h>
#include "protocol.h"
#include "wifi_config.h"

namespace net {

#if defined(ARDUINO_RASPBERRY_PI_PICO_2W)
constexpr bool kAvailable = true;
#else
constexpr bool kAvailable = false;
#endif

// Reads the stored set-up. No radio call. Call before Protocol::begin().
void begin();

// Joins the network if the stored set-up asks for it. `allowed` false (after a watchdog
// reset) holds the radio off until WIFI ON, so a radio fault cannot reset the board
// again and again. Can take as long as the radio chip's power-up.
void start(bool allowed);

// The set-up in use.
const WifiConfig &config();

// Makes cfg the set-up in use and stores it. Returns nullptr, or why not: then the
// set-up is as before, and the radio is off.
// *notSaved: nullptr, or why cfg is not in flash. Can take as long as the radio chip's
// power-up plus a flash sector erase.
const char *set(const WifiConfig &cfg, const char **notSaved);

// Call from loop(), right after a watchdog feed: the join state and the TCP link.
// Returns at once, except for the waits inside the radio's driver (see above).
void service();

// The next byte from the TCP host, or -1.
int read();

// True if more input from the TCP host has arrived.
bool inputPending();

// Sends the reply bytes queued since the last call. Call after the link's commands
// of one loop() pass.
void flush();

// The TCP host's protocol link (line buffer and reply path).
ProtocolLink &link();

// The Wi-Fi and network STATUS lines, one "KEY=value" each.
void printStatus(Print &out);

}  // namespace net
