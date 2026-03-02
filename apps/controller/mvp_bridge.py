"""
Hydravision Lite - MVP Controller Bridge
WebSocket UI bridge with dual-channel UDP:
  - Fast motion UDP (25-100Hz, send-on-change)
  - Slow control UDP (~2Hz + immediate-on-change + ack/retry)
"""

import asyncio
import json
import socket
import time
from typing import Any, Dict, Optional, Set

import websockets

import mvp_protocol

WS_PORT = 8765
FAST_HEARTBEAT_MS = 500
SLOW_HZ = 2.0
SLOW_RETRY_MS = 350
SLOW_MAX_RETRIES = 5

heads = mvp_protocol.load_heads()
selected_index = 0
clients: Set[Any] = set()

control_state: Dict[str, Any] = {
    "invert": {"yaw": False, "pitch": False, "roll": False},
    "speed": 1.0,
    "zoom_gain": 60.0,
}

fast_hz = 50.0
last_axes: Dict[str, float] = {"X": 0.0, "Y": 0.0, "Z": 0.0, "Xrotate": 0.0, "Yrotate": 0.0, "Zrotate": 0.0}
fast_seq = 0
slow_seq = 0
next_apply_id = 1

slow_state: Dict[str, Any] = {
    "motors_on": 1,
    "pan_gain": 0,
    "tilt_gain": 0,
    "roll_gain": 0,
    "pan_acceleration": 0,
    "tilt_acceleration": 0,
    "roll_acceleration": 0,
    "expo": 0,
    "pan_top_speed": 0,
    "tilt_top_speed": 0,
    "roll_top_speed": 0,
    "gyro_drift_offset": 0,
    "control_mode": "speed",
    "lens_select": "fuji",
    "source_zoom": "pc",
    "source_focus": "pc",
    "source_iris": "pc",
}

pending_slow: Dict[int, Dict[str, Any]] = {}
slow_change_queue: asyncio.Queue = asyncio.Queue()
slow_snapshot_keys = list(mvp_protocol.SLOW_KEYS.keys())
slow_snapshot_index = 0
latest_telem: Dict[str, Any] = {}
slow_io_sock: Optional[socket.socket] = None


def _current_head() -> Optional[Dict[str, Any]]:
    if not heads:
        return None
    if selected_index < 0 or selected_index >= len(heads):
        return None
    return heads[selected_index]


def _head_fast_port(head: Dict[str, Any]) -> int:
    return int(head.get("port", mvp_protocol.FAST_PORT))


def _head_slow_cmd_port(head: Dict[str, Any]) -> int:
    return int(head.get("slow_cmd_port", mvp_protocol.SLOW_CMD_PORT))


def _head_slow_telem_port(head: Dict[str, Any]) -> int:
    return int(head.get("slow_telem_port", mvp_protocol.SLOW_TELEM_PORT))


def _encode_slow_value(key: str, value: Any) -> int:
    if key in ("motors_on",):
        return 1 if bool(value) else 0
    if key == "control_mode":
        return mvp_protocol._encode_control_mode(str(value))
    if key == "lens_select":
        return mvp_protocol._encode_lens_select(str(value))
    if key in ("source_zoom", "source_focus", "source_iris"):
        return mvp_protocol._encode_source(str(value))
    return int(value)


async def _broadcast(msg: Dict[str, Any]) -> None:
    if not clients:
        return
    payload = json.dumps(msg)
    stale = []
    for ws in clients:
        try:
            await ws.send(payload)
        except Exception:
            stale.append(ws)
    for ws in stale:
        clients.discard(ws)


def _state_payload() -> Dict[str, Any]:
    return {
        "type": "STATE",
        "heads": heads,
        "selected": selected_index,
        "invert": control_state["invert"],
        "speed": control_state["speed"],
        "zoom_gain": control_state["zoom_gain"],
        "fast_hz": fast_hz,
        "slow_control": dict(slow_state),
        "slow_telem": dict(latest_telem),
    }


async def _queue_slow_update(key: str, value: Any) -> None:
    if key not in mvp_protocol.SLOW_KEYS:
        return
    if slow_state.get(key) == value:
        return
    slow_state[key] = value
    await slow_change_queue.put((key, value))
    await _broadcast({"type": "SLOW_CONTROL_STATE", "slow_control": dict(slow_state)})


async def handler(websocket):
    global selected_index, fast_hz
    clients.add(websocket)
    await websocket.send(json.dumps(_state_payload()))
    print("Web client connected")

    try:
        async for message in websocket:
            data = json.loads(message)
            msg_type = data.get("type")

            if msg_type == "GAMEPAD":
                axes = data.get("axes", {})
                for k in last_axes.keys():
                    try:
                        last_axes[k] = float(axes.get(k, 0.0))
                    except Exception:
                        last_axes[k] = 0.0
            elif msg_type == "SELECT_HEAD":
                idx = int(data.get("index", 0))
                if 0 <= idx < len(heads):
                    selected_index = idx
                    print("Selected head:", heads[idx]["name"])
                    await _broadcast({"type": "SELECTED", "selected": selected_index})
            elif msg_type == "SET_SPEED":
                control_state["speed"] = float(data.get("speed", 1.0))
            elif msg_type == "SET_ZOOM_GAIN":
                control_state["zoom_gain"] = float(data.get("zoom_gain", 60))
            elif msg_type == "SET_INVERT":
                control_state["invert"] = data.get("invert", control_state["invert"])
            elif msg_type == "SET_FAST_HZ":
                hz = float(data.get("fast_hz", fast_hz))
                fast_hz = max(25.0, min(100.0, hz))
                await _broadcast({"type": "FAST_HZ", "fast_hz": fast_hz})
            elif msg_type == "SET_SLOW_CONTROL":
                key = str(data.get("key", "")).strip()
                if key in mvp_protocol.SLOW_KEYS:
                    await _queue_slow_update(key, data.get("value"))
            elif msg_type == "SET_LENS_TYPE":
                lens_type = str(data.get("lens_type", "")).lower()
                if lens_type in ("fuji", "canon"):
                    await _queue_slow_update("lens_select", lens_type)
            elif msg_type == "SET_LENS_AXIS_SOURCE":
                axis = str(data.get("axis", "")).lower()
                source = str(data.get("source", "")).lower()
                if axis in ("zoom", "focus", "iris") and source in ("pc", "camera", "off"):
                    await _queue_slow_update(f"source_{axis}", source)

    except websockets.ConnectionClosed:
        print("Web client disconnected")
    finally:
        clients.discard(websocket)


async def fast_sender_task():
    global fast_seq
    last_sent: Optional[bytes] = None
    last_send_ms = 0
    while True:
        head = _current_head()
        if head:
            fast_seq = (fast_seq + 1) & 0xFFFF
            packet = mvp_protocol.build_fast_packet(last_axes, control_state, fast_seq)
            now_ms = int(time.time() * 1000)
            changed = packet != last_sent
            heartbeat_due = (now_ms - last_send_ms) >= FAST_HEARTBEAT_MS
            if changed or heartbeat_due:
                mvp_protocol.send_udp_to(head["ip"], _head_fast_port(head), packet)
                last_sent = packet
                last_send_ms = now_ms
        await asyncio.sleep(max(0.001, 1.0 / fast_hz))


async def slow_sender_task():
    global slow_seq, next_apply_id, slow_snapshot_index
    snapshot_period_s = 1.0 / SLOW_HZ
    last_snapshot = 0.0
    while True:
        head = _current_head()
        now = time.time()
        if not head:
            await asyncio.sleep(0.05)
            continue

        # Immediate-on-change sends first.
        try:
            while True:
                key, value = slow_change_queue.get_nowait()
                key_id = mvp_protocol.SLOW_KEYS[key]
                encoded = _encode_slow_value(key, value)
                apply_id = next_apply_id & 0xFFFF
                next_apply_id += 1
                slow_seq = (slow_seq + 1) & 0xFFFF
                packet = mvp_protocol.build_slow_cmd_packet(slow_seq, apply_id, key_id, encoded)
                if slow_io_sock:
                    slow_io_sock.sendto(packet, (head["ip"], _head_slow_cmd_port(head)))
                pending_slow[apply_id] = {
                    "packet": packet,
                    "key_id": key_id,
                    "retries_left": SLOW_MAX_RETRIES,
                    "retry_at": now + (SLOW_RETRY_MS / 1000.0),
                }
                await _broadcast({"type": "SLOW_CMD_SENT", "apply_id": apply_id, "key": key, "value": value})
        except asyncio.QueueEmpty:
            pass

        # 2Hz background snapshot of one key at a time.
        if (now - last_snapshot) >= snapshot_period_s and slow_snapshot_keys:
            key = slow_snapshot_keys[slow_snapshot_index]
            slow_snapshot_index = (slow_snapshot_index + 1) % len(slow_snapshot_keys)
            value = slow_state.get(key)
            key_id = mvp_protocol.SLOW_KEYS[key]
            encoded = _encode_slow_value(key, value)
            apply_id = next_apply_id & 0xFFFF
            next_apply_id += 1
            slow_seq = (slow_seq + 1) & 0xFFFF
            packet = mvp_protocol.build_slow_cmd_packet(slow_seq, apply_id, key_id, encoded)
            if slow_io_sock:
                slow_io_sock.sendto(packet, (head["ip"], _head_slow_cmd_port(head)))
            pending_slow[apply_id] = {
                "packet": packet,
                "key_id": key_id,
                "retries_left": SLOW_MAX_RETRIES,
                "retry_at": now + (SLOW_RETRY_MS / 1000.0),
            }
            last_snapshot = now

        # Retry unacked commands.
        expired = []
        for apply_id, item in pending_slow.items():
            if now < item["retry_at"]:
                continue
            if item["retries_left"] <= 0:
                expired.append(apply_id)
                await _broadcast(
                    {
                        "type": "SLOW_ACK_TIMEOUT",
                        "apply_id": apply_id,
                        "key": mvp_protocol.SLOW_KEYS_BY_ID.get(item["key_id"], "unknown"),
                    }
                )
                continue
            if slow_io_sock:
                slow_io_sock.sendto(item["packet"], (head["ip"], _head_slow_cmd_port(head)))
            item["retries_left"] -= 1
            item["retry_at"] = now + (SLOW_RETRY_MS / 1000.0)
        for apply_id in expired:
            pending_slow.pop(apply_id, None)

        await asyncio.sleep(0.02)


async def slow_rx_task():
    global latest_telem
    print(f"Slow RX socket listening on UDP {mvp_protocol.BRIDGE_RX_PORT}")

    while True:
        try:
            if not slow_io_sock:
                await asyncio.sleep(0.05)
                continue
            data, addr = await asyncio.to_thread(slow_io_sock.recvfrom, 2048)
        except Exception:
            await asyncio.sleep(0.01)
            continue

        ack = mvp_protocol.decode_slow_ack_packet(data)
        if ack:
            pending_slow.pop(ack["apply_id"], None)
            await _broadcast({"type": "SLOW_ACK", "from": addr[0], **ack})
            continue

        telem = mvp_protocol.decode_slow_telem_packet(data)
        if telem:
            latest_telem = telem
            await _broadcast({"type": "SLOW_TELEMETRY", "from": addr[0], **telem})
            continue


async def main():
    global slow_io_sock
    slow_io_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    slow_io_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    slow_io_sock.bind(("0.0.0.0", mvp_protocol.BRIDGE_RX_PORT))
    print(f"WebSocket server starting on ws://0.0.0.0:{WS_PORT}")
    async with websockets.serve(handler, "0.0.0.0", WS_PORT):
        await asyncio.gather(
            fast_sender_task(),
            slow_sender_task(),
            slow_rx_task(),
        )


if __name__ == "__main__":
    asyncio.run(main())
