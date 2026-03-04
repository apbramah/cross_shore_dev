# Teensy Gamepad Jitter Investigation (Evidence-Based)

## Executive Summary

- Current firmware/descriptor path is correctly signed end-to-end (`int16`, `-32768..32767`) and structurally aligned with the custom 14-byte HID report format.
- The measured gap remains large: custom controller `>8 counts p-p` vs reference controller `<=2 counts p-p` in Chromium on Pi 5 (at least 4x higher idle jitter).
- Strongest code-visible contributors are: zero firmware deadband in active build, send-on-any-change policy with no hysteresis, and high report evaluation cadence (5 ms / 200 Hz).
- ADC path is configured for 12-bit reads; firmware does not explicitly set `analogReadAveraging(...)`, so it relies on Teensy core default averaging behavior.
- Host-side Chromium filtering/normalization behavior remains partially unknown from repository evidence and should be isolated with parallel evdev vs Gamepad API measurements.
- Recommended next step is a measurement-first matrix to quantify jitter at each layer (raw ADC, scaled HID int16, evdev, Chromium) before mitigation sweeps.

`Analog pin` -> `analogRead()` (12-bit) -> `scale...()` to signed `int16` -> optional `applyCenterDeadband()` -> pack `usb_joystick_data[14]` -> `usb_joystick_send()` on change (loop every 5 ms) -> USB HID interrupt IN (descriptor: 15 buttons + 6 signed 16-bit axes) -> Linux input stack / evdev -> Chromium Gamepad normalization -> `navigator.getGamepads()[i].axes[]`

## Signal Path Map

| Stage | Transform | Owner (file + symbol) | Evidence |
|---|---|---|---|
| 1. ADC acquisition | Reads axis pins via `analogRead(...)` | `Teensey Gamepad/src/main.cpp::sendReport()` | Reads for `JOYSTICK_X/Y/Z`, `FOCUS_POT`, `IRIS_POT`, `ZOOM_ROCKER` |
| 2. ADC resolution config | Sets ADC read width to 12-bit | `Teensey Gamepad/src/main.cpp::setup()` -> `analogReadResolution(12)` | Explicit call in setup |
| 3. ADC averaging default (core) | Core default averaging is 4 samples unless changed | `.../cores/teensy4/analog.c` (`analog_num_average = 4`, `analog_init`) | No `analogReadAveraging(...)` call in project firmware |
| 4. Boot center calibration (XYZ only) | Average `kJoyCalSamples=256` with `kJoyCalDelayUs=200` us | `Teensey Gamepad/src/main.cpp::calibrateCenterRaw()`, `setup()` | `g_centerRawX/Y/Z` set at boot |
| 5. Scaling to signed axis | `raw - center` then `(centered * 32767) / 2047`, clamp to `[-32768,32767]` | `Teensey Gamepad/src/main.cpp::scaleAnalogToSignedWithCenter()`, `scaleCentered12ToSigned()`, `scaleAnalogToSigned()` | XYZ use calibrated center; Rx/Ry/Rz use fixed 2048 center |
| 6. Deadband | Zeroing near center with threshold `kAxisCenterDeadband` | `Teensey Gamepad/src/main.cpp::applyCenterDeadband()` | Current value is `0` in `main.cpp` (disabled) |
| 7. HID report packing | Buttons in first 2 bytes (15 bits + 1 pad), then 6x little-endian `int16` axes | `Teensey Gamepad/src/main.cpp::sendReport()` | `raw[0..1]` button mask, `memcpy(&raw[2], axes, sizeof(axes))` |
| 8. Send policy | Report sent only if payload changed (`memcmp(lastReport, raw, JOYSTICK_SIZE)`) | `Teensey Gamepad/src/main.cpp::sendReport()` | Change-only transmission |
| 9. Report cadence | `sendReport()` evaluated every `kReportIntervalMs = 5` ms (max 200 Hz send attempts) | `Teensey Gamepad/src/main.cpp::loop()` | timer gate |
| 10. USB descriptor semantics | HID report is 14 bytes, 15 buttons + 6 signed 16-bit axes, logical range `-32768..32767` | `.../cores/teensy4/usb_desc.h` (`USB_SERIAL_HID`, `JOYSTICK_SIZE 14`), `.../usb_desc.c` (`JOYSTICK_SIZE == 14` descriptor) | Patched core in active PlatformIO package |
| 11. Build-time USB mode forcing | Ensures `USB_SERIAL_HID` is used, removes default `USB_SERIAL` define | `Teensey Gamepad/tools/teensy_usb_serial_hid.py` | `CPPDEFINES` rewrite + `-UUSB_SERIAL -DUSB_SERIAL_HID` |
| 12. Browser endpoint | Chromium reads via Gamepad API `navigator.getGamepads()[0].axes` | `Teensey Gamepad/explainer.md`, `Teensey Gamepad/Docs/Teensey Chromium Deadband Report.txt` | Repo docs, not source-level Chromium code |

**Sampling rate / send rate**
- Firmware report scheduling: **5 ms** period => **200 Hz max** (`kReportIntervalMs`).
- USB endpoint interval in descriptor for joystick: **1 ms** (`JOYSTICK_INTERVAL 1`) in `usb_desc.h`.
- Actual send rate depends on change-only policy; can be lower when stable, can approach 200 Hz with jittering inputs.

## Resolution/Noise Budget

| Stage | Range / Type | Quantization step | Formula | Notes |
|---|---|---|---|---|
| ADC raw | `0..4095` (12-bit) | 1 raw count | `2^12 = 4096 codes` | `analogReadResolution(12)` in firmware |
| ADC voltage (theoretical) | 0..3.3 V | ~0.805 mV / count | `3.3 / 4096` | Teensy 4 analog ref comment in `core_pins.h` says 3.3V reference |
| Internal scaled int (`int16`) | `[-32768,32767]` | ~16.007 scaled counts per 1 raw count | `32767 / 2047` | From scaling in `scaleCentered12ToSigned()` |
| HID report axis field | signed `int16` | 1 HID count at report layer | descriptor logical min/max in `usb_desc.c` | Effective input-origin step still ADC-limited (~16 HID counts per raw LSB) |
| Browser normalized float | nominal `[-1,1]` | ~`1/32767 = 3.05e-5` per HID count | host normalization (exact Chromium path unknown in repo) | From signed int16 domain assumption used in docs |

### Theoretical quantization floor vs observed jitter

| Metric | Value | Evidence basis |
|---|---|---|
| Theoretical minimum input-origin step at HID integer layer | ~16 HID counts / 1 ADC LSB | `scaleCentered12ToSigned()` math |
| Theoretical minimum input-origin normalized step | ~0.000488 | `16 / 32767` |
| Observed jitter (user report) | custom: `>8 counts p-p`, commercial: `<=2 counts p-p` | User-provided measured behavior |
| Gap ratio (as reported) | custom is at least **4x** noisier p-p | `>8` vs `<=2` |

**Important uncertainty**
- The exact meaning of your "counts" scale is **unknown** from repository evidence (e.g., HID counts vs normalized\*scale).
- Missing evidence: measurement script/math used to convert Chromium `axes[]` floats to counts.

## Jitter Source Findings

| Contributor | Severity | File + symbol | Mechanism (code-backed) |
|---|---|---|---|
| Deadband disabled in active firmware | High | `Teensey Gamepad/src/main.cpp::kAxisCenterDeadband` + `applyCenterDeadband()` | Current deadband is `0`, so any non-zero scaled fluctuation is emitted and visible. |
| Change-only send with no hysteresis | High | `Teensey Gamepad/src/main.cpp::sendReport()` (`memcmp(...)` gate) | Any 1-count change in packed report triggers transmit; no temporal smoothing or min-delta threshold. |
| Report evaluation at 200 Hz | Medium-High | `Teensey Gamepad/src/main.cpp::kReportIntervalMs`, `loop()` | Frequent sampling/transmit opportunities increase visible jitter updates in host API. |
| ADC averaging not explicitly tuned by app | Medium | `Teensey Gamepad/src/main.cpp` (no `analogReadAveraging`), core `.../analog.c` defaults | App relies on core default averaging (4). No project-level optimization for lower idle noise. |
| Center calibration is one-shot at boot only | Medium | `Teensey Gamepad/src/main.cpp::calibrateCenterRaw()`, `setup()` | Drift after boot (temperature/time) is not compensated; can convert small drift into axis flutter around zero crossing. |
| Asymmetric center strategy by axis class | Medium | `Teensey Gamepad/src/main.cpp::sendReport()` | XYZ use calibrated center; Rx/Ry/Rz use fixed center (2048), so non-ideal center on pots/rocker can appear as persistent offset/jitter. |
| Integer scaling asymmetry edge | Low | `Teensey Gamepad/src/main.cpp::scaleCentered12ToSigned()` | Uses `2047` divisor and special case for `-2048`; introduces small asymmetry at extremes, not primary idle jitter source. |
| HID descriptor/signing mismatch risk | Low (currently) | `.../usb_desc.c` `JOYSTICK_SIZE==14` descriptor | Descriptor currently declares signed `int16` axes consistent with firmware packing, reducing normalization mismatch risk. |

## HID/Browser Interface Findings

| Check | Status | Evidence |
|---|---|---|
| Axis signedness | Aligned | Firmware packs `int16_t axes[6]` (`src/main.cpp::sendReport()`); descriptor uses Logical Min `-32768`, Max `32767` (`.../usb_desc.c`, `JOYSTICK_SIZE==14`) |
| Axis count/order | Aligned | Descriptor usages X/Y/Z/Rx/Ry/Rz and firmware writes exactly 6 axes in that order |
| Buttons semantics | Aligned | Descriptor declares 15 buttons + 1 padding bit; firmware masks to 15 bits (`buttonsMask &= 0x7FFF`) and packs first two bytes |
| Report size | Aligned | `JOYSTICK_SIZE=14` in patched `usb_desc.h`; firmware writes 14-byte payload pattern |
| Endianness | Likely aligned on Teensy 4 | `memcpy` of `int16_t` into report on little-endian MCU (Teensy 4 ARM). No explicit byte-swap needed in this target |
| Chromium normalization internals | Unknown | Repo has docs and observations, but no Chromium source/trace proving exact normalization/deadzone function on Pi ARM |

**Potential normalization pitfall still present (host-side)**
- Even with signed descriptor correct, Chromium may apply internal filtering/thresholding not visible in this repo; prior report claims residual thresholding after firmware/kernel cleanup (`Teensey Gamepad/Docs/Teensey Chromium Deadband Report.txt`).

## Target Gap

- Target: `<= 2 counts p-p` (user benchmark from off-the-shelf controller).
- Current: `> 8 counts p-p` (custom).
- Quantified gap: at least **+6 counts p-p absolute**, or **>=4x** relative p-p.
- Most plausible code-path contributors to this delta:
  1. `kAxisCenterDeadband = 0` in active build (`src/main.cpp`).
  2. No smoothing/hysteresis before send; change-only sends every tiny delta (`sendReport()`).
  3. App does not explicitly tune ADC averaging/sampling strategy (`analogReadAveraging` absent).
  4. Mixed centering policy (XYZ calibrated, Rx/Ry/Rz fixed-center).

No hardware-rooted claim is made here beyond code/config evidence.

## Action Plan

### Phase 1: Measurement Instrumentation

| Step | Hypothesis | Files/functions touched (later) | Pass/Fail criterion |
|---|---|---|---|
| 1. Log raw->scaled->packed per axis at rest | Jitter amplification stage can be located (ADC vs scaling vs host) | `Teensey Gamepad/src/main.cpp::sendReport()`, optional serial helper near `loop()` | **Pass:** obtain synchronized traces of raw ADC, scaled int16, and sent payload for 60s idle |
| 2. Capture host-side values from multiple layers | Host layer adds extra jitter/filtering beyond HID payload | Host scripts (new), plus existing `evtest` and Chromium console capture procedure in `explainer.md` | **Pass:** same time window shows whether jitter increases from HID/evdev to Chromium |
| 3. Define count scale explicitly | Current "counts" metric may be ambiguous | Measurement script(s) (new) | **Pass:** exact conversion formula documented and reused across devices |

### Phase 2: Firmware/Config Experiments

| Step | Hypothesis | Files/functions touched (later) | Pass/Fail criterion |
|---|---|---|---|
| 1. ADC averaging sweep (`1/4/8/16/32`) | Increasing averaging lowers idle p-p | `Teensey Gamepad/src/main.cpp::setup()` (`analogReadAveraging(...)`) | **Pass:** monotonic reduction in idle p-p with acceptable latency |
| 2. Deadband/hysteresis sweep near zero | Small deadband/hysteresis cuts visible idle flutter without harming micro-inputs | `src/main.cpp::kAxisCenterDeadband`, `applyCenterDeadband()`, send gate logic in `sendReport()` | **Pass:** idle p-p <= target while first-motion threshold stays acceptable |
| 3. Send cadence sweep (`5/10/20 ms`) | Lower report rate reduces apparent jitter in browser API | `src/main.cpp::kReportIntervalMs` | **Pass:** lower p-p without unacceptable control latency |
| 4. Centering strategy parity for all axes | Fixed-center axes contribute disproportionate drift | `src/main.cpp` center calibration and mapping for Rx/Ry/Rz | **Pass:** rest mean near zero and reduced p-p across all 6 axes |
| 5. Descriptor sanity re-verify each build | Mispatch/regression can reintroduce host normalization artifacts | `scripts/patch-teensy-core.ps1`, external `usb_desc.h/c` checks | **Pass:** descriptor dump always confirms signed 16-bit axes and 14-byte report |

### Phase 3: Host-Side Verification

| Step | Hypothesis | Files/functions touched (later) | Pass/Fail criterion |
|---|---|---|---|
| 1. Compare evdev vs Chromium concurrently | Residual gap is browser-side if evdev is clean | Host test scripts + `evtest` | **Pass:** quantified layer delta (evdev p-p vs Chromium p-p) |
| 2. Chromium vs alternate client path (WebHID) | Gamepad API adds filtering not present in raw HID reads | Web test harness (new) | **Pass:** WebHID p-p significantly lower than Gamepad API on same firmware |
| 3. Side-by-side benchmark protocol | Ensure apples-to-apples comparison with commercial controller | Shared measurement harness (new) | **Pass:** same scale, sample rate, duration, and processing pipeline for both controllers |

---

If needed, produce a strict run-sheet with exact test order, log fields, and statistics method so each phase is repeatable and comparable.
