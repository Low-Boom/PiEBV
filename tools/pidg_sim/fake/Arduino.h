#pragma once
// Host stand-in for the arduino-pico core, just enough to compile the REAL
// src/protocol.cpp for the PiDG simulator (tools/pidg_sim). Print mirrors ArduinoCore-API/api/Print.cpp of the pinned
// framework-arduinopico 1.60100.0 (println() writes "\r\n", printNumber uses
// upper-case hex digits). FakeSerial mirrors SerialUSB's observable behaviour:
// operator bool = DTR asserted, availableForWrite() = free TX FIFO bytes.
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>

class __FlashStringHelper;
#define F(s) (reinterpret_cast<const __FlashStringHelper *>(s))
#define DEC 10
#define HEX 16

uint64_t time_us_64();
inline unsigned long micros() { return (unsigned long)time_us_64(); }
inline unsigned long millis() { return (unsigned long)(time_us_64() / 1000); }
void fake_advance_us(uint64_t us);
inline void delay(unsigned long ms) { fake_advance_us((uint64_t)ms * 1000); }

class Print {
public:
    virtual ~Print() {}
    virtual size_t write(uint8_t) = 0;
    size_t write(const char *str) {
        if (str == nullptr) return 0;
        return write((const uint8_t *)str, strlen(str));
    }
    virtual size_t write(const uint8_t *buffer, size_t size) {
        size_t n = 0;
        while (size--) {
            if (write(*buffer++)) n++;
            else break;
        }
        return n;
    }
    size_t write(const char *buffer, size_t size) { return write((const uint8_t *)buffer, size); }
    virtual int availableForWrite() { return 0; }

    size_t print(const __FlashStringHelper *s) { return print(reinterpret_cast<const char *>(s)); }
    size_t print(const char s[]) { return write(s); }
    size_t print(char c) { return write((uint8_t)c); }
    size_t print(unsigned char b, int base = DEC) { return print((unsigned long)b, base); }
    size_t print(int n, int base = DEC) { return print((long)n, base); }
    size_t print(unsigned int n, int base = DEC) { return print((unsigned long)n, base); }
    size_t print(long n, int base = DEC) {
        if (base == 0) return write((uint8_t)n);
        if (base == 10 && n < 0) {
            size_t t = print('-');
            return printNumber((unsigned long)(-n), 10) + t;
        }
        return printNumber((unsigned long)n, base);
    }
    size_t print(unsigned long n, int base = DEC) {
        if (base == 0) return write((uint8_t)n);
        return printNumber(n, base);
    }
    size_t print(long long n, int base = DEC) {
        if (base == 10 && n < 0) {
            size_t t = print('-');
            return printULL((unsigned long long)(-n), 10) + t;
        }
        return printULL((unsigned long long)n, base);
    }
    size_t print(unsigned long long n, int base = DEC) { return printULL(n, base); }

    size_t println() { return write("\r\n"); }
    template <class T>
    size_t println(T v) {
        size_t n = print(v);
        return n + println();
    }
    template <class T>
    size_t println(T v, int base) {
        size_t n = print(v, base);
        return n + println();
    }

private:
    size_t printNumber(unsigned long n, uint8_t base) {
        char buf[8 * sizeof(long) + 1];
        char *str = &buf[sizeof(buf) - 1];
        *str = '\0';
        if (base < 2) base = 10;
        do {
            char c = (char)(n % base);
            n /= base;
            *--str = c < 10 ? c + '0' : c + 'A' - 10;
        } while (n);
        return write(str);
    }
    size_t printULL(unsigned long long n, uint8_t base) {
        char buf[8 * sizeof(long long) + 1];
        char *str = &buf[sizeof(buf) - 1];
        *str = '\0';
        if (base < 2) base = 10;
        do {
            char c = (char)(n % base);
            n /= base;
            *--str = c < 10 ? c + '0' : c + 'A' - 10;
        } while (n);
        return write(str);
    }
};

// Serial: SerialUSB's observable behaviour (operator bool = DTR asserted,
// availableForWrite() = free TX FIFO bytes). Output goes straight to stdout.
struct FakeSerial : public Print {
    bool connected = true;
    int txRoom = 100000;
    void begin(unsigned long) {}
    explicit operator bool() const { return connected; }
    int availableForWrite() override { return txRoom; }
    size_t write(uint8_t c) override { return write(&c, 1); }
    size_t write(const uint8_t *buf, size_t n) override {
        if (!connected) return 0;
        fwrite(buf, 1, n, stdout);
        fflush(stdout);
        return n;
    }
    using Print::write;
};
extern FakeSerial Serial;
