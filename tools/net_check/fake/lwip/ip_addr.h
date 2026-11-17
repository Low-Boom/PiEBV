#pragma once
// Model of lwIP for tools/net_check: just the address type that src/tcp_link.h needs.
#include <cstdint>
struct ip_addr_t {
    uint32_t addr;
};
#define ip_addr_copy(dest, src) ((dest) = (src))
#define IP_ANY_TYPE nullptr
