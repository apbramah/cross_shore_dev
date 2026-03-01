from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

from .canon_protocol import (
    CMD_FOCUS_POS,
    CMD_IRIS_POS,
    CMD_ZOOM_POS,
    CTRL_CMD,
    FINISH_INIT,
    LENS_NAME_REQ,
    SCMD_FOCUS_SWITCH,
    SCMD_IRIS_SWITCH,
    SCMD_ZOOM_SWITCH,
    SRC_PC,
    SUBCMD_C0,
    build_type_b,
    build_type_c_switch,
    hexdump,
)
from .keepalive import KeepaliveRunner
from .serial_worker import SerialWorker


@dataclass
class BitCallbacks:
    log: Callable[[str, str], None]
    set_status: Callable[[str, str], None]
    on_lens_id: Callable[[str], None]
    on_targets: Callable[[int, int, int], None]
    on_passed: Callable[[], None]
    on_failed: Callable[[str], None]


class BitRunner:
    def __init__(self, worker: SerialWorker, rx_frame_q: "queue.Queue[bytes]", callbacks: BitCallbacks):
        self.worker = worker
        self.rx_frame_q = rx_frame_q
        self.callbacks = callbacks

        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

        self.zoom_follow: Optional[int] = None
        self.focus_follow: Optional[int] = None
        self.iris_follow: Optional[int] = None
        self.lens_name = ""

        self.keepalive = KeepaliveRunner(worker, interval_s=0.5, frame=CTRL_CMD, log=self.callbacks.log)

    def start(self) -> None:
        self.stop()
        self.callbacks.set_status("running", "Waiting 10s after power-on, then init + take control + sweep axes...")
        self._stop.clear()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.keepalive.stop()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.3)
        self._thread = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def update_follow(self, cmd: int, value: int) -> None:
        if cmd == CMD_ZOOM_POS:
            self.zoom_follow = value
        elif cmd == CMD_FOCUS_POS:
            self.focus_follow = value
        elif cmd == CMD_IRIS_POS:
            self.iris_follow = value

    def update_lens_name(self, name: str) -> None:
        self.lens_name = name
        self.callbacks.on_lens_id(name)

    def _drain_rx_frames(self) -> None:
        try:
            while True:
                self.rx_frame_q.get_nowait()
        except queue.Empty:
            return

    def _send_and_wait_prefix(self, tx: bytes, rx_prefix: bytes, timeout_s: float) -> Optional[bytes]:
        self._drain_rx_frames()
        self.worker.send(tx)
        self.callbacks.log("TX", f"BIT_TX: {hexdump(tx)}")
        end = time.time() + timeout_s
        while time.time() < end and not self._stop.is_set():
            try:
                f = self.rx_frame_q.get(timeout=0.05)
            except queue.Empty:
                continue
            if f.startswith(rx_prefix):
                return f
        return None

    def _axis_set_source_pc(self, axis_name: str, switch_scmd: int) -> bool:
        pkt = build_type_c_switch(switch_scmd, SRC_PC)
        _ = self._send_and_wait_prefix(pkt, b"\xBE\x85", timeout_s=0.7)
        self.callbacks.log("INFO", f"BIT: {axis_name} source -> PC")
        return True

    def _axis_set_position(self, axis_name: str, motion_cmd: int, value: int) -> bool:
        pkt = build_type_b(motion_cmd, SUBCMD_C0, value)
        r = self._send_and_wait_prefix(pkt, bytes([motion_cmd, 0xC0]), timeout_s=1.2)
        if not r:
            return False

        follow = None
        if axis_name == "Zoom":
            follow = self.zoom_follow
        elif axis_name == "Focus":
            follow = self.focus_follow
        elif axis_name == "Iris":
            follow = self.iris_follow
        self.callbacks.log("INFO", f"BIT: {axis_name} target={value} follow={follow}")
        return True

    def _wait_follow_near(self, axis_name: str, target: int, tol: int = 600, timeout_s: float = 6.0) -> bool:
        end = time.time() + timeout_s
        while time.time() < end and not self._stop.is_set():
            if axis_name == "Zoom":
                cur = self.zoom_follow
            elif axis_name == "Focus":
                cur = self.focus_follow
            else:
                cur = self.iris_follow
            if cur is not None and abs(cur - target) <= tol:
                return True
            time.sleep(0.05)
        return False

    def _worker(self) -> None:
        try:
            for i in range(10):
                if self._stop.is_set():
                    return
                self.callbacks.set_status("running", f"Waiting after power-on... {10 - i}s")
                time.sleep(1.0)

            if self._stop.is_set():
                return

            self.callbacks.set_status("running", "Init: CTRL_CMD (x3)...")
            got_echo = False
            for _ in range(3):
                r = self._send_and_wait_prefix(CTRL_CMD, b"\x80\xC6\xBF", timeout_s=0.5)
                if r:
                    got_echo = True
                    break
                time.sleep(0.1)

            self.callbacks.log("INFO", f"BIT: CTRL_CMD echo: {'YES' if got_echo else 'NO'}")
            if not got_echo:
                self.callbacks.log("WARN", "No CTRL_CMD echo (continuing anyway)")

            self.callbacks.set_status("running", "Init: Lens name request...")
            r = self._send_and_wait_prefix(LENS_NAME_REQ, b"\xBE\x80\x81", timeout_s=2.0)
            if not r:
                raise RuntimeError("No lens name response")
            time.sleep(0.1)
            self.callbacks.log("INFO", f"BIT: Lens ID: {self.lens_name or '(unknown)'}")

            self.callbacks.set_status("running", "Init: Finish initialization...")
            r = self._send_and_wait_prefix(FINISH_INIT, b"\x86\xC0", timeout_s=2.0)
            if not r:
                raise RuntimeError("No FINISH_INIT answer")

            self.callbacks.set_status("running", "Starting keepalive and taking PC control...")
            self.keepalive.start()

            self._axis_set_source_pc("Zoom", SCMD_ZOOM_SWITCH)
            self._axis_set_source_pc("Focus", SCMD_FOCUS_SWITCH)
            self._axis_set_source_pc("Iris", SCMD_IRIS_SWITCH)

            def sweep(axis_name: str, cmd: int) -> None:
                self.callbacks.set_status("running", f"BIT sweep: {axis_name} -> MIN")
                if not self._axis_set_position(axis_name, cmd, 0):
                    raise RuntimeError(f"{axis_name}: no follow response (min)")
                self._wait_follow_near(axis_name, 0)

                self.callbacks.set_status("running", f"BIT sweep: {axis_name} -> MAX")
                if not self._axis_set_position(axis_name, cmd, 60000):
                    raise RuntimeError(f"{axis_name}: no follow response (max)")
                self._wait_follow_near(axis_name, 60000)

                self.callbacks.set_status("running", f"BIT sweep: {axis_name} -> CENTER")
                if not self._axis_set_position(axis_name, cmd, 30000):
                    raise RuntimeError(f"{axis_name}: no follow response (center)")
                self._wait_follow_near(axis_name, 30000)

            sweep("Zoom", CMD_ZOOM_POS)
            sweep("Focus", CMD_FOCUS_POS)
            sweep("Iris", CMD_IRIS_POS)

            z = int(self.zoom_follow if self.zoom_follow is not None else 30000)
            f = int(self.focus_follow if self.focus_follow is not None else 30000)
            i = int(self.iris_follow if self.iris_follow is not None else 30000)
            self.callbacks.on_targets(z, f, i)

            lens_id = self.lens_name or "(unknown lens)"
            self.callbacks.set_status("pass", f"Connection and control complete. Lens ID: {lens_id}")
            self.callbacks.on_passed()

        except Exception as e:
            self.callbacks.set_status("fail", str(e))
            self.callbacks.log("ERR", f"BIT failed: {e}")
            self.callbacks.on_failed(str(e))
