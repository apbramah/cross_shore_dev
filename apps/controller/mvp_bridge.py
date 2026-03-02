"""
Hydravision Lite - MVP Controller Bridge
Runs on PC or Raspberry Pi (normal Python)
WebSocket <-> UDP bridge, using shared MVP protocol helpers.
"""

import asyncio
import json

import websockets

import mvp_protocol


WS_PORT = 8765
FAST_CHANNEL_MODE = "v2"  # Set to "legacy" for immediate rollback.
ENABLE_DUAL_CHANNEL = FAST_CHANNEL_MODE == "v2"
ENABLE_SLOW_CHANNEL = True   # Slow control stays active in both modes.
SLOW_SEND_INTERVAL_S = 0.5
FAST_SEND_HZ = 50
FAST_HEARTBEAT_S = 0.5

# Heads configuration (loaded from mvp_protocol.HEADS_FILE)
heads = mvp_protocol.load_heads()
selected_index = 0

# Default control state (shared structure with desktop app)
control_state = {
    "invert": {"yaw": False, "pitch": False, "roll": False},
    "speed": 1.0,
    "zoom_gain": 60,
    "lens_type": "fuji",
    "axis_sources": {"zoom": "pc", "focus": "pc", "iris": "pc"},
}
dual_fast_seq = 0
slow_seq = 0
slow_apply_id = 0
dual_slow_state = {
    "motors_on": 1,
    "control_mode": "speed",
    "lens_select": "fuji",
    "source_zoom": "pc",
    "source_focus": "pc",
    "source_iris": "pc",
}

latest_axes = {}
have_gamepad_input = False
fast_last_packet = None
fast_last_send_monotonic = 0.0
fast_force_send = False


def _clamp_fast_hz(v):
    try:
        hz = int(v)
    except Exception:
        hz = FAST_SEND_HZ
    if hz < 25:
        return 25
    if hz > 100:
        return 100
    return hz


def _get_fast_packet():
    global dual_fast_seq
    if ENABLE_DUAL_CHANNEL:
        dual_fast_seq = (dual_fast_seq + 1) & 0xFFFF
        return mvp_protocol.build_fast_packet_v2(
            latest_axes,
            control_state,
            dual_fast_seq,
        )
    return mvp_protocol.build_udp_packet(latest_axes, control_state)


def _normalize_slow_value(key, value):
    key = str(key).strip()
    if key == "motors_on":
        return 1 if bool(value) else 0
    if key == "control_mode":
        s = str(value).lower().strip()
        return "angle" if s == "angle" else "speed"
    if key == "lens_select":
        s = str(value).lower().strip()
        return "canon" if s == "canon" else "fuji"
    if key in ("source_zoom", "source_focus", "source_iris"):
        s = str(value).lower().strip()
        if s in ("pc", "camera", "off"):
            return s
        return "pc"
    return value


async def fast_sender_task():
    global fast_last_packet, fast_last_send_monotonic, fast_force_send
    loop = asyncio.get_running_loop()
    while True:
        interval = 1.0 / float(_clamp_fast_hz(FAST_SEND_HZ))
        await asyncio.sleep(interval)
        if not heads or not have_gamepad_input:
            continue

        head = heads[selected_index]
        ip = head.get("ip")
        if not ip:
            continue

        packet = _get_fast_packet()
        now = loop.time()
        changed = packet != fast_last_packet
        heartbeat_due = (now - fast_last_send_monotonic) >= FAST_HEARTBEAT_S
        if not (changed or fast_force_send or heartbeat_due):
            continue

        if ENABLE_DUAL_CHANNEL:
            mvp_protocol.send_udp_to(
                ip,
                int(head.get("port_fast", mvp_protocol.FAST_PORT)),
                packet,
            )
        else:
            mvp_protocol.send_udp(packet, head)

        fast_last_packet = packet
        fast_last_send_monotonic = now
        fast_force_send = False


async def slow_sender_task():
    global slow_seq, slow_apply_id
    while True:
        await asyncio.sleep(SLOW_SEND_INTERVAL_S)
        if not ENABLE_SLOW_CHANNEL or not heads:
            continue
        head = heads[selected_index]
        ip = head.get("ip")
        if not ip:
            continue
        port = int(head.get("port_slow_cmd", mvp_protocol.SLOW_CMD_PORT))
        slow_apply_id = (slow_apply_id + 1) & 0xFFFF
        for key, key_id in mvp_protocol.SLOW_KEY_IDS.items():
            raw = dual_slow_state.get(key)
            enc = mvp_protocol.encode_slow_value(key, raw)
            if enc is None:
                continue
            slow_seq = (slow_seq + 1) & 0xFFFF
            pkt = mvp_protocol.build_slow_cmd_packet(slow_seq, slow_apply_id, key_id, enc)
            mvp_protocol.send_udp_to(ip, port, pkt)


async def handler(websocket):
    """
    WebSocket handler for browser clients (e.g. mvp_ui.html).
    Receives GAMEPAD / control messages and updates sender state.
    """
    global selected_index, have_gamepad_input, latest_axes, fast_force_send, FAST_SEND_HZ

    await websocket.send(
        json.dumps(
            {
                "type": "STATE",
                "heads": heads,
                "selected": selected_index,
                "invert": control_state["invert"],
                "speed": control_state["speed"],
                "zoom_gain": control_state["zoom_gain"],
                "lens_type": control_state["lens_type"],
                "axis_sources": control_state["axis_sources"],
                "slow_controls": dual_slow_state,
                "fast_hz": _clamp_fast_hz(FAST_SEND_HZ),
            }
        )
    )

    print("Web client connected")

    try:
        async for message in websocket:
            data = json.loads(message)
            msg_type = data.get("type")

            if msg_type == "GAMEPAD":
                latest_axes = data.get("axes", {}) or {}
                have_gamepad_input = True

            elif msg_type == "SELECT_HEAD":
                idx = int(data.get("index", 0))
                if 0 <= idx < len(heads):
                    selected_index = idx
                    fast_force_send = True
                    print("Selected head:", heads[idx]["name"])
                    await websocket.send(json.dumps({"type": "SELECTED", "selected": selected_index}))

            elif msg_type == "SET_SPEED":
                control_state["speed"] = float(data.get("speed", 1.0))
                fast_force_send = True
                print("Speed set to:", control_state["speed"])

            elif msg_type == "SET_ZOOM_GAIN":
                control_state["zoom_gain"] = float(data.get("zoom_gain", 60))
                fast_force_send = True
                print("Zoom gain set to:", control_state["zoom_gain"])

            elif msg_type == "SET_INVERT":
                control_state["invert"] = data.get("invert", control_state["invert"])
                fast_force_send = True
                print("Invert flags updated:", control_state["invert"])

            elif msg_type == "SET_FAST_HZ":
                FAST_SEND_HZ = _clamp_fast_hz(data.get("hz", FAST_SEND_HZ))
                print("Fast send Hz set to:", FAST_SEND_HZ)

            elif msg_type == "SET_LENS_TYPE":
                lens_type = str(data.get("lens_type", "")).lower()
                if lens_type in ("fuji", "canon"):
                    control_state["lens_type"] = lens_type
                    dual_slow_state["lens_select"] = lens_type
                    await websocket.send(json.dumps({"type": "CURRENT_LENS_TYPE", "lens_type": lens_type}))
                    print("Lens type set to:", lens_type)

            elif msg_type == "SET_LENS_AXIS_SOURCE":
                axis = str(data.get("axis", "")).lower()
                source = str(data.get("source", "")).lower()
                if axis in ("zoom", "focus", "iris") and source in ("pc", "camera", "off"):
                    control_state["axis_sources"][axis] = source
                    dual_slow_state[f"source_{axis}"] = source
                    await websocket.send(
                        json.dumps({"type": "CURRENT_LENS_AXIS_SOURCES", "sources": control_state["axis_sources"]})
                    )
                    print(f"Axis source set: {axis} -> {source}")

            elif msg_type == "SET_SLOW_CONTROL":
                key = str(data.get("key", "")).strip()
                if key in dual_slow_state:
                    dual_slow_state[key] = _normalize_slow_value(key, data.get("value"))

    except websockets.ConnectionClosed:
        print("Web client disconnected")


async def main():
    print(f"WebSocket server starting on ws://127.0.0.1:{WS_PORT}")
    print(f"Fast channel mode: {FAST_CHANNEL_MODE}")
    print(f"Fast sender running at {_clamp_fast_hz(FAST_SEND_HZ)} Hz, heartbeat {FAST_HEARTBEAT_S:.2f}s")
    asyncio.create_task(fast_sender_task())
    if ENABLE_SLOW_CHANNEL:
        print(f"Slow control sender running at {1.0 / SLOW_SEND_INTERVAL_S:.1f} Hz")
        asyncio.create_task(slow_sender_task())
    async with websockets.serve(handler, "0.0.0.0", WS_PORT):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
