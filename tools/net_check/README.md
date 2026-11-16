# PiEBV network check

The firmware's TCP link and command protocol, running on your computer against a model of lwIP.
`net_check` compiles the unmodified `src/tcp_link.cpp` and `src/protocol.cpp`. The files in `fake/`
stand in for lwIP's TCP interface and for the core's lwIP lock. The check then plays the part of
the network: hosts that connect, send, close and reset.

It exists because this part of the firmware cannot be seen in the [simulator](../piebv_sim), and
because its errors are of a kind that a first test on a board does not show.

## Building and running

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
- Run it after any change to `src/tcp_link.*` or `src/protocol.*`.
- The binary is not tracked in git.

## What it checks

| Case | What must be true |
|---|---|
| Command and reply | A command runs, its reply goes out, and the receive window opens again for what was read |
| `DISARM`, then a reset, before the loop reads | The board disarms. The link stays with that host until its input is read, then it is free. |
| A host that connects and closes, or resets, at once | Nothing is used after it is gone, and the link is free |
| Half-close (the host closes its sending side) | The reply goes out, then an orderly close, not a reset |
| A partial line, then a reset | Nothing of the line reaches the next host |
| A second host | It gets `ERR busy: another host is connected` and is closed. What it sends is discarded. The first host is not disturbed. |
| More second hosts than the limit | The extra one is reset at once, a slow one after its time limit, and the places become free again |
| lwIP has no memory | The reply waits once (the 250 ms budget) and is dropped. Later replies do not wait. Commands still run. |
| More input than the buffer, in pieces | Every command is read once, in order, with the window never exceeded |
| Radio fault with input waiting | Input that has arrived still runs (`DISARM`) |
| Stop with a host connected, then start | The connection is reset, nothing of its input is left, and a new start works |

In every case the model also fails the check when the code:
- calls lwIP without the lwIP lock (outside a callback);
- uses a connection after it closed or aborted it, or after lwIP freed it.

## What it does not check

- lwIP itself and the radio. The model has the behaviour that `src/tcp_link.cpp` expects from
  lwIP (for example, that `tcp_abort()` calls the error callback, and that an accept error aborts
  the connection). If lwIP behaves differently, the check does not show it.
- Timing on the board, the radio's driver and `src/net_link.cpp` (join, fault handling, flash).
- These need the [network checks](../../docs/FIRST_BOARD_CHECKS.md#network-checks) on a board.
