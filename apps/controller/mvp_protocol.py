import json
import os
import socket
import struct
from typing import Dict, Any, List, Optional


UDP_DEFAULT_PORT = 8888
FAST_PORT = 8888
SLOW_CMD_PORT = 8890
SLOW_TELEM_PORT = 8891

PKT_MAGIC = 0xDE
PKT_VER = 0x01
PKT_FAST_CTRL = 0x10
PKT_SLOW_CMD = 0x20
PKT_SLOW_ACK = 0x21
PKT_SLOW_TELEM = 0x30
PKT_SCHEMA_VERSION = 2

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
SLOW_KEY_WASH_WIPE = 12
SLOW_KEY_PAN_ACCEL = 13
SLOW_KEY_TILT_ACCEL = 14
SLOW_KEY_ROLL_ACCEL = 15
SLOW_KEY_PAN_GAIN = 16
SLOW_KEY_TILT_GAIN = 17
SLOW_KEY_ROLL_GAIN = 18
SLOW_KEY_NETCFG_IP_HI = 40
SLOW_KEY_NETCFG_IP_LO = 41
SLOW_KEY_NETCFG_GW_HI = 42
SLOW_KEY_NETCFG_GW_LO = 43
SLOW_KEY_NETCFG_PREFIX = 44
SLOW_KEY_NETCFG_APPLY = 45
SLOW_KEY_NETCFG_ENTER = 46
SLOW_KEY_NETCFG_EXIT = 47

SLOW_KEY_IDS = {
    "motors_on": SLOW_KEY_MOTORS_ON,
    "control_mode": SLOW_KEY_CONTROL_MODE,
    "lens_select": SLOW_KEY_LENS_SELECT,
    "source_zoom": SLOW_KEY_SOURCE_ZOOM,
    "source_focus": SLOW_KEY_SOURCE_FOCUS,
    "source_iris": SLOW_KEY_SOURCE_IRIS,
    "filter_enable_focus": SLOW_KEY_FILTER_ENABLE_FOCUS,
    "filter_enable_iris": SLOW_KEY_FILTER_ENABLE_IRIS,
    "filter_num": SLOW_KEY_FILTER_NUM,
    "filter_den": SLOW_KEY_FILTER_DEN,
    "gyro_heading_correction": SLOW_KEY_GYRO_HEADING_CORRECTION,
    "wash_wipe": SLOW_KEY_WASH_WIPE,
    "pan_accel": SLOW_KEY_PAN_ACCEL,
    "tilt_accel": SLOW_KEY_TILT_ACCEL,
    "roll_accel": SLOW_KEY_ROLL_ACCEL,
    "pan_gain": SLOW_KEY_PAN_GAIN,
    "tilt_gain": SLOW_KEY_TILT_GAIN,
    "roll_gain": SLOW_KEY_ROLL_GAIN,
}

NETWORK_SLOW_KEY_IDS = {
    "netcfg_ip_hi": SLOW_KEY_NETCFG_IP_HI,
    "netcfg_ip_lo": SLOW_KEY_NETCFG_IP_LO,
    "netcfg_gw_hi": SLOW_KEY_NETCFG_GW_HI,
    "netcfg_gw_lo": SLOW_KEY_NETCFG_GW_LO,
    "netcfg_prefix": SLOW_KEY_NETCFG_PREFIX,
    "netcfg_apply": SLOW_KEY_NETCFG_APPLY,
    "netcfg_enter": SLOW_KEY_NETCFG_ENTER,
    "netcfg_exit": SLOW_KEY_NETCFG_EXIT,
}

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


def send_udp_to(ip: str, port: int, packet: bytes) -> bool:
    """
    Best-effort UDP send.
    Returns True on success; False on transient network/socket failure.
    """
    try:
        _udp_sock.sendto(packet, (ip, int(port)))
        return True
    except OSError as e:
        # Keep callers alive during transient route/link startup races.
        print(f"UDP send failed to {ip}:{int(port)}: {e}")
        return False


def build_udp_packet(axes: Dict[str, Any], control_state: Dict[str, Any]) -> bytes:
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

    # Deadzone (float domain)
    DEADZONE = 0.06

    def dz(v: float) -> float:
        return 0.0 if -DEADZONE < v < DEADZONE else v

    pan = dz(pan)
    tilt = dz(tilt)
    roll = dz(roll)
    focus = dz(focus)
    iris = dz(iris)
    zoom = dz(zoom)

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

    if invert.get("zoom"):
        zoom = -zoom

    # === ORIGINAL INTERNAL RANGE: -512..+512 ===
    pan_i = int(pan * 512)
    tilt_i = int(tilt * 512)
    roll_i = int(roll * 512)
    focus_i = int(focus * 512)
    iris_i = int(iris * 512)

    # zoom rocker -> signed delta similar to original feel
    zg = float(control_state.get("zoom_gain", 60.0))
    zoom_i = int(zoom * zg)

    # === ORIGINAL map_* transforms (copied from controller/main.py) ===
    map_zoom = lambda value: (value + 0)
    map_iris = lambda value: (value + 512) >> 4
    map_focus = lambda value: (value + 512) >> 4
    map_pitch = lambda value: value

    tilt_i = map_pitch(tilt_i)
    zoom_i = map_zoom(zoom_i)
    focus_i = map_focus(focus_i)
    iris_i = map_iris(iris_i)

    # Optional lens control sideband for MVP head_eng.
    ctrl0, ctrl1 = _encode_lens_control(control_state)

    # Pack EXACTLY like original send_udp_message() byte order.
    # Last 2 bytes were historically reserved (0x00, 0x00). We now use them
    # for optional lens control sideband with marker ctrl1=0xA5.
    msg = bytes(
        [
            0xDE,
            0xFD,
            zoom_i & 0xFF,
            (zoom_i >> 8) & 0xFF,
            (focus_i >> 8) & 0xFF,
            focus_i & 0xFF,
            (iris_i >> 8) & 0xFF,
            iris_i & 0xFF,
            (pan_i >> 8) & 0xFF,
            pan_i & 0xFF,
            (tilt_i >> 8) & 0xFF,
            tilt_i & 0xFF,
            (roll_i >> 8) & 0xFF,
            roll_i & 0xFF,
            ctrl0 & 0xFF,
            ctrl1 & 0xFF,
        ]
    )

    return msg


def _encode_lens_control(control_state: Dict[str, Any]) -> tuple[int, int]:
    """
    Sideband encoding in bytes 14..15:
      ctrl0:
        b1..b0 lens type: 0=fuji, 1=canon
        b3..b2 zoom source: 0=pc, 1=camera, 2=off
        b5..b4 focus source: 0=pc, 1=camera, 2=off
        b7..b6 iris source: 0=pc, 1=camera, 2=off
      ctrl1:
        marker 0xA5 means sideband is valid.
    """
    lens_type = str(control_state.get("lens_type", "fuji")).lower()
    axis_sources = control_state.get("axis_sources", {}) or {}

    lens_bits = 1 if lens_type == "canon" else 0

    def src_bits(axis_name: str) -> int:
        v = str(axis_sources.get(axis_name, "pc")).lower()
        if v == "camera":
            return 1
        if v == "off":
            return 2
        return 0

    ctrl0 = (
        (lens_bits & 0x03)
        | ((src_bits("zoom") & 0x03) << 2)
        | ((src_bits("focus") & 0x03) << 4)
        | ((src_bits("iris") & 0x03) << 6)
    )
    return ctrl0, 0xA5


# -------------------------------
# Fast packet contract (ADC Fast Path Cleanup)
# -------------------------------
# Active runtime uses v2 fast decode on head (decode_fast_packet_v2). Fast packet format:
#   struct "<BBBHhHHHHHH": magic, ver, PKT_FAST_CTRL, seq(16), zoom(s16), focus(u16), iris(u16), yaw(u16), pitch(u16), roll(u16), reserved(u16).
# All axis control (yaw, pitch, roll, zoom, focus, iris) is carried ONLY on fast UDP (port 8888).
# Slow channel (port 8890) carries only config: motors_on, control_mode, lens_select, axis sources, filter keys — no axis values.

# -------------------------------
# Gate 1 dual-channel scaffolding
# -------------------------------

def _float_to_u16(v: float) -> int:
    """Map [-1, 1] to [0, 65535] with center at 32768. No deadzone or quantization."""
    x = round(32768.0 + float(v) * 32767.0)
    if x < 0:
        return 0
    if x > 65535:
        return 65535
    return int(x)


def build_fast_packet_v2(axes: Dict[str, Any], control_state: Dict[str, Any], seq: int) -> bytes:
    """
    Build v2 fast packet directly from axes (float [-1,1]) and control_state.
    No round-trip through legacy 16-byte packet. Full 16-bit range per axis.
    """
    def f(name: str, default: float = 0.0) -> float:
        try:
            return float(axes.get(name, default))
        except Exception:
            return float(default)

    pan = f("X")
    tilt = f("Y")
    roll = f("Z")
    focus = f("Xrotate")
    iris = f("Yrotate")
    zoom = f("Zrotate")

    invert = control_state.get("invert", {}) or {}
    if invert.get("yaw"):
        pan = -pan
    if invert.get("pitch"):
        tilt = -tilt
    if invert.get("roll"):
        roll = -roll
    if invert.get("zoom"):
        zoom = -zoom

    sp = float(control_state.get("speed", 1.0))
    pan = max(-1.0, min(1.0, pan * sp))
    tilt = max(-1.0, min(1.0, tilt * sp))
    roll = max(-1.0, min(1.0, roll * sp))
    focus = max(-1.0, min(1.0, focus))
    iris = max(-1.0, min(1.0, iris))
    zoom = max(-1.0, min(1.0, zoom))

    yaw_u16 = _float_to_u16(pan)
    pitch_u16 = _float_to_u16(tilt)
    roll_u16 = _float_to_u16(roll)
    focus_u16 = _float_to_u16(focus)
    iris_u16 = _float_to_u16(iris)
    zg = float(control_state.get("zoom_gain", 60.0))
    zoom_i = int(zoom * zg)
    zoom_i = max(-32768, min(32767, zoom_i))

    return struct.pack(
        "<BBBHhHHHHHH",
        PKT_MAGIC,
        PKT_VER,
        PKT_FAST_CTRL,
        int(seq) & 0xFFFF,
        zoom_i,
        focus_u16 & 0xFFFF,
        iris_u16 & 0xFFFF,
        yaw_u16 & 0xFFFF,
        pitch_u16 & 0xFFFF,
        roll_u16 & 0xFFFF,
        0,
    )


def decode_fast_packet_v2(packet: bytes) -> Optional[Dict[str, Any]]:
    if len(packet) != 19:
        return None
    try:
        magic, ver, pkt_type, seq, zoom, focus, iris, yaw, pitch, roll, _ = struct.unpack("<BBBHhHHHHHH", packet)
    except Exception:
        return None
    if magic != PKT_MAGIC or ver != PKT_VER or pkt_type != PKT_FAST_CTRL:
        return None
    return {"seq": seq, "zoom": zoom, "focus": focus, "iris": iris, "yaw": yaw, "pitch": pitch, "roll": roll}


def build_slow_cmd_packet(seq: int, apply_id: int, key_id: int, value: int) -> bytes:
    return struct.pack("<BBBHHBi", PKT_MAGIC, PKT_VER, PKT_SLOW_CMD, int(seq) & 0xFFFF, int(apply_id) & 0xFFFF, int(key_id) & 0xFF, int(value))


def build_slow_ack_packet(seq: int, apply_id: int, key_id: int, status: int) -> bytes:
    return struct.pack("<BBBHHBB", PKT_MAGIC, PKT_VER, PKT_SLOW_ACK, int(seq) & 0xFFFF, int(apply_id) & 0xFFFF, int(key_id) & 0xFF, int(status) & 0xFF)


def decode_slow_ack_packet(packet: bytes) -> Optional[Dict[str, Any]]:
    if len(packet) != 9:
        return None
    try:
        magic, ver, pkt_type, seq, apply_id, key_id, status = struct.unpack("<BBBHHBB", packet)
    except Exception:
        return None
    if magic != PKT_MAGIC or ver != PKT_VER or pkt_type != PKT_SLOW_ACK:
        return None
    return {"seq": seq, "apply_id": apply_id, "key_id": key_id, "status": status}


def build_slow_telem_packet(payload: Dict[str, Any]) -> bytes:
    """
    Build a slow telemetry packet as:
      <BBBH payload_json_utf8>
    where H is payload length in bytes.
    """
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    if len(body) > 65535:
        body = body[:65535]
    return struct.pack("<BBBH", PKT_MAGIC, PKT_VER, PKT_SLOW_TELEM, len(body)) + body


def decode_slow_telem_packet(packet: bytes) -> Optional[Dict[str, Any]]:
    if len(packet) < 5:
        return None
    try:
        magic, ver, pkt_type, body_len = struct.unpack("<BBBH", packet[:5])
    except Exception:
        return None
    if magic != PKT_MAGIC or ver != PKT_VER or pkt_type != PKT_SLOW_TELEM:
        return None
    if len(packet) < 5 + body_len:
        return None
    try:
        body = packet[5 : 5 + body_len].decode("utf-8")
        data = json.loads(body)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return data


def decode_legacy_fast_fields(packet: bytes) -> Optional[Dict[str, Any]]:
    """Decode existing 16-byte MVP packet for compatibility helpers."""
    if len(packet) != 16 or packet[0] != 0xDE or packet[1] != 0xFD:
        return None
    try:
        zoom, focus, iris, yaw, pitch, roll, _ = struct.unpack("<h5H2s", packet[2:16])
    except Exception:
        return None
    return {"zoom": zoom, "focus": focus, "iris": iris, "yaw": yaw, "pitch": pitch, "roll": roll}


def encode_slow_value(key: str, value: Any) -> Optional[int]:
    """Convert slow-control UI value to wire int value."""
    key = str(key).strip()
    if key == "motors_on":
        return 1 if bool(value) else 0
    if key == "control_mode":
        s = str(value).lower().strip()
        return 1 if s == "angle" else 0
    if key == "lens_select":
        s = str(value).lower().strip()
        return 1 if s == "canon" else 0
    if key in ("source_zoom", "source_focus", "source_iris"):
        s = str(value).lower().strip()
        if s == "camera":
            return 1
        if s == "off":
            return 2
        return 0
    if key in ("filter_enable_focus", "filter_enable_iris"):
        return 1 if bool(value) else 0
    if key in ("filter_num", "filter_den"):
        try:
            return int(value)
        except Exception:
            return None
    if key == "gyro_heading_correction":
        try:
            return int(value)
        except Exception:
            return None
    if key == "wash_wipe":
        s = str(value).lower().strip()
        return 1 if s in ("1", "wipe", "wiping", "on", "true") else 0
    if key in ("pan_accel", "tilt_accel", "roll_accel", "pan_gain", "tilt_gain", "roll_gain"):
        try:
            n = int(value)
        except Exception:
            return None
        if n < 0:
            return 0
        if n > 255:
            return 255
        return n
    try:
        return int(value)
    except Exception:
        return None

