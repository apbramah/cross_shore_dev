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
ENABLE_DUAL_CHANNEL = False  # Gate 2: keep disabled to preserve baseline behavior.

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

sock_fast = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock_fast.bind(("0.0.0.0", FAST_UDP_PORT))
sock_fast.setblocking(False)

sock_slow = None
if ENABLE_DUAL_CHANNEL:
    sock_slow = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock_slow.bind(("0.0.0.0", SLOW_UDP_PORT))
    sock_slow.setblocking(False)

print("Listening FAST UDP on", FAST_UDP_PORT)
if ENABLE_DUAL_CHANNEL:
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
    """Gate 2 scaffold: parse a slow command but do not apply behavior changes yet."""
    if not ENABLE_DUAL_CHANNEL or sock_slow is None:
        return None
    try:
        data, _addr = sock_slow.recvfrom(256)
    except OSError:
        return None
    if not data:
        return None
    return decode_slow_cmd_packet(data)

# ---------- Main Loop ----------
while True:
    pulse_update()
    _slow_cmd = poll_slow_command_once()

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
