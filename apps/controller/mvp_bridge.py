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
    Browser axes are typically floats in [-1.0, +1.0].
    BGC expects unsigned 16-bit 0..65535 with centre at 32768.
    We'll map:
      - X,Y,Z -> 0..65535 centred
      - Zrotate (zoom rocker) -> small signed delta mapped into int16 field (zoom)
      - Xrotate/Yrotate -> 0..65535 centred (placeholders for focus/iris pots)
    """

    def f(name, default=0.0):
        v = axes.get(name, default)
        try:
            return float(v)
        except Exception:
            return float(default)

    # Read floats
    x = f("X")
    y = f("Y")
    z = f("Z")
    xr = f("Xrotate")
    yr = f("Yrotate")
    zr = f("Zrotate")

    # Apply invert
    if control_state["invert"]["yaw"]:
        x = -x
    if control_state["invert"]["pitch"]:
        y = -y
    if control_state["invert"]["roll"]:
        z = -z

    # Apply speed scaling (on -1..+1 domain)
    sp = float(control_state.get("speed", 1.0))
    x *= sp
    y *= sp
    z *= sp

    # Clamp to [-1, +1] after scaling
    def clamp1(v):
        if v < -1.0: return -1.0
        if v >  1.0: return  1.0
        return v

    x = clamp1(x)
    y = clamp1(y)
    z = clamp1(z)
    xr = clamp1(xr)
    yr = clamp1(yr)
    zr = clamp1(zr)

    # Map to unsigned 16-bit centred values
    # -1 -> 0, 0 -> 32768, +1 -> 65535
    def to_u16_centered(v):
        return int((v + 1.0) * 32767.5)  # 0..65535

    yaw_u16   = to_u16_centered(x)
    pitch_u16 = to_u16_centered(y)
    roll_u16  = to_u16_centered(z)

    focus_u16 = to_u16_centered(xr)
    iris_u16  = to_u16_centered(yr)

    # Zoom: treat as DELTA per packet (small signed int16)
    # Use zoom_gain (10..150) to scale delta
    zg = float(control_state.get("zoom_gain", 60.0))
    # Map [-1..+1] to approx [-zg..+zg] steps
    zoom_delta = int(zr * zg)

    # Pack into your existing 0xDE 0xFD format:
    # <h5H2s where zoom is int16, then focus/iris/yaw/pitch/roll are uint16
    import struct
    packet = bytearray(16)
    packet[0] = 0xDE
    packet[1] = 0xFD
    struct.pack_into(
        "<h5H2s",
        packet,
        2,
        int(zoom_delta),     # zoom int16
        focus_u16,           # focus uint16
        iris_u16,            # iris uint16
        yaw_u16,             # yaw uint16
        pitch_u16,           # pitch uint16
        roll_u16,            # roll uint16
        b"\x00\x00"
    )

    return packet




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
