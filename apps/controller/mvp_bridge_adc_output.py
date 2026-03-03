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


def axes_to_list(axes: dict[str, Any]) -> list[float]:
    """Order axes as X, Y, Z, Xrotate, Yrotate, Zrotate for protocol compatibility."""
    return [float(axes.get(k, 0.0)) for k in AXIS_KEYS]


def send_fast(axes: dict[str, Any], host: str, port: int, sock: socket.socket | None = None) -> socket.socket | None:
    """Send fast path. Reuses mvp_protocol.build_fast_packet_v2 / build_udp_packet if available."""
    if MVP_PROTOCOL_AVAILABLE and hasattr(_mvp_protocol, "build_fast_packet_v2"):
        try:
            payload = _mvp_protocol.build_fast_packet_v2(axes_to_list(axes))
            if payload and sock:
                sock.sendto(payload, (host, port))
            return sock
        except Exception:
            pass
    if MVP_PROTOCOL_AVAILABLE and hasattr(_mvp_protocol, "build_udp_packet"):
        try:
            payload = _mvp_protocol.build_udp_packet(axes_to_list(axes))
            if payload and sock:
                sock.sendto(payload, (host, port))
            return sock
        except Exception:
            pass
    # Fallback: deterministic JSON for integration testing
    payload = json.dumps({"t": time.monotonic(), "axes": axes}).encode("utf-8")
    if sock is None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(payload, (host, port))
    return sock


def send_slow(axes: dict[str, Any], host: str, port: int, sock: socket.socket | None = None) -> socket.socket | None:
    """Send slow path when protocol provides slow packet builder."""
    if MVP_PROTOCOL_AVAILABLE and hasattr(_mvp_protocol, "build_slow_packet"):
        try:
            payload = _mvp_protocol.build_slow_packet(axes_to_list(axes))
            if payload and sock:
                sock.sendto(payload, (host, port))
            return sock
        except Exception:
            pass
    # Reuse fast UDP socket for slow if no dedicated slow builder
    return send_fast(axes, host, port, sock)
