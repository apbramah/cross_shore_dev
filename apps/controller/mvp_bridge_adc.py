"""
Parallel ADC bridge entrypoint. Startup and orchestration for ingest,
shaping, and output loops. Launch semantics are separate from mvp_bridge.py.
See ADC_BRIDGE_INTERFACE.md and the ADC Bridge Pivot Plan.
"""

from __future__ import annotations

import argparse
import os
import queue
import threading
import time
from typing import Any

from mvp_bridge_adc_ingest import (
    IngestState,
    open_cdc_port,
    read_frames,
)
from mvp_bridge_adc_state import ADCBridgeState
from mvp_bridge_adc_shape import shape_sample, neutral_axes
from mvp_bridge_adc_output import send_fast, send_slow, DEFAULT_FAST_PORT, DEFAULT_SLOW_PORT, DEFAULT_HEAD_ADDR

try:
    import mvp_protocol
    MVP_PROTOCOL_AVAILABLE = True
except ImportError:
    mvp_protocol = None
    MVP_PROTOCOL_AVAILABLE = False


def _port_is_open(port) -> bool:
    """True if port exists and is open; works whether is_open is a property (bool) or method."""
    if port is None:
        return False
    v = getattr(port, "is_open", None)
    if v is None:
        return True
    return v() if callable(v) else bool(v)


def _resolve_head_host_port(host: str, fast_port: int, slow_port: int, head_index: int = 0):
    """If host is default localhost and we have heads.json, use head at head_index IP and ports."""
    if host != DEFAULT_HEAD_ADDR or not MVP_PROTOCOL_AVAILABLE:
        return host, fast_port, slow_port
    try:
        heads = mvp_protocol.load_heads()
        if not heads or not (0 <= head_index < len(heads)):
            return host, fast_port, slow_port
        h = heads[head_index]
        ip = h.get("ip")
        if not ip:
            return host, fast_port, slow_port
        fp = int(h.get("port_fast", h.get("port", mvp_protocol.FAST_PORT)))
        sp = int(h.get("port_slow_cmd", mvp_protocol.SLOW_CMD_PORT))
        return ip, fp, sp
    except Exception:
        return host, fast_port, slow_port


def _run_ingest_loop(
    port_name: str | None,
    state: ADCBridgeState,
    ingest_state: IngestState,
    sample_queue: queue.Queue[dict[str, Any]],
    stop: threading.Event,
) -> None:
    """Background thread: open CDC, read frames, push samples to queue; reconnect with backoff."""
    backoff_s = 0.5
    max_backoff = 10.0
    while not stop.is_set():
        port = open_cdc_port(port_name)
        if port is None:
            ingest_state.record_reconnect()
            state.update_health(reconnect_count=ingest_state.reconnect_count)
            time.sleep(backoff_s)
            backoff_s = min(backoff_s * 1.5, max_backoff)
            continue
        backoff_s = 0.5
        ingest_state.record_reconnect()
        state.update_health(
            last_seq=ingest_state.last_seq,
            seq_gaps=ingest_state.seq_gaps,
            last_rx_monotonic_s=ingest_state.last_rx_monotonic_s,
            frame_age_ms=ingest_state.frame_age_ms,
            parse_errors=ingest_state.parse_errors,
            reconnect_count=ingest_state.reconnect_count,
            ingest_ok=ingest_state.ingest_ok,
        )

        def on_sample(sample: dict[str, Any]) -> None:
            try:
                sample_queue.put_nowait(sample)
            except queue.Full:
                pass
            snap = ingest_state.snapshot()
            state.update_health(**snap)

        while not stop.is_set() and port and _port_is_open(port):
            read_frames(port, ingest_state, state.get_stale_timeout_ms(), on_sample)
            ingest_state.update_age(state.get_stale_timeout_ms())
            time.sleep(0.001)
        try:
            port.close()
        except Exception:
            pass


def _run_output_loop(
    state: ADCBridgeState,
    shaped_queue: queue.Queue[dict[str, Any] | None],
    host: str,
    fast_port: int,
    slow_port: int,
    fast_interval_s: float,
    slow_interval_s: float,
    stop: threading.Event,
    fast_debug: bool = False,
) -> None:
    """Background thread: consume shaped axes from queue, send fast/slow UDP."""
    sock = None
    last_fast = 0.0
    last_slow = 0.0
    current_axes: dict[str, Any] | None = None
    fast_send_count = 0
    last_fast_log = 0.0
    FAST_DEBUG_INTERVAL_S = 5.0
    while not stop.is_set():
        try:
            current_axes = shaped_queue.get(timeout=0.02)
        except queue.Empty:
            pass
        if current_axes is None:
            current_axes = neutral_axes()
        now = time.monotonic()
        if now - last_fast >= fast_interval_s:
            sock = send_fast(current_axes, host, fast_port, sock)
            last_fast = now
            fast_send_count += 1
        if now - last_slow >= slow_interval_s:
            send_slow(current_axes, host, slow_port, sock)
            last_slow = now
        if fast_debug and now - last_fast_log >= FAST_DEBUG_INTERVAL_S:
            last_fast_log = now
            ax = current_axes or {}
            r = {k: (ax.get(k), ax.get(k)) for k in ("X", "Y", "Z", "Xrotate", "Yrotate", "Zrotate")}
            print(f"[FAST_DEBUG] sends={fast_send_count} axes={r}")
        time.sleep(0.001)


def run_bridge(
    port: str | None = None,
    host: str = DEFAULT_HEAD_ADDR,
    fast_port: int = DEFAULT_FAST_PORT,
    slow_port: int = DEFAULT_SLOW_PORT,
    fast_hz: float = 50.0,
    slow_hz: float = 10.0,
    profile_dir: str | None = None,
    fast_debug: bool = False,
) -> None:
    """Run ingest + shaping + output in threads. Blocks until KeyboardInterrupt."""
    state = ADCBridgeState(profile_dir=profile_dir)
    ingest_state = IngestState()
    sample_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=256)
    shaped_queue: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=8)
    stop = threading.Event()

    filter_state: dict[str, float] = {}
    last_shape_time = 0.0

    def shape_worker() -> None:
        nonlocal last_shape_time
        while not stop.is_set():
            try:
                raw = sample_queue.get(timeout=0.02)
            except queue.Empty:
                # Push latest shaped or neutral when stale
                state.update_health(**ingest_state.snapshot())
                if not ingest_state.ingest_ok:
                    try:
                        shaped_queue.put_nowait(neutral_axes())
                    except queue.Full:
                        pass
                continue
            shaped, last_shape_time = shape_sample(raw, state, filter_state, last_shape_time)
            try:
                shaped_queue.put_nowait(shaped)
            except queue.Full:
                pass

    fast_interval_s = 1.0 / fast_hz if fast_hz > 0 else 0.02
    slow_interval_s = 1.0 / slow_hz if slow_hz > 0 else 0.1
    use_fast_debug = fast_debug or os.environ.get("MVP_FAST_DEBUG", "").strip().lower() in ("1", "true", "yes")

    ingest_thread = threading.Thread(
        target=_run_ingest_loop,
        args=(port, state, ingest_state, sample_queue, stop),
        daemon=True,
    )
    shape_thread = threading.Thread(target=shape_worker, daemon=True)
    output_thread = threading.Thread(
        target=_run_output_loop,
        args=(state, shaped_queue, host, fast_port, slow_port, fast_interval_s, slow_interval_s, stop, use_fast_debug),
        daemon=True,
    )
    ingest_thread.start()
    shape_thread.start()
    output_thread.start()
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        stop.set()
    ingest_thread.join(timeout=2.0)
    shape_thread.join(timeout=2.0)
    output_thread.join(timeout=2.0)


def main() -> None:
    parser = argparse.ArgumentParser(description="ADC bridge: Teensy CDC -> shape -> UDP to head_eng")
    parser.add_argument("--port", "-p", default=None, help="CDC serial port (e.g. COM3, /dev/ttyACM0)")
    parser.add_argument(
        "--host",
        default=DEFAULT_HEAD_ADDR,
        help="Head UDP host (default: first head in heads.json if present, else 127.0.0.1)",
    )
    parser.add_argument("--fast-port", type=int, default=DEFAULT_FAST_PORT, help="Fast channel port")
    parser.add_argument("--slow-port", type=int, default=DEFAULT_SLOW_PORT, help="Slow channel port")
    parser.add_argument("--fast-hz", type=float, default=50.0, help="Fast send rate Hz")
    parser.add_argument("--slow-hz", type=float, default=10.0, help="Slow send rate Hz")
    parser.add_argument("--profile-dir", default=None, help="Directory for adc_bridge_profile.json")
    parser.add_argument(
        "--head-index",
        type=int,
        default=0,
        help="Index of head in heads.json when not passing --host (default: 0)",
    )
    parser.add_argument(
        "--fast-debug",
        action="store_true",
        help="Enable low-rate fast-path logs (send count, axes). Also set by MVP_FAST_DEBUG=1.",
    )
    args = parser.parse_args()
    host, fast_port, slow_port = _resolve_head_host_port(
        args.host, args.fast_port, args.slow_port, args.head_index
    )
    if host != DEFAULT_HEAD_ADDR:
        print(f"Using head: {host} (fast:{fast_port} slow:{slow_port})")
    run_bridge(
        port=args.port,
        host=host,
        fast_port=fast_port,
        slow_port=slow_port,
        fast_hz=args.fast_hz,
        slow_hz=args.slow_hz,
        profile_dir=args.profile_dir,
        fast_debug=args.fast_debug,
    )


if __name__ == "__main__":
    main()
