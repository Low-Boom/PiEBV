#pragma once
// Model of the arduino-pico core's lwIP lock for tools/net_check. It counts the
// nesting, so the lwIP model can check that every call is made with the lock held.
struct LWIPMutex {
    static int depth;
    LWIPMutex() { ++depth; }
    ~LWIPMutex() { --depth; }
};
