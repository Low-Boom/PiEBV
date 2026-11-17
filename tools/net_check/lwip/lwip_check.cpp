// PiEBV network check against lwIP itself: the REAL src/tcp_link.cpp and
// src/protocol.cpp, linked with the lwIP sources that the firmware uses (the pico-sdk's
// lwIP, with the firmware's TCP and memory options, inc/lwipopts.h). The "network" is
// hand-made TCP segments put into a raw-IP interface, and the hosts are small records
// of what they were sent.
//
// It shows what the model in ../net_check.cpp cannot: lwIP's own states and limits
// (closing connections, the connection pool, the heap, the receive window, keep-alive).
// It has no Ethernet, ARP, DHCP or radio driver, and lwIP's work runs only when the
// check calls it, never in the middle of a firmware function. See ../README.md.
//
// Run all cases: ./lwip_check     One case: ./lwip_check <name>   (see `only ==` below)
#include "Arduino.h"
extern "C" {
#include "lwip/init.h"
#include "lwip/netif.h"
#include "lwip/tcp.h"
#include "lwip/priv/tcp_priv.h"
#include "lwip/timeouts.h"
#include "lwip/ip4.h"
#include "lwip/ip.h"
#include "lwip/mem.h"
#include "lwip/pbuf.h"
}
#include "lwip_wrap.h"
#include "protocol.h"
#include "tcp_link.h"

#include <cstdio>
#include <cstring>
#include <map>
#include <string>
#include <vector>

FakeSerial Serial;
static uint64_t g_nowUs = 1000000;
uint64_t time_us_64() { return g_nowUs += 5; }
extern "C" u32_t sys_now(void) { return (u32_t)(g_nowUs / 1000); }
extern "C" unsigned int lwip_test_rand(void) { return (unsigned)rand(); }

// The check does not free its host records: no leak report (build.sh uses the address sanitizer).
extern "C" const char *__asan_default_options() { return "detect_leaks=0"; }

int LWIPMutex::depth = 0;
LWIPMutex::~LWIPMutex() { --depth; }

static int g_fail = 0;
static const char *g_case = "";
#define CHECK(c) do { if (!(c)) { ++g_fail; printf("FAIL [%s] line %d: %s\n", g_case, __LINE__, #c); } } while (0)
#define NOTE(...) do { printf("  [%s] ", g_case); printf(__VA_ARGS__); printf("\n"); } while (0)

static netif g_nif;
static const uint32_t kDevIp = 0x0A000001, kHostIpBase = 0x0A000002;
static const uint16_t kPort = 4242;

struct Seg { uint8_t flags; uint32_t seq, ack; uint16_t wnd; std::string data; };
struct Host {
    uint32_t ip; uint16_t port;
    uint32_t snd_nxt = 1000, rcv_nxt = 0;
    std::vector<Seg> rx; std::string got; bool gotFin = false, gotRst = false, gotSynAck = false;
    uint16_t peerWnd = 0; int frames = 0;
    bool freezeAck = false; uint32_t frozenAck = 0;
};
static std::map<uint32_t, Host *> g_hosts;  // key: ip<<16 ^ port

static err_t nifOut(netif *, pbuf *p, const ip4_addr_t *) {
    std::vector<uint8_t> b(p->tot_len);
    pbuf_copy_partial(p, b.data(), p->tot_len, 0);
    if (b.size() < 40 || b[9] != 6) return ERR_OK;
    const uint32_t dip = (b[16] << 24) | (b[17] << 16) | (b[18] << 8) | b[19];
    const uint16_t dport = (b[22] << 8) | b[23];
    auto it = g_hosts.find((dip << 16) ^ dport);
    if (it == g_hosts.end()) return ERR_OK;
    Host &h = *it->second;
    const uint8_t *t = &b[20];
    Seg s;
    s.seq = (t[4] << 24) | (t[5] << 16) | (t[6] << 8) | t[7];
    s.ack = (t[8] << 24) | (t[9] << 16) | (t[10] << 8) | t[11];
    const int hl = (t[12] >> 4) * 4;
    s.flags = t[13];
    s.wnd = (t[14] << 8) | t[15];
    s.data.assign((const char *)t + hl, b.size() - 20 - hl);
    ++h.frames;
    h.peerWnd = s.wnd;
    if (s.flags & TCP_RST) h.gotRst = true;
    if (s.flags & TCP_SYN) { h.rcv_nxt = s.seq + 1; h.gotSynAck = true; }
    else {
        if (!s.data.empty() && s.seq == h.rcv_nxt) { h.got += s.data; h.rcv_nxt += s.data.size(); }
        if ((s.flags & TCP_FIN) && s.seq + s.data.size() == h.rcv_nxt) { h.rcv_nxt++; h.gotFin = true; }
    }
    h.rx.push_back(s);
    return ERR_OK;
}
static err_t nifInit(netif *n) { n->output = nifOut; n->mtu = 1500; n->name[0] = 't'; n->name[1] = '0'; return ERR_OK; }

static void inject(Host &h, uint8_t flags, const std::string &data = "") {
    const size_t opt = (flags & TCP_SYN) ? 4 : 0;  // MSS option on the SYN, like a real host
    std::vector<uint8_t> b(40 + opt + data.size(), 0);
    b[0] = 0x45; const uint16_t tot = (uint16_t)b.size(); b[2] = tot >> 8; b[3] = tot & 0xff; b[8] = 64; b[9] = 6;
    b[12] = h.ip >> 24; b[13] = h.ip >> 16; b[14] = h.ip >> 8; b[15] = h.ip;
    b[16] = 10; b[17] = 0; b[18] = 0; b[19] = kDevIp & 0xff;
    uint8_t *t = &b[20];
    t[0] = h.port >> 8; t[1] = h.port & 0xff; t[2] = kPort >> 8; t[3] = kPort & 0xff;
    t[4] = h.snd_nxt >> 24; t[5] = h.snd_nxt >> 16; t[6] = h.snd_nxt >> 8; t[7] = h.snd_nxt;
    const uint32_t ack = h.freezeAck ? h.frozenAck : h.rcv_nxt;
    if (flags & TCP_ACK) { t[8] = ack >> 24; t[9] = ack >> 16; t[10] = ack >> 8; t[11] = ack; }
    t[12] = (uint8_t)((5 + opt / 4) << 4); t[13] = flags; t[14] = 0xff; t[15] = 0xff;
    if (opt) { t[20] = 2; t[21] = 4; t[22] = 1460 >> 8; t[23] = 1460 & 0xff; }
    memcpy(t + 20 + opt, data.data(), data.size());
    h.snd_nxt += data.size() + ((flags & (TCP_SYN | TCP_FIN)) ? 1 : 0);
    pbuf *p = pbuf_alloc(PBUF_RAW, (u16_t)b.size(), PBUF_POOL);
    if (!p) { printf("  (inject: no pbuf)\n"); return; }
    pbuf_take(p, b.data(), (u16_t)b.size());
    LWIPMutex bg;  // lwIP's background work holds the lock
    if (g_nif.input(p, &g_nif) != ERR_OK) pbuf_free(p);
}
static int g_nextPort = 50000;
static Host *newHost() {
    Host *h = new Host; h->ip = kHostIpBase; h->port = (uint16_t)g_nextPort++;
    g_hosts[(h->ip << 16) ^ h->port] = h;
    return h;
}
static Host *connect() {
    Host *h = newHost();
    inject(*h, TCP_SYN);
    if (h->gotSynAck) inject(*h, TCP_ACK);
    return h;
}
static void advance(uint32_t ms) {
    for (uint32_t i = 0; i < ms; i += 10) { g_nowUs += 10000; LWIPMutex bg; sys_check_timeouts(); }
}

static bool g_armed = false;
static Protocol g_protocol;
static PulseParams g_params;
static void loopPass() {
    tcplink::service();
    const uint64_t t0 = time_us_64();
    for (int n = 0, c; n < 128 && (c = tcplink::read()) >= 0; ++n) {
        tcplink::link().setInputPending(tcplink::inputPending());
        g_protocol.feed(tcplink::link(), (char)c);
        if (time_us_64() - t0 >= 5000) break;
    }
    tcplink::flush();
}
static bool linkHasHost() { ip_addr_t a; return tcplink::hostAddress(&a); }
static int countPcbs(tcp_pcb *l) { int n = 0; for (; l; l = l->next) ++n; return n; }
static size_t count(const std::string &s, const char *what) { size_t n = 0; for (size_t p = 0; (p = s.find(what, p)) != std::string::npos; p += strlen(what)) ++n; return n; }

int main(int argc, char **argv) {
    const std::string only = argc > 1 ? argv[1] : "";
    static const char *const kCases[] = {"reset", "halfclose", "bind", "small", "help", "window", "rejectdata", "pool", "keepalive"};
    bool known = only.empty();
    for (const char *c : kCases) known = known || only == c;
    if (!known) {
        printf("unknown case '%s'; the cases are:", only.c_str());
        for (const char *c : kCases) printf(" %s", c);
        printf("\n");
        return 2;
    }
    ProtocolHooks hooks{};
    hooks.apply = [](const PulseParams &p, RealizedTiming *r) { return realizeTiming(p, 150000000, r); };
    hooks.setArmed = [](bool arm) -> const char * { g_armed = arm; return nullptr; };
    hooks.isArmed = [] { return g_armed; };
    g_protocol.begin(&g_params, hooks);
    lwip_init();
    ip4_addr_t ip, mask, gw; IP4_ADDR(&ip, 10, 0, 0, 1); IP4_ADDR(&mask, 255, 255, 255, 0); IP4_ADDR(&gw, 10, 0, 0, 254);
    netif_add(&g_nif, &ip, &mask, &gw, nullptr, nifInit, ip_input);
    netif_set_default(&g_nif); netif_set_up(&g_nif); netif_set_link_up(&g_nif);
    CHECK(tcplink::start(kPort));

    g_case = "basic";
    Host *a = connect();
    CHECK(linkHasHost());
    inject(*a, TCP_ACK | TCP_PSH, "ARM?\n");
    loopPass();
    CHECK(a->got == "ARMED=0\r\n");
    inject(*a, TCP_ACK);
    loopPass();

    if (only == "reset" || only.empty()) {
        g_case = "DISARM, then a reset, before the loop reads";
        inject(*a, TCP_ACK | TCP_PSH, "ARM\n");
        loopPass();
        CHECK(g_armed);
        inject(*a, TCP_ACK | TCP_PSH, "DISARM\n");
        inject(*a, TCP_RST);
        CHECK(g_armed && linkHasHost());  // not read yet; the link waits for the loop
        loopPass();
        CHECK(!g_armed);                  // the input that arrived was run
        loopPass();
        CHECK(!linkHasHost());
        g_case = "hosts that connect and go at once";
        for (int i = 0; i < 6; ++i) {     // more than lwIP's 5 connection blocks
            Host *z = connect();
            inject(*z, i % 2 ? TCP_RST : (TCP_ACK | TCP_FIN));
            loopPass(); loopPass();
            inject(*z, TCP_ACK);
            CHECK(!linkHasHost());
        }
        a = connect();
        CHECK(linkHasHost());
    }

    if (only == "halfclose" || only.empty()) {
        g_case = "half-close with data+FIN in one segment";
        const size_t before = a->got.size();
        inject(*a, TCP_ACK | TCP_PSH | TCP_FIN, "ARM?\n");
        loopPass(); loopPass(); loopPass();
        CHECK(a->got.size() == before + 9);
        CHECK(a->gotFin && !a->gotRst);
        inject(*a, TCP_ACK);
        CHECK(!linkHasHost());
        NOTE("after close: active=%d tw=%d", countPcbs(tcp_active_pcbs), countPcbs(tcp_tw_pcbs));
        a = connect();
        CHECK(linkHasHost());
    }

    if (only == "bind" || only.empty()) {
        g_case = "second host, then restart of the server";
        Host *b = connect();
        CHECK(b->got == "ERR busy: another host is connected\r\n");
        inject(*b, TCP_ACK);            // the host has the line -> we close
        CHECK(b->gotFin && !b->gotRst);
        inject(*b, TCP_ACK | TCP_FIN);  // the host closes too
        NOTE("after the reject: active=%d time-wait=%d", countPcbs(tcp_active_pcbs), countPcbs(tcp_tw_pcbs));
        // What radioStop() does: stop the link, then the interface loses its address.
        tcplink::stop(false);
        { LWIPMutex l; netif_set_addr(&g_nif, IP4_ADDR_ANY4, IP4_ADDR_ANY4, IP4_ADDR_ANY4); }
        NOTE("after stop + address removed: active=%d time-wait=%d", countPcbs(tcp_active_pcbs), countPcbs(tcp_tw_pcbs));
        { LWIPMutex l; netif_set_addr(&g_nif, &ip, &mask, &gw); }
        bool ok = tcplink::start(kPort);
        NOTE("tcplink::start() right after: %s", ok ? "OK" : "FAILED");
        CHECK(ok);
        uint32_t waited = 0;
        while (!ok && waited < 200000) { advance(1000); waited += 1000; ok = tcplink::start(kPort); }
        NOTE("tcplink::start() succeeded after %u ms", waited);
        a = connect();
        CHECK(linkHasHost());
    }

    if (only == "small" || only.empty()) {
        g_case = "many one-line commands, host ACKs late";
        inject(*a, TCP_ACK); loopPass();
        a->freezeAck = true; a->frozenAck = a->rcv_nxt;
        const size_t before = a->got.size();
        int sent = 0;
        for (int i = 0; i < 30; ++i) {
            inject(*a, TCP_ACK | TCP_PSH, "ARM?\n"); ++sent;
            loopPass();
            g_nowUs += 1000;  // 1 ms between commands
            if (tcplink::link().stalled()) { NOTE("link stalled after command %d (t=+%d ms)", sent, i + 1); break; }
        }
        NOTE("commands %d, replies received %zu", sent, count(a->got.substr(before), "ARMED=0"));
        a->freezeAck = false;
        inject(*a, TCP_ACK);  // now everything is acknowledged
        const uint64_t t0 = g_nowUs;
        size_t got0 = count(a->got, "ARMED=0");
        int tries = 0;
        for (; tries < 60; ++tries) {
            advance(100);
            inject(*a, TCP_ACK | TCP_PSH, "ARM?\n"); loopPass(); inject(*a, TCP_ACK);
            if (count(a->got, "ARMED=0") > got0) break;
        }
        NOTE("first reply again %llu ms after the host acknowledged everything", (unsigned long long)((g_nowUs - t0) / 1000));
        CHECK(sent == 30);                        // no reply waited for memory
        CHECK(count(a->got.substr(before), "ARMED=0") >= 30);  // and none was dropped
    }

    if (only == "help" || only.empty()) {
        g_case = "HELP";
        advance(3000); inject(*a, TCP_ACK); loopPass();
        const size_t before = a->got.size();
        inject(*a, TCP_ACK | TCP_PSH, "HELP\n");
        loopPass();
        for (int i = 0; i < 10; ++i) { inject(*a, TCP_ACK); loopPass(); }
        NOTE("HELP reply bytes received: %zu, stalled=%d", a->got.size() - before, (int)tcplink::link().stalled());
        CHECK(!tcplink::link().stalled());
        CHECK(a->got.find("the set period. The reply comes at once; the pulses follow the hold-off.\r\n", before) != std::string::npos);
    }

    if (only == "window" || only.empty()) {
        g_case = "window";
        advance(3000); inject(*a, TCP_ACK); loopPass();
        inject(*a, TCP_ACK | TCP_PSH, "ARM\n"); loopPass(); inject(*a, TCP_ACK); loopPass();
        CHECK(g_armed);
        // Fill the whole announced window without the loop running.
        std::string line = "\n", chunk;  // empty lines: no replies, so only tcp_recved() can open the window
        while (chunk.size() + line.size() <= 1460) chunk += line;
        size_t total = 0; int n0 = (int)a->rx.size();
        while (total + chunk.size() <= TCP_WND) { inject(*a, TCP_ACK | TCP_PSH, chunk); total += chunk.size(); }
        std::string rest(TCP_WND - total, '\n');
        if (!rest.empty()) { inject(*a, TCP_ACK | TCP_PSH, rest); total += rest.size(); }
        NOTE("sent %zu bytes; window announced now %u", total, a->peerWnd);
        inject(*a, TCP_ACK | TCP_PSH, "DISARM\n");  // beyond the window: must be refused, not stored
        a->snd_nxt -= 7;
        (void)n0;
        int passes = 0; uint16_t w = a->peerWnd;
        for (; passes < 2000 && a->peerWnd == w; ++passes) { loopPass(); g_nowUs += 100; }
        NOTE("window update (wnd=%u) after %d loop passes", a->peerWnd, passes);
        for (int i = 0; i < 400; ++i) { loopPass(); inject(*a, TCP_ACK); }
        NOTE("final window %u (the announced value can lag the real window by less than 4 segments)", a->peerWnd);
        CHECK(passes < 2000 && a->peerWnd >= TCP_WND - 4 * TCP_MSS);
        CHECK(g_armed);  // the DISARM beyond the window was refused by lwIP, not stored
        inject(*a, TCP_ACK | TCP_PSH, "DISARM\n"); loopPass(); inject(*a, TCP_ACK); loopPass();
        CHECK(!g_armed);
    }

    if (only == "rejectdata" || only.empty()) {
        g_case = "second host sends data with its handshake ACK and with the ACK of the busy line";
        Host *b = newHost();
        inject(*b, TCP_SYN);
        inject(*b, TCP_ACK | TCP_PSH, "ARM\n");
        CHECK(b->got == "ERR busy: another host is connected\r\n");
        inject(*b, TCP_ACK | TCP_PSH, "ARM\n");
        loopPass();
        NOTE("fin=%d rst=%d armed=%d", (int)b->gotFin, (int)b->gotRst, (int)g_armed);
        CHECK(!g_armed);
        // more than the limit, none of them ever answers: how long are they in the way?
        Host *c1 = connect(), *c2 = connect(), *c3 = connect();
        NOTE("3 silent second hosts: busy lines %zu/%zu/%zu rst %d/%d/%d active pcbs %d", c1->got.size(), c2->got.size(), c3->got.size(), c1->gotRst, c2->gotRst, c3->gotRst, countPcbs(tcp_active_pcbs));
        advance(2600);
        NOTE("after 2.6 s: rst %d/%d active pcbs %d", c1->gotRst, c2->gotRst, countPcbs(tcp_active_pcbs));
        CHECK(countPcbs(tcp_active_pcbs) == 1);  // only the link's host is left
    }

    if (only == "pool" || only.empty()) {
        g_case = "second hosts that read the busy line and keep the socket open";
        Host *h[4];
        for (int i = 0; i < 4; ++i) {
            h[i] = connect();
            inject(*h[i], TCP_ACK);   // has the line; we send FIN
            inject(*h[i], TCP_ACK);   // acknowledges our FIN, does not close
            advance(100);
        }
        NOTE("busy lines %zu/%zu/%zu/%zu, active pcbs %d (pool 5)", h[0]->got.size(), h[1]->got.size(), h[2]->got.size(), h[3]->got.size(), countPcbs(tcp_active_pcbs));
        Host *x = newHost();
        uint32_t t = 0;
        for (; t < 40000 && !x->gotSynAck; t += 1000) { x->snd_nxt = 1000; inject(*x, TCP_SYN); if (!x->gotSynAck) advance(1000); }
        NOTE("a further SYN was answered after %u ms", t);
        CHECK(t <= 3000);  // the places come back within the time limit of a second host
        advance(3000);
        loopPass();
    }

    if (only == "keepalive" || only.empty()) {
        g_case = "keep-alive";
        inject(*a, TCP_ACK); loopPass();
        const uint64_t t0 = g_nowUs; int f0 = a->frames;
        while (linkHasHost() && g_nowUs - t0 < 60000000) { advance(100); loopPass(); }
        NOTE("silent host: link free after %llu ms, %d probes, rst=%d", (unsigned long long)((g_nowUs - t0) / 1000), a->frames - f0, (int)a->gotRst);
        CHECK(g_nowUs - t0 >= 10000000 && g_nowUs - t0 <= 13000000);
    }

    printf(g_fail ? "%d check(s) FAILED\n" : "lwip_check: all checks passed\n", g_fail);
    return g_fail ? 1 : 0;
}
