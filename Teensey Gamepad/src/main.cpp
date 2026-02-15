#include <Arduino.h>
#include <usb_joystick.h>

#ifndef FW_VERSION
#define FW_VERSION "dev"
#endif

// Encoder pins
constexpr uint8_t ENC1_A = 31;
constexpr uint8_t ENC1_B = 30;
constexpr uint8_t ENC1_SW = 32;

constexpr uint8_t ENC2_A = 28;
constexpr uint8_t ENC2_B = 27;
constexpr uint8_t ENC2_SW = 29;

constexpr uint8_t ENC3_A = 25;
constexpr uint8_t ENC3_B = 24;
constexpr uint8_t ENC3_SW = 26;

constexpr uint8_t ENC4_A = 5;
constexpr uint8_t ENC4_B = 9;
constexpr uint8_t ENC4_SW = 10;

constexpr uint8_t ENC5_A = 3;
constexpr uint8_t ENC5_B = 2;
constexpr uint8_t ENC5_SW = 4;

// Analog input pins
constexpr uint8_t FOCUS_POT = A17;
constexpr uint8_t IRIS_POT = A16;
constexpr uint8_t ZOOM_ROCKER = A0;
constexpr uint8_t JOYSTICK_X = A5;
constexpr uint8_t JOYSTICK_Y = A7;
constexpr uint8_t JOYSTICK_Z = A6;

constexpr uint8_t kEncoderCount = 5;
constexpr uint8_t kButtonsPerEncoder = 3;
constexpr uint8_t kButtonCount = kEncoderCount * kButtonsPerEncoder;

constexpr uint32_t kEncoderPulseMs = 20;
constexpr uint32_t kSwitchDebounceMs = 8;
constexpr uint32_t kReportIntervalMs = 5;
constexpr uint32_t kHeartbeatMs = 500;
constexpr uint32_t kHeartbeatSlowMs = 500;
constexpr uint32_t kHeartbeatFastMs = 100;
constexpr uint16_t kAxisDeadband = 250;

// Set to 1 to output a visible test pattern instead of analog inputs.
constexpr uint8_t kTestPattern = 0;

struct EncoderState {
  uint8_t pinA;
  uint8_t pinB;
  uint8_t pinSw;
  uint8_t lastAB;
  bool swState;
  bool swRawLast;
  uint32_t swChangeMs;
};

EncoderState encoders[kEncoderCount] = {
  {ENC1_A, ENC1_B, ENC1_SW, 0, false, false, 0},
  {ENC2_A, ENC2_B, ENC2_SW, 0, false, false, 0},
  {ENC3_A, ENC3_B, ENC3_SW, 0, false, false, 0},
  {ENC4_A, ENC4_B, ENC4_SW, 0, false, false, 0},
  {ENC5_A, ENC5_B, ENC5_SW, 0, false, false, 0},
};

bool buttonStates[kButtonCount] = {};
uint32_t buttonReleaseMs[kButtonCount] = {};

uint32_t lastReportMs = 0;
uint32_t lastHeartbeatMs = 0;
bool heartbeatState = false;
uint32_t lastSendOkMs = 0;
bool axesInitialized = false;
uint16_t lastAxes[6] = {};
uint8_t lastReport[JOYSTICK_SIZE] = {};

static inline uint16_t scaleAnalog(uint16_t raw) {
  return static_cast<uint16_t>((static_cast<uint32_t>(raw) * 65535u) / 4095u);
}

static inline uint8_t readEncoderAB(const EncoderState &enc) {
  uint8_t a = digitalRead(enc.pinA) ? 1 : 0;
  uint8_t b = digitalRead(enc.pinB) ? 1 : 0;
  return static_cast<uint8_t>((a << 1) | b);
}

static inline uint16_t applyDeadband(uint16_t value, uint16_t last, uint16_t deadband) {
  if (value > static_cast<uint32_t>(last) + deadband) return value;
  if (value + deadband < last) return value;
  return last;
}

void pulseButton(uint8_t index) {
  if (index >= kButtonCount) return;
  buttonStates[index] = true;
  buttonReleaseMs[index] = millis() + kEncoderPulseMs;
}

void updatePulseReleases(uint32_t nowMs) {
  for (uint8_t i = 0; i < kButtonCount; ++i) {
    if (buttonStates[i] && buttonReleaseMs[i] != 0 && nowMs >= buttonReleaseMs[i]) {
      buttonStates[i] = false;
      buttonReleaseMs[i] = 0;
    }
  }
}

void updateEncoders(uint32_t nowMs) {
  static const int8_t kEncTable[16] = {
    0, -1, 1, 0,
    1, 0, 0, -1,
    -1, 0, 0, 1,
    0, 1, -1, 0
  };

  for (uint8_t i = 0; i < kEncoderCount; ++i) {
    EncoderState &enc = encoders[i];
    uint8_t currAB = readEncoderAB(enc);
    uint8_t idx = static_cast<uint8_t>((enc.lastAB << 2) | currAB);
    int8_t delta = kEncTable[idx];
    if (delta != 0) {
      uint8_t base = static_cast<uint8_t>(i * kButtonsPerEncoder);
      if (delta > 0) {
        pulseButton(base + 0); // CW
      } else {
        pulseButton(base + 1); // CCW
      }
    }
    enc.lastAB = currAB;

    bool swRaw = digitalRead(enc.pinSw) == LOW;
    if (swRaw != enc.swRawLast) {
      enc.swRawLast = swRaw;
      enc.swChangeMs = nowMs;
    } else if ((nowMs - enc.swChangeMs) >= kSwitchDebounceMs && swRaw != enc.swState) {
      enc.swState = swRaw;
      uint8_t base = static_cast<uint8_t>(i * kButtonsPerEncoder);
      buttonStates[base + 2] = enc.swState;
    }
  }
}

void sendReport() {
  uint16_t x = 0;
  uint16_t y = 0;
  uint16_t z = 0;
  uint16_t rx = 0;
  uint16_t ry = 0;
  uint16_t rz = 0;

  if (kTestPattern) {
    uint16_t sweep = static_cast<uint16_t>((millis() * 37u) & 0xFFFFu);
    x = sweep;
    y = static_cast<uint16_t>(0xFFFFu - sweep);
    z = 0x8000u;
    rx = 0x4000u;
    ry = 0xC000u;
    rz = static_cast<uint16_t>((sweep >> 1) | 0x8000u);

    // Pulse button 1 in test mode to prove button updates.
    bool pulse = ((millis() / 250u) % 2u) == 0u;
    buttonStates[0] = pulse;
  } else {
    x = scaleAnalog(analogRead(JOYSTICK_X));
    y = scaleAnalog(analogRead(JOYSTICK_Y));
    z = scaleAnalog(analogRead(JOYSTICK_Z));
    rx = scaleAnalog(analogRead(FOCUS_POT));
    ry = scaleAnalog(analogRead(IRIS_POT));
    rz = scaleAnalog(analogRead(ZOOM_ROCKER));
  }

  if (!axesInitialized) {
    lastAxes[0] = x;
    lastAxes[1] = y;
    lastAxes[2] = z;
    lastAxes[3] = rx;
    lastAxes[4] = ry;
    lastAxes[5] = rz;
    axesInitialized = true;
  } else {
    x = applyDeadband(x, lastAxes[0], kAxisDeadband);
    y = applyDeadband(y, lastAxes[1], kAxisDeadband);
    z = applyDeadband(z, lastAxes[2], kAxisDeadband);
    rx = applyDeadband(rx, lastAxes[3], kAxisDeadband);
    ry = applyDeadband(ry, lastAxes[4], kAxisDeadband);
    rz = applyDeadband(rz, lastAxes[5], kAxisDeadband);

    lastAxes[0] = x;
    lastAxes[1] = y;
    lastAxes[2] = z;
    lastAxes[3] = rx;
    lastAxes[4] = ry;
    lastAxes[5] = rz;
  }

  uint16_t buttonsMask = 0;
  for (uint8_t i = 0; i < kButtonCount; ++i) {
    if (buttonStates[i]) {
      buttonsMask |= static_cast<uint16_t>(1u << i);
    }
  }
  buttonsMask &= 0x7FFFu;

  uint8_t *raw = reinterpret_cast<uint8_t *>(usb_joystick_data);
  raw[0] = static_cast<uint8_t>(buttonsMask & 0xFFu);
  raw[1] = static_cast<uint8_t>((buttonsMask >> 8) & 0xFFu);

  uint16_t axes[6] = {x, y, z, rx, ry, rz};
  memcpy(&raw[2], axes, sizeof(axes));

  // Clear any remaining bytes in the transfer buffer.
  for (uint8_t i = 2 + sizeof(axes); i < JOYSTICK_SIZE; ++i) {
    raw[i] = 0;
  }

  if (memcmp(lastReport, raw, JOYSTICK_SIZE) != 0) {
    memcpy(lastReport, raw, JOYSTICK_SIZE);
    if (usb_joystick_send() == 0) {
      lastSendOkMs = millis();
    }
  }
}

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  pinMode(ENC1_A, INPUT_PULLUP);
  pinMode(ENC1_B, INPUT_PULLUP);
  pinMode(ENC1_SW, INPUT_PULLUP);
  pinMode(ENC2_A, INPUT_PULLUP);
  pinMode(ENC2_B, INPUT_PULLUP);
  pinMode(ENC2_SW, INPUT_PULLUP);
  pinMode(ENC3_A, INPUT_PULLUP);
  pinMode(ENC3_B, INPUT_PULLUP);
  pinMode(ENC3_SW, INPUT_PULLUP);
  pinMode(ENC4_A, INPUT_PULLUP);
  pinMode(ENC4_B, INPUT_PULLUP);
  pinMode(ENC4_SW, INPUT_PULLUP);
  pinMode(ENC5_A, INPUT_PULLUP);
  pinMode(ENC5_B, INPUT_PULLUP);
  pinMode(ENC5_SW, INPUT_PULLUP);

  analogReadResolution(12);
  delay(50);
  usb_joystick_configure();
  Serial.begin(115200);
  uint32_t serialStart = millis();
  while (!Serial && (millis() - serialStart) < 1500u) {
    // wait for serial host
  }
  Serial.print("FW_VERSION=");
  Serial.println(FW_VERSION);

  uint32_t nowMs = millis();
  for (uint8_t i = 0; i < kEncoderCount; ++i) {
    encoders[i].lastAB = readEncoderAB(encoders[i]);
    encoders[i].swRawLast = digitalRead(encoders[i].pinSw) == LOW;
    encoders[i].swState = encoders[i].swRawLast;
    encoders[i].swChangeMs = nowMs;
    buttonStates[i * kButtonsPerEncoder + 2] = encoders[i].swState;
  }
}

void loop() {
  uint32_t nowMs = millis();
  uint32_t heartbeatPeriod = (nowMs - lastSendOkMs > 1000u) ? kHeartbeatFastMs : kHeartbeatSlowMs;
  if (nowMs - lastHeartbeatMs >= heartbeatPeriod) {
    heartbeatState = !heartbeatState;
    digitalWrite(LED_BUILTIN, heartbeatState ? HIGH : LOW);
    lastHeartbeatMs = nowMs;
  }
  updateEncoders(nowMs);
  updatePulseReleases(nowMs);

  if (nowMs - lastReportMs >= kReportIntervalMs) {
    sendReport();
    lastReportMs = nowMs;
  }
}
