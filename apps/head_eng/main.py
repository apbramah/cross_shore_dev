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
import fuji_lens_from_calibration
import fuji_control_calibration

# Explicit startup Fuji ownership mode (applied once).
# - "pc_all": zoom/focus/iris on host
# - "pc_zf_camera_i": zoom/focus host, iris camera
FUJI_OWNERSHIP_MODE = "pc_all"
FAST_CHANNEL_MODE = "v2"  # Set to "legacy" for immediate rollback.
ENABLE_DUAL_CHANNEL = FAST_CHANNEL_MODE == "v2"
ENABLE_SLOW_CHANNEL = True   # Slow receive/apply remains active in both modes.
CTRL_DEBUG = True
CTRL_DEBUG_INTERVAL_MS = 250
ENABLE_STARTUP_BIT = False
MVP_FAST_DEBUG = False
MVP_FAST_DEBUG_INTERVAL_MS = 5000
# Set True to log Fuji focus input/target and UART connection (SW4 poll, FOCUS TX).
FUJI_DEBUG = False

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

nic = network.WIZNET5K(  # type: ignore[attr-defined]
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
last_applied_sources = {"zoom": "pc", "focus": "pc", "iris": "pc"}
_last_slow_apply_id = None
_last_slow_seq = None
slow_motors_on = True
slow_control_mode = "speed"
_last_ctrl_debug_ms = 0
_fast_recv_count = 0
_last_fast_fields = None
_last_fast_debug_ms = 0

print("BGC + ENG lens ready")
if FUJI_DEBUG:
    fuji_lens_from_calibration.FUJI_FOCUS_DEBUG = True
    fuji_control_calibration.FUJI_CONN_DEBUG = True
    print("Fuji focus/connection debug ON")
# Lens startup is timing-sensitive on real hardware; give it a short settle window.
for remaining in range(8, 0, -1):
    print("Waiting for lens settle...", remaining, "s")
    time.sleep(1)
if ENABLE_STARTUP_BIT:
    bit_ok = lens.startup_diagnostics()
    print("LENS startup diagnostics:", "PASS" if bit_ok else "FAIL")
else:
    bit_ok = True
    print("LENS startup diagnostics: SKIPPED (ENABLE_STARTUP_BIT=False)")

def _fuji_sw4_bits_from_sources(sources):
    bits = 0xF8
    if sources.get("focus") != "pc":
        bits |= 0x01
    if sources.get("zoom") != "pc":
        bits |= 0x02
    if sources.get("iris") != "pc":
        bits |= 0x04
    return bits & 0xFF


def apply_fuji_ownership_mode_once():
    mode = str(FUJI_OWNERSHIP_MODE).lower().strip()
    if lens.get_lens_type() != LENS_FUJI:
        print("Fuji ownership mode skipped (active lens is not Fuji)")
        return
    mode_map = {
        "pc_all": {"zoom": "pc", "focus": "pc", "iris": "pc"},
        "pc_zf_camera_i": {"zoom": "pc", "focus": "pc", "iris": "camera"},
    }
    desired_sources = mode_map.get(mode)
    if desired_sources is None:
        print("Fuji ownership mode ignored (invalid mode):", mode)
        return
    for axis in ("zoom", "focus", "iris"):
        source = desired_sources[axis]
        ok = lens.set_axis_source(axis, source)
        print("Fuji ownership apply", axis, "->", source, "ok=" + str(ok))
    effective_sources = lens.get_axis_sources()
    print(
        "Fuji ownership mode effective:",
        mode,
        "sources=" + str(effective_sources),
        "desired_sw4=0x{:02X}".format(_fuji_sw4_bits_from_sources(effective_sources)),
    )

apply_fuji_ownership_mode_once()
last_applied_lens_type = lens.get_lens_type()
last_applied_sources = lens.get_axis_sources()

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
SLOW_KEY_FILTER_ENABLE_FOCUS = 7
SLOW_KEY_FILTER_ENABLE_IRIS = 8
SLOW_KEY_FILTER_NUM = 9
SLOW_KEY_FILTER_DEN = 10
SLOW_KEY_GYRO_HEADING_CORRECTION = 11

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


def recv_latest_fast_packet():
    """Drain fast socket and return the most recent packet."""
    latest_data = None
    latest_addr = None
    while True:
        try:
            data, addr = sock_fast.recvfrom(1024)
        except OSError:
            break
        if not data:
            continue
        latest_data = data
        latest_addr = addr
    return latest_data, latest_addr


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
    global last_applied_lens_type, last_applied_sources, _last_slow_apply_id, _last_slow_seq
    global slow_motors_on, slow_control_mode
    apply_id = cmd.get("apply_id")
    seq = cmd.get("seq")
    if apply_id == _last_slow_apply_id and seq == _last_slow_seq:
        return
    _last_slow_apply_id = apply_id
    _last_slow_seq = seq
    key = cmd.get("key_id")
    value = cmd.get("value")
    if key == SLOW_KEY_LENS_SELECT:
        requested_type = _decode_lens_select(value)
        if requested_type != lens.get_lens_type():
            changed = lens.set_lens_type(requested_type)
            if changed:
                last_applied_lens_type = requested_type
                last_applied_sources = lens.get_axis_sources()
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

    if key == SLOW_KEY_FILTER_ENABLE_FOCUS:
        enabled = int(value) != 0
        if lens.set_input_filter_enabled("focus", enabled):
            print("Slow apply focus_filter_enabled ->", enabled)
        return

    if key == SLOW_KEY_FILTER_ENABLE_IRIS:
        enabled = int(value) != 0
        if lens.set_input_filter_enabled("iris", enabled):
            print("Slow apply iris_filter_enabled ->", enabled)
        return

    if key == SLOW_KEY_FILTER_NUM:
        if lens.set_input_filter_num(int(value)):
            print("Slow apply input_filter_num ->", int(value))
        return

    if key == SLOW_KEY_FILTER_DEN:
        if lens.set_input_filter_den(int(value)):
            print("Slow apply input_filter_den ->", int(value))
        return

    if key == SLOW_KEY_MOTORS_ON:
        enabled = int(value) != 0
        if enabled != slow_motors_on:
            slow_motors_on = enabled
            bgc.set_motors_enabled(enabled)
            print("Slow apply motors_on ->", 1 if enabled else 0, "(BGC CMD sent)")
        return

    if key == SLOW_KEY_CONTROL_MODE:
        mode = "angle" if int(value) == 1 else "speed"
        if mode != slow_control_mode:
            slow_control_mode = mode
            if mode == "speed":
                bgc.disable_angle_mode()
                print("Slow apply control_mode -> speed (angle mode disabled)")
            else:
                print("Slow apply control_mode -> angle (accepted; apply pending)")
        return

    if key == SLOW_KEY_GYRO_HEADING_CORRECTION:
        v = int(value)
        print("Slow recv gyro_heading_correction key/value:", key, v)
        bgc.set_gyro_heading_correction(v)
        print("Slow apply gyro_heading_correction ->", v, "(BGC CMD sent)")
        return

# ---------- Main Loop ----------
while True:
    pulse_update()
    _slow_cmd = poll_slow_command_once()
    if _slow_cmd:
        apply_slow_command(_slow_cmd)

    data, addr = recv_latest_fast_packet()

    if not data:
        # Keep lens ownership/keepalive alive even without incoming UDP packets.
        lens.periodic()
        time.sleep(0.001)
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

    _fast_recv_count += 1
    _last_fast_fields = fields
    if MVP_FAST_DEBUG:
        now_fd = time.ticks_ms()
        if time.ticks_diff(now_fd, _last_fast_debug_ms) >= MVP_FAST_DEBUG_INTERVAL_MS:
            _last_fast_debug_ms = now_fd
            print(
                "[FAST_DEBUG] recvs=",
                _fast_recv_count,
                "seq=",
                fields.get("seq"),
                "yaw pitch roll zoom focus iris:",
                fields.get("yaw"),
                fields.get("pitch"),
                fields.get("roll"),
                fields.get("zoom"),
                fields.get("focus"),
                fields.get("iris"),
            )

    if CTRL_DEBUG:
        now_dbg = time.ticks_ms()
        if time.ticks_diff(now_dbg, _last_ctrl_debug_ms) >= CTRL_DEBUG_INTERVAL_MS:
            _last_ctrl_debug_ms = now_dbg
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

    # Apply slow gate to BGC joystick stream.
    if slow_motors_on:
        # SimpleBGC CMD 45 Speed: u16 0 -> -500, 32768 -> 0, 65535 -> +500; int16 LE
        def u16_to_bgc_speed(u):
            u = max(0, min(65535, int(u)))
            s = round((u - 32768) / 32768.0 * 500.0)
            return max(-500, min(500, s))
        yaw_s = u16_to_bgc_speed(fields["yaw"])
        pitch_s = u16_to_bgc_speed(fields["pitch"])
        roll_s = u16_to_bgc_speed(fields["roll"])
        bgc.send_joystick_control(yaw_s, pitch_s, roll_s)

    # Runtime lens commands are not gated by startup BIT.
    lens_control = fields.get("lens_control")
    if lens_control:
        requested_type = lens_control.get("lens_type")
        if requested_type and requested_type != lens.get_lens_type():
            changed = lens.set_lens_type(requested_type)
            if changed:
                last_applied_lens_type = requested_type
                last_applied_sources = lens.get_axis_sources()
                print("Applied lens_type from packet:", requested_type)

        requested_sources = lens_control.get("axis_sources", {}) or {}
        for axis in ("zoom", "focus", "iris"):
            req_src = requested_sources.get(axis)
            if req_src and req_src != last_applied_sources.get(axis):
                ok = lens.set_axis_source(axis, req_src)
                if ok:
                    last_applied_sources[axis] = req_src
                    print("Applied source from packet:", axis, "->", req_src)

    lens.move_zoom(fields["zoom"])
    lens.set_focus_input(fields["focus"])
    lens.set_iris_input(fields["iris"])
    lens.periodic()
