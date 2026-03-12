from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable, Optional

from .sony_protocol import (
    build_cam_ae_manual,
    build_address_set,
    build_cam_b_gain_direct,
    build_cam_iris_direct,
    build_cam_r_gain_direct,
    build_cam_saturation,
    build_cam_version_inquiry,
    build_cam_wb_manual,
    build_interface_clear,
)


@dataclass
class SonyBitCallbacks:
    log: Callable[[str, str], None]
    set_status: Callable[[str, str], None]
    get_mode: Callable[[], str]
    get_targets: Callable[[], dict[str, int]]
    send_with_optional_wait: Callable[[bytes, str, float, bool], bool]
    inquire_value: Callable[[str, float], Optional[int]]
    on_passed: Callable[[], None]
    on_failed: Callable[[str], None]


class SonyBitRunner:
    def __init__(self, callbacks: SonyBitCallbacks):
        self.callbacks = callbacks
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def start(self) -> None:
        self.stop()
        self._stop.clear()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.3)
        self._thread = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run_step(self, tx: bytes, label: str, timeout_s: float, wait_for_response: bool) -> None:
        if self._stop.is_set():
            raise RuntimeError("Stopped")
        ok = self.callbacks.send_with_optional_wait(tx, label, timeout_s, wait_for_response)
        if not ok:
            raise RuntimeError(f"{label}: no valid response")

    def _worker(self) -> None:
        try:
            mode = self.callbacks.get_mode()
            mode_is_bidirectional = mode.upper().startswith("A")
            mode_name = "Mode A (bidirectional)" if mode_is_bidirectional else "Mode B (no-wait stream)"

            self.callbacks.set_status("running", f"Running Sony comms proof in {mode_name}...")
            self.callbacks.log("INFO", f"Sony BIT start: {mode_name}")

            if mode_is_bidirectional:
                self._run_step(build_interface_clear(), "IF_CLEAR", 1.2, wait_for_response=False)
                self._run_step(build_address_set(1), "ADDRESS_SET", 1.2, wait_for_response=False)
                self._run_step(build_cam_version_inquiry(), "VERSION_INQ", 1.5, wait_for_response=True)
                # Required for direct Iris / RGain / BGain control paths.
                self._run_step(build_cam_ae_manual(), "AE_MANUAL", 1.5, wait_for_response=True)
                self._run_step(build_cam_wb_manual(), "WB_MANUAL", 1.5, wait_for_response=True)

            targets = self.callbacks.get_targets()
            steps = [
                ("IRIS", build_cam_iris_direct(targets.get("iris", 0x08))),
                ("SATURATION", build_cam_saturation(targets.get("saturation", 0x08))),
                ("RED", build_cam_r_gain_direct(targets.get("red", 0x80))),
                ("BLUE", build_cam_b_gain_direct(targets.get("blue", 0x80))),
            ]
            for name, pkt in steps:
                self.callbacks.set_status("running", f"Proving control: {name}...")
                self._run_step(pkt, f"BIT_{name}", 1.5, wait_for_response=mode_is_bidirectional)
                if mode_is_bidirectional:
                    self.callbacks.set_status("running", f"Verifying readback: {name}...")
                    got = self.callbacks.inquire_value(name.lower(), 1.5)
                    if got is None:
                        raise RuntimeError(f"{name}: inquiry readback missing")
                    expected = int(targets.get(name.lower(), 0))
                    if name == "IRIS":
                        # FCB-ES8230 reports iris in camera position scale; it does not
                        # track direct command value 1:1, so command ACK + valid inquiry
                        # is treated as pass for comms/control proof.
                        self.callbacks.log("INFO", f"{name} readback present: {got} (camera scale)")
                    else:
                        tol = 2 if name == "SATURATION" else 3
                        if abs(got - expected) > tol:
                            raise RuntimeError(f"{name}: readback {got} != expected {expected}")
                        self.callbacks.log("INFO", f"{name} readback ok: {got}")

            self.callbacks.set_status("pass", f"Sony VISCA comms/control complete ({mode_name}).")
            self.callbacks.on_passed()
        except Exception as e:
            self.callbacks.set_status("fail", str(e))
            self.callbacks.log("ERR", f"Sony BIT failed: {e}")
            self.callbacks.on_failed(str(e))
