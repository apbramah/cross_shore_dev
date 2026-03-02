import json
import os
import socket
import struct
from typing import Dict, Any, List, Optional


UDP_DEFAULT_PORT = 8888
FAST_PORT = 8888
SLOW_CMD_PORT = 8890
SLOW_TELEM_PORT = 8891
BRIDGE_RX_PORT = 8892

PKT_MAGIC = 0xDE
PKT_VER = 0x01

PKT_FAST_CTRL = 0x10
PKT_SLOW_CMD = 0x20
PKT_SLOW_ACK = 0x21
PKT_SLOW_TELEM = 0x30

# Slow-control key IDs (v1)
KEY_MOTORS_ON = 1
KEY_PAN_GAIN = 2
KEY_TILT_GAIN = 3
KEY_ROLL_GAIN = 4
KEY_PAN_ACCEL = 5
KEY_TILT_ACCEL = 6
KEY_ROLL_ACCEL = 7
KEY_EXPO = 8
KEY_PAN_TOP_SPEED = 9
KEY_TILT_TOP_SPEED = 10
KEY_ROLL_TOP_SPEED = 11
KEY_GYRO_DRIFT_OFFSET = 12
KEY_CONTROL_MODE = 13
KEY_LENS_SELECT = 20
KEY_SOURCE_ZOOM = 21
KEY_SOURCE_FOCUS = 22
KEY_SOURCE_IRIS = 23

SLOW_KEYS = {
    "motors_on": KEY_MOTORS_ON,
    "pan_gain": KEY_PAN_GAIN,
    "tilt_gain": KEY_TILT_GAIN,
    "roll_gain": KEY_ROLL_GAIN,
    "pan_acceleration": KEY_PAN_ACCEL,
    "tilt_acceleration": KEY_TILT_ACCEL,
    "roll_acceleration": KEY_ROLL_ACCEL,
    "expo": KEY_EXPO,
    "pan_top_speed": KEY_PAN_TOP_SPEED,
    "tilt_top_speed": KEY_TILT_TOP_SPEED,
    "roll_top_speed": KEY_ROLL_TOP_SPEED,
    "gyro_drift_offset": KEY_GYRO_DRIFT_OFFSET,
    "control_mode": KEY_CONTROL_MODE,
    "lens_select": KEY_LENS_SELECT,
    "source_zoom": KEY_SOURCE_ZOOM,
    "source_focus": KEY_SOURCE_FOCUS,
    "source_iris": KEY_SOURCE_IRIS,
}

SLOW_KEYS_BY_ID = {v: k for (k, v) in SLOW_KEYS.items()}

# Resolve heads.json relative to this file so it works from any CWD
HEADS_FILE = os.path.join(os.path.dirname(__file__), "heads.json")


def load_heads(heads_file: str = HEADS_FILE) -> List[Dict[str, Any]]:
    """
    Load the PTZ heads configuration from heads.json.
    """
    try:
        with open(heads_file, "r") as f:
            heads = json.load(f)
        print(f"Loaded {len(heads)} heads from {heads_file}")
        return heads
    except Exception as e:
        print("Error loading heads.json:", e)
        return []


# Reuse a single UDP socket for the process
_udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


def send_udp(packet: bytes, head: Dict[str, Any]) -> None:
    """
    Send a 16-byte packet to a specific head.
    `head` is a dict like: {"name": "...", "ip": "x.x.x.x", "port": 8888}
    """
    if not head:
        return

    ip = head.get("ip")
    if not ip:
        return

    port = int(head.get("port", UDP_DEFAULT_PORT))
    send_udp_to(ip, port, packet)


def send_udp_to(ip: str, port: int, packet: bytes) -> None:
    _udp_sock.sendto(packet, (ip, int(port)))


def build_fast_packet(axes: Dict[str, Any], control_state: Dict[str, Any], seq: int) -> bytes:
    """
    Match the ORIGINAL controller/main.py behaviour:
    - Browser/desktop axes float [-1..+1] -> int [-512..+512]
    - Apply the same map_* transforms you were using
    - Pack bytes in the SAME byte order as the original send_udp_message()

    Expected axes keys:
      X, Y, Z, Xrotate, Yrotate, Zrotate

    control_state structure:
      {
        "invert": {"yaw": bool, "pitch": bool, "roll": bool},
        "speed": float,
        "zoom_gain": float,
      }
    """

    def f(name: str, default: float = 0.0) -> float:
        try:
            return float(axes.get(name, default))
        except Exception:
            return float(default)

    # Float axes from UI (joysticks/sliders)
    pan = f("X")          # Joystick.X
    tilt = f("Y")         # Joystick.Y
    roll = f("Z")         # Joystick.Z
    focus = f("Xrotate")  # Joystick.Xrotate
    iris = f("Yrotate")   # Joystick.Yrotate
    zoom = f("Zrotate")   # Joystick.Zrotate

    # Deadzones (float domain). Lens axes get stronger deadzone to suppress
    # idle drift/jitter from gamepad ADC noise.
    DEADZONE_MOTION = 0.06
    DEADZONE_LENS = 0.12

    def dz(v: float, threshold: float) -> float:
        return 0.0 if -threshold < v < threshold else v

    pan = dz(pan, DEADZONE_MOTION)
    tilt = dz(tilt, DEADZONE_MOTION)
    roll = dz(roll, DEADZONE_MOTION)
    zoom = dz(zoom, DEADZONE_MOTION)
    focus = dz(focus, DEADZONE_LENS)
    iris = dz(iris, DEADZONE_LENS)

    invert = control_state.get("invert", {}) or {}

    # Invert flags
    if invert.get("yaw"):
        pan = -pan
    if invert.get("pitch"):
        tilt = -tilt
    if invert.get("roll"):
        roll = -roll

    # Speed scaling (float domain, then clamp)
    sp = float(control_state.get("speed", 1.0))
    pan *= sp
    tilt *= sp
    roll *= sp

    def clamp1(v: float) -> float:
        if v < -1.0:
            return -1.0
        if v > 1.0:
            return 1.0
        return v

    pan = clamp1(pan)
    tilt = clamp1(tilt)
    roll = clamp1(roll)
    focus = clamp1(focus)
    iris = clamp1(iris)
    zoom = clamp1(zoom)

    # === ORIGINAL INTERNAL RANGE: -512..+512 ===
    pan_i = int(pan * 512)
    tilt_i = int(tilt * 512)
    roll_i = int(roll * 512)
    # Lens focus/iris are sent as high-resolution absolute controls in 0..16384.
    # This avoids 0..64 quantization noise that caused visible lens jitter.
    focus_i = int(((focus + 1.0) * 0.5) * 16384.0)
    iris_i = int(((iris + 1.0) * 0.5) * 16384.0)
    if focus_i < 0:
        focus_i = 0
    elif focus_i > 16384:
        focus_i = 16384
    if iris_i < 0:
        iris_i = 0
    elif iris_i > 16384:
        iris_i = 16384

    # zoom rocker -> signed delta similar to original feel
    zg = float(control_state.get("zoom_gain", 60.0))
    zoom_i = int(zoom * zg)

    # === ORIGINAL map_* transforms (copied from controller/main.py) ===
    map_zoom = lambda value: (value + 0)
    map_pitch = lambda value: value

    tilt_i = map_pitch(tilt_i)
    zoom_i = map_zoom(zoom_i)

    return struct.pack(
        "<BBBHhHHHHHH",
        PKT_MAGIC,
        PKT_VER,
        PKT_FAST_CTRL,
        int(seq) & 0xFFFF,
        int(zoom_i),
        int(focus_i) & 0xFFFF,
        int(iris_i) & 0xFFFF,
        int(pan_i) & 0xFFFF,
        int(tilt_i) & 0xFFFF,
        int(roll_i) & 0xFFFF,
        0,  # reserved
    )


def decode_fast_packet(packet: bytes) -> Optional[Dict[str, Any]]:
    if len(packet) != 19:
        return None
    magic, ver, pkt_type, seq, zoom, focus, iris, yaw, pitch, roll, _ = struct.unpack("<BBBHhHHHHHH", packet)
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


def build_slow_cmd_packet(seq: int, apply_id: int, key_id: int, value: int) -> bytes:
    return struct.pack(
        "<BBBHHBi",
        PKT_MAGIC,
        PKT_VER,
        PKT_SLOW_CMD,
        int(seq) & 0xFFFF,
        int(apply_id) & 0xFFFF,
        int(key_id) & 0xFF,
        int(value),
    )


def decode_slow_cmd_packet(packet: bytes) -> Optional[Dict[str, Any]]:
    if len(packet) != 12:
        return None
    magic, ver, pkt_type, seq, apply_id, key_id, value = struct.unpack("<BBBHHBi", packet)
    if magic != PKT_MAGIC or ver != PKT_VER or pkt_type != PKT_SLOW_CMD:
        return None
    return {"seq": seq, "apply_id": apply_id, "key_id": key_id, "key": SLOW_KEYS_BY_ID.get(key_id), "value": value}


def build_slow_ack_packet(seq: int, apply_id: int, key_id: int, status: int) -> bytes:
    return struct.pack(
        "<BBBHHBB",
        PKT_MAGIC,
        PKT_VER,
        PKT_SLOW_ACK,
        int(seq) & 0xFFFF,
        int(apply_id) & 0xFFFF,
        int(key_id) & 0xFF,
        int(status) & 0xFF,
    )


def decode_slow_ack_packet(packet: bytes) -> Optional[Dict[str, Any]]:
    if len(packet) != 9:
        return None
    magic, ver, pkt_type, seq, apply_id, key_id, status = struct.unpack("<BBBHHBB", packet)
    if magic != PKT_MAGIC or ver != PKT_VER or pkt_type != PKT_SLOW_ACK:
        return None
    return {"seq": seq, "apply_id": apply_id, "key_id": key_id, "key": SLOW_KEYS_BY_ID.get(key_id), "status": status}


def build_slow_telem_packet(seq: int, telem: Dict[str, Any]) -> bytes:
    motor_power = 1 if bool(telem.get("motor_power", False)) else 0
    control_mode = _encode_control_mode(telem.get("control_mode", "speed"))
    voltage_mv = int(telem.get("voltage_mv", 0)) & 0xFFFF
    pan_pos = int(telem.get("pan_position", 0)) & 0xFFFF
    tilt_pos = int(telem.get("tilt_position", 0)) & 0xFFFF
    roll_pos = int(telem.get("roll_position", 0)) & 0xFFFF
    lens_select = _encode_lens_select(telem.get("lens_select", "fuji"))
    src_zoom = _encode_source(telem.get("source_zoom", "pc"))
    src_focus = _encode_source(telem.get("source_focus", "pc"))
    src_iris = _encode_source(telem.get("source_iris", "pc"))
    zoom_pos = int(telem.get("zoom_position", 0)) & 0xFFFF
    focus_pos = int(telem.get("focus_position", 0)) & 0xFFFF
    iris_pos = int(telem.get("iris_position", 0)) & 0xFFFF
    return struct.pack(
        "<BBBHBBHHHHBBBBHHH",
        PKT_MAGIC,
        PKT_VER,
        PKT_SLOW_TELEM,
        int(seq) & 0xFFFF,
        motor_power,
        control_mode,
        voltage_mv,
        pan_pos,
        tilt_pos,
        roll_pos,
        lens_select,
        src_zoom,
        src_focus,
        src_iris,
        zoom_pos,
        focus_pos,
        iris_pos,
    )


def decode_slow_telem_packet(packet: bytes) -> Optional[Dict[str, Any]]:
    if len(packet) != 25:
        return None
    (
        magic,
        ver,
        pkt_type,
        seq,
        motor_power,
        control_mode,
        voltage_mv,
        pan_pos,
        tilt_pos,
        roll_pos,
        lens_select,
        src_zoom,
        src_focus,
        src_iris,
        zoom_pos,
        focus_pos,
        iris_pos,
    ) = struct.unpack("<BBBHBBHHHHBBBBHHH", packet)
    if magic != PKT_MAGIC or ver != PKT_VER or pkt_type != PKT_SLOW_TELEM:
        return None
    return {
        "seq": seq,
        "motor_power": bool(motor_power),
        "control_mode": _decode_control_mode(control_mode),
        "voltage_mv": voltage_mv,
        "pan_position": pan_pos,
        "tilt_position": tilt_pos,
        "roll_position": roll_pos,
        "lens_select": _decode_lens_select(lens_select),
        "source_zoom": _decode_source(src_zoom),
        "source_focus": _decode_source(src_focus),
        "source_iris": _decode_source(src_iris),
        "zoom_position": zoom_pos,
        "focus_position": focus_pos,
        "iris_position": iris_pos,
    }


def build_udp_packet(axes: Dict[str, Any], control_state: Dict[str, Any]) -> bytes:
    # Back-compat wrapper used by old callers.
    return build_fast_packet(axes, control_state, seq=0)


def _encode_lens_select(value: str) -> int:
    return 1 if str(value).lower() == "canon" else 0


def _decode_lens_select(value: int) -> str:
    return "canon" if int(value) == 1 else "fuji"


def _encode_source(value: str) -> int:
    v = str(value).lower()
    if v == "camera":
        return 1
    if v == "off":
        return 2
    return 0


def _decode_source(value: int) -> str:
    if int(value) == 1:
        return "camera"
    if int(value) == 2:
        return "off"
    return "pc"


def _encode_control_mode(value: str) -> int:
    return 1 if str(value).lower() == "angle" else 0


def _decode_control_mode(value: int) -> str:
    return "angle" if int(value) == 1 else "speed"

