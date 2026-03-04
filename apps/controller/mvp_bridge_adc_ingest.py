"""
CDC transport ingest for the ADC bridge: device discovery, open/reconnect,
framed ADC parse, timestamping, frame-age health. Outputs normalized raw
axis sample for downstream shaping. See ADC_BRIDGE_INTERFACE.md.
"""

from __future__ import annotations

import time
import threading
from typing import Any, Callable

try:
    import serial
    import serial.tools.list_ports
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False

AXIS_KEYS = ("X", "Y", "Z", "Xrotate", "Yrotate", "Zrotate")
FRAME_PREFIX = "ADCv1,"
ADC_MAX = 4095
ADC_MIN = 0


def parse_frame(line: str) -> dict[str, Any] | None:
    """
    Parse one ADCv1 line. Returns dict with seq, teensy_us, and axis keys
    (normalized to [0, 4095] ints), or None on parse failure.
    """
    line = line.strip()
    if not line.startswith(FRAME_PREFIX):
        return None
    rest = line[len(FRAME_PREFIX):]
    parts = rest.split(",")
    if len(parts) != 8:
        return None
    try:
        seq = int(parts[0])
        teensy_us = int(parts[1])
        raw = [int(parts[i]) for i in range(2, 8)]
    except ValueError:
        return None
    out: dict[str, Any] = {"seq": seq, "teensy_us": teensy_us}
    for i, k in enumerate(AXIS_KEYS):
        v = raw[i] if i < len(raw) else 2048
        out[k] = max(ADC_MIN, min(ADC_MAX, v))
    return out


class IngestState:
    """Mutable ingest health state; can be wired to ADCBridgeState."""

    def __init__(self, on_health: Callable[[], None] | None = None):
        self.last_seq: int | None = None
        self.seq_gaps = 0
        self.last_rx_monotonic_s: float | None = None
        self.frame_age_ms: float | None = None
        self.parse_errors = 0
        self.range_warnings = 0
        self.reconnect_count = 0
        self.ingest_ok = False
        self._lock = threading.Lock()
        self._on_health = on_health

    def _notify_health(self) -> None:
        if self._on_health:
            self._on_health()

    def record_frame(self, sample: dict[str, Any]) -> None:
        with self._lock:
            seq = sample.get("seq", 0)
            if self.last_seq is not None and seq != (self.last_seq + 1) % (1 << 32):
                self.seq_gaps += 1
            self.last_seq = seq
            now = time.monotonic()
            self.last_rx_monotonic_s = now
            self.frame_age_ms = 0.0
            self.ingest_ok = True
        self._notify_health()

    def record_parse_error(self) -> None:
        with self._lock:
            self.parse_errors += 1
        self._notify_health()

    def record_range_warning(self) -> None:
        with self._lock:
            self.range_warnings += 1
        self._notify_health()

    def record_reconnect(self) -> None:
        with self._lock:
            self.reconnect_count += 1
        self._notify_health()

    def update_age(self, stale_timeout_ms: float) -> None:
        with self._lock:
            if self.last_rx_monotonic_s is None:
                self.frame_age_ms = None
                self.ingest_ok = False
            else:
                self.frame_age_ms = (time.monotonic() - self.last_rx_monotonic_s) * 1000.0
                self.ingest_ok = self.frame_age_ms <= stale_timeout_ms
        self._notify_health()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "last_seq": self.last_seq,
                "seq_gaps": self.seq_gaps,
                "last_rx_monotonic_s": self.last_rx_monotonic_s,
                "frame_age_ms": self.frame_age_ms,
                "parse_errors": self.parse_errors,
                "reconnect_count": self.reconnect_count,
                "ingest_ok": self.ingest_ok,
            }


def open_cdc_port(port: str | None = None, baud: int = 115200):  # noqa: ANN201
    """Open serial port. If port is None, try to find Teensy CDC by VID/PID when available."""
    if not SERIAL_AVAILABLE:
        return None
    if port:
        try:
            return serial.Serial(port, baud, timeout=0, write_timeout=1)
        except Exception:
            return None
    # Optional: list by VID/PID (Teensy USB serial). For now return None so caller passes port.
    for p in serial.tools.list_ports.comports():
        if p.vid is not None and p.pid is not None:
            # Common Teensy 4.x CDC VID/PID can be used here when defined
            try:
                return serial.Serial(p.device, baud, timeout=0, write_timeout=1)
            except Exception:
                continue
    return None


def _is_port_open(port) -> bool:
    """True if port exists and is open; works whether is_open is a property (bool) or method."""
    if port is None:
        return False
    v = getattr(port, "is_open", None)
    if v is None:
        return True
    return v() if callable(v) else bool(v)


def read_frames(port, state: IngestState, stale_timeout_ms: float, on_sample: Callable[[dict[str, Any]], None]) -> None:
    """
    Read lines from port, parse ADCv1 frames, update state, call on_sample for each valid frame.
    Caller should run this in a loop with reconnect/backoff when port is None or closed.
    """
    if not port or not _is_port_open(port):
        return
    try:
        line = port.readline()
    except Exception:
        state.record_parse_error()
        return
    if not line:
        state.update_age(stale_timeout_ms)
        return
    try:
        text = line.decode("utf-8", errors="replace")
    except Exception:
        state.record_parse_error()
        return
    sample = parse_frame(text)
    if sample is None:
        state.record_parse_error()
        return
    state.record_frame(sample)
    on_sample(sample)
