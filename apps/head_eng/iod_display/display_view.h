#pragma once

#include <Arduino.h>
#include "status_model.h"

namespace hv {

class DisplayView {
 public:
  void begin();
  void render(const RuntimeStatus& s, uint32_t nowMs);

 private:
  uint32_t lastRenderMs_ = 0;
};

}  // namespace hv
