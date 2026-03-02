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
# Gate 1 dual-channel scaffolding
# -------------------------------
# These helpers are intentionally additive and are not used by default.
# The legacy build_udp_packet() path remains the active runtime path.

def build_fast_packet_v2(axes: Dict[str, Any], control_state: Dict[str, Any], seq: int) -> bytes:
    """Versioned fast packet helper for staged migration (inactive by default)."""
    legacy = build_udp_packet(axes, control_state)
    fields = decode_legacy_fast_fields(legacy)
    if not fields:
        fields = {"zoom": 0, "focus": 0, "iris": 0, "yaw": 0, "pitch": 0, "roll": 0}
    return struct.pack(
        "<BBBHhHHHHHH",
        PKT_MAGIC,
        PKT_VER,
        PKT_FAST_CTRL,
        int(seq) & 0xFFFF,
        int(fields["zoom"]),
        int(fields["focus"]) & 0xFFFF,
        int(fields["iris"]) & 0xFFFF,
        int(fields["yaw"]) & 0xFFFF,
        int(fields["pitch"]) & 0xFFFF,
        int(fields["roll"]) & 0xFFFF,
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


def decode_legacy_fast_fields(packet: bytes) -> Optional[Dict[str, Any]]:
    """Decode existing 16-byte MVP packet for compatibility helpers."""
    if len(packet) != 16 or packet[0] != 0xDE or packet[1] != 0xFD:
        return None
    try:
        zoom, focus, iris, yaw, pitch, roll, _ = struct.unpack("<h5H2s", packet[2:16])
    except Exception:
        return None
    return {"zoom": zoom, "focus": focus, "iris": iris, "yaw": yaw, "pitch": pitch, "roll": roll}

