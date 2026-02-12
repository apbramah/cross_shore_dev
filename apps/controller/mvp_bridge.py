import asyncio
import json
import os
import socket
import struct
from pathlib import Path

import websockets

HEADS_JSON = Path(__file__).with_name("heads.json")
WS_HOST = "0.0.0.0"
WS_PORT = 8765

# Default: Pico used 8888 in your old MicroPython gather_candidates()
DEFAULT_UDP_PORT = 8888

# ---------- Packet ----------
def _clamp_i16(x: int) -> int:
    if x < -32768: return -32768
    if x > 32767: return 32767
    return int(x)

def _clamp_u16(x: int) -> int:
    if x < 0: return 0
    if x > 65535: return 65535
    return int(x)

def build_packet_from_gamepad(gp: dict, invert: dict, speed: float, zoom_gain: float, pot_center: int = 512) -> bytes:
    """
    Browser sends normalized axes in range [-1..+1]:
      X, Y, Z, Xrotate, Yrotate, Zrotate

    Mapping requested:
      X -> pan(yaw), Y -> tilt(pitch), Z -> roll
      Xrotate -> focus_pot, Yrotate -> iris_pot, Zrotate -> zoom_rocker

    Pico expects 16 bytes: <BBhHHHHH2s
      0xDE 0xFD, zoom(i16), focus(u16), iris(u16), yaw(u16), pitch(u16), roll(u16), pad(2)
    """

    def s512(v: float) -> int:
        return int(float(v) * 512.0)

    # Pull raw axes (normalized)
    x = float(gp.get("X", 0.0))
    y = float(gp.get("Y", 0.0))
    z = float(gp.get("Z", 0.0))
    xr = float(gp.get("Xrotate", 0.0))
    yr = float(gp.get("Yrotate", 0.0))
    zr = float(gp.get("Zrotate", 0.0))

    # Apply invert + speed to gimbal only
    yaw   = s512(-x if invert.get("yaw") else x) * speed
    pitch = s512(-y if invert.get("pitch") else y) * speed
    roll  = s512(-z if invert.get("roll") else z) * speed

    # Zoom is RELATIVE delta (your CameraSony.move_zoom(delta))
    zoom = _clamp_i16(int(zr * zoom_gain))

    # Focus/Iris are POT-like; we map [-1..+1] -> [0..1024] centered at 512
    focus_u16 = _clamp_u16(int(pot_center + s512(xr)))
    iris_u16  = _clamp_u16(int(pot_center + s512(yr)))

    # Yaw/Pitch/Roll: also map to centered unsigned 0..1024 style
    yaw_u16   = _clamp_u16(int(pot_center + yaw))
    pitch_u16 = _clamp_u16(int(pot_center + pitch))
    roll_u16  = _clamp_u16(int(pot_center + roll))

    return struct.pack(
        "<BBhHHHHH2s",
        0xDE, 0xFD,
        zoom,
        focus_u16,
        iris_u16,
        yaw_u16,
        pitch_u16,
        roll_u16,
        b"\x00\x00",
    )

# ---------- Heads ----------
def load_heads():
    if not HEADS_JSON.exists():
        raise FileNotFoundError(f"Missing {HEADS_JSON}. Create it (see example below).")
    heads = json.loads(HEADS_JSON.read_text())
    if not isinstance(heads, list):
        raise ValueError("heads.json must be a list")
    # normalize
    out = []
    for h in heads:
        out.append({
            "name": h.get("name", h.get("ip", "HEAD")),
            "ip": h["ip"],
            "port": int(h.get("port", DEFAULT_UDP_PORT)),
        })
    return out

# ---------- Server ----------
class State:
    def __init__(self, heads):
        self.heads = heads
        self.selected = 0
        self.invert = {"yaw": False, "pitch": False, "roll": False}
        self.speed = 1.0        # gimbal speed multiplier
        self.zoom_gain = 60.0   # zoom delta per frame (tune 30..120)

    def current_head(self):
        if not self.heads:
            return None
        return self.heads[self.selected]

async def handler(ws, state: State):
    # UDP socket for this client
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    # Send initial state to UI
    await ws.send(json.dumps({
        "type": "STATE",
        "heads": state.heads,
        "selected": state.selected,
        "invert": state.invert,
        "speed": state.speed,
        "zoom_gain": state.zoom_gain,
    }))

    async for msg in ws:
        try:
            data = json.loads(msg)
        except Exception:
            continue

        t = data.get("type")
        if t == "SELECT_HEAD":
            idx = int(data.get("index", 0))
            state.selected = max(0, min(idx, len(state.heads) - 1))
            await ws.send(json.dumps({"type": "SELECTED", "selected": state.selected}))
            continue

        if t == "SET_INVERT":
            inv = data.get("invert", {})
            for k in ("yaw", "pitch", "roll"):
                if k in inv:
                    state.invert[k] = bool(inv[k])
            await ws.send(json.dumps({"type": "INVERT", "invert": state.invert}))
            continue

        if t == "SET_SPEED":
            state.speed = float(data.get("speed", 1.0))
            await ws.send(json.dumps({"type": "SPEED", "speed": state.speed}))
            continue

        if t == "SET_ZOOM_GAIN":
            state.zoom_gain = float(data.get("zoom_gain", state.zoom_gain))
            await ws.send(json.dumps({"type": "ZOOM_GAIN", "zoom_gain": state.zoom_gain}))
            continue

        if t == "GAMEPAD":
            head = state.current_head()
            if not head:
                continue
            gp = data.get("axes", {})
            pkt = build_packet_from_gamepad(gp, state.invert, state.speed, state.zoom_gain)
            try:
                udp.sendto(pkt, (head["ip"], head["port"]))
            except Exception:
                pass

async def main():
    heads = load_heads()
    state = State(heads)
    print(f"Loaded {len(heads)} heads from heads.json")
    print(f"Web UI connects to ws://<pi-ip>:{WS_PORT}")

    async with websockets.serve(lambda ws: handler(ws, state), WS_HOST, WS_PORT, max_size=2_000_000):
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
