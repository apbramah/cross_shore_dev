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

$descH = Get-Content $usbDescH -Raw

# Require clean file: Teensy 4 has no USB_SERIAL_HID; if file was previously mis-patched we need a clean core
if ($descH -match '\$114') {
  Write-Host "ERROR: usb_desc.h contains corrupted fragment (old patch). Restore a clean Teensy core:" -ForegroundColor Red
  Write-Host "  python -m platformio pkg uninstall -g framework-arduinoteensy"
  Write-Host "  python -m platformio run"
  Write-Host "  Then run this patch again."
  throw "Restore clean Teensy core (see above) then re-run patch."
}

# Teensy 4 usb_desc.h has no USB_SERIAL_HID block (Teensy 3 has it). Insert one if missing.
if ($descH -notmatch "#elif defined\(USB_SERIAL_HID\)") {
  $usbSerialHidBlock = @"
#elif defined(USB_SERIAL_HID)
  #define VENDOR_ID		0x16C0
  #define PRODUCT_ID		0x0487
  #define MANUFACTURER_NAME	{'T','e','e','n','s','y','d','u','i','n','o'}
  #define MANUFACTURER_NAME_LEN	11
  #define PRODUCT_NAME		{'S','e','r','i','a','l','/','K','e','y','b','o','a','r','d','/','M','o','u','s','e','/','J','o','y','s','t','i','c','k'}
  #define PRODUCT_NAME_LEN	30
  #define EP0_SIZE		64
  #define NUM_ENDPOINTS         7
  #define NUM_INTERFACE		6
  #define CDC_IAD_DESCRIPTOR	1
  #define CDC_STATUS_INTERFACE	0
  #define CDC_DATA_INTERFACE	1
  #define CDC_ACM_ENDPOINT	2
  #define CDC_RX_ENDPOINT       3
  #define CDC_TX_ENDPOINT       3
  #define CDC_ACM_SIZE          16
  #define CDC_RX_SIZE_480       512
  #define CDC_TX_SIZE_480       512
  #define CDC_RX_SIZE_12        64
  #define CDC_TX_SIZE_12        64
  #define KEYBOARD_INTERFACE    2
  #define KEYBOARD_ENDPOINT     4
  #define KEYBOARD_SIZE         8
  #define KEYBOARD_INTERVAL     1
  #define KEYMEDIA_INTERFACE    5
  #define KEYMEDIA_ENDPOINT     5
  #define KEYMEDIA_SIZE         8
  #define KEYMEDIA_INTERVAL     4
  #define MOUSE_INTERFACE       3
  #define MOUSE_ENDPOINT        6
  #define MOUSE_SIZE            8
  #define MOUSE_INTERVAL        1
  #define JOYSTICK_INTERFACE    4
  #define JOYSTICK_ENDPOINT     7
  #define JOYSTICK_SIZE         14
  #define JOYSTICK_INTERVAL     1
  #define ENDPOINT2_CONFIG	ENDPOINT_RECEIVE_UNUSED + ENDPOINT_TRANSMIT_INTERRUPT
  #define ENDPOINT3_CONFIG	ENDPOINT_RECEIVE_BULK + ENDPOINT_TRANSMIT_BULK
  #define ENDPOINT4_CONFIG	ENDPOINT_RECEIVE_UNUSED + ENDPOINT_TRANSMIT_INTERRUPT
  #define ENDPOINT5_CONFIG	ENDPOINT_RECEIVE_UNUSED + ENDPOINT_TRANSMIT_INTERRUPT
  #define ENDPOINT6_CONFIG	ENDPOINT_RECEIVE_UNUSED + ENDPOINT_TRANSMIT_INTERRUPT
  #define ENDPOINT7_CONFIG	ENDPOINT_RECEIVE_UNUSED + ENDPOINT_TRANSMIT_INTERRUPT

"@
  # Insert before next #elif (Teensy 4 has no USB_TOUCHSCREEN; use USB_MTPDISK or USB_TOUCHSCREEN)
  $try1 = $descH -replace "(#elif defined\(USB_TOUCHSCREEN\))", "$usbSerialHidBlock`r`n`$1"
  if ($try1 -eq $descH) { $descH = $descH -replace "(#elif defined\(USB_MTPDISK\))", "$usbSerialHidBlock`r`n`$1" } else { $descH = $try1 }
  if ($descH -notmatch "#elif defined\(USB_SERIAL_HID\)") { throw "Failed to insert USB_SERIAL_HID block in usb_desc.h" }
  Set-Content -Path $usbDescH -Value $descH -NoNewline
  $descH = Get-Content $usbDescH -Raw
  Write-Host "Inserted USB_SERIAL_HID block (Teensy 4 has no built-in Serial+Joystick config)"
}

# Update JOYSTICK_SIZE in usb_desc.h (USB_SERIAL_HID section) to 14 if still 12
$descHUpdated = $descH -replace "(#elif defined\(USB_SERIAL_HID\)[\s\S]*?#define JOYSTICK_SIZE\s+)\d+(\s*//[^\r\n]*)", '${1}14${2}'
if ($descHUpdated -ne $descH) {
  Set-Content -Path $usbDescH -Value $descHUpdated -NoNewline
}

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
      // Signed 16-bit axes: Logical Min -32768, Max 32767. Linux evdev/Chromium
      // normalize and apply deadzone assuming axes are centered at 0; unsigned
      // 0..65535 causes asymmetric one-sided deadband when stack assumes center.
      0x05, 0x01,                     //   Usage Page (Generic Desktop)
      0x16, 0x00, 0x80,               //   Logical Minimum (-32768) signed 16-bit
      0x26, 0xFF, 0x7F,               //   Logical Maximum (32767)
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
  # Update existing descriptor to signed 16-bit axes if still unsigned (idempotent)
  $descCUpdated = $descC -replace "0x15, 0x00,\s+//\s+Logical Minimum \(0\)\s+0x26, 0xFF, 0xFF,\s+//\s+Logical Maximum \(65535\)", "0x16, 0x00, 0x80,               //   Logical Minimum (-32768) signed 16-bit`r`n      0x26, 0xFF, 0x7F,               //   Logical Maximum (32767)"
  if ($descCUpdated -ne $descC) {
    Set-Content -Path $usbDescC -Value $descCUpdated -NoNewline
    Write-Host "Updated axis range to signed 16-bit (-32768..32767)"
  }
}

# Teensy 4 usb_joystick.h already has manual_mode; ensure JOYSTICK_SIZE == 14 is accepted (add #elif if needed)
$joyH = Get-Content $usbJoyH -Raw
if ($joyH -notmatch "JOYSTICK_SIZE == 14" -and $joyH -match "#elif JOYSTICK_SIZE == 64") {
  $joyHUpdated = $joyH -replace "(#elif JOYSTICK_SIZE == 64)", "#elif JOYSTICK_SIZE == 14`r`n`t// 14-byte manual report (15 buttons + 6 axes)`r`n#elif JOYSTICK_SIZE == 64"
  if ($joyHUpdated -ne $joyH) { Set-Content -Path $usbJoyH -Value $joyHUpdated -NoNewline; Write-Host "Added JOYSTICK_SIZE == 14 branch in usb_joystick.h" }
} elseif ($joyH -notmatch "#else[\s\r\n]+private:[\s\r\n]+static uint8_t manual_mode;") {
  $joyHUpdated = $joyH -replace "private:\s*static uint8_t manual_mode;\s*#endif", "private:`r`n`tstatic uint8_t manual_mode;`r`n#else`r`nprivate:`r`n`tstatic uint8_t manual_mode;`r`n#endif"
  if ($joyHUpdated -ne $joyH) { Set-Content -Path $usbJoyH -Value $joyHUpdated -NoNewline; Write-Host "Updated usb_joystick.h manual_mode guard" }
} else {
  Write-Host "usb_joystick.h already OK for JOYSTICK_SIZE 14"
}

Write-Host "Done. Clean/rebuild required: python -m platformio run -t clean"
