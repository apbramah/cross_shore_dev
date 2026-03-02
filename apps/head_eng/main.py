# =====================================
# MVP Head Firmware (Ethernet + Control)
# =====================================

import network
import machine
import time
import socket
import struct

from bgc import BGC
from lens_controller import LensController, LENS_FUJI

# Local debug override when running MVP without websocket source controls.
# Set to one of: "pc", "camera", "off"
TEST_FUJI_SOURCE_MODE = "pc"
FAST_CHANNEL_MODE = "v2"  # Set to "legacy" for immediate rollback.
ENABLE_DUAL_CHANNEL = FAST_CHANNEL_MODE == "v2"
ENABLE_SLOW_CHANNEL = True   # Slow receive/apply remains active in both modes.

# ---------- LED ----------
led = machine.Pin("LED", machine.Pin.OUT)
pulse_until = 0


def pulse(ms=20):
    global pulse_until
    led.on()
    pulse_until = time.ticks_add(time.ticks_ms(), ms)


def pulse_update():
    global pulse_until
    if pulse_until and time.ticks_diff(time.ticks_ms(), pulse_until) >= 0:
        led.off()
        pulse_until = 0


# ---------- Ethernet ----------
spi = machine.SPI(
    0,
    2_000_000,
    mosi=machine.Pin(19),
    miso=machine.Pin(16),
    sck=machine.Pin(18)
)

nic = network.WIZNET5K(
    spi,
    machine.Pin(17),  # CS
    machine.Pin(20)   # RESET
)

nic.active(True)

nic.ifconfig((
    "192.168.60.120",
    "255.255.255.0",
    "192.168.60.1",
    "8.8.8.8"
))

while not nic.isconnected():
    time.sleep(0.2)

print("Ethernet ready:", nic.ifconfig())

# ---------- Hardware ----------
bgc = BGC()
lens = LensController(default_lens_type=LENS_FUJI)
last_applied_lens_type = None
last_applied_sources = {"zoom": None, "focus": None, "iris": None}

print("BGC + ENG lens ready")
# Lens startup is timing-sensitive on real hardware; give it a short settle window.
for remaining in range(8, 0, -1):
    print("Waiting for lens settle...", remaining, "s")
    time.sleep(1)
bit_ok = lens.startup_diagnostics()
print("LENS startup diagnostics:", "PASS" if bit_ok else "FAIL")

def apply_fuji_source_override():
    mode = str(TEST_FUJI_SOURCE_MODE).lower().strip()
    if lens.get_lens_type() != LENS_FUJI:
        print("Fuji source override skipped (active lens is not Fuji)")
        return
    if mode not in ("pc", "camera", "off"):
        print("Fuji source override ignored (invalid mode):", mode)
        return
    for axis in ("zoom", "focus", "iris"):
        ok = lens.set_axis_source(axis, mode)
        print("Fuji source override", axis, "->", mode, "ok=" + str(ok))

apply_fuji_source_override()

# ---------- UDP ----------
FAST_UDP_PORT = 8888
SLOW_UDP_PORT = 8890

PKT_MAGIC = 0xDE
PKT_VER = 0x01
PKT_FAST_CTRL = 0x10
PKT_SLOW_CMD = 0x20
SLOW_KEY_MOTORS_ON = 1
SLOW_KEY_CONTROL_MODE = 2
SLOW_KEY_LENS_SELECT = 3
SLOW_KEY_SOURCE_ZOOM = 4
SLOW_KEY_SOURCE_FOCUS = 5
SLOW_KEY_SOURCE_IRIS = 6

sock_fast = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock_fast.bind(("0.0.0.0", FAST_UDP_PORT))
sock_fast.setblocking(False)

sock_slow = None
if ENABLE_SLOW_CHANNEL:
    sock_slow = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock_slow.bind(("0.0.0.0", SLOW_UDP_PORT))
    sock_slow.setblocking(False)

print("Listening FAST UDP on", FAST_UDP_PORT)
print("Fast channel mode:", FAST_CHANNEL_MODE)
if ENABLE_SLOW_CHANNEL:
    print("Listening SLOW UDP on", SLOW_UDP_PORT)


def decode_fast_packet_v2(packet):
    # <BBBHhHHHHHH => magic, ver, type, seq, zoom, focus, iris, yaw, pitch, roll, reserved
    if len(packet) != 19:
        return None
    try:
        magic, ver, pkt_type, seq, zoom, focus, iris, yaw, pitch, roll, _ = struct.unpack("<BBBHhHHHHHH", packet)
    except Exception:
        return None
    if magic != PKT_MAGIC or ver != PKT_VER or pkt_type != PKT_FAST_CTRL:
        return None
    return {
        "seq": seq,
        "zoom": zoom,
        "focus": focus,
        "iris": iris,
        "yaw": yaw,
        "pitch": pitch,
        "roll": roll,
    }


def decode_slow_cmd_packet(packet):
    # <BBBHHBi => magic, ver, type, seq, apply_id, key_id, value
    if len(packet) != 12:
        return None
    try:
        magic, ver, pkt_type, seq, apply_id, key_id, value = struct.unpack("<BBBHHBi", packet)
    except Exception:
        return None
    if magic != PKT_MAGIC or ver != PKT_VER or pkt_type != PKT_SLOW_CMD:
        return None
    return {
        "seq": seq,
        "apply_id": apply_id,
        "key_id": key_id,
        "value": value,
    }


def poll_slow_command_once():
    """Read one slow command packet if available."""
    if not ENABLE_SLOW_CHANNEL or sock_slow is None:
        return None
    try:
        data, _addr = sock_slow.recvfrom(256)
    except OSError:
        return None
    if not data:
        return None
    return decode_slow_cmd_packet(data)


def _decode_lens_select(v):
    return "canon" if int(v) == 1 else "fuji"


def _decode_source(v):
    iv = int(v)
    if iv == 1:
        return "camera"
    if iv == 2:
        return "off"
    return "pc"


def apply_slow_command(cmd):
    global last_applied_lens_type, last_applied_sources
    key = cmd.get("key_id")
    value = cmd.get("value")
    if key == SLOW_KEY_LENS_SELECT:
        requested_type = _decode_lens_select(value)
        if requested_type != last_applied_lens_type:
            changed = lens.set_lens_type(requested_type)
            if changed:
                last_applied_lens_type = requested_type
                print("Slow apply lens_select ->", requested_type)
        return

    if key == SLOW_KEY_SOURCE_ZOOM:
        src = _decode_source(value)
        if src != last_applied_sources.get("zoom"):
            if lens.set_axis_source("zoom", src):
                last_applied_sources["zoom"] = src
                print("Slow apply source_zoom ->", src)
        return

    if key == SLOW_KEY_SOURCE_FOCUS:
        src = _decode_source(value)
        if src != last_applied_sources.get("focus"):
            if lens.set_axis_source("focus", src):
                last_applied_sources["focus"] = src
                print("Slow apply source_focus ->", src)
        return

    if key == SLOW_KEY_SOURCE_IRIS:
        src = _decode_source(value)
        if src != last_applied_sources.get("iris"):
            if lens.set_axis_source("iris", src):
                last_applied_sources["iris"] = src
                print("Slow apply source_iris ->", src)
        return

    if key == SLOW_KEY_MOTORS_ON:
        # BGC slow keys are accepted on wire in Gate 3 but not applied yet.
        return

    if key == SLOW_KEY_CONTROL_MODE:
        # BGC slow keys are accepted on wire in Gate 3 but not applied yet.
        return

# ---------- Main Loop ----------
while True:
    pulse_update()
    _slow_cmd = poll_slow_command_once()
    if _slow_cmd:
        apply_slow_command(_slow_cmd)

    try:
        data, addr = sock_fast.recvfrom(1024)
    except OSError:
        # Keep lens ownership/keepalive alive even without incoming UDP packets.
        lens.periodic()
        time.sleep(0.001)
        continue

    if not data:
        lens.periodic()
        continue

    if ENABLE_DUAL_CHANNEL:
        fields = decode_fast_packet_v2(data)
        if not fields:
            lens.periodic()
            continue
    else:
        fields = BGC.decode_udp_packet(data)
    if not fields:
        lens.periodic()
        continue

    print(
        "CTRL YPRZFI:",
        fields["yaw"],
        fields["pitch"],
        fields["roll"],
        fields["zoom"],
        fields["focus"],
        fields["iris"],
    )
    pulse(15)

    # Send directly to BGC
    bgc.send_joystick_control(
        fields["yaw"],
        fields["pitch"],
        fields["roll"]
    )

    # Gate runtime lens commands until startup BIT passes.
    lens_control = fields.get("lens_control")
    if lens_control:
        requested_type = lens_control.get("lens_type")
        if requested_type and requested_type != last_applied_lens_type:
            changed = lens.set_lens_type(requested_type)
            if changed:
                last_applied_lens_type = requested_type
                print("Applied lens_type from packet:", requested_type)

        requested_sources = lens_control.get("axis_sources", {}) or {}
        for axis in ("zoom", "focus", "iris"):
            req_src = requested_sources.get(axis)
            if req_src and req_src != last_applied_sources.get(axis):
                ok = lens.set_axis_source(axis, req_src)
                if ok:
                    last_applied_sources[axis] = req_src
                    print("Applied source from packet:", axis, "->", req_src)

    if bit_ok:
        lens.move_zoom(fields["zoom"])
        lens.set_focus_input(fields["focus"])
        lens.set_iris_input(fields["iris"])
    lens.periodic()
