// PiEBV network check: the REAL TCP link (src/tcp_link.cpp) and command protocol
// (src/protocol.cpp) on a computer, against a model of lwIP (fake/).
//
// It checks the connection handling that cannot be seen in the simulator: what happens
// to input and replies when a host resets or closes the connection, when a second host
// connects, and when lwIP has no memory. The model fails the check when the code calls
// lwIP without the lock, or uses a connection it has given up or that lwIP has freed.
//
// It is a model: it does not show that lwIP or the radio behave as modelled. See
// README.md for what it covers and how to build it.
#include "Arduino.h"
#include "lwip/tcp.h"
#include "lwip_wrap.h"
#include "protocol.h"
#include "tcp_link.h"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <string>
#include <vector>

// ---------------------------------------------------------------- test support
FakeSerial Serial;  // not used by the code under test; fake/Arduino.h declares it
static uint64_t g_nowUs = 1000000;
uint64_t time_us_64() { return g_nowUs += 5; }  // every look at the clock takes 5 us
void fake_advance_us(uint64_t us) { g_nowUs += us; }

static int g_failures = 0;
static const char *g_case = "";
#define CHECK(cond)                                                                      \
    do {                                                                                 \
        if (!(cond)) {                                                                   \
            ++g_failures;                                                                \
            printf("FAIL [%s] line %d: %s\n", g_case, __LINE__, #cond);                  \
        }                                                                                \
    } while (0)

// ---------------------------------------------------------------- lwIP model
int LWIPMutex::depth = 0;
static int g_inCallback = 0;  // lwIP's background work holds the lock while it calls back
static bool g_writeFails = false;  // tcp_write() returns ERR_MEM
static int g_pbufsLive = 0;
static std::vector<std::unique_ptr<tcp_pcb>> g_pcbs;  // kept for the whole run, so a late use is seen
static tcp_pcb *g_listener = nullptr;

static void use(tcp_pcb *pcb, const char *what) {
    if (LWIPMutex::depth == 0 && g_inCallback == 0) {
        ++g_failures;
        printf("FAIL [%s] %s without the lwIP lock\n", g_case, what);
    }
    if (!pcb || pcb->gone) {
        ++g_failures;
        printf("FAIL [%s] %s on a connection that is gone\n", g_case, what);
    }
}

tcp_pcb *tcp_new() {
    g_pcbs.push_back(std::make_unique<tcp_pcb>());
    g_pcbs.back()->state = CLOSED;
    return g_pcbs.back().get();
}
err_t tcp_bind(tcp_pcb *pcb, const ip_addr_t *, u16_t) {
    use(pcb, "tcp_bind");
    return ERR_OK;
}
tcp_pcb *tcp_listen_with_backlog(tcp_pcb *pcb, u8_t) {
    use(pcb, "tcp_listen");
    pcb->state = LISTEN;
    g_listener = pcb;
    return pcb;
}
void tcp_accept(tcp_pcb *pcb, tcp_accept_fn fn) {
    use(pcb, "tcp_accept");
    pcb->accept = fn;
}
void tcp_arg(tcp_pcb *pcb, void *arg) {
    use(pcb, "tcp_arg");
    pcb->arg = arg;
}
void tcp_recv(tcp_pcb *pcb, tcp_recv_fn fn) {
    use(pcb, "tcp_recv");
    pcb->recv = fn;
}
void tcp_sent(tcp_pcb *pcb, tcp_sent_fn fn) {
    use(pcb, "tcp_sent");
    pcb->sent = fn;
}
void tcp_err(tcp_pcb *pcb, tcp_err_fn fn) {
    use(pcb, "tcp_err");
    pcb->errf = fn;
}
void tcp_poll(tcp_pcb *pcb, tcp_poll_fn fn, u8_t) {
    use(pcb, "tcp_poll");
    pcb->poll = fn;
}
err_t tcp_write(tcp_pcb *pcb, const void *data, u16_t len, u8_t) {
    use(pcb, "tcp_write");
    if (pcb->state != ESTABLISHED && pcb->state != CLOSE_WAIT) {
        ++g_failures;
        printf("FAIL [%s] tcp_write in state %d\n", g_case, (int)pcb->state);
        return ERR_ARG;
    }
    if (pcb->txClosed) {
        ++g_failures;
        printf("FAIL [%s] tcp_write after the sending side was closed\n", g_case);
        return ERR_ARG;
    }
    if (g_writeFails || len > pcb->snd_buf) {
        return ERR_MEM;
    }
    pcb->out.append((const char *)data, len);
    pcb->snd_buf = (u16_t)(pcb->snd_buf - len);
    pcb->unsent = pcb;
    return ERR_OK;
}
err_t tcp_output(tcp_pcb *pcb) {
    use(pcb, "tcp_output");
    if (pcb->unsent) {
        pcb->unsent = nullptr;
        pcb->unacked = pcb;
    }
    pcb->sentBytes = pcb->out.size();
    return ERR_OK;
}
void tcp_recved(tcp_pcb *pcb, u16_t len) {
    use(pcb, "tcp_recved");
    pcb->recved += len;
}
err_t tcp_shutdown(tcp_pcb *pcb, int shutRx, int shutTx) {
    use(pcb, "tcp_shutdown");
    if (shutRx || !shutTx) {
        ++g_failures;
        printf("FAIL [%s] tcp_shutdown: only the sending side is modelled\n", g_case);
    }
    tcp_output(pcb);  // lwIP sends what is queued, then FIN; the receiving side stays open
    pcb->txClosed = true;
    return ERR_OK;
}
err_t tcp_close(tcp_pcb *pcb) {
    use(pcb, "tcp_close");
    if (pcb->state == LISTEN) {
        g_listener = nullptr;
    } else {
        tcp_output(pcb);  // lwIP sends what is queued, then FIN
    }
    pcb->closed = true;
    pcb->gone = true;
    return ERR_OK;
}
void tcp_abort(tcp_pcb *pcb) {
    use(pcb, "tcp_abort");
    pcb->aborted = true;
    pcb->gone = true;
    if (pcb->errf) {  // as lwIP: the error callback runs, with the connection already freed
        pcb->errf(pcb->arg, ERR_ABRT);
    }
}
u8_t pbuf_free(pbuf *p) {
    while (p) {
        pbuf *next = p->next;
        free(p->payload);
        delete p;
        --g_pbufsLive;
        p = next;
    }
    return 1;
}

// --- what the network does (lwIP's background work)
struct Bg {
    Bg() { ++g_inCallback; }
    ~Bg() { --g_inCallback; }
};

// A host connects. Returns its connection, or nullptr if the listener is gone.
static tcp_pcb *hostConnects(err_t *result = nullptr) {
    if (!g_listener || !g_listener->accept) {
        return nullptr;
    }
    g_pcbs.push_back(std::make_unique<tcp_pcb>());
    tcp_pcb *pcb = g_pcbs.back().get();
    pcb->remote_ip.addr = 0x0A000001u + (uint32_t)g_pcbs.size();
    Bg bg;
    const err_t r = g_listener->accept(g_listener->arg, pcb, ERR_OK);
    if (result) {
        *result = r;
    }
    if (r != ERR_OK && !pcb->gone) {  // as lwIP: an accept error other than ERR_ABRT aborts
        tcp_abort(pcb);
    }
    return pcb;
}

// The host sends text, as a chain of two buffers. Returns what the receive callback
// returned (the model then keeps or frees the data as lwIP does).
static err_t hostSends(tcp_pcb *pcb, const std::string &text) {
    if (pcb->gone || !pcb->recv) {
        return ERR_ABRT;
    }
    const size_t n1 = text.size() / 2, n2 = text.size() - n1;
    pbuf *second = nullptr;
    if (n2) {
        second = new pbuf{nullptr, malloc(n2), (u16_t)n2, (u16_t)n2};
        memcpy(second->payload, text.data() + n1, n2);
        ++g_pbufsLive;
    }
    pbuf *first = second;
    if (n1) {
        first = new pbuf{second, malloc(n1), (u16_t)text.size(), (u16_t)n1};
        memcpy(first->payload, text.data(), n1);
        ++g_pbufsLive;
    }
    Bg bg;
    const err_t r = pcb->recv(pcb->arg, pcb, first, ERR_OK);
    if (r != ERR_OK && r != ERR_ABRT) {
        pbuf_free(first);  // lwIP would keep it and offer it again; the check drops it
    }
    return r;
}

static void hostCloses(tcp_pcb *pcb) {  // FIN: the host closes its sending side
    if (pcb->gone || !pcb->recv) {
        return;
    }
    pcb->state = CLOSE_WAIT;
    Bg bg;
    pcb->recv(pcb->arg, pcb, nullptr, ERR_OK);
}

static void hostResets(tcp_pcb *pcb) {  // RST, or lwIP's own time-out: lwIP frees, then tells
    if (pcb->gone) {
        return;
    }
    pcb->gone = true;
    Bg bg;
    if (pcb->errf) {
        pcb->errf(pcb->arg, ERR_RST);
    }
}

static void hostAcks(tcp_pcb *pcb) {  // the host acknowledges everything that was sent
    if (pcb->gone) {
        return;
    }
    const bool had = pcb->unacked != nullptr;
    pcb->unacked = nullptr;
    pcb->snd_buf = (u16_t)(TCP_SND_BUF - (pcb->out.size() - pcb->sentBytes));
    Bg bg;
    if (had && pcb->sent) {
        pcb->sent(pcb->arg, pcb, 1);
    }
}

static void pollFires(tcp_pcb *pcb) {
    if (pcb->gone || !pcb->poll) {
        return;
    }
    Bg bg;
    pcb->poll(pcb->arg, pcb);
}

// ---------------------------------------------------------------- the firmware side
static bool g_armed = false;
static Protocol g_protocol;
static PulseParams g_params;

// One pass of main.cpp's loop() for the network link.
static void loopPass() {
    tcplink::service();
    const uint64_t t0 = time_us_64();
    for (int n = 0, c; n < 128 && (c = tcplink::read()) >= 0; ++n) {
        tcplink::link().setInputPending(tcplink::inputPending());
        g_protocol.feed(tcplink::link(), (char)c);
        if (time_us_64() - t0 >= 5000) {  // kLinkTurnUs
            break;
        }
    }
    tcplink::flush();
}

static bool linkHasHost() {
    ip_addr_t a;
    return tcplink::hostAddress(&a);
}

static const char kBusy[] = "ERR busy: another host is connected\r\n";

int main() {
    ProtocolHooks hooks{};
    hooks.apply = [](const PulseParams &p, RealizedTiming *r) { return realizeTiming(p, 150000000, r); };
    hooks.setArmed = [](bool arm) -> const char * {
        g_armed = arm;
        return nullptr;
    };
    hooks.isArmed = [] { return g_armed; };
    CHECK(g_protocol.begin(&g_params, hooks) == nullptr);
    CHECK(tcplink::start(4242));
    CHECK(g_listener != nullptr);

    g_case = "command and reply";
    tcp_pcb *a = hostConnects();
    CHECK(linkHasHost());
    CHECK((a->so_options & SOF_KEEPALIVE) && a->keep_idle == 5000 && a->keep_intvl == 2000 && a->keep_cnt == 3);
    hostSends(a, "ARM\n");
    loopPass();
    CHECK(g_armed);
    CHECK(a->out == "OK ARMED=1\r\n" && a->sentBytes == a->out.size());
    loopPass();
    CHECK(a->recved == 4);  // the window is open again for what was read
    hostAcks(a);

    g_case = "DISARM, then a reset, before the loop reads";
    hostSends(a, "DISARM\n");
    hostResets(a);
    CHECK(g_armed);       // not read yet
    CHECK(linkHasHost()); // the link is held until the input is read
    loopPass();
    CHECK(!g_armed);      // the input that arrived was run
    loopPass();
    CHECK(!linkHasHost());

    g_case = "a host that connects and closes at once";
    tcp_pcb *b = hostConnects();
    hostCloses(b);
    loopPass();
    CHECK(b->closed && !b->aborted && !linkHasHost());
    tcp_pcb *c = hostConnects();
    hostResets(c);
    loopPass();
    CHECK(!linkHasHost());

    g_case = "half-close: the reply goes out, then an orderly close";
    tcp_pcb *d = hostConnects();
    hostSends(d, "ARM?\n");
    hostCloses(d);
    loopPass();
    CHECK(d->out == "ARMED=0\r\n" && !d->gone);
    loopPass();
    CHECK(d->closed && !d->aborted && d->recved == 5 && d->sentBytes == d->out.size());
    CHECK(!linkHasHost());

    g_case = "a partial line does not reach the next host";
    tcp_pcb *e = hostConnects();
    hostSends(e, "AR");
    loopPass();
    hostResets(e);
    loopPass();
    loopPass();
    tcp_pcb *f = hostConnects();
    CHECK(linkHasHost());
    hostSends(f, "M\n");
    loopPass();
    CHECK(!g_armed);
    CHECK(f->out.rfind("ERR M unknown command", 0) == 0);

    g_case = "a second host";
    err_t r = ERR_OK;
    tcp_pcb *g = hostConnects(&r);
    CHECK(r == ERR_OK && g->out == kBusy && !g->gone);
    hostSends(g, "ARM\n");  // taken and discarded
    loopPass();
    CHECK(!g_armed && g->recved == 4 && g_pbufsLive == 0);
    hostAcks(g);            // the host has the line: our FIN goes out, we still listen
    CHECK(g->txClosed && !g->gone);
    hostCloses(g);          // the host closes: now the connection is given up
    CHECK(g->closed && !g->aborted);
    hostSends(f, "ARM?\n"); // the first host is not disturbed
    loopPass();
    CHECK(f->out.find("ARMED=0\r\n") != std::string::npos);

    g_case = "more second hosts than the limit";
    tcp_pcb *h1 = hostConnects(), *h2 = hostConnects();
    tcp_pcb *h3 = hostConnects(&r);
    CHECK(!h1->gone && !h2->gone && h1->out == kBusy && h2->out == kBusy);
    CHECK(r == ERR_ABRT && h3->aborted && h3->out.empty());
    pollFires(h1);          // did not take the line in time
    CHECK(h1->aborted);
    hostResets(h2);
    hostCloses(hostConnects(&r));  // the two places are free again: this one closes first
    CHECK(r == ERR_OK && g_pcbs.back()->closed);
    tcp_pcb *h5 = hostConnects(&r), *h6 = hostConnects(&r);
    CHECK(r == ERR_OK && h5->out == kBusy && h6->out == kBusy);
    hostAcks(h5);           // both read the line and keep their sockets open:
    hostAcks(h6);           // they still hold their places ...
    tcp_pcb *h7 = hostConnects(&r);
    CHECK(r == ERR_ABRT && h7->aborted && h5->txClosed && !h5->gone);
    pollFires(h5);          // ... until the time limit
    pollFires(h6);
    CHECK(h5->aborted && h6->aborted);
    hostCloses(hostConnects(&r));
    CHECK(r == ERR_OK);

    g_case = "lwIP has no memory: one bounded wait, then none";
    hostAcks(f);
    g_writeFails = true;
    uint64_t t0 = g_nowUs;
    hostSends(f, "HELP\n");
    loopPass();
    uint64_t dt = g_nowUs - t0;
    CHECK(dt >= 250000 && dt < 300000);  // the reply budget, once
    CHECK(tcplink::link().stalled());
    t0 = g_nowUs;
    hostSends(f, "STATUS\nHELP\n");
    for (int i = 0; i < 20; ++i) {
        loopPass();
    }
    CHECK(g_nowUs - t0 < 20000);         // no second wait
    hostSends(f, "ARM\n");               // commands still run
    loopPass();
    loopPass();
    CHECK(g_armed);
    g_writeFails = false;
    hostAcks(f);
    fake_advance_us(2500000);            // the memory hold time
    const size_t before = f->out.size();
    hostSends(f, "DISARM\n");
    loopPass();
    CHECK(!g_armed && f->out.size() > before && !tcplink::link().stalled());

    g_case = "more input than the buffer, in pieces";
    {
        std::string line = "ARM?\n", all;
        size_t replies = 0;
        loopPass();  // the window is open for everything read so far
        hostAcks(f);
        const size_t start = f->out.size(), recvedStart = f->recved;
        for (int round = 0; round < 40; ++round) {
            // The host sends as much as the open window allows, like a real one.
            const size_t window = TCP_WND - (all.size() - (f->recved - recvedStart));
            std::string chunk;
            while (chunk.size() + line.size() <= window && chunk.size() < 3000) {
                chunk += line;
            }
            if (!chunk.empty()) {
                CHECK(hostSends(f, chunk) == ERR_OK);
                all += chunk;
            }
            for (int i = 0; i < 8; ++i) {
                loopPass();
                hostAcks(f);
            }
        }
        for (int i = 0; i < 400; ++i) {
            loopPass();
            hostAcks(f);
        }
        const std::string got = f->out.substr(start);
        for (size_t pos = 0; (pos = got.find("ARMED=0\r\n", pos)) != std::string::npos; pos += 9) {
            ++replies;
        }
        CHECK(all.size() > 3 * TCP_WND);
        CHECK(replies == all.size() / line.size());  // every command was read, in order, once
        CHECK(got.size() == replies * 9);
        CHECK(f->recved - recvedStart == all.size());
        CHECK(g_pbufsLive == 0);
    }

    g_case = "radio fault: input that has arrived still runs";
    hostSends(f, "ARM\n");
    loopPass();
    CHECK(g_armed);
    hostSends(f, "DISARM\n");
    tcplink::stop(true);
    CHECK(f->aborted && g_armed);
    err_t stopped = ERR_OK;
    tcp_pcb *late = hostConnects(&stopped);  // the listening socket stays, but takes no host
    CHECK(stopped == ERR_ABRT && late->aborted);
    loopPass();
    CHECK(!g_armed);
    loopPass();
    CHECK(!linkHasHost());
    CHECK(tcplink::start(4242));
    f = hostConnects();
    CHECK(linkHasHost());

    g_case = "stop with a host connected, then start again";
    hostSends(f, "ARM");
    tcplink::stop(false);
    CHECK(f->aborted && !linkHasHost());
    hostConnects(&stopped);
    CHECK(stopped == ERR_ABRT);
    loopPass();
    CHECK(!g_armed);
    CHECK(tcplink::start(4242));
    tcp_pcb *k = hostConnects();
    hostSends(k, "\nARM?\n");  // nothing of "ARM" is left
    loopPass();
    CHECK(k->out == "ARMED=0\r\n");
    tcplink::stop(false);
    tcplink::stop(true);  // twice is harmless

    CHECK(LWIPMutex::depth == 0 && g_pbufsLive == 0);
    if (g_failures) {
        printf("%d check(s) FAILED\n", g_failures);
        return 1;
    }
    printf("net_check: all checks passed\n");
    return 0;
}
