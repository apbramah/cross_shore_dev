#include <Arduino.h>
#include <ESP8266WiFi.h>

#include "display_view.h"
#include "i2c_client.h"
#include "status_model.h"
#include "web_server.h"

namespace {

// Wiring per first-pass requirement:
// IoD GPIO0 = SDA, IoD GPIO2 = SCL. Keep pins high during boot.
constexpr int kI2cSdaPin = 0;
constexpr int kI2cSclPin = 2;
constexpr uint8_t kPicoI2cAddress = 0x3A;
constexpr uint32_t kI2cClockHz = 100000;
constexpr uint32_t kPollEveryMs = 250;
constexpr uint32_t kStaleAfterMs = 1500;

constexpr char kApSsid[] = "HV-IOD-MON";
constexpr char kApPassword[] = "hvmonitor";

hv::RuntimeStatus gStatus;
hv::I2CStatusClient gI2c(kPicoI2cAddress, kPollEveryMs);
hv::DisplayView gDisplay;
hv::WebStatusServer gWeb(80);

}  // namespace

void setup() {
  Serial.begin(115200);
  delay(50);

  // Start AP first so web monitoring is available even if I2C is down.
  WiFi.mode(WIFI_AP);
  WiFi.softAP(kApSsid, kApPassword);
  Serial.print("AP ready: ");
  Serial.println(kApSsid);
  Serial.print("AP IP: ");
  Serial.println(WiFi.softAPIP());

  gI2c.begin(kI2cSdaPin, kI2cSclPin, kI2cClockHz);
  gDisplay.begin();
  gWeb.begin(&gStatus);
}

void loop() {
  const uint32_t nowMs = millis();
  gI2c.poll(gStatus, nowMs);
  hv::updateStale(gStatus, nowMs, kStaleAfterMs);
  gDisplay.render(gStatus, nowMs);
  gWeb.loop();
  delay(5);
}
