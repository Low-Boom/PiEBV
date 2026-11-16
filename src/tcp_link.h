#pragma once
// TCP side of the network link (net_link.h): a server on lwIP's callback interface
// that gives the command protocol to one host at a time. Only net_link.cpp uses it.
// It is a file of its own so that tools/net_check can compile it on a computer against
// a model of lwIP and test the connection handling.
//
// The core's WiFiServer / WiFiClient are not used: their write waits inside the core
// when lwIP cannot queue the bytes, a connection that the host has reset reads as
// "closed" while its last input (possibly DISARM) is still unread, and several of
// their calls are not protected against lwIP's background work.
//
// What this code guarantees:
//   * Input that has arrived is never lost. It is copied into a buffer at once; when
//     the host closes or resets the connection, the loop first reads and runs
//     everything in the buffer, and only then is the link free for the next host.
//   * Nothing waits for the host. Replies are queued with tcp_write() and dropped when
//     lwIP cannot take them (ReplyOut, protocol.h, counts them).
//   * A second host gets "ERR busy: another host is connected" and is closed.

#include <Arduino.h>
#include <lwip/ip_addr.h>
#include "protocol.h"

namespace tcplink {

// Starts listening on `port`. False if lwIP has no memory for it.
bool start(uint16_t port);

// Resets the host's connection, if any, and stops listening. `keepInput` true: input
// that has arrived stays for read(), and service() frees the link when it is read
// (for a radio that failed: a DISARM that arrived just before must still act).
// `keepInput` false: unread input is discarded.
void stop(bool keepInput);

// From loop(), before the link's read turn, also while the radio is off: opens the
// receive window for what was read, and frees the link when its host is gone and all
// of its input has been read.
void service();

// The next byte from the host, or -1.
int read();

// Sends the reply bytes queued since the last call.
void flush();

// The host's protocol link (line buffer and reply path).
ProtocolLink &link();

// True and *addr if a host has the link.
bool hostAddress(ip_addr_t *addr);

}  // namespace tcplink
