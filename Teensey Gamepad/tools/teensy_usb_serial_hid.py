"""
Ensure USB_SERIAL_HID is used for Teensy build. The platform's Arduino script
adds USB_SERIAL to CPPDEFINES when no USB flag is present; build_flags -D are
merged into CXXFLAGS later, so both can end up defined and usb_desc.h picks
USB_SERIAL first. This script removes USB_SERIAL from CPPDEFINES and adds
USB_SERIAL_HID so the Serial+Joystick HID configuration is used.
"""
Import("env")

defines = env.get("CPPDEFINES", [])
# Normalize to list of items (each is string or (name, value))
if not isinstance(defines, list):
    defines = [defines] if defines else []
def _name(d):
    return d[0] if isinstance(d, (list, tuple)) and len(d) else d

# Remove default USB_SERIAL so USB_SERIAL_HID takes effect in usb_desc.h
new_defines = [d for d in defines if _name(d) != "USB_SERIAL"]
# Ensure USB_SERIAL_HID is in CPPDEFINES
if not any(_name(d) == "USB_SERIAL_HID" for d in new_defines):
    new_defines.append("USB_SERIAL_HID")
env.Replace(CPPDEFINES=new_defines)

# Force -U USB_SERIAL and -D USB_SERIAL_HID on compiler line so usb_desc.h
# selects Serial+Joystick HID even if CPPDEFINES order is wrong
env.Append(CCFLAGS=["-UUSB_SERIAL", "-DUSB_SERIAL_HID"])
env.Append(CXXFLAGS=["-UUSB_SERIAL", "-DUSB_SERIAL_HID"])
