#pragma once
// Wi-Fi configuration of the PiEBV firmware: the values, their limits and the flash
// record. Header-only and free of hardware calls, so the simulator (tools/piebv_sim)
// compiles the same code.
//
// The network link joins an existing network as a station. Supported: open networks and
// WPA2 with a passphrase (WPA2-PSK). Not supported: WPA2-Enterprise (a user name and a
// password, or a certificate).
//
// The record is stored as plain text in the Pico's flash. Anyone who holds the board can
// read it.

#include <cstddef>
#include <cstdint>
#include <cstring>

constexpr size_t kWifiSsidMax = 32;      // IEEE 802.11: an SSID is 1 to 32 bytes
constexpr size_t kWifiPassMin = 8;       // WPA2 passphrase: 8 to 63 characters
constexpr size_t kWifiPassMax = 63;
constexpr uint16_t kNetPort = 4242;      // TCP port of the command link
constexpr char kNetHostname[] = "piebv"; // DHCP host name and mDNS name (piebv.local)

struct WifiConfig {
    bool enabled = false;               // join the network at power-up
    char ssid[kWifiSsidMax + 1] = "";   // "" = not set
    char pass[kWifiPassMax + 1] = "";   // "" = open network
};

inline bool wifiConfigSame(const WifiConfig &a, const WifiConfig &b) {
    return a.enabled == b.enabled && strcmp(a.ssid, b.ssid) == 0 && strcmp(a.pass, b.pass) == 0;
}

// A network name is printed in replies, where control characters could change what a
// terminal shows. So a name must be well-formed UTF-8 (plain ASCII is that) without
// control characters (C0, DEL, C1), line and paragraph separators, and the characters
// that change the writing direction. A name in another encoding (e.g. Shift-JIS) is
// refused unless it happens to pass.
inline bool wifiNameTextOk(const char *s) {
    static constexpr uint32_t kMinOfLength[] = {0, 0, 0x80, 0x800, 0x10000};  // shorter forms are overlong
    for (const unsigned char *p = (const unsigned char *)s; *p;) {
        uint32_t cp;
        int n;
        if (*p < 0x80) {
            cp = *p, n = 1;
        } else if ((*p & 0xE0) == 0xC0) {
            cp = *p & 0x1Fu, n = 2;
        } else if ((*p & 0xF0) == 0xE0) {
            cp = *p & 0x0Fu, n = 3;
        } else if ((*p & 0xF8) == 0xF0) {
            cp = *p & 0x07u, n = 4;
        } else {
            return false;  // a continuation byte or 0xF8..0xFF where a character must start
        }
        for (int i = 1; i < n; ++i) {
            if ((p[i] & 0xC0) != 0x80) {  // also the end of the text
                return false;
            }
            cp = (cp << 6) | (p[i] & 0x3Fu);
        }
        if (cp < kMinOfLength[n] || cp > 0x10FFFF || (cp >= 0xD800 && cp <= 0xDFFF)) {
            return false;
        }
        if (cp < 0x20 || (cp >= 0x7F && cp <= 0x9F) || cp == 0x200E || cp == 0x200F ||
            (cp >= 0x2028 && cp <= 0x202E) || (cp >= 0x2066 && cp <= 0x2069)) {
            return false;
        }
        p += n;
    }
    return true;
}

// A WPA2 passphrase is 8 to 63 printable ASCII characters (IEEE 802.11).
inline bool wifiPassTextOk(const char *s) {
    for (; *s; ++s) {
        if (*s < 0x20 || *s > 0x7E) {
            return false;
        }
    }
    return true;
}

// nullptr, or why `s` cannot be an SSID.
inline const char *wifiCheckSsid(const char *s) {
    const size_t n = strlen(s);
    if (n == 0) {
        return "needs a network name";
    }
    if (n > kWifiSsidMax) {
        return "the network name is longer than 32 characters";
    }
    return wifiNameTextOk(s) ? nullptr : "the network name must be UTF-8 text without control characters";
}

// nullptr, or why `s` cannot be a passphrase. "" is an open network.
inline const char *wifiCheckPass(const char *s) {
    const size_t n = strlen(s);
    if (n == 0) {
        return nullptr;
    }
    if (n < kWifiPassMin || n > kWifiPassMax) {
        return "the passphrase must have 8 to 63 characters";
    }
    return wifiPassTextOk(s) ? nullptr : "the passphrase must be printable ASCII characters";
}

// ---------------------------------------------------------------- flash record
// Fixed layout, little-endian:
//   0   4  magic "PWF1"
//   4   1  enabled (0 or 1)
//   5  33  ssid, NUL-terminated, NUL-padded
//  38  64  passphrase, NUL-terminated, NUL-padded
// 102   2  0
// 104   4  CRC-32 (IEEE 802.3) of bytes 0..103
constexpr size_t kWifiRecordSize = 108;
constexpr uint8_t kWifiRecordMagic[4] = {'P', 'W', 'F', '1'};

inline uint32_t wifiCrc32(const uint8_t *p, size_t n) {
    uint32_t crc = 0xFFFFFFFFu;
    for (size_t i = 0; i < n; ++i) {
        crc ^= p[i];
        for (int b = 0; b < 8; ++b) {
            crc = (crc >> 1) ^ (0xEDB88320u & (0u - (crc & 1u)));
        }
    }
    return ~crc;
}

inline void wifiRecordEncode(const WifiConfig &cfg, uint8_t out[kWifiRecordSize]) {
    static_assert(4 + 1 + sizeof(cfg.ssid) + sizeof(cfg.pass) + 2 + 4 == kWifiRecordSize, "record layout");
    memset(out, 0, kWifiRecordSize);
    memcpy(out, kWifiRecordMagic, 4);
    out[4] = cfg.enabled ? 1 : 0;
    strncpy((char *)out + 5, cfg.ssid, kWifiSsidMax);
    strncpy((char *)out + 38, cfg.pass, kWifiPassMax);
    const uint32_t crc = wifiCrc32(out, kWifiRecordSize - 4);
    for (int i = 0; i < 4; ++i) {
        out[kWifiRecordSize - 4 + i] = (uint8_t)(crc >> (8 * i));
    }
}

// False if the bytes are not a valid record (erased flash, another version, damage):
// *cfg is then left as it was.
inline bool wifiRecordDecode(const uint8_t in[kWifiRecordSize], WifiConfig *cfg) {
    if (memcmp(in, kWifiRecordMagic, 4) != 0) {
        return false;
    }
    uint32_t crc = 0;
    for (int i = 0; i < 4; ++i) {
        crc |= (uint32_t)in[kWifiRecordSize - 4 + i] << (8 * i);
    }
    if (crc != wifiCrc32(in, kWifiRecordSize - 4) || in[4] > 1 || in[5 + kWifiSsidMax] != 0 ||
        in[38 + kWifiPassMax] != 0) {
        return false;
    }
    WifiConfig c;
    c.enabled = in[4] == 1;
    memcpy(c.ssid, in + 5, sizeof(c.ssid));
    memcpy(c.pass, in + 38, sizeof(c.pass));
    if (wifiCheckPass(c.pass) || (c.ssid[0] && wifiCheckSsid(c.ssid)) || (c.enabled && !c.ssid[0])) {
        return false;
    }
    *cfg = c;
    return true;
}
