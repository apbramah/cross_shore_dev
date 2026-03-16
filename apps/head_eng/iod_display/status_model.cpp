#include "status_model.h"

namespace hv {

String networkModeText(const RuntimeStatus& s) {
  if (!s.hasFrame) {
    return "unknown";
  }
  const bool known = (s.frame.flags & kFlagNetworkModeKnown) != 0;
  if (!known) {
    return "unknown";
  }
  const bool dhcp = (s.frame.flags & kFlagNetworkModeDhcp) != 0;
  return dhcp ? "dhcp" : "manual";
}

String linkText(const RuntimeStatus& s) {
  if (!s.hasFrame) {
    return "unknown";
  }
  return (s.frame.flags & kFlagLinkUp) ? "up" : "down";
}

String voltageText(uint16_t mv) {
  if (mv == kVoltageUnavailableMv) {
    return "N/A";
  }
  const float v = static_cast<float>(mv) / 1000.0f;
  String out = String(v, 3);
  out += " V";
  return out;
}

uint32_t ageMs(const RuntimeStatus& s, uint32_t nowMs) {
  if (s.lastGoodMs == 0) {
    return UINT32_MAX;
  }
  return nowMs - s.lastGoodMs;
}

void updateStale(RuntimeStatus& s, uint32_t nowMs, uint32_t staleAfterMs) {
  const uint32_t age = ageMs(s, nowMs);
  s.stale = (!s.hasFrame) || (age == UINT32_MAX) || (age > staleAfterMs);
  s.commsOk = s.hasFrame && !s.stale;
}

}  // namespace hv
