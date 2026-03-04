"""
Hydravision MVP - slow-only bridge

Runs on PC/Raspberry Pi (normal Python):
- WebSocket control plane for mvp_ui_2.html
- UDP slow-command sender to selected head
- Persistent slow state for key controls (starting with motors_on)
"""

from __future__ import annotations

import asyncio
import json
import os

import websockets

import mvp_protocol


WS_PORT = 8766
SLOW_SEND_INTERVAL_S = 0.5
STATE_FILE = os.path.join(os.path.dirname(__file__), "mvp_slow_state.json")
SELECTED_HEAD_FILE = os.path.join(os.path.dirname(__file__), "mvp_selected_head.json")


heads = mvp_protocol.load_heads()
selected_index = 0

slow_seq = 0
slow_apply_id = 0

dual_slow_state = {
    "motors_on": 1,
    "gyro_heading_correction": 0x00001500,
}


def _normalize_motors_on(value) -> int:
    return 1 if bool(value) else 0


def _normalize_gyro_heading_correction(value) -> int:
    try:
        return int(value)
    except Exception:
        return 0x00001500


def _load_state() -> None:
    global selected_index
    if not os.path.isfile(STATE_FILE):
        return
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        dual_slow_state["motors_on"] = _normalize_motors_on(data.get("motors_on", 1))
        dual_slow_state["gyro_heading_correction"] = _normalize_gyro_heading_correction(
            data.get("gyro_heading_correction", 0x00001500)
        )
        idx = int(data.get("selected_index", 0))
        if 0 <= idx < len(heads):
            selected_index = idx
    except Exception as e:
        print("Slow state load failed:", e)


def _save_state() -> None:
    data = {
        "motors_on": int(dual_slow_state.get("motors_on", 1)),
        "gyro_heading_correction": int(dual_slow_state.get("gyro_heading_correction", 0x00001500)),
        "selected_index": int(selected_index),
    }
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print("Slow state save failed:", e)


def _save_selected_head_index() -> None:
    try:
        with open(SELECTED_HEAD_FILE, "w", encoding="utf-8") as f:
            json.dump({"selected_index": int(selected_index)}, f, indent=2)
    except Exception as e:
        print("Selected head save failed:", e)


def _send_one_slow_key_now(key: str) -> bool:
    """Send one slow key packet immediately to current selected head."""
    global slow_seq, slow_apply_id
    if not heads:
        return False
    head = heads[selected_index]
    ip = head.get("ip")
    if not ip:
        return False
    key_id = mvp_protocol.SLOW_KEY_IDS.get(key)
    if not key_id:
        return False
    enc = mvp_protocol.encode_slow_value(key, dual_slow_state.get(key))
    if enc is None:
        return False
    port = int(head.get("port_slow_cmd", mvp_protocol.SLOW_CMD_PORT))
    slow_apply_id = (slow_apply_id + 1) & 0xFFFF
    slow_seq = (slow_seq + 1) & 0xFFFF
    pkt = mvp_protocol.build_slow_cmd_packet(slow_seq, slow_apply_id, key_id, enc)
    mvp_protocol.send_udp_to(ip, port, pkt)
    print(f"Slow immediate send {key}={enc} -> {ip}:{port} apply_id={slow_apply_id} seq={slow_seq}")
    return True


async def slow_sender_task():
    global slow_seq, slow_apply_id
    while True:
        await asyncio.sleep(SLOW_SEND_INTERVAL_S)
        if not heads:
            continue
        head = heads[selected_index]
        ip = head.get("ip")
        if not ip:
            continue
        port = int(head.get("port_slow_cmd", mvp_protocol.SLOW_CMD_PORT))

        slow_apply_id = (slow_apply_id + 1) & 0xFFFF
        for key in ("motors_on", "gyro_heading_correction"):
            key_id = mvp_protocol.SLOW_KEY_IDS.get(key)
            if not key_id:
                continue
            enc = mvp_protocol.encode_slow_value(key, dual_slow_state.get(key))
            if enc is None:
                continue
            slow_seq = (slow_seq + 1) & 0xFFFF
            pkt = mvp_protocol.build_slow_cmd_packet(slow_seq, slow_apply_id, key_id, enc)
            mvp_protocol.send_udp_to(ip, port, pkt)


async def handler(websocket):
    global selected_index
    await websocket.send(
        json.dumps(
            {
                "type": "STATE",
                "heads": heads,
                "selected": selected_index,
                "slow_controls": dict(dual_slow_state),
            }
        )
    )
    print("Slow UI client connected")

    try:
        async for message in websocket:
            data = json.loads(message)
            msg_type = data.get("type")

            if msg_type == "SELECT_HEAD":
                idx = int(data.get("index", 0))
                if 0 <= idx < len(heads):
                    selected_index = idx
                    _save_state()
                    _save_selected_head_index()
                    await websocket.send(json.dumps({"type": "SELECTED", "selected": selected_index}))
                    print("Slow bridge selected head:", heads[idx].get("name", idx))

            elif msg_type == "SET_SLOW_CONTROL":
                key = str(data.get("key", "")).strip()
                if key == "motors_on":
                    v = _normalize_motors_on(data.get("value"))
                    dual_slow_state["motors_on"] = v
                    _save_state()
                    await websocket.send(
                        json.dumps(
                            {
                                "type": "SLOW_APPLIED",
                                "key": "motors_on",
                                "value": v,
                            }
                        )
                    )
                    print("Slow apply motors_on ->", v)
                elif key == "gyro_heading_correction":
                    v = _normalize_gyro_heading_correction(data.get("value"))
                    dual_slow_state["gyro_heading_correction"] = v
                    _save_state()
                    _send_one_slow_key_now("gyro_heading_correction")
                    await websocket.send(
                        json.dumps(
                            {
                                "type": "SLOW_APPLIED",
                                "key": "gyro_heading_correction",
                                "value": v,
                            }
                        )
                    )
                    print("Slow apply gyro_heading_correction ->", v)

    except websockets.ConnectionClosed:
        print("Slow UI client disconnected")


async def main():
    _load_state()
    _save_selected_head_index()
    print(f"Slow WebSocket server starting on ws://127.0.0.1:{WS_PORT}")
    print(f"Slow sender running at {1.0 / SLOW_SEND_INTERVAL_S:.1f} Hz")
    asyncio.create_task(slow_sender_task())
    async with websockets.serve(handler, "0.0.0.0", WS_PORT):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
