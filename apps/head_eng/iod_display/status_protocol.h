#pragma once

#include <Arduino.h>

namespace hv {

static constexpr uint8_t kMagic0 = 0x48;  // H
static constexpr uint8_t kMagic1 = 0x56;  // V
static constexpr uint8_t kProtoVersion = 1;
static constexpr uint8_t kPayloadLen = 20;
static constexpr size_t kFrameLen = 28;

static constexpr uint16_t kFlagLinkUp = 1u << 0;
static constexpr uint16_t kFlagNetworkModeKnown = 1u << 1;
static constexpr uint16_t kFlagNetworkModeDhcp = 1u << 2;
static constexpr uint16_t kFlagVoltageMainValid = 1u << 3;
static constexpr uint16_t kFlagVoltageAuxValid = 1u << 4;

static constexpr uint16_t kVoltageUnavailableMv = 0xFFFF;

struct StatusFrame {
  uint16_t flags = 0;
  uint8_t ip[4] = {0, 0, 0, 0};
  uint8_t mask[4] = {0, 0, 0, 0};
  uint8_t gateway[4] = {0, 0, 0, 0};
  uint16_t vMainMv = kVoltageUnavailableMv;
  uint16_t vAuxMv = kVoltageUnavailableMv;
  uint32_t sourceAgeMs = 0;
};

uint16_t crc16Ibm(const uint8_t* data, size_t len);
bool decodeStatusFrame(const uint8_t* frame, size_t len, StatusFrame& out, String& err);
String ipv4ToString(const uint8_t ip[4]);

}  // namespace hv
