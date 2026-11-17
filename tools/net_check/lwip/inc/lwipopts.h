#pragma once
// lwIP options for tools/net_check/lwip: the TCP and memory settings of the firmware's
// lwIP (framework-arduinopico/include/lwipopts.h, with __LWIP_MEMMULT 1), without
// Ethernet, ARP and DHCP. Keep them in step with that file when the core is upgraded.
#define NO_SYS 1
#define SYS_LIGHTWEIGHT_PROT 0
#define LWIP_SOCKET 0
#define LWIP_NETCONN 0
#define MEM_LIBC_MALLOC 0
#define MEM_ALIGNMENT 8
#define MEM_SIZE 16384
#define MEMP_NUM_TCP_SEG 32
#define PBUF_POOL_SIZE 24
#define LWIP_ARP 0
#define LWIP_ETHERNET 0
#define LWIP_ICMP 1
#define LWIP_RAW 0
#define TCP_MSS 1460
#define TCP_WND (8 * TCP_MSS)
#define TCP_SND_BUF (8 * TCP_MSS)
#define TCP_SND_QUEUELEN ((4 * (TCP_SND_BUF) + (TCP_MSS - 1)) / (TCP_MSS))
#define TCP_LISTEN_BACKLOG 1
#define TCP_DEFAULT_LISTEN_BACKLOG 2
#define LWIP_DHCP 0
#define LWIP_IPV4 1
#define LWIP_IPV6 0
#define LWIP_TCP 1
#define LWIP_UDP 1
#define LWIP_DNS 0
#define LWIP_TCP_KEEPALIVE 1
#define LWIP_NETIF_TX_SINGLE_PBUF 1
#define LWIP_IGMP 0
#define MEMP_NUM_UDP_PCB 7
#define MEMP_NUM_TCP_PCB 5
#define LWIP_STATS 0
#define CHECKSUM_CHECK_IP 0
#define CHECKSUM_CHECK_TCP 0
#define LWIP_NETIF_STATUS_CALLBACK 1
#define LWIP_NETIF_LINK_CALLBACK 1
