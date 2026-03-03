"""
Shaping/tuning layer for the ADC bridge: deadband, center offset, low-pass,
expo, slew, invert/gain/clamp. Produces protocol-ready axes keyed as
X/Y/Z/Xrotate/Yrotate/Zrotate. See ADC_BRIDGE_INTERFACE.md.
"""

from __future__ import annotations

import math
import time
from typing import Any

from mvp_bridge_adc_state import AXIS_KEYS, ADCBridgeState

ADC_MAX = 4095
ADC_MIN = 0
ADC_CENTER = (ADC_MIN + ADC_MAX) / 2.0


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


def shape_sample(
    raw_sample: dict[str, Any],
    state: ADCBridgeState,
    filter_state: dict[str, float],
    last_time: float,
) -> tuple[dict[str, Any], float]:
    """
    Take raw axis sample and state, return protocol-ready axes dict
    (X, Y, Z, Xrotate, Yrotate, Zrotate) and new last_time.
    filter_state holds per-axis LPF and slew state; mutated in place.
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
    return out, now


def neutral_axes() -> dict[str, Any]:
    """Protocol-ready centered (zero) axes for stale/timeout safe output."""
    return {k: 0.0 for k in AXIS_KEYS}
