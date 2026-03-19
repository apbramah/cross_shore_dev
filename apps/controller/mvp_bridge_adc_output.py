"""
Output layer for the ADC bridge: reuse mvp_protocol packet builders and UDP
send helpers when available; otherwise emit deterministic JSON over UDP.
Preserves fast/slow channel behavior where possible. See ADC_BRIDGE_INTERFACE.md.
"""

from __future__ import annotations

import json
import socket
import time
from typing import Any

# Optional: reuse existing protocol when present in same app
try:
    import mvp_protocol as _mvp_protocol
    MVP_PROTOCOL_AVAILABLE = True
except ImportError:
    _mvp_protocol = None
    MVP_PROTOCOL_AVAILABLE = False

AXIS_KEYS = ("X", "Y", "Z", "Xrotate", "Yrotate", "Zrotate")
DEFAULT_FAST_PORT = 8888
DEFAULT_SLOW_PORT = 8890
DEFAULT_HEAD_ADDR = "127.0.0.1"
_fast_seq = 0
_lens_axis_state = {"Xrotate": 0.0, "Yrotate": 0.0, "last_t": 0.0}
# Bridge-side lens axis stabilization to suppress analog jitter that causes
# visible focus/iris reversals on Canon when operator intent is monotonic.
LENS_AXIS_ALPHA = 0.22
LENS_AXIS_MAX_RATE_PER_S = 2.2
LENS_AXIS_DEADBAND = 0.004
_default_control_state = {
    "invert": {"yaw": False, "pitch": False, "roll": False},
    "speed": 1.0,
    "zoom_gain": 60,
    "lens_type": "fuji",
    "axis_sources": {"zoom": "pc", "focus": "pc", "iris": "pc"},
}


def axes_to_list(axes: dict[str, Any]) -> list[float]:
    """Order axes as X, Y, Z, Xrotate, Yrotate, Zrotate for protocol compatibility."""
    return [float(axes.get(k, 0.0)) for k in AXIS_KEYS]


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _stabilize_lens_axes(axes: dict[str, Any]) -> dict[str, Any]:
    """Apply LPF + slew limit + tiny deadband on focus/iris command axes."""
    out = dict(axes or {})
    now = time.monotonic()
    last_t = float(_lens_axis_state.get("last_t", 0.0) or 0.0)
    dt = (now - last_t) if last_t > 0.0 else (1.0 / 50.0)
    if dt < 0.001:
        dt = 0.001
    if dt > 0.200:
        dt = 0.200
    _lens_axis_state["last_t"] = now

    for axis in ("Xrotate", "Yrotate"):
        target = float(out.get(axis, 0.0) or 0.0)
        target = _clamp(target, -1.0, 1.0)
        if abs(target) < LENS_AXIS_DEADBAND:
            target = 0.0
        prev = float(_lens_axis_state.get(axis, 0.0) or 0.0)
        lpf = (LENS_AXIS_ALPHA * target) + ((1.0 - LENS_AXIS_ALPHA) * prev)
        max_step = LENS_AXIS_MAX_RATE_PER_S * dt
        delta = lpf - prev
        if delta > max_step:
            lpf = prev + max_step
        elif delta < -max_step:
            lpf = prev - max_step
        lpf = _clamp(lpf, -1.0, 1.0)
        _lens_axis_state[axis] = lpf
        out[axis] = lpf
    return out


def send_fast(axes: dict[str, Any], host: str, port: int, sock: socket.socket | None = None) -> socket.socket | None:
    """Send fast path. Reuses mvp_protocol.build_fast_packet_v2 / build_udp_packet if available."""
    global _fast_seq
    if sock is None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    shaped_axes = _stabilize_lens_axes(axes)

    if MVP_PROTOCOL_AVAILABLE and hasattr(_mvp_protocol, "build_fast_packet_v2"):
        try:
            _fast_seq = (_fast_seq + 1) & 0xFFFF
            payload = _mvp_protocol.build_fast_packet_v2(shaped_axes, _default_control_state, _fast_seq)
            if payload:
                try:
                    sock.sendto(payload, (host, port))
                except OSError:
                    return sock
            return sock
        except Exception:
            pass
    if MVP_PROTOCOL_AVAILABLE and hasattr(_mvp_protocol, "build_udp_packet"):
        try:
            payload = _mvp_protocol.build_udp_packet(shaped_axes, _default_control_state)
            if payload:
                try:
                    sock.sendto(payload, (host, port))
                except OSError:
                    return sock
            return sock
        except Exception:
            pass
    # Fallback: deterministic JSON for integration testing
    payload = json.dumps({"t": time.monotonic(), "axes": shaped_axes}).encode("utf-8")
    try:
        sock.sendto(payload, (host, port))
    except OSError:
        return sock
    return sock


def send_slow(axes: dict[str, Any], host: str, port: int, sock: socket.socket | None = None) -> socket.socket | None:
    """Send slow path only when a dedicated slow builder exists."""
    if sock is None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    if MVP_PROTOCOL_AVAILABLE and hasattr(_mvp_protocol, "build_slow_packet"):
        try:
            payload = _mvp_protocol.build_slow_packet(axes)
            if payload:
                try:
                    sock.sendto(payload, (host, port))
                except OSError:
                    return sock
            return sock
        except Exception:
            pass
    return sock
