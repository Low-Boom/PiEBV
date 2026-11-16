#pragma once
// Model of lwIP's TCP callback interface for tools/net_check: the declarations that
// src/tcp_link.cpp uses, with a connection object that records what was done to it.
// The functions are in net_check.cpp. They fail the check when a call is made without
// the lwIP lock, or on a connection that the caller has already given up (closed,
// aborted) or that lwIP has freed (after the error callback).
#include <cstddef>
#include <cstdint>
#include <string>
#include "lwip/ip_addr.h"

typedef int8_t err_t;
typedef uint8_t u8_t;
typedef uint16_t u16_t;
enum : err_t { ERR_OK = 0, ERR_MEM = -1, ERR_VAL = -6, ERR_ABRT = -13, ERR_RST = -14, ERR_ARG = -16 };

#define TCP_MSS 1460
#define TCP_WND (8 * TCP_MSS)
#define TCP_SND_BUF (8 * TCP_MSS)
#define TCP_WRITE_FLAG_COPY 0x01
#define SOF_REUSEADDR 0x04
#define SOF_KEEPALIVE 0x08

enum tcp_state { CLOSED, LISTEN, SYN_SENT, SYN_RCVD, ESTABLISHED, FIN_WAIT_1, FIN_WAIT_2, CLOSE_WAIT, CLOSING, LAST_ACK, TIME_WAIT };

struct pbuf {
    pbuf *next;
    void *payload;
    u16_t tot_len;
    u16_t len;
};

struct tcp_pcb;
typedef err_t (*tcp_accept_fn)(void *arg, tcp_pcb *newpcb, err_t err);
typedef err_t (*tcp_recv_fn)(void *arg, tcp_pcb *pcb, pbuf *p, err_t err);
typedef err_t (*tcp_sent_fn)(void *arg, tcp_pcb *pcb, u16_t len);
typedef err_t (*tcp_poll_fn)(void *arg, tcp_pcb *pcb);
typedef void (*tcp_err_fn)(void *arg, err_t err);

struct tcp_pcb {
    // --- fields that the code under test reads or writes, as in lwIP
    tcp_state state = ESTABLISHED;
    void *unacked = nullptr;
    void *unsent = nullptr;
    u16_t snd_buf = TCP_SND_BUF;
    ip_addr_t remote_ip{};
    u8_t so_options = 0;
    uint32_t keep_idle = 0, keep_intvl = 0, keep_cnt = 0;
    // --- callbacks
    void *arg = nullptr;
    tcp_accept_fn accept = nullptr;
    tcp_recv_fn recv = nullptr;
    tcp_sent_fn sent = nullptr;
    tcp_poll_fn poll = nullptr;
    tcp_err_fn errf = nullptr;
    // --- the model's record
    std::string out;         // bytes taken by tcp_write()
    size_t sentBytes = 0;    // of `out`, handed on by tcp_output()
    size_t recved = 0;       // sum of tcp_recved()
    bool nagleOff = false;
    bool closed = false;     // tcp_close(): orderly
    bool aborted = false;    // tcp_abort(): reset
    bool gone = false;       // the application must not use it any more
};

#define tcp_sndbuf(pcb) ((pcb)->snd_buf)
#define tcp_nagle_disable(pcb) ((pcb)->nagleOff = true)
#define ip_set_option(pcb, opt) ((pcb)->so_options |= (opt))

tcp_pcb *tcp_new();
err_t tcp_bind(tcp_pcb *pcb, const ip_addr_t *addr, u16_t port);
tcp_pcb *tcp_listen_with_backlog(tcp_pcb *pcb, u8_t backlog);
void tcp_accept(tcp_pcb *pcb, tcp_accept_fn fn);
void tcp_arg(tcp_pcb *pcb, void *arg);
void tcp_recv(tcp_pcb *pcb, tcp_recv_fn fn);
void tcp_sent(tcp_pcb *pcb, tcp_sent_fn fn);
void tcp_err(tcp_pcb *pcb, tcp_err_fn fn);
void tcp_poll(tcp_pcb *pcb, tcp_poll_fn fn, u8_t interval);
err_t tcp_write(tcp_pcb *pcb, const void *data, u16_t len, u8_t flags);
err_t tcp_output(tcp_pcb *pcb);
void tcp_recved(tcp_pcb *pcb, u16_t len);
err_t tcp_close(tcp_pcb *pcb);
void tcp_abort(tcp_pcb *pcb);
u8_t pbuf_free(pbuf *p);
