#pragma once

#include <ESP8266WebServer.h>
#include "status_model.h"

namespace hv {

class WebStatusServer {
 public:
  explicit WebStatusServer(uint16_t port = 80) : server_(port) {}
  void begin(const RuntimeStatus* state);
  void loop();

 private:
  static String htmlTemplate();
  String jsonStatus() const;

  ESP8266WebServer server_;
  const RuntimeStatus* state_ = nullptr;
};

}  // namespace hv
