"""
Runtime/config state for the ADC bridge. Tunable parameters, validation,
active profile versioning, and health snapshot. See ADC_BRIDGE_INTERFACE.md.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any

AXIS_KEYS = ("X", "Y", "Z", "Xrotate", "Yrotate", "Zrotate")
PROFILE_FILENAME = "adc_bridge_profile.json"
SCHEMA_VERSION = 1
STALE_TIMEOUT_MS_DEFAULT = 150

# Passthrough defaults per ADC Fast Path Cleanup: no filtering, no bit loss.
DEFAULT_AXIS_TUNING: dict[str, Any] = {
    "deadband": 0.0,
    "center_offset": 0.0,
    "lpf_alpha": 1.0,   # 1.0 = no LPF (passthrough)
    "expo": 0.0,
    "slew_rate": 1000.0,  # high = effectively no slew limit
    "invert": False,
    "gain": 1.0,
    "clamp_min": -1.0,
    "clamp_max": 1.0,
}


def default_profile() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "stale_timeout_ms": STALE_TIMEOUT_MS_DEFAULT,
        "axes": {k: dict(DEFAULT_AXIS_TUNING) for k in AXIS_KEYS},
    }


def validate_axis_tuning(data: dict[str, Any]) -> tuple[bool, str]:
    """Validate one axis tuning block. Returns (ok, error_message)."""
    for key, (lo, hi) in [
        ("deadband", (0.0, 1.0)),
        ("center_offset", (-1.0, 1.0)),
        ("lpf_alpha", (0.0, 1.0)),
        ("expo", (-1.0, 1.0)),
        ("slew_rate", (0.0, float("inf"))),
        ("gain", (0.0, float("inf"))),
        ("clamp_min", (-1.0, 0.0)),
        ("clamp_max", (0.0, 1.0)),
    ]:
        if key not in data:
            return False, f"missing key: {key}"
        v = data[key]
        if key == "lpf_alpha" and (v <= 0 or v > 1):
            return False, f"{key} must be in (0.0, 1.0]"
        if key in ("deadband", "center_offset", "lpf_alpha", "expo", "clamp_min", "clamp_max") and isinstance(v, (int, float)):
            if not (lo <= v <= hi):
                return False, f"{key} must be in [{lo}, {hi}]"
        if key in ("slew_rate", "gain") and isinstance(v, (int, float)):
            if v <= 0 or (key == "gain" and v == float("inf")):
                return False, f"{key} must be > 0"
    if "invert" not in data:
        return False, "missing key: invert"
    if not isinstance(data["invert"], bool):
        return False, "invert must be bool"
    cmin, cmax = data.get("clamp_min", -1.0), data.get("clamp_max", 1.0)
    if cmin >= cmax:
        return False, "clamp_min must be < clamp_max"
    return True, ""


def validate_profile(data: dict[str, Any]) -> tuple[bool, str]:
    """Validate full profile. Returns (ok, error_message)."""
    if not isinstance(data, dict):
        return False, "profile must be a dict"
    if data.get("schema_version") != SCHEMA_VERSION:
        return False, f"schema_version must be {SCHEMA_VERSION}"
    for k in AXIS_KEYS:
        if k not in data.get("axes", {}):
            return False, f"axes missing key: {k}"
        ok, msg = validate_axis_tuning(data["axes"][k])
        if not ok:
            return False, f"axes.{k}: {msg}"
    return True, ""


class ADCBridgeState:
    """Thread-safe runtime state: profile, health snapshot, and apply semantics."""

    def __init__(self, profile_dir: str | None = None):
        self._profile_dir = profile_dir or os.path.dirname(os.path.abspath(__file__))
        self._lock = threading.Lock()
        self._profile = default_profile()
        self._load_profile()
        # Health snapshot (updated by ingest/output)
        self._health: dict[str, Any] = {
            "last_seq": None,
            "seq_gaps": 0,
            "last_rx_monotonic_s": None,
            "frame_age_ms": None,
            "parse_errors": 0,
            "reconnect_count": 0,
            "ingest_ok": False,
        }

    def _profile_path(self) -> str:
        return os.path.join(self._profile_dir, PROFILE_FILENAME)

    def _load_profile(self) -> None:
        path = self._profile_path()
        if not os.path.isfile(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            ok, _ = validate_profile(data)
            if ok:
                self._profile = data
        except Exception:
            pass

    def get_profile(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._profile))

    def get_axis_tuning(self, axis: str) -> dict[str, Any]:
        with self._lock:
            axes = self._profile.get("axes", {})
            return dict(axes.get(axis, DEFAULT_AXIS_TUNING))

    def get_stale_timeout_ms(self) -> float:
        with self._lock:
            return float(self._profile.get("stale_timeout_ms", STALE_TIMEOUT_MS_DEFAULT))

    def apply_profile_update(self, new_profile: dict[str, Any]) -> tuple[bool, str]:
        """Stage -> validate -> atomic swap. Returns (success, message)."""
        ok, msg = validate_profile(new_profile)
        if not ok:
            return False, msg
        with self._lock:
            self._profile = new_profile
        try:
            path = self._profile_path()
            with open(path, "w", encoding="utf-8") as f:
                json.dump(new_profile, f, indent=2)
        except Exception as e:
            return False, str(e)
        return True, "ACK"

    def update_health(self, **kwargs: Any) -> None:
        with self._lock:
            for k, v in kwargs.items():
                if k in self._health:
                    self._health[k] = v

    def get_health(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._health)
