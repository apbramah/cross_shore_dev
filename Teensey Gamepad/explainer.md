# Project Explainer

This document explains what was built, how it works, and which files were
created or modified to make the Teensy 4.1 appear as a USB gamepad with
6 axes and 15 buttons in Windows/Chromium.

## Overview

Goal:
- Teensy 4.1 shows up as a USB HID gamepad.
- Report includes **6 joystick axes** (X/Y/Z/Rx/Ry/Rz) and **15 buttons**.
- Five rotary encoders provide 15 buttons (CW, CCW, and switch per encoder).
- Six analog inputs map to the 6 axes.
- Added deadband and “send only on change” to prevent noisy axis drift.

Key files in this repo:
- `platformio.ini` — PlatformIO configuration for Teensy 4.1 + USB HID.
- `src/main.cpp` — Application logic for encoders, analog inputs, HID report.
- `PATCH_NOTES.md` — Instructions for patching the Teensy core.
- `scripts/patch-teensy-core.ps1` — Patch script for Teensy core HID changes.

External (non-repo) files modified by patch:
- `C:\Users\andre\.platformio\packages\framework-arduinoteensy\cores\teensy4\usb_desc.h`
- `C:\Users\andre\.platformio\packages\framework-arduinoteensy\cores\teensy4\usb_desc.c`
- `C:\Users\andre\.platformio\packages\framework-arduinoteensy\cores\teensy4\usb_joystick.h`

Those external changes are re-applied by `scripts/patch-teensy-core.ps1`.

## Project Layout

- `platformio.ini`
  - Targets `teensy41` with the Arduino framework.
  - Uses `USB_SERIAL_HID` so the board enumerates with HID support.
- `src/main.cpp`
  - Pin mapping for 5 encoders and 6 analog inputs.
  - Encoder state machine and switch debounce.
  - HID report packing (15 buttons + 6 axes).
  - Deadband and change-detection to reduce noisy updates.
  - Heartbeat LED (fast/slow blink based on USB send health).
- `scripts/patch-teensy-core.ps1`
  - Applies the custom USB descriptor to the PlatformIO Teensy core.
- `PATCH_NOTES.md`
  - Quick instructions for applying the patch on new machines.

## USB HID Descriptor Changes

Why:
- The default Teensy joystick descriptor does not match 15 buttons + 6 axes.
- We need Chromium and Windows to see exactly 6 axes and 15 buttons.

What the patch does:
- Sets `JOYSTICK_SIZE` to **14 bytes** in the `USB_SERIAL_HID` configuration.
- Inserts a **custom report descriptor** for:
  - 15 buttons (bits, with 1 padding bit)
  - 6 axes (16-bit each): X, Y, Z, Rx, Ry, Rz
- Ensures the `manual_mode` static exists in `usb_joystick.h` for non-64 sizes
  (so the core compiles cleanly).

Patch locations (external to repo):
- `...\usb_desc.h`  
  Sets `JOYSTICK_SIZE` to 14 in the `USB_SERIAL_HID` block.
- `...\usb_desc.c`  
  Adds a `JOYSTICK_SIZE == 14` descriptor with 15 buttons + 6 axes.
- `...\usb_joystick.h`  
  Ensures `manual_mode` exists outside the `JOYSTICK_SIZE == 64` guard.

How to apply on a new machine:
```
powershell -ExecutionPolicy Bypass -File scripts/patch-teensy-core.ps1
python -m platformio run -t clean
```

## Pin Mapping (Hardware)

Encoders:
- ENC1_A = D31, ENC1_B = D30, ENC1_SW = D32
- ENC2_A = D28, ENC2_B = D27, ENC2_SW = D29
- ENC3_A = D25, ENC3_B = D24, ENC3_SW = D26
- ENC4_A = D5,  ENC4_B = D9,  ENC4_SW = D10
- ENC5_A = D3,  ENC5_B = D2,  ENC5_SW = D4

Analog inputs:
- FOCUS_POT = A17
- IRIS_POT = A16
- ZOOM_ROCKER = A0
- JOYSTICK_X = A5
- JOYSTICK_Y = A7
- JOYSTICK_Z = A6

## HID Mapping

Buttons (15 total):
- Encoder 1: Button 1 (CW), Button 2 (CCW), Button 3 (Switch)
- Encoder 2: Button 4, 5, 6
- Encoder 3: Button 7, 8, 9
- Encoder 4: Button 10, 11, 12
- Encoder 5: Button 13, 14, 15

Axes (16-bit each):
- X  = JOYSTICK_X
- Y  = JOYSTICK_Y
- Z  = JOYSTICK_Z
- Rx = FOCUS_POT
- Ry = IRIS_POT
- Rz = ZOOM_ROCKER

## Encoder Logic

File: `src/main.cpp`

- Each encoder uses a 2-bit Gray code table to detect direction.
- On each step:
  - CW triggers a momentary button press.
  - CCW triggers a momentary button press.
- Switch inputs are debounced and act as held buttons.

## Analog Scaling and Noise Control

File: `src/main.cpp`

- `analogReadResolution(12)` reads 0–4095.
- Scaled to 16-bit (0–65535).
- Per-axis deadband via `kAxisDeadband` (default 250).
- Report is only sent if the payload changes (prevents idle jitter).

## Heartbeat LED

File: `src/main.cpp`

- LED toggles in `loop()` for a visual USB send health indicator.
- **Slow blink** when HID reports are being accepted.
- **Fast blink** when `usb_joystick_send()` does not succeed for >1s.

You can tune the blink by adjusting:
- `kHeartbeatSlowMs`
- `kHeartbeatFastMs`

## Build and Upload

From the project root:
```
python -m platformio run
python -m platformio run -t upload
```

Clean rebuild (recommended after patching the core):
```
python -m platformio run -t clean
python -m platformio run -t upload
```

## Firmware Version

At boot, the firmware prints the git version to USB serial:

```
FW_VERSION=<short-hash>
```

This is injected at build time by `tools/git_version.py`. If the working tree
was dirty at build, the version is `-dirty` suffixed. You can view it with:

```
python -m platformio device monitor
```

## Notes

- The project depends on patched Teensy core files; use the script in
  `scripts/patch-teensy-core.ps1` to replicate this on another machine.
- If you change the HID report descriptor, update the packing code in
  `src/main.cpp` to match the byte layout.
