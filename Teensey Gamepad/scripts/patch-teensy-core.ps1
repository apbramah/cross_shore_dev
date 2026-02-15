param(
  [string]$CoreRoot = "$env:USERPROFILE\.platformio\packages\framework-arduinoteensy\cores\teensy4"
)

$ErrorActionPreference = "Stop"

$usbDescH = Join-Path $CoreRoot "usb_desc.h"
$usbDescC = Join-Path $CoreRoot "usb_desc.c"
$usbJoyH = Join-Path $CoreRoot "usb_joystick.h"

if (!(Test-Path $usbDescH) -or !(Test-Path $usbDescC) -or !(Test-Path $usbJoyH)) {
  throw "Teensy core files not found at $CoreRoot"
}

Write-Host "Patching Teensy core in $CoreRoot"

# Update JOYSTICK_SIZE in usb_desc.h (USB_SERIAL_HID section)
$descH = Get-Content $usbDescH -Raw
$descHUpdated = $descH -replace "(#elif defined\(USB_SERIAL_HID\)[\s\S]*?#define JOYSTICK_SIZE\s+)\d+(\s*//[^\r\n]*)", "`$114`$2"
if ($descHUpdated -eq $descH) { throw "Failed to update JOYSTICK_SIZE in usb_desc.h" }
Set-Content -Path $usbDescH -Value $descHUpdated -NoNewline

# Inject custom report descriptor for JOYSTICK_SIZE == 14
$descC = Get-Content $usbDescC -Raw
if ($descC -notmatch "JOYSTICK_SIZE == 14") {
  $insert = @"
#elif JOYSTICK_SIZE == 14
static uint8_t joystick_report_desc[] = {
      0x05, 0x01,                     // Usage Page (Generic Desktop)
      0x09, 0x05,                     // Usage (Gamepad)
      0xA1, 0x01,                     // Collection (Application)
      0x15, 0x00,                     //   Logical Minimum (0)
      0x25, 0x01,                     //   Logical Maximum (1)
      0x75, 0x01,                     //   Report Size (1)
      0x95, 0x0F,                     //   Report Count (15)
      0x05, 0x09,                     //   Usage Page (Button)
      0x19, 0x01,                     //   Usage Minimum (Button #1)
      0x29, 0x0F,                     //   Usage Maximum (Button #15)
      0x81, 0x02,                     //   Input (variable,absolute)
      0x75, 0x01,                     //   Report Size (1)
      0x95, 0x01,                     //   Report Count (1)
      0x81, 0x03,                     //   Input (constant) padding
      0x05, 0x01,                     //   Usage Page (Generic Desktop)
      0x15, 0x00,                     //   Logical Minimum (0)
      0x26, 0xFF, 0xFF,               //   Logical Maximum (65535)
      0x75, 0x10,                     //   Report Size (16)
      0x95, 0x06,                     //   Report Count (6)
      0x09, 0x30,                     //   Usage (X)
      0x09, 0x31,                     //   Usage (Y)
      0x09, 0x32,                     //   Usage (Z)
      0x09, 0x33,                     //   Usage (Rx)
      0x09, 0x34,                     //   Usage (Ry)
      0x09, 0x35,                     //   Usage (Rz)
      0x81, 0x02,                     //   Input (variable,absolute)
      0xC0                            // End Collection
};
"@
  $descCUpdated = $descC -replace "#elif JOYSTICK_SIZE == 64", "$insert`r`n#elif JOYSTICK_SIZE == 64"
  if ($descCUpdated -eq $descC) { throw "Failed to insert JOYSTICK_SIZE 14 descriptor in usb_desc.c" }
  Set-Content -Path $usbDescC -Value $descCUpdated -NoNewline
} else {
  Write-Host "JOYSTICK_SIZE 14 descriptor already present"
}

# Ensure manual_mode static exists for non-64 sizes
$joyH = Get-Content $usbJoyH -Raw
if ($joyH -notmatch "#else[\s\r\n]+private:[\s\r\n]+static uint8_t manual_mode;") {
  $joyHUpdated = $joyH -replace "private:\s*static uint8_t manual_mode;\s*#endif", "private:`r`n`tstatic uint8_t manual_mode;`r`n#else`r`nprivate:`r`n`tstatic uint8_t manual_mode;`r`n#endif"
  if ($joyHUpdated -eq $joyH) { throw "Failed to update usb_joystick.h manual_mode guard" }
  Set-Content -Path $usbJoyH -Value $joyHUpdated -NoNewline
} else {
  Write-Host "usb_joystick.h manual_mode guard already updated"
}

Write-Host "Done. Clean/rebuild required: python -m platformio run -t clean"
