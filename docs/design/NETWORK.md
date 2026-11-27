# PiEBV design: network link

This page gives the design of the Wi-Fi and TCP link of the firmware: the structure, the rules
that keep `DISARM` and the watchdog safe, the reasons for each choice, and what was verified.
To *use* the link, see [Network (Wi-Fi)](../CONNECTING.md#network-wi-fi) and the
[Wi-Fi commands](../COMMANDS.md#wi-fi-set-up).
Back to: [hardware reference](../../Hardware.md) · [design notes index](../DESIGN_NOTES.md)

> **Status:** the link was not tested on a board. The code compiles, and its command handling
> and connection handling were tested on a computer (see [Verification](#verification)). The
> radio, its driver, the join and the flash write did not run. Do the
> [network checks](../FIRST_BOARD_CHECKS.md#network-checks) first.

---

## Decisions

These were set by the owner of the project:

| Decision | Result in the firmware |
|---|---|
| The board joins an existing laboratory network | Station mode only. No access point, no set-up web page. |
| Arming is permitted over the network | The TCP link has all commands of the USB link (`:OUTP ON` included), except the Wi-Fi settings |
| A lost link does not disarm | As on USB: a closed or lost connection changes no output |
| No password on the network link | No login and no encryption. The link is for a controlled laboratory network. |
| The set-up is done over USB | The Wi-Fi settings (`:SYST:COMM:WLAN:SSID`, `WLAN:PASS`, `:SYST:COMM:WLAN ON`, `OFF` and `WLAN:CLEar`) are refused from the network link with error -203 |

## Structure

```
 USB host ── Serial ──────────────┐
                                  ├─ ProtocolLink (USB) ─┐
                                  │                      ├─ Protocol ── hooks ── pulse hardware
 TCP host ── lwIP ── tcp_link ────┴─ ProtocolLink (TCP) ─┘        (main.cpp)
                │
        radio driver (CYW43) ── net_link: join, fault handling, flash record
```

| File | Contents |
|---|---|
| `src/protocol.*` | The SCPI command protocol. One `ProtocolLink` for each host link: its own line buffer, `DISARM` match, reply path, error queue, status registers and echo switch. The settings and the arm state are shared. A reply goes only to the link that sent the command. |
| `src/tcp_link.*` | The TCP server, on lwIP's callback interface, for one host at a time |
| `src/net_link.*` | The radio: power, join, fault handling, the stored set-up, the values for the `:SYST:COMM:WLAN` queries |
| `src/wifi_config.h` | Set-up values, their limits and the flash record. No hardware calls, so the simulator uses the same code. |
| `src/main.cpp` | Reads both links in turns; owns the watchdog and the arm state |

The image for a plain Pico 2 (`pico2`) has no radio: `net_link` is then a set of empty functions,
`:SYST:COMM:WLAN:LINK?` gives `UNAVAILABLE`, and the Wi-Fi settings give error -241.

## Rules that the link must keep

1. **The command loop must not be held up.** `DISARM` is acted on when the firmware reads its
   letters, and the watchdog is fed only from `loop()`.
2. **Input that has arrived is run.** A `DISARM` that reached the board must act, also when the
   host then closes or resets the connection.
3. **A reply goes only to the host that sent the command.**
4. **The pulse outputs do not depend on the link.** They come from PIO and the clock generator.
   The radio's driver takes one PIO state machine outside pio0 (which `main.cpp` claims first) and
   two DMA channels.

## Radio

**Join without waiting.** The core's `WiFi.begin()` and `WiFi.beginNoBlock()` wait inside the
join (with `delay()`, for up to their time-out, and without a limit in one case). The link starts
the join through the same CYW43 driver and then polls every 200 ms. The interface is marked
"link down" until the driver reports the join as complete; lwIP starts DHCP at that moment. A join
that fails or gives no result is requested again after 5 s to 20 s.

**The chip is off whenever the link is off.** `:SYST:COMM:WLAN OFF`, `:SYST:COMM:WLAN:CLE`, a fault and a failed start
all power the radio chip off (`WL_REG_ON` low) and release the driver's bus. Each start is then the
same power-up, and none needs an answer from an old chip state. The power-up loads the chip's
firmware and is the one long call: it runs only while DISARMED, with the watchdog period set to
8 s for that call. After a watchdog reset the radio is not started at power-up
(`:SYST:COMM:WLAN:LINK?` gives `OFF,"held off …"`), so a radio fault cannot restart the board again
and again.

**A chip that stops answering.** The radio's driver is a compiled library. With a chip that does
not answer, it waits for its own time-outs (about 1 s each) in every command and every frame, also
in lwIP's background work. The firmware cannot shorten these waits. It limits how often they occur:

- One test command (the signal-level read) goes to the chip every 2 s while joined, before each
  join request, and at once after a frame send that took longer than 300 ms.
- No frame is handed to the driver during a test, nor after a failed one. lwIP sends a dropped
  TCP segment again.
- One failed test can come from a chip that is alive on a bad link, so the second failed test in a
  row is the fault: the chip is powered off and `:SYST:COMM:WLAN:LINK?` gives `FAULT` until
  `:SYST:COMM:WLAN ON`.
- `loop()` feeds the watchdog right before each test. A wait above the 3 s watchdog period restarts
  the board, DISARMED.

**Flash.** The set-up is one record (magic, enabled flag, name, passphrase, CRC-32) in the core's
EEPROM sector. It is written only at the 150 MHz clock: after a flash write the SDK restores the
flash interface timing of its start-up, which does not agree with the timing that
`clock_mode.cpp` sets at 300 MHz. With the clock jumper fitted, a new set-up holds until power-off
(error 101, `Set-up not stored`; `:SYST:COMM:WLAN:SAV?` gives `0`). The record is written unless the flash holds the same bytes, or is erased and the
set-up is empty; a record that cannot be read is always written over, because it can hold a
passphrase.

## TCP link

The core's `WiFiServer` and `WiFiClient` are not used. Their write waits inside the core when lwIP
cannot queue the bytes; a connection that the host has reset reads as "closed" while its last
input is still unread; and several of their calls are not protected against lwIP's background
work. The link is a server on lwIP's callback interface (`tcp_link.cpp`):

| Subject | Design | Reason |
|---|---|---|
| Lock | All access to the connection is made with the lwIP lock held | lwIP calls back from its background work |
| Input | Copied at once into a buffer as large as the receive window. The window opens again only as the loop reads. | The buffer cannot overflow, and input survives a close or a reset: the loop reads and runs all of it before the link is free for the next host |
| Replies | Queued with `tcp_write()`, sent once in each loop pass. A reply that lwIP cannot take is dropped and counted. | Nothing waits for the host |
| Reply queue | At most 3 segments' worth (4380 bytes). Nagle's rule stays on. | lwIP gives each segment a full-size buffer from a 16 kB heap that DHCP, ARP and mDNS share. Cost: a reply longer than one packet can arrive 40 ms to 200 ms late. |
| Listening socket | Made once and kept, also while the link is stopped | This lwIP build has no address re-use: a second bind to the port fails for up to 2 minutes after a closed connection |
| Second host | Gets `ERR busy: another host is connected` (not an SCPI reply) and our FIN. At most two at a time, each for at most 2 s. | lwIP has 5 connection blocks in all |
| Closed connection | Reset after 2 s if its host does not finish the close | It would hold its reply buffers for 2 minutes |
| Silent host | TCP keep-alive: 5 s idle, then 3 probes 2 s apart | The link is free again after about 11 s |

## Two links and `DISARM`

`loop()` reads the USB link, then the TCP link, in turns of at most 128 characters and 5 ms.

A reply line waits for a host that is slow to take it only out of a time budget of the link:
250 ms, which comes back at one eighth of the time that passes. When it is used up, replies are
dropped without a wait until the host has drained the link again.

- While more input of the link waits behind the command (a `DISARM` could be in it), each wait is
  charged to the budget in full. A queue of commands before a `DISARM` cannot add up.
- While nothing waits behind the command, a wait is charged only as far as the host reads slower
  than 20 kB/s. A host that sends a command and reads the reply before it sends the next one keeps
  its budget and loses no line, also in a tight loop.

| Case (tests on a computer, long command queues) | `DISARM` acted after at most |
|---|---|
| Its own host slow | 0.54 s |
| The hosts of both links slow | 1.24 s |

These times were not measured on a board. The waits of the radio's driver (above) come on top.

## Wi-Fi set-up commands

- **USB only, DISARMED only.** A network host must not be able to move the board to another
  network or lock the USB user out: the Wi-Fi settings from the network link give error -203.
  `:SYST:COMM:WLAN ON`, `OFF` and `WLAN:CLEar` stop the command loop for the radio start and the
  flash write, so they are refused (error -200) while ARMED or while a laser start is pending.
- **A name and passphrase are collected, then used.** `:SYST:COMM:WLAN:SSID` and `WLAN:PASS` hold
  their values in RAM until the next `WLAN ON`, `OFF` or `CLEar`, accepted or refused.
  `:SYST:COMM:WLAN:PEND?` gives `1` while something is collected.
- **A new name never gets another network's passphrase.** `WLAN:SSID` discards a passphrase given
  before it.
- **The passphrase is never printed.** `WLAN:PASS` has no query form. `:SYST:COMM:WLAN:SEC?` gives
  `WPA2` or `NONE`, and the echo line gives `(set; …)` or `(none: open network; …)`.
- **Text rules.** The name and the passphrase are SCPI strings in quotes. The letters `disarm` in a
  name or passphrase would act as the command. A name must be UTF-8 text without control and
  writing-direction characters, because it is printed in replies. A passphrase must be printable
  ASCII (IEEE 802.11).

## Web GUI

The GUI server (`tools/piebv_gui`) owns the link to the board, over USB or over the network.

- The set-up sequence (`:SYST:COMM:WLAN:SSID`, `WLAN:PASS`, `:SYST:COMM:WLAN ON`) holds the command
  lock from its first command to its last, and the server checks that the board joined what was
  asked for.
- `DISARM` is written to the board at once, without the command lock, and its request is handled
  before the request body is read.
- An arming request (`:OUTP ON`) that waited for the lock is not sent if a `DISARM` was sent in
  the meantime.
- All POST routes other than `DISARM` need a JSON object body and refuse a request that carries
  the Origin of another site.
- The passphrase is masked in the console log, in error messages and in the page.

## Verification

| Check | What it covers |
|---|---|
| `pio run`, `pio run -e pico2` | Both images compile without warnings |
| [`tools/net_check`](../../tools/net_check/README.md) `net_check` | `tcp_link.cpp` and `protocol.cpp` against a model of lwIP that fails on a call without the lwIP lock and on use of a connection that is gone |
| `tools/net_check/lwip` `lwip_check` | The same code linked with lwIP's own sources and the firmware's lwIP options: reset after `DISARM`, half-close, server restart, heap use, receive window, second hosts, keep-alive |
| [`tools/piebv_sim`](../../tools/piebv_sim/README.md) | The Wi-Fi commands and all replies, with a radio that joins at once; `scpi_check.py` checks the SCPI replies, the Wi-Fi set-up included |
| USB replies against `main` | 1500 random inputs gave the same replies as before the network link (a check of the earlier text commands, before the change to SCPI) |
| GUI against the simulator | The set-up paths, passphrase masking, arming behind a delayed join followed by `DISARM`, malformed requests, the page in a browser. Done with the earlier text commands, and again after the change to SCPI. |
| SCPI parser on a computer | 400 random inputs with the address and undefined-behaviour sanitizers: no failure, and `DISARM` acted in every case. 802 realized values in NR3 form agree with an exact calculation. |

The link went through four rounds of independent adversarial review, each followed by
corrections. Rounds 1 to 3 found high-severity defects in the firmware; round 4 found none. In
round 4 the reviewer also ran lwIP's pending work at each release of the lwIP lock and found no
lost input and no reply to the wrong host.

**Not verified:**

- Everything in `net_link.cpp` that needs the radio: power-up time, join, the power-off and
  power-on cycle, the fault handling, the flash write.
- lwIP together with DHCP, ARP, mDNS and the radio's driver, which share its memory.
- All times on the board: the radio start, the `DISARM` delays, the driver's waits.
- Radio range (the board has copper under the module's antenna) and interference with the
  camera and laser lines.

## Not done

| Item | Note |
|---|---|
| Ethernet with PoE | Assessed and shelved. It needs a new board revision: no free GPIO is routed on this board. A W5500 on GP2–GP5 (SPI0) would use the same TCP link code. |
| WPA2-Enterprise | Not supported by this join path |
| Login or encryption on the network link | Left out by decision |
| Disarm on a lost link | Left out by decision |
| Bluetooth | Not used |
