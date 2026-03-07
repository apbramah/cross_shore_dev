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


def send_fast(axes: dict[str, Any], host: str, port: int, sock: socket.socket | None = None) -> socket.socket | None:
    """Send fast path. Reuses mvp_protocol.build_fast_packet_v2 / build_udp_packet if available."""
    global _fast_seq
    if sock is None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    if MVP_PROTOCOL_AVAILABLE and hasattr(_mvp_protocol, "build_fast_packet_v2"):
        try:
            _fast_seq = (_fast_seq + 1) & 0xFFFF
            payload = _mvp_protocol.build_fast_packet_v2(axes, _default_control_state, _fast_seq)
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
            payload = _mvp_protocol.build_udp_packet(axes, _default_control_state)
            if payload:
                try:
                    sock.sendto(payload, (host, port))
                except OSError:
                    return sock
            return sock
        except Exception:
            pass
    # Fallback: deterministic JSON for integration testing
    payload = json.dumps({"t": time.monotonic(), "axes": axes}).encode("utf-8")
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
