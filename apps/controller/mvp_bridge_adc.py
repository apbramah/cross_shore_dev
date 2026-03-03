"""
Parallel ADC bridge entrypoint. Startup and orchestration for ingest,
shaping, and output loops. Launch semantics are separate from mvp_bridge.py.
See ADC_BRIDGE_INTERFACE.md and the ADC Bridge Pivot Plan.
"""

from __future__ import annotations

import argparse
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

        while not stop.is_set() and port and getattr(port, "is_open", lambda: False)():
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
) -> None:
    """Background thread: consume shaped axes from queue, send fast/slow UDP."""
    sock = None
    last_fast = 0.0
    last_slow = 0.0
    current_axes: dict[str, Any] | None = None
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
        if now - last_slow >= slow_interval_s:
            send_slow(current_axes, host, slow_port, sock)
            last_slow = now
        time.sleep(0.001)


def run_bridge(
    port: str | None = None,
    host: str = DEFAULT_HEAD_ADDR,
    fast_port: int = DEFAULT_FAST_PORT,
    slow_port: int = DEFAULT_SLOW_PORT,
    fast_hz: float = 50.0,
    slow_hz: float = 10.0,
    profile_dir: str | None = None,
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

    ingest_thread = threading.Thread(
        target=_run_ingest_loop,
        args=(port, state, ingest_state, sample_queue, stop),
        daemon=True,
    )
    shape_thread = threading.Thread(target=shape_worker, daemon=True)
    output_thread = threading.Thread(
        target=_run_output_loop,
        args=(state, shaped_queue, host, fast_port, slow_port, fast_interval_s, slow_interval_s, stop),
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
    parser.add_argument("--host", default=DEFAULT_HEAD_ADDR, help="Head UDP host")
    parser.add_argument("--fast-port", type=int, default=DEFAULT_FAST_PORT, help="Fast channel port")
    parser.add_argument("--slow-port", type=int, default=DEFAULT_SLOW_PORT, help="Slow channel port")
    parser.add_argument("--fast-hz", type=float, default=50.0, help="Fast send rate Hz")
    parser.add_argument("--slow-hz", type=float, default=10.0, help="Slow send rate Hz")
    parser.add_argument("--profile-dir", default=None, help="Directory for adc_bridge_profile.json")
    args = parser.parse_args()
    run_bridge(
        port=args.port,
        host=args.host,
        fast_port=args.fast_port,
        slow_port=args.slow_port,
        fast_hz=args.fast_hz,
        slow_hz=args.slow_hz,
        profile_dir=args.profile_dir,
    )


if __name__ == "__main__":
    main()
