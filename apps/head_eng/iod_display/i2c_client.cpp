#include "i2c_client.h"
#include "status_protocol.h"

namespace hv {

void I2CStatusClient::begin(int sdaPin, int sclPin, uint32_t freqHz) {
  Wire.begin(sdaPin, sclPin);
  Wire.setClock(freqHz);
}

void I2CStatusClient::poll(RuntimeStatus& state, uint32_t nowMs) {
  if ((nowMs - lastPollAttemptMs_) < pollEveryMs_) {
    return;
  }
  lastPollAttemptMs_ = nowMs;
  state.lastPollMs = nowMs;

  uint8_t frame[kFrameLen] = {0};
  const uint8_t readLen = static_cast<uint8_t>(kFrameLen);
  const uint8_t got = Wire.requestFrom(static_cast<int>(picoAddr_), static_cast<int>(readLen), true);
  if (got != readLen) {
    state.errCount += 1;
    state.lastError = "short_i2c_read";
    return;
  }
  size_t idx = 0;
  while (Wire.available() && idx < kFrameLen) {
    frame[idx++] = static_cast<uint8_t>(Wire.read());
  }
  if (idx != kFrameLen) {
    state.errCount += 1;
    state.lastError = "short_buffer";
    return;
  }

  StatusFrame parsed;
  String err;
  if (!decodeStatusFrame(frame, kFrameLen, parsed, err)) {
    state.errCount += 1;
    state.lastError = err;
    return;
  }

  state.frame = parsed;
  state.hasFrame = true;
  state.okCount += 1;
  state.lastGoodMs = nowMs;
  state.lastError = "";
}

}  // namespace hv
