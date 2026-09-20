#include "protocol.h"

#include <Arduino.h>
#include <cstdlib>
#include <cstring>
#include <strings.h>  // strcasecmp

namespace {

struct FieldCommand {
    const char *name;
    uint32_t PulseParams::*field;
};

const FieldCommand kFields[] = {
    {"FREQ", &PulseParams::freqHz},
    {"WIDTH", &PulseParams::widthNs},
    {"DELAY", &PulseParams::delayNs},
    {"MARKERDIV", &PulseParams::markerDiv},
    {"MARKERWIDTH", &PulseParams::markerWidthNs},
    {"SYNC", &PulseParams::syncHz},
};

void reportQuery(const char *name, uint32_t value) {
    Serial.print(name);
    Serial.print('=');
    Serial.println(value);
}

void reportOk(const char *name, uint32_t value) {
    Serial.print(F("OK "));
    Serial.print(name);
    Serial.print('=');
    Serial.println(value);
}

void reportErr(const char *name, const char *reason) {
    Serial.print(F("ERR "));
    Serial.print(name);
    Serial.print(' ');
    Serial.println(reason);
}

void printHelp() {
    Serial.println(F(
        "FREQ <Hz>          pulse-pair repetition frequency\n"
        "WIDTH <ns>         CH1/CH2 pulse width\n"
        "DELAY <ns>         CH2-after-CH1 delay\n"
        "MARKERDIV <N>      marker fires every N pulses\n"
        "MARKERWIDTH <ns>   marker pulse width\n"
        "SYNC <Hz>          camera sync clock frequency\n"
        "STATUS             show all current settings\n"
        "ID?                firmware identity\n"
        "HELP               this text"));
}

}  // namespace

void Protocol::begin(PulseParams *params, ApplyParamsFn apply) {
    params_ = params;
    apply_ = apply;
    len_ = 0;
}

void Protocol::feed(char c) {
    if (c == '\r') {
        return;
    }
    if (c == '\n') {
        buf_[len_] = '\0';
        if (len_ > 0) {
            dispatch(buf_);
        }
        len_ = 0;
        return;
    }
    if (len_ + 1 >= sizeof(buf_)) {
        len_ = 0;
        Serial.println(F("ERR line too long"));
        return;
    }
    buf_[len_++] = c;
}

void Protocol::dispatch(char *line) {
    char *cmd = strtok(line, " \t");
    if (!cmd) {
        return;
    }
    char *valueStr = strtok(nullptr, " \t");

    for (const auto &f : kFields) {
        if (strcasecmp(cmd, f.name) != 0) {
            continue;
        }
        if (!valueStr) {
            reportQuery(f.name, params_->*(f.field));
            return;
        }
        char *end = nullptr;
        long v = strtol(valueStr, &end, 10);
        if (end == valueStr || *end != '\0' || v < 0) {
            reportErr(f.name, "invalid value");
            return;
        }
        PulseParams candidate = *params_;
        candidate.*(f.field) = (uint32_t)v;
        if (apply_ && apply_(candidate)) {
            *params_ = candidate;
            reportOk(f.name, (uint32_t)v);
        } else {
            reportErr(f.name, "rejected (out of range for current settings)");
        }
        return;
    }

    if (strcasecmp(cmd, "STATUS") == 0) {
        reportQuery("FREQ", params_->freqHz);
        reportQuery("WIDTH", params_->widthNs);
        reportQuery("DELAY", params_->delayNs);
        reportQuery("MARKERDIV", params_->markerDiv);
        reportQuery("MARKERWIDTH", params_->markerWidthNs);
        reportQuery("SYNC", params_->syncHz);
        return;
    }

    if (strcasecmp(cmd, "ID?") == 0 || strcasecmp(cmd, "ID") == 0) {
        Serial.println(F("PiDG-Pico2W delay generator, built " __DATE__ " " __TIME__));
        return;
    }

    if (strcasecmp(cmd, "HELP") == 0) {
        printHelp();
        return;
    }

    reportErr(cmd, "unknown command");
}
