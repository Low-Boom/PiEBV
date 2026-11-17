# Troubleshooting

This page lists symptoms, their likely causes and the fixes. This page is part of the PiEBV
documentation. The overview and the list of all pages are in the [README](../README.md).

| Symptom | Likely cause | Fix |
|---|---|---|
| No serial port appears | Cable in J17 (power only) instead of the Pico's micro-USB; a charge-only cable; or the Pico is in bootloader mode (a drive named `RP2350` appears instead) | Use the Pico's port with a data cable. In bootloader mode, copy `firmware.uf2` to the drive, or unplug both J17 and the Pico's USB. |
| Port opens but nothing appears | The greeting is only sent in the first 1.5 s, and the firmware does not echo | Type `ID?` or `STATUS`; turn on local echo |
| Commands work but no replies arrive | The terminal has DTR off | Turn DTR on in the terminal settings |
| The port vanishes and an `RP2350` drive appears | The port was opened at 1200 baud, which restarts the Pico into its bootloader | Use any other baud rate. Copy `firmware.uf2` to the drive, or unplug both J17 and the Pico's USB. |
| `ERR … unknown command` for everything | A typo, the `FREQ?` form, or XON/XOFF flow control | Use bare names; set flow control to None |
| `ERR … rejected: DELAY must leave >= WIDTH …` | DELAY + 2 × WIDTH is longer than 1/FREQ | Shorten DELAY or WIDTH, or lower FREQ; the message gives the longest allowed DELAY |
| `ERR … MARKERWIDTH must be <= half the period …` at high FREQ | The marker (2 µs by default) is longer than half the period | Shorten MARKERWIDTH first; the message gives the limit |
| `ERR ARM …`, or `HW=ERR …` in STATUS | The pulse hardware did not start | Load the firmware again; if it keeps happening, report the `STATUS` output |
| `ARMED=1` but no laser pulses | J11 not on 1-2; J17 unplugged or the charger isn't giving 15 V; or still in the hold-off (`START_PENDING_US` > 0) | Check each gate. Measure `VBUS_PD` at C12 (about 15 V) and +12V at C17 (about 11.8 V; the outputs stay off outside 10.6–13.3 V). |
| Outputs dead after a restart | The board always restarts DISARMED | Send `ARM` |
| About 12 V pulses on the scope | J18/J19 on 1-2 (50 Ω mode) into a 1 MΩ scope input | Set the scope to 50 Ω (the laser driver has its own 50 Ω), or move the shunt to 2-3 for a high-impedance load |
| About 2.5 V pulses at the laser driver | J18/J19 on 2-3 (Hi-Z mode) into the driver's 50 Ω input | Move the shunt to 1-2 |
| One output gives ~3.5 V into 50 Ω, or ~12 V open | No shunt on that output's J18/J19 | Fit the shunt: 1-2 for 50 Ω, 2-3 for Hi-Z |
| About 3 V pulses at the laser driver | Two 50 Ω loads on one output (e.g. a tee into both a 50 Ω scope input and the driver) | Watch with a high-impedance scope probe instead, or on J10 pin 1 (CH1, through 100 Ω) / R18 pin 1 (CH2) |
| Cameras get no trigger | J10 on 1-2 while DISARMED, or no shunt on J10 | J10 on 2-3 |
| Cameras don't synchronise | A camera set as sync master | Set every camera to sync slave |
| All cameras stuck in pixel reset | `PIXGATE` 1 or 2 with a window that leaves little free time (`PIXRESET` in STATUS) | Check PIXLEAD/PIXLAG, or set `PIXGATE 0` |
| No pulses on J12 (External Sync Out) | J17 unplugged or the charger isn't giving 15 V; no camera trigger (J10 empty, or on 1-2 while DISARMED); no shunt on J21 gives ~3.5 V into 50 Ω | Check J17 and +12V, set J10 to 2-3, fit J21 |
| Cameras see no events around the laser pulses with `PIXGATE` on | PIXLEAD too short for the sensor to settle, or PIXLAG shorter than the sensor's event delay | Increase PIXLEAD and PIXLAG, or set `PIXGATE 0` to compare |
| `RESET=WATCHDOG` in STATUS | The firmware hung and restarted itself, DISARMED | Note what you were doing and report it; arm again deliberately |
| `TX_DROPPED` keeps rising | The host is not reading the replies | Read every reply line |
| `ERR WIFI refused: …` | A Wi-Fi set-up command was sent over the network link | Send it over the Pico's USB port |
| `ERR WIFI ON refused: DISARM first: …` | The board is ARMED, or a laser start is pending | Send `DISARM`, then the `WIFI` command |
| `WIFI=JOINING (network not found)` | Wrong network name, the access point is off or out of range, or it is a 5 GHz-only network (the Pico 2 W radio uses 2.4 GHz) | Check the name (capitals matter) and the access point |
| `WIFI=JOINING (the network refused the passphrase)` | Wrong passphrase, or a network that needs a user name (WPA2-Enterprise, not supported) | Send `WIFI SSID`, `WIFI PASS` and `WIFI ON` again |
| `WIFI=DHCP` and it stays | The board joined, but the network gave no address | Check the network's DHCP server; give its administrator `WIFI_MAC` if the network accepts only known devices |
| `WIFI=CONNECTED`, but the computer cannot connect | Wrong address or port, a firewall, or a network that isolates its clients | Use `WIFI_IP` and port 4242; connect from a computer on the same network |
| `ERR busy: another host is connected` | Another connection has the link, or your own old connection was cut without a close | Close the other connection, or wait about 11 s |
| `OK WIFI=ON … PASS=NONE …` for a network with a passphrase | `WIFI SSID` was sent after `WIFI PASS`, or without it: a new name discards the passphrase | Send `WIFI SSID`, then `WIFI PASS`, then `WIFI ON` |
| `… SAVED=0 (not stored: flash is written only at the 150 MHz clock …)` | The clock jumper J20 is fitted | The set-up holds until power-off. To store it, remove the J20 shunt, power-cycle, and send it again. |
| `WIFI=FAULT (…)` | The radio chip did not answer two tests in a row; the board switched it off | Send `WIFI ON` over USB. If it comes back often, note `WIFI_RSSI_DBM` and report it. |
| `WIFI=OFF (held off after a watchdog reset …)` | The board restarted itself; the radio is not started again without a command | Check `RESET` and `WDT_RESETS`, then send `WIFI ON` or power-cycle |
| `WIFI=OFF (the stored set-up cannot be read …)` | The stored record is damaged, or was written by firmware with other rules | Send the set-up again, or `WIFI CLEAR` |
| `WIFI=UNAVAILABLE` | The `pico2` firmware image is loaded | Load the `pico2w` image on a Pico 2 W |
| Replies over the network stop, `TX_DROPPED` rises | The host does not read or acknowledge the replies | Read every reply line; check the radio link (`WIFI_RSSI_DBM`) |
| `pio run -t upload` can't find the Pico | The automatic restart into the bootloader failed | Unplug J17, then hold BOOTSEL while plugging in the Pico's USB, and upload again or copy the UF2 |
| First build fails on Windows with git path errors | The PlatformIO folder is on a long path | Keep it at the default `%USERPROFILE%\.platformio` |
