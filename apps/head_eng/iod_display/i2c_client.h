#pragma once

#include <Arduino.h>
#include <Wire.h>
#include "status_model.h"

namespace hv {

class I2CStatusClient {
 public:
  I2CStatusClient(uint8_t picoAddr, uint32_t pollEveryMs)
      : picoAddr_(picoAddr), pollEveryMs_(pollEveryMs) {}

  void begin(int sdaPin, int sclPin, uint32_t freqHz);
  void poll(RuntimeStatus& state, uint32_t nowMs);

 private:
  uint8_t picoAddr_;
  uint32_t pollEveryMs_;
  uint32_t lastPollAttemptMs_ = 0;
};

}  // namespace hv
