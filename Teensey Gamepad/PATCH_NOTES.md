# Teensy Core Patch

This project relies on a custom Teensy core HID descriptor (15 buttons + 6 axes).

To apply the patch on a new machine:

```
powershell -ExecutionPolicy Bypass -File scripts/patch-teensy-core.ps1
python -m platformio run -t clean
```

Patched files in the PlatformIO Teensy core:

- `usb_desc.h` (JOYSTICK_SIZE set to 14 in `USB_SERIAL_HID`)
- `usb_desc.c` (custom report descriptor for 15 buttons + 6 axes)
- `usb_joystick.h` (manual_mode guard for non-64 sizes)
