#pragma once
// Stand-in for the arduino-pico core's lwIP lock in tools/net_check/lwip.
struct LWIPMutex {
    static int depth;
    LWIPMutex() { ++depth; }
    ~LWIPMutex();
};
