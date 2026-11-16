# PiEBV network check

The firmware's TCP link and command protocol, running on your computer. There are two checks of
the unmodified `src/tcp_link.cpp` and `src/protocol.cpp`:

| Check | Runs against | Needs |
|---|---|---|
| `net_check` | A small model of lwIP (`fake/`) that records every call | A C++17 compiler |
| `lwip/lwip_check` | **lwIP itself**: the lwIP sources of the firmware's SDK, with the firmware's TCP and memory options | The PlatformIO package of the firmware (run `pio run` once) |

Each check plays the part of the network: hosts that connect, send, close and reset.

They exist because this part of the firmware cannot be seen in the [simulator](../piebv_sim), and
because its errors are of a kind that a first test on a board does not show. Run both after any
change to `src/tcp_link.*` or `src/protocol.*`.

## The check against the model (`net_check`)

Any C++17 compiler works. From this directory:

```
g++ -std=c++17 -O1 -g -Wall -Wextra -fsanitize=address,undefined -DPIEBV_NET_CHECK \
    -I fake -I ../piebv_sim/fake -I ../../src -o net_check \
    net_check.cpp ../../src/tcp_link.cpp ../../src/protocol.cpp
./net_check
```

- The expected output is `net_check: all checks passed`. A failed check prints its case and line,
  and the exit code is 1.
- `-fsanitize=address,undefined` is optional (leave it out with MSVC or MinGW).
- The binary is not tracked in git.

What it checks:

| Case | What must be true |
|---|---|
| Command and reply | A command runs, its reply goes out, and the receive window opens again for what was read |
| `DISARM`, then a reset, before the loop reads | The board disarms. The link stays with that host until its input is read, then it is free. |
| A host that connects and closes, or resets, at once | Nothing is used after it is gone, and the link is free |
| Half-close (the host closes its sending side) | The reply goes out, then an orderly close, not a reset |
| A partial line, then a reset | Nothing of the line reaches the next host |
| A second host | It gets `ERR busy: another host is connected`, then our FIN; the connection is given up when the host closes. What it sends is discarded. The first host is not disturbed. |
| More second hosts than the limit | The extra one is reset at once. A host that does not take the line, or does not close, is reset at its time limit, and the places become free again. |
| lwIP has no memory | The reply waits once (the 250 ms budget) and is dropped. Later replies do not wait. Commands still run. |
| More input than the buffer, in pieces | Every command is read once, in order, with the window never exceeded |
| Radio fault with input waiting | Input that has arrived still runs (`DISARM`). While stopped, a new connection is reset. |
| Stop with a host connected, then start | The connection is reset, nothing of its input is left, and a new start works |

In every case the model also fails the check when the code:
- calls lwIP without the lwIP lock (outside a callback);
- uses a connection after it closed or aborted it, or after lwIP freed it.

The model has the behaviour that `src/tcp_link.cpp` expects from lwIP (for example, that
`tcp_abort()` calls the error callback). Where lwIP behaves differently, only `lwip_check` shows it.
The model has no connection pool, no closing states and no heap.

## The check against lwIP itself (`lwip/`)

```
cd lwip
sh build.sh          # or: sh build.sh <path to pico-sdk/lib/lwip/src>
./lwip_check         # one case only: ./lwip_check <name>
```

- The expected last line is `lwip_check: all checks passed`. The lines before it are
  measurements (times, counts) for the record.
- `build.sh` compiles lwIP's core and TCP files from
  `~/.platformio/packages/framework-arduinopico/pico-sdk/lib/lwip/src` with `inc/lwipopts.h`. Keep
  that file in step with the core's `include/lwipopts.h` when the core is upgraded.
- With the address sanitizer, run it as `ASAN_OPTIONS=detect_leaks=0 ./lwip_check`: the check
  does not free its host records.

| Case (name) | What must be true |
|---|---|
| `reset` | `DISARM` followed by a reset still disarms. Six hosts that connect and go at once (more than lwIP's 5 connection blocks) leave the link free. |
| `halfclose` | Data and FIN in one segment: the reply arrives, then FIN, and no reset |
| `bind` | After a second host and a stop, a new start works at once (lwIP keeps a closed connection on the port for 2 minutes, and the build has no address re-use) |
| `small` | 30 one-line commands whose replies the host acknowledges late: no reply waits for memory, and none is lost |
| `help` | The whole `HELP` reply arrives without a stall |
| `window` | A full receive window is read, and the window opens again |
| `rejectdata` | A second host that sends data gets the busy line; silent second hosts are gone after their time limit |
| `pool` | Second hosts that read the busy line and keep their sockets open do not use up lwIP's connection blocks |
| `keepalive` | A silent host frees the link after 10 s to 13 s |

## What the checks do not show

- lwIP's work at the moments when the firmware releases the lwIP lock, or from an interrupt
  between two statements. In both checks lwIP runs only when the check calls it.
- Ethernet, ARP, DHCP, mDNS and the radio's driver, which share lwIP's memory on the board.
- Timing on the board, and `src/net_link.cpp` (join, fault handling, flash).
- These need the [network checks](../../docs/FIRST_BOARD_CHECKS.md#network-checks) on a board.
