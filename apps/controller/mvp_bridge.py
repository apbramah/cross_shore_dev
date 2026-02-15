# ==========================================
# Hydravision Lite - MVP Controller Bridge
# Runs on PC or Raspberry Pi (normal Python)
# WebSocket <-> UDP bridge
# ==========================================

import asyncio
import websockets
import json
import socket

WS_PORT = 8765
UDP_DEFAULT_PORT = 8888

HEADS_FILE = "heads.json"

# -----------------------------
# Load heads configuration
# -----------------------------

def load_heads():
    try:
        with open(HEADS_FILE, "r") as f:
            heads = json.load(f)
        print(f"Loaded {len(heads)} heads from {HEADS_FILE}")
        return heads
    except Exception as e:
        print("Error loading heads.json:", e)
        return []


heads = load_heads()
selected_index = 0

# Default control state
control_state = {
    "invert": {"yaw": False, "pitch": False, "roll": False},
    "speed": 1.0,
    "zoom_gain": 60
}

# UDP socket
udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


# -----------------------------------
# Build 16-byte UDP packet
# -----------------------------------

def build_udp_packet(axes):
    """
    Match the ORIGINAL controller/main.py behaviour:
    - Browser axes float [-1..+1] -> int [-512..+512]
    - Apply the same map_* transforms you were using
    - Pack bytes in the SAME byte order as the original send_udp_message()
    """

    def f(name, default=0.0):
        try:
            return float(axes.get(name, default))
        except Exception:
            return float(default)

    # Browser float axes
    pan   = f("X")         # Joystick.X
    tilt  = f("Y")         # Joystick.Y
    roll  = f("Z")         # Joystick.Z
    focus = f("Xrotate")   # Joystick.Xrotate
    iris  = f("Yrotate")   # Joystick.Yrotate
    zoom  = f("Zrotate")   # Joystick.Zrotate

    # Deadzone (same idea as before, but applied in float domain)
    DEADZONE = 0.06
    def dz(v): return 0.0 if -DEADZONE < v < DEADZONE else v
    pan = dz(pan); tilt = dz(tilt); roll = dz(roll)
    focus = dz(focus); iris = dz(iris); zoom = dz(zoom)

    # Invert flags (match original intent)
    if control_state["invert"]["yaw"]:
        pan = -pan
    if control_state["invert"]["pitch"]:
        tilt = -tilt
    if control_state["invert"]["roll"]:
        roll = -roll

    # Speed scaling (float domain, then clamp)
    sp = float(control_state.get("speed", 1.0))
    pan *= sp; tilt *= sp; roll *= sp

    def clamp1(v):
        if v < -1.0: return -1.0
        if v >  1.0: return  1.0
        return v

    pan = clamp1(pan); tilt = clamp1(tilt); roll = clamp1(roll)
    focus = clamp1(focus); iris = clamp1(iris); zoom = clamp1(zoom)

    # === ORIGINAL INTERNAL RANGE: -512..+512 ===
    pan_i   = int(pan   * 512)
    tilt_i  = int(tilt  * 512)
    roll_i  = int(roll  * 512)
    focus_i = int(focus * 512)
    iris_i  = int(iris  * 512)

    # zoom rocker -> signed delta similar to original feel
    zg = float(control_state.get("zoom_gain", 60.0))
    zoom_i = int(zoom * zg)

    # === ORIGINAL map_* transforms (copied from controller/main.py) ===
    map_zoom  = lambda value: (value + 0)
    map_iris  = lambda value: (value + 512) >> 4
    map_focus = lambda value: (value + 512) >> 4
    map_pitch = lambda value: value

    tilt_i  = map_pitch(tilt_i)
    zoom_i  = map_zoom(zoom_i)
    focus_i = map_focus(focus_i)
    iris_i  = map_iris(iris_i)

    # Pack EXACTLY like original send_udp_message() byte order
    msg = bytes([
        0xDE, 0xFD,

        zoom_i & 0xFF, (zoom_i >> 8) & 0xFF,

        (focus_i >> 8) & 0xFF, focus_i & 0xFF,
        (iris_i  >> 8) & 0xFF, iris_i  & 0xFF,

        (pan_i  >> 8) & 0xFF, pan_i  & 0xFF,
        (tilt_i >> 8) & 0xFF, tilt_i & 0xFF,
        (roll_i >> 8) & 0xFF, roll_i & 0xFF,

        0x00, 0x00
    ])

    return msg



# -----------------------------------
# Send UDP to selected head
# -----------------------------------

def send_udp(packet):
    if not heads:
        return

    head = heads[selected_index]
    ip = head["ip"]
    port = head.get("port", UDP_DEFAULT_PORT)

    udp_sock.sendto(packet, (ip, port))


# -----------------------------------
# WebSocket handler
# -----------------------------------

async def handler(websocket):
    global selected_index

    # Send initial STATE
    await websocket.send(json.dumps({
        "type": "STATE",
        "heads": heads,
        "selected": selected_index,
        "invert": control_state["invert"],
        "speed": control_state["speed"],
        "zoom_gain": control_state["zoom_gain"]
    }))

    print("Web client connected")

    try:
        async for message in websocket:
            data = json.loads(message)
            msg_type = data.get("type")

            # -----------------
            # GAMEPAD streaming
            # -----------------
            if msg_type == "GAMEPAD":
                packet = build_udp_packet(data.get("axes", {}))
                send_udp(packet)

            # -----------------
            # Select head
            # -----------------
            elif msg_type == "SELECT_HEAD":
                idx = int(data.get("index", 0))
                if 0 <= idx < len(heads):
                    selected_index = idx
                    print("Selected head:", heads[idx]["name"])
                    await websocket.send(json.dumps({
                        "type": "SELECTED",
                        "selected": selected_index
                    }))

            # -----------------
            # Speed adjust
            # -----------------
            elif msg_type == "SET_SPEED":
                control_state["speed"] = float(data.get("speed", 1.0))
                print("Speed set to:", control_state["speed"])

            # -----------------
            # Zoom gain
            # -----------------
            elif msg_type == "SET_ZOOM_GAIN":
                control_state["zoom_gain"] = float(data.get("zoom_gain", 60))
                print("Zoom gain set to:", control_state["zoom_gain"])

            # -----------------
            # Invert flags
            # -----------------
            elif msg_type == "SET_INVERT":
                control_state["invert"] = data.get("invert", control_state["invert"])
                print("Invert flags updated:", control_state["invert"])

    except websockets.ConnectionClosed:
        print("Web client disconnected")


# -----------------------------------
# Main entry
# -----------------------------------

async def main():
    print(f"WebSocket server starting on ws://127.0.0.1:{WS_PORT}")
    async with websockets.serve(handler, "0.0.0.0", WS_PORT):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
