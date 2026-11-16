#!/bin/sh
# Builds tools/net_check/lwip/lwip_check: the firmware's TCP link and protocol, linked
# with the lwIP sources of the pico-sdk that PlatformIO installed for the firmware.
# Run `pio run` once before, so that the package is there.
#   sh build.sh [path to .../pico-sdk/lib/lwip/src]
set -e
cd "$(dirname "$0")"
L="${1:-$HOME/.platformio/packages/framework-arduinopico/pico-sdk/lib/lwip/src}"
if [ ! -f "$L/core/tcp.c" ]; then
    echo "lwIP sources not found in $L (run 'pio run' first, or give the path)" >&2
    exit 1
fi
S=../../../src
mkdir -p obj
for f in core/init.c core/def.c core/inet_chksum.c core/ip.c core/mem.c core/memp.c core/netif.c core/pbuf.c \
         core/stats.c core/sys.c core/tcp.c core/tcp_in.c core/tcp_out.c core/timeouts.c core/udp.c \
         core/ipv4/ip4.c core/ipv4/ip4_addr.c core/ipv4/ip4_frag.c core/ipv4/icmp.c; do
    ${CC:-gcc} -c -O1 -g -fsanitize=address -I inc -I "$L/include" -o "obj/$(basename "$f" .c).o" "$L/$f"
done
${CXX:-g++} -std=c++17 -O1 -g -fsanitize=address -DPIEBV_NET_CHECK -I inc -I "$L/include" -I ../../piebv_sim/fake -I "$S" \
    -o lwip_check lwip_check.cpp "$S/tcp_link.cpp" "$S/protocol.cpp" obj/*.o
echo "built: tools/net_check/lwip/lwip_check"
