from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

from .canon_protocol import CMD_FOCUS_POS, CMD_IRIS_POS, CMD_ZOOM_POS, SUBCMD_C0, build_type_b
from .serial_worker import SerialWorker

try:
    import pygame

    PYGAME_OK = True
except Exception:
    pygame = None
    PYGAME_OK = False


@dataclass
class GamepadConfig:
    enabled: bool = True
    zoom_axis_index: int = 3
    focus_dec_button: int = 4
    focus_inc_button: int = 5
    iris_dec_button: int = 1
    iris_inc_button: int = 2
    zoom_deadband: float = 0.12
    zoom_max_counts_per_s: float = 18000.0
    focus_step: int = 250
    iris_step: int = 250
    button_repeat_hz: float = 10.0
    loop_hz: float = 40.0
    zoom_send_hz: float = 20.0
    debug_log_buttons: bool = False
    debug_log_zoom: bool = False


class GamepadRunner:
    def __init__(
        self,
        worker: SerialWorker,
        cfg: GamepadConfig,
        can_drive: Callable[[], bool],
        get_follow: Callable[[], Tuple[Optional[int], Optional[int], Optional[int]]],
        set_targets: Callable[[int, int, int], None],
        log: Callable[[str, str], None],
        send_axis: Optional[Callable[[str, int], None]] = None,
        target_max: int = 60000,
    ):
        self.worker = worker
        self.cfg = cfg
        self.can_drive = can_drive
        self.get_follow = get_follow
        self.set_targets = set_targets
        self.log = log
        self.send_axis = send_axis
        self.target_max = int(max(1, target_max))

        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._connected = False
        self._name = ""

        self.zoom_target = 30000
        self.focus_target = 30000
        self.iris_target = 30000

    def _send_zoom(self, value: int) -> None:
        if self.send_axis is not None:
            self.send_axis("zoom", int(value))
        else:
            self.worker.send(build_type_b(CMD_ZOOM_POS, SUBCMD_C0, int(value)))

    def _send_focus(self, value: int) -> None:
        if self.send_axis is not None:
            self.send_axis("focus", int(value))
        else:
            self.worker.send(build_type_b(CMD_FOCUS_POS, SUBCMD_C0, int(value)))

    def _send_iris(self, value: int) -> None:
        if self.send_axis is not None:
            self.send_axis("iris", int(value))
        else:
            self.worker.send(build_type_b(CMD_IRIS_POS, SUBCMD_C0, int(value)))

    def start(self) -> None:
        if not self.cfg.enabled:
            return
        if not PYGAME_OK:
            raise RuntimeError("pygame not available. Install with: pip install pygame")
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self.log("INFO", "Gamepad thread started.")

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.6)
        self._thread = None
        self._connected = False

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def set_deadband(self, deadband: float) -> None:
        self.cfg.zoom_deadband = float(deadband)

    def is_connected(self) -> bool:
        return self._connected

    def device_name(self) -> str:
        return self._name

    @staticmethod
    def _apply_deadband(x: float, deadband: float) -> float:
        ax = abs(x)
        if ax <= deadband:
            return 0.0
        sign = 1.0 if x >= 0 else -1.0
        scaled = (ax - deadband) / (1.0 - deadband)
        return sign * scaled

    def _loop(self) -> None:
        pygame.init()
        pygame.joystick.init()

        js = None
        last_time = time.time()
        zoom_send_period = 1.0 / max(1.0, self.cfg.zoom_send_hz)
        loop_period = 1.0 / max(5.0, self.cfg.loop_hz)
        last_zoom_send = 0.0
        repeat_period = 1.0 / max(1.0, self.cfg.button_repeat_hz)
        last_button_fire = {"focus_dec": 0.0, "focus_inc": 0.0, "iris_dec": 0.0, "iris_inc": 0.0}

        def held(button_index: int) -> bool:
            return bool(js.get_button(button_index)) if js else False

        def maybe_fire(key: str, now: float) -> bool:
            if now - last_button_fire[key] >= repeat_period:
                last_button_fire[key] = now
                return True
            return False

        while not self._stop.is_set():
            try:
                pygame.event.pump()

                if pygame.joystick.get_count() == 0:
                    if self._connected:
                        self._connected = False
                        self._name = ""
                        self.log("INFO", "Gamepad disconnected.")
                    time.sleep(0.2)
                    continue

                if not self._connected:
                    js = pygame.joystick.Joystick(0)
                    js.init()
                    self._connected = True
                    name = js.get_name()
                    self._name = name
                    self.log("INFO", f"Gamepad connected: {name}")

                    zf, ff, inf = self.get_follow()
                    if zf is not None:
                        self.zoom_target = int(zf)
                    if ff is not None:
                        self.focus_target = int(ff)
                    if inf is not None:
                        self.iris_target = int(inf)
                    self.set_targets(self.zoom_target, self.focus_target, self.iris_target)

                if self.cfg.debug_log_buttons:
                    pressed = []
                    for i in range(js.get_numbuttons()):
                        if js.get_button(i):
                            pressed.append(i)
                    if pressed:
                        self.log("INFO", f"GAMEPAD buttons down: {pressed}")

                now = time.time()
                dt = now - last_time
                last_time = now

                if not self.can_drive():
                    time.sleep(0.05)
                    continue

                raw = float(js.get_axis(self.cfg.zoom_axis_index))
                val = self._apply_deadband(raw, self.cfg.zoom_deadband)
                rate = val * self.cfg.zoom_max_counts_per_s
                self.zoom_target = int(max(0, min(self.target_max, self.zoom_target + rate * dt)))

                if (now - last_zoom_send) >= zoom_send_period:
                    self._send_zoom(self.zoom_target)
                    last_zoom_send = now
                    self.log("TX", f"GAMEPAD_ZOOM({self.zoom_target})")

                if held(self.cfg.focus_dec_button) and maybe_fire("focus_dec", now):
                    self.focus_target = max(0, self.focus_target - self.cfg.focus_step)
                    self._send_focus(self.focus_target)
                    self.log("TX", f"GAMEPAD_FOCUS({self.focus_target})")

                if held(self.cfg.focus_inc_button) and maybe_fire("focus_inc", now):
                    self.focus_target = min(self.target_max, self.focus_target + self.cfg.focus_step)
                    self._send_focus(self.focus_target)
                    self.log("TX", f"GAMEPAD_FOCUS({self.focus_target})")

                if held(self.cfg.iris_dec_button) and maybe_fire("iris_dec", now):
                    self.iris_target = max(0, self.iris_target - self.cfg.iris_step)
                    self._send_iris(self.iris_target)
                    self.log("TX", f"GAMEPAD_IRIS({self.iris_target})")

                if held(self.cfg.iris_inc_button) and maybe_fire("iris_inc", now):
                    self.iris_target = min(self.target_max, self.iris_target + self.cfg.iris_step)
                    self._send_iris(self.iris_target)
                    self.log("TX", f"GAMEPAD_IRIS({self.iris_target})")

                self.set_targets(self.zoom_target, self.focus_target, self.iris_target)
                time.sleep(loop_period)

            except Exception as e:
                self.log("ERR", f"Gamepad loop error: {e}")
                time.sleep(0.2)

        try:
            if js:
                js.quit()
        except Exception:
            pass
        pygame.joystick.quit()
        pygame.quit()
