from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class FujiBitCallbacks:
    log: Callable[[str, str], None]
    set_status: Callable[[str, str], None]
    send_connect: Callable[[], None]
    switch4_host: Callable[[], None]
    read_sw4: Callable[[], None]
    request_axis_position: Callable[[str], None]
    send_axis_control: Callable[[str, int], None]
    on_passed: Callable[[], None]
    on_failed: Callable[[str], None]


class FujiBitRunner:
    def __init__(self, callbacks: FujiBitCallbacks):
        self.callbacks = callbacks
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def start(self) -> None:
        self.stop()
        self._stop.clear()
        self.callbacks.set_status("running", "Starting Fuji BIT...")
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.3)
        self._thread = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _sleep_or_stop(self, seconds: float) -> bool:
        end = time.time() + seconds
        while time.time() < end:
            if self._stop.is_set():
                return False
            time.sleep(0.02)
        return True

    def _worker(self) -> None:
        try:
            steps: list[tuple[str, Callable[[], None], float]] = [
                ("CONNECT", self.callbacks.send_connect, 0.35),
                ("Switch4 Host", self.callbacks.switch4_host, 0.35),
                ("Read SW4", self.callbacks.read_sw4, 0.35),
                ("Read initial Iris", lambda: self.callbacks.request_axis_position("Iris"), 0.35),
                ("Read initial Zoom", lambda: self.callbacks.request_axis_position("Zoom"), 0.35),
                ("Read initial Focus", lambda: self.callbacks.request_axis_position("Focus"), 0.35),
            ]

            for axis in ("Iris", "Zoom", "Focus"):
                for label, value in (("MIN", 0), ("MAX", 65535), ("CENTER", 32768)):
                    steps.append((f"{axis} -> {label}", lambda a=axis, v=value: self.callbacks.send_axis_control(a, v), 0.5))
                    steps.append(
                        (f"{axis} position readback", lambda a=axis: self.callbacks.request_axis_position(a), 0.35)
                    )

            for name, fn, delay_s in steps:
                if self._stop.is_set():
                    return
                self.callbacks.set_status("running", f"BIT step: {name}")
                self.callbacks.log("INFO", f"BIT: {name}")
                fn()
                if not self._sleep_or_stop(delay_s):
                    return

            self.callbacks.set_status("pass", "Connection and control complete.")
            self.callbacks.log("INFO", "BIT complete.")
            self.callbacks.on_passed()
        except Exception as e:
            self.callbacks.set_status("fail", str(e))
            self.callbacks.log("ERR", f"BIT failed: {e}")
            self.callbacks.on_failed(str(e))
