# Teensy Core Patch

This project relies on a custom Teensy core HID descriptor (15 buttons + 6 axes, signed 16-bit).

To apply the patch on a new machine:

1. **Use a clean Teensy 4 core.** From the `Teensey Gamepad` folder, run (the first word must be `powershell` — the executable — not `Get-ExecutionPolicy`):

```powershell
powershell -ExecutionPolicy Bypass -File scripts/patch-teensy-core.ps1
python -m platformio run -t clean
```

If the script reports **"usb_desc.h contains corrupted fragment"**, the core was previously mis-patched. Restore a clean core then re-run the patch:

```powershell
Remove-Item -Recurse -Force "$env:USERPROFILE\.platformio\packages\framework-arduinoteensy" -ErrorAction SilentlyContinue
python -m platformio run
powershell -ExecutionPolicy Bypass -File scripts/patch-teensy-core.ps1
python -m platformio run -t clean
python -m platformio run
```

Patched files in the PlatformIO Teensy core:

- `usb_desc.h` (JOYSTICK_SIZE set to 14 in `USB_SERIAL_HID`)
- `usb_desc.c` (custom report descriptor for 15 buttons + 6 axes)
- `usb_joystick.h` (manual_mode guard for non-64 sizes)
