"""
Shaping/tuning layer for the ADC bridge: deadband, center offset, low-pass,
expo, slew, invert/gain/clamp. Produces protocol-ready axes keyed as
X/Y/Z/Xrotate/Yrotate/Zrotate. See ADC_BRIDGE_INTERFACE.md.

Zoom feedback PTR damping: when zoom_feedback_runtime is provided, applies
a log-scale multiplier to X/Y/Z (pan/tilt/roll) based on zoom_norm and
zoom_feedback strength (1..10). Zrotate (zoom axis) is unchanged.
"""

from __future__ import annotations

import math
import time
from typing import Any

from mvp_bridge_adc_state import AXIS_KEYS, ADCBridgeState

ADC_MAX = 4095
ADC_MIN = 0
ADC_CENTER = (ADC_MIN + ADC_MAX) / 2.0

# Log blend factor for zoom-based PTR damping (plan: k fixed, e.g. 9)
ZOOM_FEEDBACK_LOG_K = 9.0


def _norm(raw: int) -> float:
    """Raw ADC [0, 4095] -> [-1, 1] with center at 0."""
    return (float(raw) - ADC_CENTER) / (ADC_CENTER - ADC_MIN)


def _apply_center_offset(v: float, center_offset: float) -> float:
    return v - center_offset


def _apply_deadband(v: float, deadband: float) -> float:
    if abs(v) <= deadband:
        return 0.0
    if v > 0:
        return (v - deadband) / (1.0 - deadband)
    return (v + deadband) / (1.0 - deadband)


def _apply_expo(v: float, expo: float) -> float:
    if expo == 0:
        return v
    # expo curve: sign(v) * (|v|^exp) with exp = 1 + expo
    exp = 1.0 + expo
    return math.copysign(abs(v) ** exp, v)


def _apply_lpf(current: float, new_val: float, alpha: float) -> float:
    return alpha * new_val + (1.0 - alpha) * current


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _slew(current: float, target: float, rate_per_sec: float, dt: float) -> float:
    if dt <= 0:
        return current
    delta = target - current
    step = rate_per_sec * dt
    if abs(delta) <= step:
        return target
    return current + math.copysign(step, delta)


def _is_passthrough_tuning(t: dict[str, Any]) -> bool:
    """True if tuning is identity (no deadband, expo, LPF, slew effect)."""
    return (
        t.get("deadband", 0) == 0
        and t.get("center_offset", 0) == 0
        and t.get("expo", 0) == 0
        and t.get("lpf_alpha", 0.5) >= 1.0
        and t.get("slew_rate", 10) >= 500.0
        and t.get("gain", 1) == 1.0
        and t.get("clamp_min", -1) <= -1.0
        and t.get("clamp_max", 1) >= 1.0
    )


def _ptr_damping_multiplier(zoom_feedback: float, zoom_norm: float) -> float:
    """
    Compute PTR gain multiplier from zoom feedback (1..10) and normalized zoom (0..1).
    mult_end = 1.0 / zoom_feedback; blend = log1p(k*zoom_norm)/log1p(k);
    mult = 1.0 - (1.0 - mult_end) * blend.
    """
    if zoom_feedback <= 0:
        return 1.0
    mult_end = 1.0 / max(1.0, float(zoom_feedback))
    z = _clamp(float(zoom_norm), 0.0, 1.0)
    k = ZOOM_FEEDBACK_LOG_K
    if z <= 0:
        return 1.0
    blend = math.log1p(k * z) / math.log1p(k)
    blend = _clamp(blend, 0.0, 1.0)
    return 1.0 - (1.0 - mult_end) * blend


def shape_sample(
    raw_sample: dict[str, Any],
    state: ADCBridgeState,
    filter_state: dict[str, float],
    last_time: float,
    zoom_feedback_runtime: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], float]:
    """
    Take raw axis sample and state, return protocol-ready axes dict
    (X, Y, Z, Xrotate, Yrotate, Zrotate) and new last_time.
    filter_state holds per-axis LPF and slew state; mutated in place.
    When all axes use passthrough tuning, only norm + invert + clamp are applied (no LPF/slew).
    If zoom_feedback_runtime is provided (zoom_feedback, zoom_norm), applies PTR damping to X,Y,Z only.
    """
    now = time.monotonic()
    dt = now - last_time if last_time else 0.0
    out: dict[str, Any] = {}
    for k in AXIS_KEYS:
        tuning = state.get_axis_tuning(k)
        raw = raw_sample.get(k, int(ADC_CENTER))
        v = _norm(raw)
        v = _apply_center_offset(v, tuning["center_offset"])
        v = _apply_deadband(v, tuning["deadband"])
        v = _apply_expo(v, tuning["expo"])
        if _is_passthrough_tuning(tuning):
            # Passthrough baseline: skip LPF and slew to preserve resolution.
            pass
        else:
            lpf_alpha = tuning["lpf_alpha"]
            key_lpf = f"{k}_lpf"
            prev_lpf = filter_state.get(key_lpf, 0.0)
            v = _apply_lpf(prev_lpf, v, lpf_alpha)
            filter_state[key_lpf] = v
            v = _slew(filter_state.get(f"{k}_out", 0.0), v, tuning["slew_rate"], dt)
        if tuning["invert"]:
            v = -v
        v = v * tuning["gain"]
        v = _clamp(v, tuning["clamp_min"], tuning["clamp_max"])
        filter_state[f"{k}_out"] = v
        out[k] = v
    # Apply zoom-feedback PTR damping to X, Y, Z only (not Zrotate).
    if zoom_feedback_runtime:
        try:
            zf = float(zoom_feedback_runtime.get("zoom_feedback", 1.0) or 1.0)
            zn = float(zoom_feedback_runtime.get("zoom_norm", 0.0) or 0.0)
            mult = _ptr_damping_multiplier(zf, zn)
            for axis in ("X", "Y", "Z"):
                if axis in out:
                    out[axis] = out[axis] * mult
        except (TypeError, ValueError):
            pass
    return out, now


def neutral_axes() -> dict[str, Any]:
    """Protocol-ready centered (zero) axes for stale/timeout safe output."""
    return {k: 0.0 for k in AXIS_KEYS}
