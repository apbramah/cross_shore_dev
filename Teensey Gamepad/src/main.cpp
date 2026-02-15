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

// Center deadband in signed 16-bit units. Linux/evdev and Chromium expect axes
// centered at 0; applying deadband around 0 avoids small noise/jitter.
constexpr int16_t kAxisCenterDeadband = 0;

// Boot-time calibration settings for joystick axes only (X/Y/Z).
// We do this because real sticks rarely center exactly at raw=2048 due to
// hardware tolerances. If center is biased, deadzones (kernel/app) can feel
// one-sided. Calibrating the raw center makes rest land near 0.
constexpr uint16_t kJoyCalSamples = 256;
constexpr uint16_t kJoyCalDelayUs = 200;

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
int16_t lastAxes[6] = {};
uint8_t lastReport[JOYSTICK_SIZE] = {};
uint32_t lastVersionPrintMs = 0;

// Boot-calibrated raw centers for joystick X/Y/Z only.
static int32_t g_centerRawX = 2048;
static int32_t g_centerRawY = 2048;
static int32_t g_centerRawZ = 2048;

static inline int32_t clampI32(int32_t v, int32_t lo, int32_t hi) {
  if (v < lo) return lo;
  if (v > hi) return hi;
  return v;
}

// Measure the true analog center for a joystick axis at boot.
// Assumption: user is not touching the stick during startup.
static int32_t calibrateCenterRaw(uint8_t pin, uint16_t samples) {
  int64_t sum = 0;
  for (uint16_t i = 0; i < samples; ++i) {
    sum += analogRead(pin);
    delayMicroseconds(kJoyCalDelayUs);
  }
  return static_cast<int32_t>(sum / samples);
}

// Map centered 12-bit analog delta to signed 16-bit joystick axis [-32768, 32767].
// Input is expected to be roughly [-2048..+2047] when using 12-bit ADC.
// We clamp to be safe, then scale.
static inline int16_t scaleCentered12ToSigned(int32_t centered) {
  constexpr int32_t kHalf = 2047; // max positive from center (4095-2048)
  centered = clampI32(centered, -2048, 2047);
  // Use 32767 on positive side; allow -32768 on negative extreme.
  int32_t scaled = (centered * 32767) / kHalf;
  if (centered <= -2048) scaled = -32768;
  if (scaled < -32768) scaled = -32768;
  if (scaled > 32767) scaled = 32767;
  return static_cast<int16_t>(scaled);
}

// Map 12-bit analog 0..4095 to signed 16-bit joystick axis [-32768, 32767],
// centered at 0 using a provided raw center (for X/Y/Z boot calibration).
static inline int16_t scaleAnalogToSignedWithCenter(uint16_t raw, int32_t rawCenter) {
  int32_t centered = static_cast<int32_t>(raw) - rawCenter;
  return scaleCentered12ToSigned(centered);
}

// Original mapping (still used for Rx/Ry/Rz pots/rocker).
static inline int16_t scaleAnalogToSigned(uint16_t raw) {
  constexpr int32_t kCenter = 2048;   // 12-bit analog center
  constexpr int32_t kHalf = 2047;     // max positive from center (4095-2048)
  int32_t centered = static_cast<int32_t>(raw) - kCenter;
  int32_t scaled = (centered * 32767) / kHalf;
  if (scaled < -32768) scaled = -32768;
  if (scaled > 32767) scaled = 32767;
  return static_cast<int16_t>(scaled);
}

static inline uint8_t readEncoderAB(const EncoderState &enc) {
  uint8_t a = digitalRead(enc.pinA) ? 1 : 0;
  uint8_t b = digitalRead(enc.pinB) ? 1 : 0;
  return static_cast<uint8_t>((a << 1) | b);
}

// Zero out small values near center so Linux/Chromium see a clean rest state.
static inline int16_t applyCenterDeadband(int16_t value) {
  if (value > -kAxisCenterDeadband && value < kAxisCenterDeadband) return 0;
  return value;
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
  int16_t x = 0;
  int16_t y = 0;
  int16_t z = 0;
  int16_t rx = 0;
  int16_t ry = 0;
  int16_t rz = 0;

  if (kTestPattern) {
    uint32_t sweep = (millis() * 37u) & 0xFFFFu;
    int32_t c = static_cast<int32_t>(sweep) - 32768;
    x = static_cast<int16_t>(c);
    y = static_cast<int16_t>(32767 - static_cast<int32_t>(sweep));
    z = 0;
    rx = static_cast<int16_t>(16384 - 32768);
    ry = static_cast<int16_t>(-16384);
    rz = static_cast<int16_t>((sweep >> 1) - 16384);

    bool pulse = ((millis() / 250u) % 2u) == 0u;
    buttonStates[0] = pulse;
  } else {
    // X/Y/Z: use boot-calibrated centers to ensure rest is ~0 on real hardware.
    x = scaleAnalogToSignedWithCenter(analogRead(JOYSTICK_X), g_centerRawX);
    y = scaleAnalogToSignedWithCenter(analogRead(JOYSTICK_Y), g_centerRawY);
    z = scaleAnalogToSignedWithCenter(analogRead(JOYSTICK_Z), g_centerRawZ);

    // Rx/Ry/Rz: leave as original mapping (no auto-centering per your request).
    rx = scaleAnalogToSigned(analogRead(FOCUS_POT));
    ry = scaleAnalogToSigned(analogRead(IRIS_POT));
    rz = scaleAnalogToSigned(analogRead(ZOOM_ROCKER));

    x = applyCenterDeadband(x);
    y = applyCenterDeadband(y);
    z = applyCenterDeadband(z);
    rx = applyCenterDeadband(rx);
    ry = applyCenterDeadband(ry);
    rz = applyCenterDeadband(rz);
  }

  lastAxes[0] = x;
  lastAxes[1] = y;
  lastAxes[2] = z;
  lastAxes[3] = rx;
  lastAxes[4] = ry;
  lastAxes[5] = rz;
  if (!axesInitialized) {
    axesInitialized = true;
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

  int16_t axes[6] = {x, y, z, rx, ry, rz};
  memcpy(&raw[2], axes, sizeof(axes));

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

  // Boot-time joystick center calibration (X/Y/Z only).
  // Do this before HID starts sending reports so the first values are stable.
  if (!kTestPattern) {
    g_centerRawX = calibrateCenterRaw(JOYSTICK_X, kJoyCalSamples);
    g_centerRawY = calibrateCenterRaw(JOYSTICK_Y, kJoyCalSamples);
    g_centerRawZ = calibrateCenterRaw(JOYSTICK_Z, kJoyCalSamples);
  }

  usb_joystick_configure();
  Serial.begin(115200);
  uint32_t serialStart = millis();
  while (!Serial && (millis() - serialStart) < 1500u) {
    // wait for serial host
  }
  Serial.print("FW_VERSION=");
  Serial.println(FW_VERSION);

  // Print calibrated centers for debugging (does not change naming/behavior).
  if (Serial && !kTestPattern) {
    Serial.print("JOY_CENTER_RAW_X=");
    Serial.println(g_centerRawX);
    Serial.print("JOY_CENTER_RAW_Y=");
    Serial.println(g_centerRawY);
    Serial.print("JOY_CENTER_RAW_Z=");
    Serial.println(g_centerRawZ);
  }

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
  if (Serial) {
    if (Serial.available() > 0) {
      char c = static_cast<char>(Serial.read());
      if (c == 'v' || c == 'V') {
        Serial.print("FW_VERSION=");
        Serial.println(FW_VERSION);
      }
    }
    if (nowMs - lastVersionPrintMs >= 2000u) {
      Serial.print("FW_VERSION=");
      Serial.println(FW_VERSION);
      lastVersionPrintMs = nowMs;
    }
  }
  updateEncoders(nowMs);
  updatePulseReleases(nowMs);

  if (nowMs - lastReportMs >= kReportIntervalMs) {
    sendReport();
    lastReportMs = nowMs;
  }
}
