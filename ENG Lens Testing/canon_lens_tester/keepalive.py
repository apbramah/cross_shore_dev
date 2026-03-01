from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from .canon_protocol import CTRL_CMD, hexdump
from .serial_worker import SerialWorker


class KeepaliveRunner:
    def __init__(
        self,
        worker: SerialWorker,
        interval_s: float = 0.5,
        frame: bytes = CTRL_CMD,
        log: Optional[Callable[[str, str], None]] = None,
    ):
        self.worker = worker
        self.interval_s = interval_s
        self.frame = frame
        self.log = log or (lambda _tag, _msg: None)

        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._ka_log_tick = 0

    def start(self) -> None:
        if not self.worker.is_open():
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._ka_log_tick = 0
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self.log("INFO", f"Keepalive enabled: CTRL_CMD every {self.interval_s:.1f}s")

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.3)
        self._thread = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                if self.worker.is_open():
                    self.worker.send(self.frame)
                    self._ka_log_tick += 1
                    if self._ka_log_tick % 10 == 0:
                        self.log("TX", f"KEEPALIVE: {hexdump(self.frame)}")
            except Exception as e:
                self.log("ERR", f"Keepalive send failed: {e}")
                break
            time.sleep(self.interval_s)
