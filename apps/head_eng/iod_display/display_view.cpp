#include "display_view.h"
#include "status_protocol.h"

#if __has_include(<GFX4dIoD9.h>)
#define HV_HAS_GFX4D 1
#include <GFX4dIoD9.h>
static gfx4desp gfx;
#else
#define HV_HAS_GFX4D 0
#endif

namespace hv {

void DisplayView::begin() {
#if HV_HAS_GFX4D
  gfx.begin();
  gfx.Cls();
  gfx.TextColor(WHITE, BLACK);
  gfx.Font(1);
#endif
}

void DisplayView::render(const RuntimeStatus& s, uint32_t nowMs) {
  if ((nowMs - lastRenderMs_) < 300) {
    return;
  }
  lastRenderMs_ = nowMs;

  const String ip = s.hasFrame ? ipv4ToString(s.frame.ip) : "N/A";
  const String mask = s.hasFrame ? ipv4ToString(s.frame.mask) : "N/A";
  const String gw = s.hasFrame ? ipv4ToString(s.frame.gateway) : "N/A";
  const String mode = networkModeText(s);
  const String link = linkText(s);
  const String vMain = s.hasFrame ? voltageText(s.frame.vMainMv) : "N/A";
  const String vAux = s.hasFrame ? voltageText(s.frame.vAuxMv) : "N/A";
  const uint32_t age = ageMs(s, nowMs);

#if HV_HAS_GFX4D
  gfx.Cls();
  gfx.MoveTo(0, 0);
  gfx.putstr("PICO MONITOR");
  gfx.MoveTo(0, 14);
  gfx.putstr(String("IP: ") + ip);
  gfx.MoveTo(0, 26);
  gfx.putstr(String("MASK: ") + mask);
  gfx.MoveTo(0, 38);
  gfx.putstr(String("GW: ") + gw);
  gfx.MoveTo(0, 50);
  gfx.putstr(String("MODE: ") + mode + " LINK:" + link);
  gfx.MoveTo(0, 62);
  gfx.putstr(String("VMAIN: ") + vMain);
  gfx.MoveTo(0, 74);
  gfx.putstr(String("VAUX: ") + vAux);
  gfx.MoveTo(0, 86);
  if (s.stale) {
    gfx.putstr(String("STALE ") + (age == UINT32_MAX ? String("N/A") : String(age)) + "ms");
  } else {
    gfx.putstr(String("OK age=") + String(age) + "ms");
  }
#else
  static uint32_t lastSerialMs = 0;
  if ((nowMs - lastSerialMs) > 2000) {
    lastSerialMs = nowMs;
    Serial.println("---- IoD local status ----");
    Serial.println(String("IP: ") + ip);
    Serial.println(String("MASK: ") + mask);
    Serial.println(String("GW: ") + gw);
    Serial.println(String("MODE: ") + mode + " LINK:" + link);
    Serial.println(String("VMAIN: ") + vMain + " VAUX: " + vAux);
    if (s.stale) {
      Serial.println(String("COMMS: STALE err=") + s.lastError);
    } else {
      Serial.println(String("COMMS: OK age=") + String(age) + "ms");
    }
  }
#endif
}

}  // namespace hv
