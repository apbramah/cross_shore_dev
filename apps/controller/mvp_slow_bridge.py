"""
Hydravision MVP - expanded control bridge.

Responsibilities:
- WebSocket control plane for `mvp_ui_3.html`
- Full slow-command sender + apply status tracking
- Shaping/defaults persistence management
- Head telemetry + ACK ingest
- Connection/IP and Wi-Fi status/control plane
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import socket
import subprocess
import time
from typing import Any

import websockets

import mvp_protocol

WS_PORT = 8766
SLOW_SEND_INTERVAL_S = 0.5
STATUS_PUBLISH_INTERVAL_S = 1.0
HEAD_CONNECTED_TIMEOUT_S = 2.5

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "mvp_slow_state.json")
SELECTED_HEAD_FILE = os.path.join(BASE_DIR, "mvp_selected_head.json")
HEADS_FILE = os.path.join(BASE_DIR, "heads.json")
USER_DEFAULTS_FILE = os.path.join(BASE_DIR, "mvp_user_defaults.json")
NETWORK_USER_FILE = os.path.join(BASE_DIR, "mvp_network_user_config.json")
NETWORK_FACTORY_FILE = os.path.join(BASE_DIR, "mvp_network_factory_config.json")
ADC_CAL_REQUEST_FILE = "adc_input_calibration_request.json"
ADC_CAL_RESULT_FILE = "adc_input_calibration_result.json"
ZOOM_FEEDBACK_RUNTIME_FILENAME = "zoom_feedback_runtime.json"

SLOW_TELEM_LISTEN_PORT = mvp_protocol.SLOW_TELEM_PORT
SCHEMA_VERSION = mvp_protocol.PKT_SCHEMA_VERSION
ETH_IFACE = "eth0"
WLAN_IFACE = "wlan0"
UI_INPUT_TEST_DEFAULTS = {
    "debounce_ms": 100,
    "group_lockout_ms": 175,
}


def _safe_load_json(path: str, default: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return copy.deepcopy(default)


def _safe_save_json(path: str, data: Any) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"JSON save failed ({path}):", e)


def _normalize_slow_value(key: str, value: Any) -> Any:
    if key == "motors_on":
        return 1 if bool(value) else 0
    if key == "control_mode":
        s = str(value).strip().lower()
        return "angle" if s == "angle" or str(value) == "1" else "speed"
    if key == "lens_select":
        s = str(value).strip().lower()
        return "canon" if s == "canon" or str(value) == "1" else "fuji"
    if key in ("source_zoom", "source_focus", "source_iris"):
        s = str(value).strip().lower()
        if s not in ("pc", "camera", "off"):
            return "pc"
        return s
    if key == "wash_wipe":
        s = str(value).strip().lower()
        return "wiping" if s in ("1", "wipe", "wiping", "on", "true") else "parked"
    if key in ("filter_enable_focus", "filter_enable_iris"):
        return 1 if bool(value) else 0
    try:
        return int(value)
    except Exception:
        return value


def _default_slow_state() -> dict[str, Any]:
    return {
        "motors_on": 1,
        "control_mode": "speed",
        "lens_select": "fuji",
        "source_zoom": "pc",
        "source_focus": "pc",
        "source_iris": "pc",
        "filter_enable_focus": 0,
        "filter_enable_iris": 0,
        "filter_num": 1,
        "filter_den": 1,
        "gyro_heading_correction": 0x00001500,
        "wash_wipe": "parked",
    }


def _default_shaping_profile() -> dict[str, Any]:
    return {
        "ui_scale": True,
        "expo": 5.0,
        "expo_zoom": 5.0,
        "top_speed": {"yaw": 5.0, "pitch": 5.0, "roll": 5.0, "zoom": 5.0},
        "invert": {"yaw": False, "pitch": False, "roll": False},
        "deadband": {"yaw": 0.0, "pitch": 0.0, "roll": 0.0, "zoom": 0.0},
        "zoom_feedback": 1.0,
    }


def _clamp(v: float, lo: float, hi: float) -> float:
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


def _map_0_10_to_range(ui_val: float, out_min: float, out_max: float) -> float:
    u = _clamp(float(ui_val), 0.0, 10.0)
    return out_min + ((out_max - out_min) * (u / 10.0))


def _map_range_to_0_10(raw_val: float, in_min: float, in_max: float) -> float:
    if in_max <= in_min:
        return 0.0
    x = (float(raw_val) - in_min) / (in_max - in_min)
    return _clamp(x * 10.0, 0.0, 10.0)


def _normalized_shaping_profile(raw: Any) -> dict[str, Any]:
    base = _default_shaping_profile()
    if not isinstance(raw, dict):
        return base
    is_ui_scale = bool(raw.get("ui_scale", False))
    if is_ui_scale:
        if "expo" in raw:
            try:
                base["expo"] = _clamp(float(raw.get("expo", base["expo"])), 1.0, 10.0)
            except Exception:
                pass
        if "expo_zoom" in raw:
            try:
                base["expo_zoom"] = _clamp(float(raw.get("expo_zoom", base["expo_zoom"])), 1.0, 10.0)
            except Exception:
                pass
        if "top_speed" in raw:
            ts = raw.get("top_speed")
            if isinstance(ts, dict):
                for k in ("yaw", "pitch", "roll", "zoom"):
                    if k in ts:
                        try:
                            base["top_speed"][k] = _clamp(float(ts[k]), 0.0, 10.0)
                        except Exception:
                            pass
            else:
                try:
                    v = _clamp(float(ts), 0.0, 10.0)
                    for k in ("yaw", "pitch", "roll", "zoom"):
                        base["top_speed"][k] = v
                except Exception:
                    pass
    else:
        # Backward-compat migration from engineering units to normalized UI units.
        if "expo" in raw:
            try:
                base["expo"] = _clamp(_map_range_to_0_10(float(raw.get("expo", 0.0)), -1.0, 1.0), 1.0, 10.0)
            except Exception:
                pass
        if "expo_zoom" in raw:
            try:
                base["expo_zoom"] = _clamp(_map_range_to_0_10(float(raw.get("expo_zoom", 0.0)), -1.0, 1.0), 1.0, 10.0)
            except Exception:
                pass
        else:
            base["expo_zoom"] = base["expo"]
        if "top_speed" in raw:
            ts = raw.get("top_speed")
            if isinstance(ts, dict):
                for k in ("yaw", "pitch", "roll", "zoom"):
                    if k in ts:
                        try:
                            base["top_speed"][k] = _map_range_to_0_10(float(ts[k]), 0.0, 2.0)
                        except Exception:
                            pass
            else:
                try:
                    v = _map_range_to_0_10(float(ts), 0.0, 2.0)
                    for k in ("yaw", "pitch", "roll", "zoom"):
                        base["top_speed"][k] = v
                except Exception:
                    pass
    inv = raw.get("invert", {})
    if isinstance(inv, dict):
        for k in ("yaw", "pitch", "roll"):
            if k in inv:
                base["invert"][k] = bool(inv[k])
    db = raw.get("deadband", {})
    if isinstance(db, dict):
        for k in ("yaw", "pitch", "roll", "zoom"):
            if k in db:
                try:
                    v = float(db[k])
                    if is_ui_scale:
                        base["deadband"][k] = _clamp(v, 0.0, 10.0)
                    else:
                        base["deadband"][k] = _map_range_to_0_10(v, 0.0, 0.25)
                except Exception:
                    pass
    if "zoom_feedback" in raw:
        try:
            base["zoom_feedback"] = _clamp(float(raw["zoom_feedback"]), 1.0, 10.0)
        except Exception:
            base["zoom_feedback"] = 1.0
    else:
        base["zoom_feedback"] = 1.0
    base["ui_scale"] = True
    return base


def _default_network_model(head_count: int, source_heads: list[dict[str, Any]]) -> dict[str, Any]:
    heads_cfg = []
    for i in range(max(15, head_count)):
        base = source_heads[i] if i < len(source_heads) else {}
        heads_cfg.append(
            {
                "index": i,
                "name": base.get("name", f"HEAD-{i+1:02d}"),
                "ip": base.get("ip", f"192.168.60.{120 + i}"),
                "prefix": int(base.get("prefix", 24)),
                "gateway": base.get("gateway", "192.168.60.1"),
                "port_fast": int(base.get("port_fast", base.get("port", mvp_protocol.FAST_PORT))),
                "port_slow_cmd": int(base.get("port_slow_cmd", mvp_protocol.SLOW_CMD_PORT)),
            }
        )
    return {
        "pi_lan": {"address": "", "prefix": 24, "gateway": "192.168.60.1"},
        "heads": heads_cfg,
    }


def _parse_iface_ipv4(iface: str) -> dict[str, Any]:
    try:
        out = subprocess.run(
            ["ip", "-4", "addr", "show", iface],
            capture_output=True,
            text=True,
            check=False,
            timeout=2,
        ).stdout
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("inet "):
                ip_prefix = line.split()[1]
                addr, prefix = ip_prefix.split("/")
                return {"address": addr, "prefix": int(prefix)}
    except Exception:
        pass
    return {"address": "", "prefix": 24}


def _read_carrier(iface: str) -> bool:
    path = f"/sys/class/net/{iface}/carrier"
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip() == "1"
    except Exception:
        return False


def _run_nmcli(args: list[str]) -> tuple[bool, str]:
    try:
        p = subprocess.run(["nmcli"] + args, capture_output=True, text=True, check=False, timeout=10)
        ok = p.returncode == 0
        out = (p.stdout or "").strip()
        err = (p.stderr or "").strip()
        msg = out if out else err
        return ok, msg
    except Exception as e:
        return False, str(e)


heads = mvp_protocol.load_heads(HEADS_FILE)
selected_index = 0
slow_seq = 0
slow_apply_id = 0

dual_slow_state = _default_slow_state()
slow_apply_status: dict[str, dict[str, Any]] = {
    k: {"state": "idle", "apply_id": None, "seq": None, "updated_at": 0.0}
    for k in mvp_protocol.SLOW_KEY_IDS.keys()
}

factory_defaults = {"slow": _default_slow_state(), "shaping": _default_shaping_profile()}
user_defaults = {"shaping": _default_shaping_profile()}
shaping_state = _default_shaping_profile()

network_factory = _default_network_model(len(heads), heads)
network_user = _default_network_model(len(heads), heads)

head_feedback: dict[str, Any] = {"slow": {}, "lens": {}, "bgc": {}, "updated_at": 0.0}
# Zoom normalization: track observed lens zoom range, expose zoom_norm in [0, 1].
_zoom_raw_min: float = 0.0
_zoom_raw_max: float = 1.0
connection_status: dict[str, Any] = {
    "physical_link": {"eth0_up": False},
    "head": {"state": "disconnected", "last_telem_age_s": None, "last_send_ok": False},
    "bridge": {"ws_clients": 0},
}
wifi_status: dict[str, Any] = {"state": "unknown", "ssid": "", "ip": "", "last_error": ""}
calibration_status: dict[str, Any] = {
    "state": "idle",
    "request_id": "",
    "ok": None,
    "message": "",
    "updated_at": 0.0,
}
_calibration_result_mtime = 0.0

clients: set[Any] = set()
telem_sock: socket.socket | None = None


def _load_state() -> None:
    global selected_index, dual_slow_state, shaping_state, user_defaults
    data = _safe_load_json(STATE_FILE, {})
    idx = int(data.get("selected_index", 0))
    if 0 <= idx < len(heads):
        selected_index = idx
    for k in dual_slow_state:
        if k in data.get("slow_controls", {}):
            dual_slow_state[k] = _normalize_slow_value(k, data["slow_controls"][k])
    user_defaults = _safe_load_json(USER_DEFAULTS_FILE, {"shaping": _default_shaping_profile()})
    if "shaping" in user_defaults:
        shaping_state = _normalized_shaping_profile(user_defaults["shaping"])


def _save_state() -> None:
    data = {
        "schema_version": SCHEMA_VERSION,
        "selected_index": int(selected_index),
        "slow_controls": dict(dual_slow_state),
        "shaping": dict(shaping_state),
    }
    _safe_save_json(STATE_FILE, data)


def _save_selected_head_index() -> None:
    _safe_save_json(SELECTED_HEAD_FILE, {"selected_index": int(selected_index)})


def _load_network_models() -> None:
    global network_factory, network_user, heads
    network_factory = _safe_load_json(NETWORK_FACTORY_FILE, _default_network_model(len(heads), heads))
    network_user = _safe_load_json(NETWORK_USER_FILE, copy.deepcopy(network_factory))
    # Ensure fixed head slots (15) and required keys.
    base = _default_network_model(len(heads), heads)
    merged_heads = []
    for i in range(15):
        src = (network_user.get("heads") or [{}] * 15)[i] if i < len(network_user.get("heads", [])) else {}
        h = dict(base["heads"][i])
        h.update(src)
        h["index"] = i
        merged_heads.append(h)
    network_user["heads"] = merged_heads
    network_factory["heads"] = (network_factory.get("heads") or base["heads"])[:15]
    pi_detect = _parse_iface_ipv4(ETH_IFACE)
    if not network_factory.get("pi_lan", {}).get("address") and pi_detect.get("address"):
        network_factory["pi_lan"] = {
            "address": pi_detect["address"],
            "prefix": int(pi_detect.get("prefix", 24)),
            "gateway": "192.168.60.1",
        }
    if not network_user.get("pi_lan", {}).get("address"):
        network_user["pi_lan"] = copy.deepcopy(network_factory.get("pi_lan", {}))
    _safe_save_json(NETWORK_FACTORY_FILE, network_factory)
    _safe_save_json(NETWORK_USER_FILE, network_user)
    _apply_network_user_to_heads()


def _apply_network_user_to_heads() -> None:
    global heads
    src = network_user.get("heads", [])
    updated = []
    for i, h in enumerate(src):
        if i >= 15:
            break
        updated.append(
            {
                "name": h.get("name", f"HEAD-{i+1:02d}"),
                "ip": h.get("ip", f"192.168.60.{120+i}"),
                "prefix": int(h.get("prefix", 24)),
                "gateway": h.get("gateway", "192.168.60.1"),
                "port": int(h.get("port_fast", mvp_protocol.FAST_PORT)),
                "port_fast": int(h.get("port_fast", mvp_protocol.FAST_PORT)),
                "port_slow_cmd": int(h.get("port_slow_cmd", mvp_protocol.SLOW_CMD_PORT)),
            }
        )
    heads = updated
    _safe_save_json(HEADS_FILE, heads)


def _build_adc_profile_file_path() -> str:
    candidates = [
        os.path.join(BASE_DIR, "adc_bridge_profile.json"),
        "/home/admin/Dev/cross_shore_dev/apps/controller/adc_bridge_profile.json",
        "/home/admin/cross_shore_dev/apps/controller/adc_bridge_profile.json",
    ]
    for p in candidates:
        d = os.path.dirname(p)
        if os.path.isdir(d):
            return p
    return candidates[0]


def _build_controller_runtime_file_path(filename: str) -> str:
    candidates = []
    env_dir = os.environ.get("MVP_CONTROLLER_RUNTIME_DIR", "").strip()
    if env_dir:
        candidates.append(env_dir)
    candidates.extend(
        [
            os.path.dirname(_build_adc_profile_file_path()),
            "/home/admin/Dev/cross_shore_dev/apps/controller",
            "/home/admin/cross_shore_dev/apps/controller",
        ]
    )
    for d in candidates:
        try:
            if os.path.isdir(d) and os.path.isfile(os.path.join(d, "mvp_bridge_adc.py")):
                return os.path.join(d, filename)
        except Exception:
            continue
    return os.path.join(os.path.dirname(_build_adc_profile_file_path()), filename)


def _zoom_feedback_runtime_path() -> str:
    """Path for zoom feedback runtime JSON consumed by ADC bridge. Prefer /opt/wsbridge."""
    opt_ws = "/opt/wsbridge"
    try:
        if os.path.isdir(opt_ws):
            return os.path.join(opt_ws, ZOOM_FEEDBACK_RUNTIME_FILENAME)
    except Exception:
        pass
    return _build_controller_runtime_file_path(ZOOM_FEEDBACK_RUNTIME_FILENAME)


def _load_adc_profile() -> dict[str, Any]:
    path = _build_adc_profile_file_path()
    data = _safe_load_json(path, {})
    if not isinstance(data, dict) or "axes" not in data:
        return {"schema_version": 1, "stale_timeout_ms": 150, "axes": {k: {} for k in ("X", "Y", "Z", "Xrotate", "Yrotate", "Zrotate")}}
    return data


def _apply_shaping_to_adc_profile() -> tuple[bool, str]:
    profile = _load_adc_profile()
    axes = profile.setdefault("axes", {})
    expo_ui_ptr = _clamp(float(shaping_state.get("expo", 5.0)), 1.0, 10.0)
    expo_ui_zoom = _clamp(float(shaping_state.get("expo_zoom", expo_ui_ptr)), 1.0, 10.0)
    expo_ptr = _map_0_10_to_range(expo_ui_ptr, -1.0, 1.0)
    expo_zoom = _map_0_10_to_range(expo_ui_zoom, -1.0, 1.0)
    top_speed = shaping_state.get("top_speed", {})
    invert = shaping_state.get("invert", {})
    deadband = shaping_state.get("deadband", {})
    for axis, inv_key in (("X", "yaw"), ("Y", "pitch"), ("Z", "roll"), ("Zrotate", "zoom")):
        t = axes.setdefault(axis, {})
        t["expo"] = expo_zoom if axis == "Zrotate" else expo_ptr
        try:
            ui_gain = float(top_speed.get(inv_key, 5.0)) if isinstance(top_speed, dict) else float(top_speed)
        except Exception:
            ui_gain = 5.0
        t["gain"] = _map_0_10_to_range(_clamp(ui_gain, 0.0, 10.0), 0.0, 2.0)
        if axis != "Zrotate":
            t["invert"] = bool(invert.get(inv_key, False))
        try:
            db_ui = float(deadband.get(inv_key, 0.0))
        except Exception:
            db_ui = 0.0
        t["deadband"] = _map_0_10_to_range(db_ui, 0.0, 0.25)
    try:
        _safe_save_json(_build_adc_profile_file_path(), profile)
        return True, "adc_profile_updated"
    except Exception as e:
        return False, str(e)


def _start_input_calibration(duration_s: float = 2.5) -> tuple[bool, str, str]:
    global calibration_status
    req_id = str(int(time.time() * 1000))
    d = float(duration_s or 2.5)
    if d < 0.5:
        d = 0.5
    if d > 10.0:
        d = 10.0
    payload = {
        "request_id": req_id,
        "duration_s": d,
        "axes": ["X", "Y", "Z", "Zrotate"],
        "requested_at": time.time(),
    }
    req_path = _build_controller_runtime_file_path(ADC_CAL_REQUEST_FILE)
    try:
        with open(req_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        calibration_status = {
            "state": "requested",
            "request_id": req_id,
            "ok": None,
            "message": "calibration_requested",
            "updated_at": time.time(),
        }
        return True, "calibration_requested", req_id
    except Exception as e:
        return False, str(e), req_id


def _refresh_calibration_status() -> None:
    global _calibration_result_mtime
    result_path = _build_controller_runtime_file_path(ADC_CAL_RESULT_FILE)
    try:
        if not os.path.isfile(result_path):
            return
        mtime = os.path.getmtime(result_path)
        if mtime <= _calibration_result_mtime:
            return
        data = _safe_load_json(result_path, {})
        _calibration_result_mtime = mtime
        calibration_status.update(
            {
                "state": str(data.get("state", "done")),
                "request_id": str(data.get("request_id", "")),
                "ok": bool(data.get("ok")) if data.get("ok") is not None else None,
                "message": str(data.get("message", "")),
                "updated_at": time.time(),
                "result": data,
            }
        )
    except Exception:
        return


def _write_zoom_feedback_runtime() -> None:
    """Write zoom_feedback and zoom_norm to runtime JSON for ADC bridge (PTR damping)."""
    try:
        zoom_feedback = _clamp(float(shaping_state.get("zoom_feedback", 1.0)), 1.0, 10.0)
        lens = head_feedback.get("lens", {}) or {}
        zoom_norm = _clamp(float(lens.get("zoom_norm", 0.0)), 0.0, 1.0)
        payload = {
            "zoom_feedback": zoom_feedback,
            "zoom_norm": zoom_norm,
            "timestamp": time.time(),
        }
        path = _zoom_feedback_runtime_path()
        _safe_save_json(path, payload)
    except Exception:
        pass


def _send_one_slow_key_now(key: str) -> bool:
    global slow_seq, slow_apply_id
    if not heads or not (0 <= selected_index < len(heads)):
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
    pkt = mvp_protocol.build_slow_cmd_packet(slow_seq, slow_apply_id, key_id, int(enc))
    ok = mvp_protocol.send_udp_to(ip, port, pkt)
    slow_apply_status[key] = {
        "state": "sent" if ok else "send_error",
        "apply_id": slow_apply_id,
        "seq": slow_seq,
        "updated_at": time.time(),
    }
    connection_status["head"]["last_send_ok"] = bool(ok)
    return bool(ok)


def _selected_head_ip() -> str:
    if 0 <= selected_index < len(heads):
        return str(heads[selected_index].get("ip", "")).strip()
    return ""


def _normalize_lens_feedback(lens_payload: dict[str, Any]) -> dict[str, Any]:
    global _zoom_raw_min, _zoom_raw_max
    lens_payload = dict(lens_payload or {})
    pos = lens_payload.get("positions", {}) or {}
    zoom = pos.get("zoom", lens_payload.get("zoom_position", 0))
    focus = pos.get("focus", lens_payload.get("focus_position", 0))
    iris = pos.get("iris", lens_payload.get("iris_position", 0))
    zoom_val = int(zoom) if zoom is not None else 0
    focus_val = int(focus) if focus is not None else 0
    iris_val = int(iris) if iris is not None else 0
    lens_payload["positions"] = {
        "zoom": zoom_val,
        "focus": focus_val,
        "iris": iris_val,
    }
    # Track zoom range and compute normalized zoom [0, 1] for PTR feedback damping.
    if zoom_val < _zoom_raw_min:
        _zoom_raw_min = float(zoom_val)
    if zoom_val > _zoom_raw_max:
        _zoom_raw_max = float(zoom_val)
    span = _zoom_raw_max - _zoom_raw_min
    if span <= 0:
        zoom_norm = 0.0
    else:
        zoom_norm = _clamp((float(zoom_val) - _zoom_raw_min) / span, 0.0, 1.0)
    lens_payload["zoom_norm"] = zoom_norm
    if "lens_full_name" not in lens_payload:
        lens_payload["lens_full_name"] = ""
    lens_payload["zoom_control_mode"] = str(lens_payload.get("zoom_control_mode", "position"))
    lens_payload["zoom_velocity_cmd"] = int(lens_payload.get("zoom_velocity_cmd", 0) or 0)
    lens_payload["zoom_speed_raw"] = int(lens_payload.get("zoom_speed_raw", 0) or 0)
    return lens_payload


def _state_payload() -> dict[str, Any]:
    return {
        "type": "STATE",
        "schema_version": SCHEMA_VERSION,
        "heads": heads,
        "selected": selected_index,
        "slow_controls": dict(dual_slow_state),
        "slow_apply_status": copy.deepcopy(slow_apply_status),
        "shaping": dict(shaping_state),
        "defaults": {"factory": copy.deepcopy(factory_defaults), "user": copy.deepcopy(user_defaults)},
        "head_feedback": copy.deepcopy(head_feedback),
        "connection_status": copy.deepcopy(connection_status),
        "network_config": copy.deepcopy(network_user),
        "wifi_status": copy.deepcopy(wifi_status),
        "calibration": copy.deepcopy(calibration_status),
        "ui_config": {
            "input_tests": dict(UI_INPUT_TEST_DEFAULTS),
        },
    }


async def _broadcast(payload: dict[str, Any]) -> None:
    if not clients:
        return
    msg = json.dumps(payload)
    dead = []
    for ws in clients:
        try:
            await ws.send(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        clients.discard(ws)


async def _publish_state() -> None:
    await _broadcast(_state_payload())


async def slow_sender_task() -> None:
    while True:
        await asyncio.sleep(SLOW_SEND_INTERVAL_S)
        if not heads:
            continue
        for key in mvp_protocol.SLOW_KEY_IDS.keys():
            _send_one_slow_key_now(key)


async def telemetry_receiver_task() -> None:
    global telem_sock
    telem_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    telem_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    telem_sock.bind(("0.0.0.0", SLOW_TELEM_LISTEN_PORT))
    telem_sock.setblocking(False)
    loop = asyncio.get_running_loop()
    while True:
        try:
            data, addr = await loop.sock_recvfrom(telem_sock, 8192)
        except Exception:
            await asyncio.sleep(0.05)
            continue
        src_ip = str((addr or ("", 0))[0]).strip()
        want_ip = _selected_head_ip()
        # Bind feedback to selected head only so runtime status flips correctly.
        if want_ip and src_ip and src_ip != want_ip:
            continue
        ack = mvp_protocol.decode_slow_ack_packet(data)
        if ack:
            key = next((k for k, kid in mvp_protocol.SLOW_KEY_IDS.items() if kid == ack.get("key_id")), None)
            if key:
                slow_apply_status[key] = {
                    "state": "confirmed" if int(ack.get("status", 1)) == 1 else "rejected",
                    "apply_id": ack.get("apply_id"),
                    "seq": ack.get("seq"),
                    "updated_at": time.time(),
                }
            continue
        telem = mvp_protocol.decode_slow_telem_packet(data)
        if telem:
            head_feedback["slow"] = telem.get("slow", {})
            head_feedback["lens"] = _normalize_lens_feedback(telem.get("lens", {}))
            head_feedback["bgc"] = telem.get("bgc", {})
            head_feedback["updated_at"] = time.time()


def _refresh_connection_status() -> None:
    connection_status["physical_link"]["eth0_up"] = _read_carrier(ETH_IFACE)
    age_s = None
    if head_feedback.get("updated_at"):
        age_s = max(0.0, time.time() - float(head_feedback.get("updated_at")))
    head_state = "disconnected"
    if age_s is not None and age_s < HEAD_CONNECTED_TIMEOUT_S:
        head_state = "connected"
    elif connection_status["head"].get("last_send_ok"):
        head_state = "trying"
    connection_status["head"]["state"] = head_state
    connection_status["head"]["last_telem_age_s"] = age_s
    connection_status["head"]["selected_ip"] = _selected_head_ip()
    connection_status["bridge"]["ws_clients"] = len(clients)
    lan = _parse_iface_ipv4(ETH_IFACE)
    # Keep desired Pi LAN config persistent; expose live interface status separately.
    connection_status["pi_lan_live"] = {
        "address": lan.get("address", ""),
        "prefix": int(lan.get("prefix", 24)),
    }


def _refresh_wifi_status() -> None:
    ok, out = _run_nmcli(["-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"])
    if not ok:
        wifi_status["last_error"] = out
        return
    wifi_status.update({"state": "disconnected", "ssid": "", "ip": "", "last_error": ""})
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) < 4:
            continue
        dev, typ, st, conn = parts[0], parts[1], parts[2], parts[3]
        if dev == WLAN_IFACE and typ == "wifi":
            wifi_status["state"] = st
            wifi_status["ssid"] = "" if conn == "--" else conn
    ip = _parse_iface_ipv4(WLAN_IFACE)
    wifi_status["ip"] = ip.get("address", "")


async def status_publish_task() -> None:
    while True:
        _refresh_connection_status()
        _refresh_wifi_status()
        _refresh_calibration_status()
        _write_zoom_feedback_runtime()
        await _publish_state()
        await asyncio.sleep(STATUS_PUBLISH_INTERVAL_S)


def _set_head_config(index: int, config: dict[str, Any]) -> tuple[bool, str]:
    if index < 0 or index >= 15:
        return False, "index_out_of_range"
    h = network_user["heads"][index]
    for key in ("name", "ip", "gateway"):
        if key in config:
            h[key] = str(config[key]).strip()
    for key in ("prefix", "port_fast", "port_slow_cmd"):
        if key in config:
            h[key] = int(config[key])
    _safe_save_json(NETWORK_USER_FILE, network_user)
    _apply_network_user_to_heads()
    return True, "head_config_saved"


def _set_pi_lan_config(config: dict[str, Any]) -> tuple[bool, str]:
    pi = network_user.setdefault("pi_lan", {})
    for key in ("address", "gateway"):
        if key in config:
            pi[key] = str(config[key]).strip()
    if "prefix" in config:
        pi["prefix"] = int(config["prefix"])
    _safe_save_json(NETWORK_USER_FILE, network_user)
    return True, "pi_lan_saved"


def _apply_pi_lan_config() -> tuple[bool, str]:
    pi = network_user.get("pi_lan", {})
    address = str(pi.get("address", "")).strip()
    prefix = int(pi.get("prefix", 24))
    gateway = str(pi.get("gateway", "")).strip()
    if not address or not gateway:
        return False, "pi_lan_missing_address_or_gateway"
    ok, out = _run_nmcli(["-t", "-f", "NAME,TYPE", "connection", "show"])
    if not ok:
        return False, out
    conn = ""
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) >= 2 and parts[1] == "802-3-ethernet":
            conn = parts[0]
            break
    if not conn:
        ok, devs = _run_nmcli(["-t", "-f", "DEVICE,TYPE", "device", "status"])
        if not ok:
            return False, devs
        iface = ""
        for line in devs.splitlines():
            parts = line.split(":")
            if len(parts) >= 2 and parts[1] == "ethernet":
                iface = parts[0]
                break
        if not iface:
            return False, "no_ethernet_interface"
        conn = "HydraVision Ethernet"
        _run_nmcli(["connection", "add", "type", "ethernet", "ifname", iface, "con-name", conn])
    ok, msg = _run_nmcli(
        [
            "connection",
            "modify",
            conn,
            "ipv4.method",
            "manual",
            "ipv4.addresses",
            f"{address}/{prefix}",
            "ipv4.gateway",
            gateway,
            "ipv6.method",
            "ignore",
            "connection.autoconnect",
            "yes",
        ]
    )
    if not ok:
        return False, msg
    _run_nmcli(["connection", "up", conn])
    return True, "pi_lan_applied"


def _factory_reset_network() -> tuple[bool, str]:
    # Per requirement: reset Pi LAN and Head #1 only.
    network_user["pi_lan"] = copy.deepcopy(network_factory.get("pi_lan", {}))
    if network_user.get("heads") and network_factory.get("heads"):
        network_user["heads"][0] = copy.deepcopy(network_factory["heads"][0])
    _safe_save_json(NETWORK_USER_FILE, network_user)
    _apply_network_user_to_heads()
    return True, "factory_reset_pi_lan_and_head1"


def _wifi_scan() -> tuple[bool, Any]:
    ok, out = _run_nmcli(["-t", "-f", "SSID,SIGNAL,SECURITY", "dev", "wifi", "list"])
    if not ok:
        return False, out
    rows = []
    seen = set()
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) < 3:
            continue
        ssid = parts[0].strip()
        if not ssid or ssid in seen:
            continue
        seen.add(ssid)
        rows.append({"ssid": ssid, "signal": int(parts[1] or 0), "security": parts[2]})
    rows.sort(key=lambda x: x["signal"], reverse=True)
    return True, rows


def _wifi_connect(ssid: str, password: str) -> tuple[bool, str]:
    if not ssid:
        return False, "ssid_required"
    args = ["dev", "wifi", "connect", ssid]
    if password:
        args += ["password", password]
    return _run_nmcli(args)


def _wifi_disconnect() -> tuple[bool, str]:
    return _run_nmcli(["device", "disconnect", WLAN_IFACE])


async def handler(websocket: Any) -> None:
    global selected_index
    clients.add(websocket)
    await websocket.send(json.dumps(_state_payload()))
    print("Slow UI client connected")
    try:
        async for message in websocket:
            try:
                data = json.loads(message)
            except Exception:
                continue
            msg_type = str(data.get("type", "")).strip()
            if msg_type == "REQUEST_STATE":
                await websocket.send(json.dumps(_state_payload()))
            elif msg_type == "SELECT_HEAD":
                idx = int(data.get("index", 0))
                if 0 <= idx < len(heads):
                    selected_index = idx
                    _save_selected_head_index()
                    _save_state()
                    # Force status to re-evaluate selected-head connectivity.
                    head_feedback["updated_at"] = 0.0
                    connection_status["head"]["last_send_ok"] = False
            elif msg_type == "SET_SLOW_CONTROL":
                key = str(data.get("key", "")).strip()
                if key in mvp_protocol.SLOW_KEY_IDS:
                    dual_slow_state[key] = _normalize_slow_value(key, data.get("value"))
                    _save_state()
                    slow_apply_status[key]["state"] = "pending"
                    slow_apply_status[key]["updated_at"] = time.time()
                    _send_one_slow_key_now(key)
            elif msg_type == "SET_SHAPING":
                payload = data.get("value", {}) or {}
                if not isinstance(shaping_state.get("top_speed"), dict):
                    try:
                        sv = float(shaping_state.get("top_speed", 5.0))
                    except Exception:
                        sv = 5.0
                    shaping_state["top_speed"] = {"yaw": sv, "pitch": sv, "roll": sv, "zoom": sv}
                if "expo" in payload:
                    shaping_state["expo"] = _clamp(float(payload["expo"]), 1.0, 10.0)
                if "expo_zoom" in payload:
                    shaping_state["expo_zoom"] = _clamp(float(payload["expo_zoom"]), 1.0, 10.0)
                if "top_speed" in payload:
                    ts = payload.get("top_speed")
                    if isinstance(ts, dict):
                        for k in ("yaw", "pitch", "roll", "zoom"):
                            if k in ts:
                                try:
                                    shaping_state["top_speed"][k] = _clamp(float(ts[k]), 0.0, 10.0)
                                except Exception:
                                    pass
                    else:
                        v = _clamp(float(ts), 0.0, 10.0)
                        for k in ("yaw", "pitch", "roll", "zoom"):
                            shaping_state["top_speed"][k] = v
                inv = payload.get("invert", {})
                if isinstance(inv, dict):
                    for k in ("yaw", "pitch", "roll"):
                        if k in inv:
                            shaping_state["invert"][k] = bool(inv[k])
                db = payload.get("deadband", {})
                if isinstance(db, dict):
                    for k in ("yaw", "pitch", "roll", "zoom"):
                        if k in db:
                            try:
                                v = float(db[k])
                            except Exception:
                                continue
                            shaping_state["deadband"][k] = _clamp(v, 0.0, 10.0)
                if "zoom_feedback" in payload:
                    try:
                        shaping_state["zoom_feedback"] = _clamp(float(payload["zoom_feedback"]), 1.0, 10.0)
                    except Exception:
                        pass
                shaping_state["ui_scale"] = True
                ok, msg = _apply_shaping_to_adc_profile()
                await websocket.send(json.dumps({"type": "SHAPING_APPLIED", "ok": ok, "message": msg, "value": shaping_state}))
            elif msg_type == "SAVE_USER_DEFAULTS":
                user_defaults["shaping"] = copy.deepcopy(shaping_state)
                _safe_save_json(USER_DEFAULTS_FILE, user_defaults)
                await websocket.send(json.dumps({"type": "USER_DEFAULTS_SAVED", "ok": True}))
            elif msg_type == "RESET_USER_DEFAULTS":
                shaping_state.update(copy.deepcopy(factory_defaults["shaping"]))
                user_defaults["shaping"] = copy.deepcopy(factory_defaults["shaping"])
                _safe_save_json(USER_DEFAULTS_FILE, user_defaults)
                ok, msg = _apply_shaping_to_adc_profile()
                await websocket.send(json.dumps({"type": "USER_DEFAULTS_RESET", "ok": ok, "message": msg}))
            elif msg_type == "SET_PI_LAN_CONFIG":
                ok, msg = _set_pi_lan_config(data.get("value", {}) or {})
                await websocket.send(json.dumps({"type": "PI_LAN_SAVED", "ok": ok, "message": msg}))
            elif msg_type == "SET_HEAD_CONFIG":
                idx = int(data.get("index", -1))
                ok, msg = _set_head_config(idx, data.get("value", {}) or {})
                await websocket.send(json.dumps({"type": "HEAD_CONFIG_SAVED", "index": idx, "ok": ok, "message": msg}))
            elif msg_type == "APPLY_NETWORK_CONFIG":
                ok, msg = _apply_pi_lan_config()
                await websocket.send(json.dumps({"type": "NETWORK_APPLIED", "ok": ok, "message": msg}))
            elif msg_type == "FACTORY_RESET_NETWORK":
                ok, msg = _factory_reset_network()
                await websocket.send(json.dumps({"type": "NETWORK_FACTORY_RESET", "ok": ok, "message": msg}))
            elif msg_type == "WIFI_SCAN":
                ok, rows = await asyncio.to_thread(_wifi_scan)
                await websocket.send(json.dumps({"type": "WIFI_SCAN_RESULT", "ok": ok, "networks": rows if ok else [], "message": "" if ok else str(rows)}))
            elif msg_type == "WIFI_CONNECT":
                ssid = str(data.get("ssid", "")).strip()
                password = str(data.get("password", ""))
                ok, msg = await asyncio.to_thread(_wifi_connect, ssid, password)
                await websocket.send(json.dumps({"type": "WIFI_CONNECT_RESULT", "ok": ok, "message": msg}))
            elif msg_type == "WIFI_DISCONNECT":
                ok, msg = await asyncio.to_thread(_wifi_disconnect)
                await websocket.send(json.dumps({"type": "WIFI_DISCONNECT_RESULT", "ok": ok, "message": msg}))
            elif msg_type == "WIFI_STATUS":
                _refresh_wifi_status()
                await websocket.send(json.dumps({"type": "WIFI_STATUS_RESULT", "ok": True, "status": wifi_status}))
            elif msg_type == "CALIBRATE_INPUTS":
                ok, msg, req_id = _start_input_calibration(float(data.get("duration_s", 2.5) or 2.5))
                await websocket.send(
                    json.dumps(
                        {
                            "type": "CALIBRATE_INPUTS_ACCEPTED",
                            "ok": ok,
                            "message": msg,
                            "request_id": req_id,
                        }
                    )
                )
            await _publish_state()
    except websockets.ConnectionClosed:
        print("Slow UI client disconnected")
    finally:
        clients.discard(websocket)


async def main() -> None:
    _load_state()
    _load_network_models()
    _save_selected_head_index()
    _apply_shaping_to_adc_profile()
    print(f"Slow WebSocket server starting on ws://127.0.0.1:{WS_PORT}")
    print(f"Slow sender running at {1.0 / SLOW_SEND_INTERVAL_S:.1f} Hz")
    asyncio.create_task(slow_sender_task())
    asyncio.create_task(telemetry_receiver_task())
    asyncio.create_task(status_publish_task())
    async with websockets.serve(handler, "0.0.0.0", WS_PORT):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
