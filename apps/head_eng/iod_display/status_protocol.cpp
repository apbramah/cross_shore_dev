#include "status_protocol.h"

namespace hv {

uint16_t crc16Ibm(const uint8_t* data, size_t len) {
  uint16_t crc = 0x0000;
  constexpr uint16_t poly = 0x8005;
  for (size_t i = 0; i < len; ++i) {
    const uint8_t byte = data[i];
    for (uint8_t bit = 0; bit < 8; ++bit) {
      const uint8_t dataBit = (byte >> bit) & 0x01;
      const uint8_t crcBit = (crc >> 15) & 0x01;
      crc = static_cast<uint16_t>((crc << 1) & 0xFFFF);
      if (dataBit != crcBit) {
        crc ^= poly;
      }
    }
  }
  return crc;
}

static uint16_t readU16Le(const uint8_t* p) {
  return static_cast<uint16_t>(p[0] | (static_cast<uint16_t>(p[1]) << 8));
}

static uint32_t readU32Le(const uint8_t* p) {
  return static_cast<uint32_t>(p[0]) |
         (static_cast<uint32_t>(p[1]) << 8) |
         (static_cast<uint32_t>(p[2]) << 16) |
         (static_cast<uint32_t>(p[3]) << 24);
}

bool decodeStatusFrame(const uint8_t* frame, size_t len, StatusFrame& out, String& err) {
  if (frame == nullptr || len != kFrameLen) {
    err = "bad_frame_len";
    return false;
  }
  if (frame[0] != kMagic0 || frame[1] != kMagic1) {
    err = "bad_magic";
    return false;
  }
  if (frame[2] != kProtoVersion) {
    err = "bad_version";
    return false;
  }
  if (frame[3] != kPayloadLen) {
    err = "bad_payload_len";
    return false;
  }
  const uint16_t rxCrc = readU16Le(frame + (kFrameLen - 2));
  const uint16_t calcCrc = crc16Ibm(frame, kFrameLen - 2);
  if (rxCrc != calcCrc) {
    err = "bad_crc";
    return false;
  }

  out.flags = readU16Le(frame + 4);
  for (size_t i = 0; i < 4; ++i) {
    out.ip[i] = frame[6 + i];
    out.mask[i] = frame[10 + i];
    out.gateway[i] = frame[14 + i];
  }
  out.vMainMv = readU16Le(frame + 18);
  out.vAuxMv = readU16Le(frame + 20);
  out.sourceAgeMs = readU32Le(frame + 22);
  err = "";
  return true;
}

String ipv4ToString(const uint8_t ip[4]) {
  return String(ip[0]) + "." + String(ip[1]) + "." + String(ip[2]) + "." + String(ip[3]);
}

}  // namespace hv
