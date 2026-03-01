import json
import os
import socket
from typing import Dict, Any, List


UDP_DEFAULT_PORT = 8888

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
    _udp_sock.sendto(packet, (ip, port))


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

    # Pack EXACTLY like original send_udp_message() byte order
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
            0x00,
            0x00,
        ]
    )

    return msg

