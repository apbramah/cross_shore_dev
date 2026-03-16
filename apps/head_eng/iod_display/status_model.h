#pragma once

#include <Arduino.h>
#include "status_protocol.h"

namespace hv {

struct RuntimeStatus {
  bool hasFrame = false;
  bool commsOk = false;
  bool stale = true;
  uint32_t lastGoodMs = 0;
  uint32_t lastPollMs = 0;
  uint32_t okCount = 0;
  uint32_t errCount = 0;
  String lastError = "";
  StatusFrame frame;
};

String networkModeText(const RuntimeStatus& s);
String linkText(const RuntimeStatus& s);
String voltageText(uint16_t mv);
uint32_t ageMs(const RuntimeStatus& s, uint32_t nowMs);
void updateStale(RuntimeStatus& s, uint32_t nowMs, uint32_t staleAfterMs);

}  // namespace hv
