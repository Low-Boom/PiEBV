#include "tcp_link.h"

#if defined(ARDUINO_RASPBERRY_PI_PICO_2W) || defined(PIEBV_NET_CHECK)

#include <lwip/tcp.h>
#include <lwip_wrap.h>  // LWIPMutex

// Everything that touches g_conn or an lwIP connection runs with the lwIP lock held:
// the callbacks (lwIP calls them from its background work, which holds the lock) and
// the main-loop functions (LWIPMutex). The lock is recursive.
//
// Input is copied into g_conn.rx as it arrives, and the receive window opens again
// only as the main loop reads it (tcp_recved() in service()). The buffer is as large
// as the window, so it cannot overflow.

namespace {

// Free send-buffer space that counts as "the host reads again" after a reply was
// dropped: room for the longest reply (HELP, about 3.3 kB) in one piece, so a host
// that drains slowly cannot make every command wait out its reply budget.
constexpr int kDrainedRoom = 4096;
static_assert(kDrainedRoom < TCP_SND_BUF, "the send buffer must be able to reach the drained level");
// After lwIP refused a write for lack of memory, no room is reported for at least this
// long, so that the wait for memory (ReplyOut's reply budget) is not repeated at once.
constexpr uint32_t kNoMemoryHoldMs = 2000;
// TCP keep-alive: a host that went away without closing (crash, cable, sleep) frees
// the link after about 5 + 3 x 2 = 11 s of silence.
constexpr uint32_t kKeepAliveIdleMs = 5000, kKeepAliveIntervalMs = 2000, kKeepAliveCount = 3;
// A second host gets the "busy" line and is closed. At most this many such connections
// at a time (each holds an lwIP segment), each for at most kRejectPollTicks x 0.5 s.
constexpr int kMaxRejecting = 2;
constexpr uint8_t kRejectPollTicks = 4;

struct Conn {
    tcp_pcb *pcb = nullptr;      // nullptr: no host, or its connection ended (reset, time-out)
    volatile bool open = false;  // a host has the link, until the loop has read its last input
    bool peerClosed = false;     // the host closed its sending side (FIN)
    uint8_t rx[TCP_WND];
    size_t rxHead = 0, rxCount = 0;
    size_t consumed = 0;         // bytes read since the last tcp_recved()
    size_t unsent = 0;           // bytes queued since the last tcp_output()
    bool noMemory = false;       // lwIP refused a write for lack of memory ...
    uint32_t noMemoryMs = 0;     // ... at this time (millis)
    ip_addr_t remote;
};
Conn g_conn;
tcp_pcb *g_listen = nullptr;
int g_rejecting = 0;  // "busy" connections that are not closed yet

err_t onRecv(void *, tcp_pcb *pcb, pbuf *p, err_t err) {
    if (pcb != g_conn.pcb) {  // not the link's connection: cannot happen
        if (p) {
            pbuf_free(p);
        }
        tcp_err(pcb, nullptr);
        tcp_abort(pcb);
        return ERR_ABRT;
    }
    if (!p) {
        g_conn.peerClosed = true;  // the loop closes after it has read the input
        return ERR_OK;
    }
    if (err != ERR_OK) {
        pbuf_free(p);
        return err;
    }
    if (p->tot_len > sizeof(g_conn.rx) - g_conn.rxCount) {
        return ERR_MEM;  // cannot happen (window = buffer size); lwIP keeps p and offers it again
    }
    for (const pbuf *q = p; q; q = q->next) {
        const uint8_t *src = (const uint8_t *)q->payload;
        for (u16_t i = 0; i < q->len; ++i) {
            g_conn.rx[(g_conn.rxHead + g_conn.rxCount++) % sizeof(g_conn.rx)] = src[i];
        }
    }
    pbuf_free(p);
    return ERR_OK;
}

// lwIP has already freed the connection (reset by the host, keep-alive or retransmit
// time-out). Input in the buffer stays for the loop.
void onErr(void *, err_t) {
    g_conn.pcb = nullptr;
}

// --- a second host: one line of text, then close
void rejectDetach(tcp_pcb *pcb) {
    tcp_recv(pcb, nullptr);
    tcp_sent(pcb, nullptr);
    tcp_err(pcb, nullptr);
    tcp_poll(pcb, nullptr, 0);
    --g_rejecting;
}

err_t rejectClose(tcp_pcb *pcb) {
    rejectDetach(pcb);
    if (tcp_close(pcb) != ERR_OK) {
        tcp_abort(pcb);
        return ERR_ABRT;
    }
    return ERR_OK;
}

err_t onRejectRecv(void *, tcp_pcb *pcb, pbuf *p, err_t) {
    if (!p) {
        return rejectClose(pcb);  // the host closed first
    }
    // Take and discard what the host sends: a close with unread input would reset the
    // connection, and the host could lose the "busy" line.
    tcp_recved(pcb, p->tot_len);
    pbuf_free(p);
    return ERR_OK;
}

err_t onRejectSent(void *, tcp_pcb *pcb, u16_t) {
    return rejectClose(pcb);  // the host has the line
}

err_t onRejectPoll(void *, tcp_pcb *pcb) {  // the host did not take the line in time
    rejectDetach(pcb);
    tcp_abort(pcb);
    return ERR_ABRT;
}

void onRejectErr(void *, err_t) {
    --g_rejecting;
}

err_t onAccept(void *, tcp_pcb *pcb, err_t err) {
    if (err != ERR_OK || !pcb) {
        return ERR_VAL;
    }
    tcp_arg(pcb, nullptr);
    if (g_conn.open) {  // one host at a time; the first one keeps the link
        static const char kBusy[] = "ERR busy: another host is connected\r\n";
        if (g_rejecting >= kMaxRejecting ||
            tcp_write(pcb, kBusy, sizeof(kBusy) - 1, TCP_WRITE_FLAG_COPY) != ERR_OK) {
            tcp_abort(pcb);
            return ERR_ABRT;
        }
        ++g_rejecting;
        tcp_recv(pcb, onRejectRecv);
        tcp_sent(pcb, onRejectSent);
        tcp_err(pcb, onRejectErr);
        tcp_poll(pcb, onRejectPoll, kRejectPollTicks);
        tcp_output(pcb);
        return ERR_OK;
    }
    // The link is free: its last host was closed by connEnd(), which also cleared the
    // buffer and the protocol link's line.
    g_conn.pcb = pcb;
    g_conn.peerClosed = false;
    ip_addr_copy(g_conn.remote, pcb->remote_ip);
    tcp_recv(pcb, onRecv);
    tcp_err(pcb, onErr);
    tcp_nagle_disable(pcb);  // flushConn() decides when a reply goes out
    ip_set_option(pcb, SOF_KEEPALIVE);
    pcb->keep_idle = kKeepAliveIdleMs;
    pcb->keep_intvl = kKeepAliveIntervalMs;
    pcb->keep_cnt = kKeepAliveCount;
    g_conn.open = true;
    return ERR_OK;
}

// Replies can go out while the connection is open in our direction: established, or
// the host has closed its sending side only (CLOSE_WAIT), e.g. `echo STATUS | nc -N`.
bool canSend(const tcp_pcb *pcb) {
    return pcb && (pcb->state == ESTABLISHED || pcb->state == CLOSE_WAIT);
}

class TcpSink final : public ReplySink {
public:
    bool connected() override {
        if (!g_conn.open) {
            return false;
        }
        LWIPMutex lock;
        return canSend(g_conn.pcb);
    }
    int room() override {
        LWIPMutex lock;
        tcp_pcb *pcb = g_conn.pcb;
        if (!canSend(pcb)) {
            return 0;
        }
        if (g_conn.noMemory) {
            // Until the host has acknowledged everything (the memory of this
            // connection is back) and the hold time is over (memory that other
            // connections hold has had time to come back).
            if (pcb->unacked != nullptr || pcb->unsent != nullptr || millis() - g_conn.noMemoryMs < kNoMemoryHoldMs) {
                return 0;
            }
            g_conn.noMemory = false;
        }
        return (int)tcp_sndbuf(pcb);
    }
    // All or nothing, and never waits for the host: 0 when lwIP cannot take the whole
    // line now (no room, or no memory for a segment). The bytes are only queued here;
    // flushConn() sends them, so the lines of one reply share segments. (One segment
    // per line would use a full-size lwIP buffer for each line until the host
    // acknowledges it.)
    size_t write(const uint8_t *buf, size_t n) override {
        LWIPMutex lock;
        tcp_pcb *pcb = g_conn.pcb;
        if (!canSend(pcb) || tcp_sndbuf(pcb) < n) {
            return 0;
        }
        if (tcp_write(pcb, buf, (u16_t)n, TCP_WRITE_FLAG_COPY) != ERR_OK) {
            g_conn.noMemory = true;
            g_conn.noMemoryMs = millis();
            g_conn.unsent = 0;
            tcp_output(pcb);  // what is queued must go out for its memory to come back
            return 0;
        }
        g_conn.unsent += n;
        if (g_conn.unsent >= TCP_MSS) {  // a full segment is ready: send it, so that its space comes back
            g_conn.unsent = 0;
            tcp_output(pcb);
        }
        return n;
    }
    int drainedRoom() override { return kDrainedRoom; }
};
TcpSink g_sink;
ProtocolLink g_link(g_sink, false);

void flushConn() {
    if (g_conn.unsent == 0) {
        return;
    }
    LWIPMutex lock;
    g_conn.unsent = 0;
    if (g_conn.pcb) {
        tcp_output(g_conn.pcb);
    }
}

// Ends the host's use of the link. `abort` false: an orderly close, which sends the
// queued replies and then FIN. `abort` true: a reset, which frees the connection's
// memory at once. Unread input is discarded: the callers make sure that none is left,
// except when the radio is switched off.
void connEnd(bool abort) {
    {
        LWIPMutex lock;
        if (tcp_pcb *pcb = g_conn.pcb) {
            g_conn.pcb = nullptr;
            tcp_recv(pcb, nullptr);
            tcp_err(pcb, nullptr);
            if (!abort && g_conn.consumed) {
                tcp_recved(pcb, (u16_t)g_conn.consumed);  // window fully open: the close sends no reset
            }
            if (abort || tcp_close(pcb) != ERR_OK) {
                tcp_abort(pcb);
            }
        }
        g_conn.peerClosed = false;
        g_conn.rxHead = g_conn.rxCount = 0;
        g_conn.consumed = 0;
        g_conn.unsent = 0;
        g_conn.noMemory = false;
        g_conn.open = false;  // last: from here on onAccept() can give the link to a new host
    }
    g_link.reset();
}

// From loop(): opens the receive window for what was read, and closes the link when
// its host is gone and its last input has been read (and run: loop() calls this before
// the link's read turn, so the input read in one pass is run before the next pass).
void serviceConn() {
    if (!g_conn.open) {
        return;
    }
    bool ended = false;
    {
        LWIPMutex lock;
        if (g_conn.consumed) {
            if (g_conn.pcb) {
                tcp_recved(g_conn.pcb, (u16_t)g_conn.consumed);
            }
            g_conn.consumed = 0;
        }
        ended = g_conn.rxCount == 0 && (g_conn.pcb == nullptr || g_conn.peerClosed);
    }
    if (ended) {
        connEnd(false);
    }
}

}  // namespace

namespace tcplink {

bool start(uint16_t port) {
    LWIPMutex lock;
    tcp_pcb *pcb = tcp_new();
    if (!pcb) {
        return false;
    }
    ip_set_option(pcb, SOF_REUSEADDR);
    if (tcp_bind(pcb, IP_ANY_TYPE, port) != ERR_OK) {
        tcp_close(pcb);
        return false;
    }
    tcp_pcb *listen = tcp_listen_with_backlog(pcb, 2);  // frees pcb, or leaves it on failure
    if (!listen) {
        tcp_close(pcb);
        return false;
    }
    g_listen = listen;
    tcp_accept(listen, onAccept);
    return true;
}

void stop(bool keepInput) {
    if (keepInput) {
        LWIPMutex lock;
        if (tcp_pcb *pcb = g_conn.pcb) {  // as a reset by the host: serviceConn() ends the link
            g_conn.pcb = nullptr;
            tcp_recv(pcb, nullptr);
            tcp_err(pcb, nullptr);
            tcp_abort(pcb);
        }
    } else {
        connEnd(true);
    }
    LWIPMutex lock;
    if (g_listen) {
        tcp_accept(g_listen, nullptr);
        tcp_close(g_listen);
        g_listen = nullptr;
    }
}

void service() {
    serviceConn();
}

int read() {
    if (!g_conn.open) {
        return -1;
    }
    LWIPMutex lock;
    if (g_conn.rxCount == 0) {
        return -1;
    }
    const uint8_t c = g_conn.rx[g_conn.rxHead];
    g_conn.rxHead = (g_conn.rxHead + 1) % sizeof(g_conn.rx);
    --g_conn.rxCount;
    ++g_conn.consumed;
    return c;
}

void flush() {
    flushConn();
}

ProtocolLink &link() {
    return g_link;
}

bool hostAddress(ip_addr_t *addr) {
    if (!g_conn.open) {
        return false;
    }
    LWIPMutex lock;  // the caller prints after this returns: a reply write can wait for the host
    ip_addr_copy(*addr, g_conn.remote);
    return true;
}

}  // namespace tcplink

#endif
