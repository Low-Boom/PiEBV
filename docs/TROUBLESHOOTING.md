# Troubleshooting

This page lists symptoms, their likely causes and the fixes. This page is part of the PiEBV
documentation. The overview and the list of all pages are in the [README](../README.md).

| Symptom | Likely cause | Fix |
|---|---|---|
| No serial port appears | Cable in J17 (power only) instead of the Pico's micro-USB; a charge-only cable; or the Pico is in bootloader mode (a drive named `RP2350` appears instead) | Use the Pico's port with a data cable. In bootloader mode, copy `firmware.uf2` to the drive, or unplug both J17 and the Pico's USB. |
| Port opens but nothing appears | The firmware sends no greeting, gives no reply to a setting and does not echo what you type | Type `*IDN?`; turn on local echo; send `:SYST:ECHO ON` to get a reply to each setting and error |
| Commands work but no replies arrive | The terminal has DTR off | Turn DTR on in the terminal settings |
| The port vanishes and an `RP2350` drive appears | The port was opened at 1200 baud, which restarts the Pico into its bootloader | Use any other baud rate. Copy `firmware.uf2` to the drive, or unplug both J17 and the Pico's USB. |
| A setting has no effect, and no reply comes | A setting gives no reply; a rejected setting changes nothing, and its error goes into the error queue | Send `:SYST:ERR?` until it gives `0,"No error"`, or send `:SYST:ECHO ON` |
| `-113,"Undefined header;…"` for everything | A typo, an old command (`ARM`, `STATUS`, `ID?`, `WIFI ON`), or XON/XOFF flow control | Use the SCPI commands ([old commands](COMMANDS.md#old-commands-and-status-keys)); set flow control to None |
| `-109,"Missing parameter"` | A setting without a value, for example `FREQ` on its own to read the value (old form) | Add `?` to read a value: `:FREQ?` |
| `-222,"Data out of range;longer than 4.29 s"` for a time | A time without a suffix is in seconds | Add the suffix: `:PULS:WIDT 100 NS` |
| `-221,"Settings conflict;DELAY must leave >= WIDTH …"` | DELAY + 2 × WIDTH is longer than 1/FREQ | Shorten the delay or the pulse width, or lower the frequency; the text gives the longest permitted DELAY |
| `-221,"Settings conflict;MARKERWIDTH must be <= half the period …"` at a high frequency | The marker (2 µs by default) is longer than half the period | Shorten the marker width (`:MARK:WIDT`) first; the text gives the limit |
| `-240,"Hardware error;…"` in the error queue, or `:DIAG:HARD?` not `"OK"` | The pulse hardware did not start | Load the firmware again; if it keeps happening, report the `:DIAG:HARD?` reply |
| `:OUTP?` gives `1` but no laser pulses | J11 not on 1-2; J17 unplugged or the charger isn't giving 15 V; or still in the hold-off (`:OUTP:PEND?` not 0) | Check each gate. Measure `VBUS_PD` at C12 (about 15 V) and +12V at C17 (about 11.8 V; the outputs stay off outside 10.6–13.3 V). |
| Outputs dead after a restart | The board always restarts DISARMED | Send `:OUTP ON` |
| About 12 V pulses on the scope | J18/J19 on 1-2 (50 Ω mode) into a 1 MΩ scope input | Set the scope to 50 Ω (the laser driver has its own 50 Ω), or move the shunt to 2-3 for a high-impedance load |
| About 2.5 V pulses at the laser driver | J18/J19 on 2-3 (Hi-Z mode) into the driver's 50 Ω input | Move the shunt to 1-2 |
| One output gives ~3.5 V into 50 Ω, or ~12 V open | No shunt on that output's J18/J19 | Fit the shunt: 1-2 for 50 Ω, 2-3 for Hi-Z |
| About 3 V pulses at the laser driver | Two 50 Ω loads on one output (e.g. a tee into both a 50 Ω scope input and the driver) | Watch with a high-impedance scope probe instead, or on J10 pin 1 (CH1, through 100 Ω) / R18 pin 1 (CH2) |
| Cameras get no trigger | J10 on 1-2 while DISARMED, or no shunt on J10 | J10 on 2-3 |
| Cameras don't synchronise | A camera set as sync master | Set every camera to sync slave |
| All cameras stuck in pixel reset | `:PIX:GATE ARMed` or `ALWays` with a window that leaves little free time (`:PIX:WIND?`) | Check `:PIX:LEAD` and `:PIX:LAG`, or send `:PIX:GATE OFF` |
| No pulses on J12 (External Sync Out) | J17 unplugged or the charger isn't giving 15 V; no camera trigger (J10 empty, or on 1-2 while DISARMED); no shunt on J21 gives ~3.5 V into 50 Ω | Check J17 and +12V, set J10 to 2-3, fit J21 |
| Cameras see no events around the laser pulses with the pixel-reset gate on | The lead time too short for the sensor to settle, or the lag time shorter than the event delay of the sensor | Increase `:PIX:LEAD` and `:PIX:LAG`, or send `:PIX:GATE OFF` to compare |
| `:DIAG:RES:CAUS?` gives `WATCHDOG` | The firmware stopped and the watchdog restarted it, DISARMED | Note what you were doing and report it; arm again deliberately |
| `:DIAG:TXDR?` keeps rising | The host is not reading the replies | Read every reply line |
| `-350,"Queue overflow"` | More than 8 errors were not read | Read the error queue with `:SYST:ERR?`, or send `*CLS` |
| `-203,"Command protected;…"` | A Wi-Fi setting was sent over the network link | Send it over the Pico's USB port |
| `-200,"Execution error;DISARM first: …"` after a Wi-Fi command | The board is ARMED, or a laser start is pending | Send `DISARM`, then the Wi-Fi command again |
| `:SYST:COMM:WLAN:LINK?` gives `JOINING,"network not found"` | Wrong network name, the access point is off or out of range, or it is a 5 GHz-only network (the Pico 2 W radio uses 2.4 GHz) | Check the name (capitals matter) and the access point |
| `JOINING,"the network refused the passphrase"` | Wrong passphrase, or a network that needs a user name (WPA2-Enterprise, not supported) | Send `:SYST:COMM:WLAN:SSID`, `:SYST:COMM:WLAN:PASS` and `:SYST:COMM:WLAN ON` again |
| `DHCP`, and it stays | The board joined, but the network gave no address | Check the network's DHCP server; give its administrator the address from `:SYST:COMM:WLAN:MAC?` if the network accepts only known devices |
| `CONNECTED`, but the computer cannot connect | Wrong address or port, a firewall, or a network that isolates its clients | Use the address from `:SYST:COMM:WLAN:IPAD?` and port 4242; connect from a computer on the same network |
| `ERR busy: another host is connected` | Another connection has the link, or your own old connection was cut without a close | Close the other connection, or wait about 11 s |
| `:SYST:COMM:WLAN:SEC?` gives `NONE` for a network with a passphrase | `WLAN:SSID` was sent after `WLAN:PASS`, or without it: a new name discards the passphrase | Send `:SYST:COMM:WLAN:SSID`, then `:SYST:COMM:WLAN:PASS`, then `:SYST:COMM:WLAN ON` |
| `101,"Set-up not stored;flash is written only at the 150 MHz clock …"` | The clock jumper J20 is fitted | The set-up holds until power-off. To store it, remove the J20 shunt, power-cycle, and send it again. |
| `FAULT,"…"` | The radio chip did not answer two tests in a row; the board switched it off | Send `:SYST:COMM:WLAN ON` over USB. If it comes back often, note `:SYST:COMM:WLAN:RSSI?` and report it. |
| `OFF,"held off after a watchdog reset …"` | The board restarted itself; the radio is not started again without a command | Read `:DIAG:RES:CAUS?` and `:DIAG:WATC:RES?`, then send `:SYST:COMM:WLAN ON` or power-cycle |
| `OFF,"the stored set-up cannot be read …"` | The stored record is damaged, or was written by firmware with other rules | Send the set-up again, or `:SYST:COMM:WLAN:CLE` |
| `UNAVAILABLE`, or `-241,"Hardware missing;…"` | The `pico2` firmware image is loaded | Load the `pico2w` image on a Pico 2 W |
| Replies over the network stop, `:DIAG:TXDR?` rises | The host does not read or acknowledge the replies | Read every reply line; check the radio link (`:SYST:COMM:WLAN:RSSI?`) |
| `pio run -t upload` can't find the Pico | The automatic restart into the bootloader failed | Unplug J17, then hold BOOTSEL while plugging in the Pico's USB, and upload again or copy the UF2 |
| First build fails on Windows with git path errors | The PlatformIO folder is on a long path | Keep it at the default `%USERPROFILE%\.platformio` |
