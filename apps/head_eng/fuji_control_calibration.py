"""
Standalone Fujinon bench calibration/sweep utility.

This script intentionally does not depend on runtime lens-controller logic.
It reuses protocol and transport helpers, forces SW4 ownership on PC, reads lens
ID, then continuously sweeps zoom/focus/iris for bench validation.
"""

import socket
import struct

from fuji_protocol import (
    FUJI_BAUD,
    FUJI_BITS,
    FUJI_PARITY,
    FUJI_STOP,
    FUNC_CONNECT,
    FUNC_LENS_NAME_1,
    FUNC_LENS_NAME_2,
    FUNC_IRIS_CONTROL,
    FUNC_FOCUS_CONTROL,
    FUNC_ZOOM_CONTROL,
    FUNC_SWITCH_4_POSITION,
    SW4_HOST_ALL,
    build_connect,
    build_lens_name_request,
    build_focus_control,
    build_iris_control,
    build_switch4_control,
    build_switch4_position_request,
    build_zoom_control,
    checksum,
    decode_lens_name_chunk,
)
from lens_serial import DEFAULT_RX_PIN, DEFAULT_TX_PIN, DEFAULT_UART_ID, LensSerial


# UART pin config for bench use.
UART_ID = DEFAULT_UART_ID
UART_TX_PIN = DEFAULT_TX_PIN
UART_RX_PIN = DEFAULT_RX_PIN

# Sweep endpoints and timing.
AXIS_MIN = 0
AXIS_MAX = 65535
TRAVEL_MS = 5000
HOLD_MS = 5000
UPDATE_MS = 50
DRIVE_MODE = "sweep"  # "sweep", "stress", or "udp_gamepad"

# Deterministic stress pattern tuning.
STRESS_ZOOM_PERIOD_MS = 3200
STRESS_FOCUS_PERIOD_MS = 4700
STRESS_IRIS_PERIOD_MS = 6100
STRESS_NOISE_AMPLITUDE = 2600
STRESS_STEP_AMPLITUDE = 9000
STRESS_STEP_PERIOD_MS = 1400

# UDP/gamepad ingest mode (mirrors controller fast packet formats).
GAMEPAD_UDP_PORT = 8888
PKT_MAGIC = 0xDE
PKT_VER = 0x01
PKT_FAST_CTRL = 0x10
ZOOM_DELTA_SCALE = 12
ZOOM_DEADBAND = 1

# Ownership target:
# SW4 bit0=focus, bit1=zoom, bit2=iris; 0=PC(host), 1=local.
# For this 3-axis sweep test, keep all three axes on host control.
SW4_DESIRED_BITS = SW4_HOST_ALL  # 0xF8

# Optional command smoothing (applied to each axis output).
FILTER_ENABLE = True
AXIS_FILTER_ENABLE = {"zoom": True, "focus": False, "iris": True}
AXIS_FILTER_CONFIG = {
    # lp_num/lp_den: integer low-pass blend toward trajectory target.
    # max_rate: max output change per second (u16 units/s).
    # deadband: hold output when near target to avoid chatter.
    # min_step: minimum commanded step once moving.
    "zoom": {"lp_num": 1, "lp_den": 3, "max_rate": 22000, "deadband": 12, "min_step": 6},
    "focus": {"lp_num": 1, "lp_den": 3, "max_rate": 18000, "deadband": 12, "min_step": 6},
    "iris": {"lp_num": 1, "lp_den": 3, "max_rate": 14000, "deadband": 12, "min_step": 4},
}

# Link/watchdog timing.
CONNECT_RETRIES = 3
CONNECT_WAIT_MS = 1200
NAME_WAIT_MS = 500
SW4_POLL_MS = 300
CONNECT_KEEPALIVE_MS = 1000
# If any host control demand was sent recently, skip connect keepalive.
DEMAND_ACTIVE_WINDOW_MS = 800

# Protocol pacing experiment mode:
# - burst: current behavior, no ACK pacing
# - strict: wait ACK for each zoom command, fail on timeout
# - semi_strict: wait ACK, but continue on timeout
TX_MODE = "burst"
COMMAND_ACK_TIMEOUT_MS = 15
FAIL_ON_COMMAND_TIMEOUT = True
FAIL_ON_SW4_MISMATCH = True
RECOVER_ON_SW4_MISMATCH = True
MAX_SW4_RECOVERY_ATTEMPTS = 1
EVENT_RING_SIZE = 200
ACK_STATS_PRINT_MS = 10000
# Set True to log Fuji UART connection: FOCUS_CONTROL TX, SW4 poll/readback (for focus/debug).
FUJI_CONN_DEBUG = False


def _ticks_ms():
    import time

    if hasattr(time, "ticks_ms"):
        return time.ticks_ms()
    return int(time.time() * 1000)


def _ticks_diff(a, b):
    import time

    if hasattr(time, "ticks_diff"):
        return time.ticks_diff(a, b)
    return a - b


def _sleep_ms(ms):
    import time

    time.sleep(ms / 1000.0)


def _clamp_u16(v):
    if v < 0:
        return 0
    if v > 0xFFFF:
        return 0xFFFF
    return int(v)


def _lerp_u16(start_value, end_value, elapsed_ms, total_ms):
    if total_ms <= 0:
        return _clamp_u16(end_value)
    if elapsed_ms <= 0:
        return _clamp_u16(start_value)
    if elapsed_ms >= total_ms:
        return _clamp_u16(end_value)
    delta = int(end_value) - int(start_value)
    return _clamp_u16(int(start_value) + ((delta * int(elapsed_ms)) // int(total_ms)))


def _format_bits(bits):
    return "0x{:02X}".format(bits & 0xFF)


class FujiCalibration:
    def __init__(self, transport):
        self.transport = transport
        self._rx_buf = bytearray()
        self._last_sw4_bits = None
        self._next_sw4_poll_ms = 0
        self._next_connect_keepalive_ms = 0
        self._last_status_print_ms = 0
        self._last_connect_tx_ms = 0
        self._last_control_tx_ms = 0
        self._sw4_mismatch_count = 0
        self._sw4_recovery_attempts = 0
        self._timeout_count = 0
        self._tx_count = 0
        self._rx_count = 0
        self._frame_error_count = 0
        self._failed = False
        self._events = []
        self._ack_latency_samples_ms = []
        self._ack_latency_overflow = 0
        self._next_ack_stats_print_ms = 0
        self._axis_filter_state = {}
        self._rng_state = 0x1234ABCD
        self._udp_sock = None
        self._zoom_target = 0x7FFF
        self._focus_target = 0x7FFF
        self._iris_target = 0x7FFF

    def run(self):
        self._print_startup_banner()
        self._connect()
        self._force_sw4_pc()
        lens_name = self._read_lens_name()
        if lens_name:
            print("[CAL] Lens ID:", lens_name)
        else:
            print("[CAL] Lens ID unavailable")

        print(
            "[CAL] 3-axis sweep: move {}ms / hold {}ms, endpoints {}..{}, update {}ms".format(
                TRAVEL_MS, HOLD_MS, AXIS_MIN, AXIS_MAX, UPDATE_MS
            )
        )
        print("[CAL] DRIVE_MODE={}".format(DRIVE_MODE))
        if DRIVE_MODE == "stress":
            self._run_stress_loop()
        elif DRIVE_MODE == "udp_gamepad":
            self._run_udp_gamepad_loop()
        else:
            self._run_sweep_loop()

    def _print_startup_banner(self):
        print("[CAL] Fuji calibration utility")
        print(
            "[CAL] UART id={} tx=GP{} rx=GP{} baud={} bits={} parity={} stop={}".format(
                UART_ID,
                UART_TX_PIN,
                UART_RX_PIN,
                FUJI_BAUD,
                FUJI_BITS,
                FUJI_PARITY,
                FUJI_STOP,
            )
        )
        print("[CAL] TX_MODE={} ack_timeout_ms={}".format(TX_MODE, COMMAND_ACK_TIMEOUT_MS))

    def _connect(self):
        print("[CAL] Connecting to lens...")
        for attempt in range(1, CONNECT_RETRIES + 1):
            self._send_connect()
            frame = self._wait_for_funcs({FUNC_CONNECT}, CONNECT_WAIT_MS)
            if frame:
                print("[CAL] Connect ACK on attempt", attempt)
                return True
            _sleep_ms(80)
        print("[CAL] WARN: no connect ACK, proceeding with best effort")
        return False

    def _force_sw4_pc(self):
        self._write_frame(build_switch4_control(SW4_DESIRED_BITS), "SW4_CONTROL")
        print("[CAL] SW4 ownership target bits={}".format(_format_bits(SW4_DESIRED_BITS)))

    def _read_lens_name(self):
        self._drain_rx()
        frame1 = None
        frame2 = None

        for _ in range(10):
            self.transport.write(build_lens_name_request(True))
            got = self._wait_for_funcs({FUNC_LENS_NAME_1, FUNC_LENS_NAME_2}, NAME_WAIT_MS)
            if not got:
                continue
            if got[1] == FUNC_LENS_NAME_1:
                frame1 = got
                break
            if got[1] == FUNC_LENS_NAME_2 and frame2 is None:
                frame2 = got

        if frame1 is not None and (frame1[0] & 0x0F) == 15:
            self.transport.write(build_lens_name_request(False))
            got2 = self._wait_for_funcs({FUNC_LENS_NAME_2}, NAME_WAIT_MS)
            if got2:
                frame2 = got2

        name = ""
        if frame1:
            name += decode_lens_name_chunk(frame1)
        if frame2:
            name += decode_lens_name_chunk(frame2)
        name = name.strip()
        return name or None

    def _run_sweep_loop(self):
        phase = "move_to_max"
        phase_start_ms = _ticks_ms()
        start_value = AXIS_MIN
        end_value = AXIS_MAX
        current_value = start_value
        self._reset_axis_filters(current_value, phase_start_ms)
        self._send_axes(current_value, phase_start_ms)

        while True:
            now_ms = _ticks_ms()
            self._poll_watchdog(now_ms)
            if self._failed:
                return
            if now_ms >= self._next_ack_stats_print_ms:
                self._print_ack_stats()
                self._next_ack_stats_print_ms = now_ms + ACK_STATS_PRINT_MS

            if phase == "move_to_max":
                elapsed = _ticks_diff(now_ms, phase_start_ms)
                current_value = _lerp_u16(start_value, end_value, elapsed, TRAVEL_MS)
                self._send_axes(current_value, now_ms)
                self._print_status(now_ms, phase, current_value, end_value)
                if elapsed >= TRAVEL_MS:
                    phase = "hold_max"
                    phase_start_ms = now_ms
                    current_value = AXIS_MAX
                    self._send_axes(current_value, now_ms)
                    self._print_status(now_ms, phase, current_value, current_value, force=True)

            elif phase == "hold_max":
                self._send_axes(AXIS_MAX, now_ms)
                self._print_status(now_ms, phase, AXIS_MAX, AXIS_MAX)
                if _ticks_diff(now_ms, phase_start_ms) >= HOLD_MS:
                    phase = "move_to_min"
                    phase_start_ms = now_ms
                    start_value = AXIS_MAX
                    end_value = AXIS_MIN
                    self._print_status(now_ms, phase, AXIS_MAX, AXIS_MIN, force=True)

            elif phase == "move_to_min":
                elapsed = _ticks_diff(now_ms, phase_start_ms)
                current_value = _lerp_u16(start_value, end_value, elapsed, TRAVEL_MS)
                self._send_axes(current_value, now_ms)
                self._print_status(now_ms, phase, current_value, end_value)
                if elapsed >= TRAVEL_MS:
                    phase = "hold_min"
                    phase_start_ms = now_ms
                    current_value = AXIS_MIN
                    self._send_axes(current_value, now_ms)
                    self._print_status(now_ms, phase, current_value, current_value, force=True)

            else:  # hold_min
                self._send_axes(AXIS_MIN, now_ms)
                self._print_status(now_ms, phase, AXIS_MIN, AXIS_MIN)
                if _ticks_diff(now_ms, phase_start_ms) >= HOLD_MS:
                    phase = "move_to_max"
                    phase_start_ms = now_ms
                    start_value = AXIS_MIN
                    end_value = AXIS_MAX
                    self._print_status(now_ms, phase, AXIS_MIN, AXIS_MAX, force=True)

            _sleep_ms(UPDATE_MS)

    def _run_stress_loop(self):
        start_ms = _ticks_ms()
        mid = 0x7FFF
        self._reset_axis_filters(mid, start_ms)
        self._send_axes_triplet(mid, mid, mid, start_ms)

        while True:
            now_ms = _ticks_ms()
            self._poll_watchdog(now_ms)
            if self._failed:
                return
            if now_ms >= self._next_ack_stats_print_ms:
                self._print_ack_stats()
                self._next_ack_stats_print_ms = now_ms + ACK_STATS_PRINT_MS

            elapsed = _ticks_diff(now_ms, start_ms)
            zoom_v = _triangle_u16(elapsed, STRESS_ZOOM_PERIOD_MS, 0)
            focus_v = _triangle_u16(elapsed, STRESS_FOCUS_PERIOD_MS, STRESS_FOCUS_PERIOD_MS // 3)
            iris_v = _triangle_u16(elapsed, STRESS_IRIS_PERIOD_MS, (2 * STRESS_IRIS_PERIOD_MS) // 3)

            noise = self._next_noise(STRESS_NOISE_AMPLITUDE)
            step_sign = -1 if ((elapsed // STRESS_STEP_PERIOD_MS) & 1) else 1
            step = step_sign * STRESS_STEP_AMPLITUDE

            focus_v = _clamp_u16(focus_v + noise + step)
            iris_v = _clamp_u16(iris_v - noise)

            self._send_axes_triplet(zoom_v, focus_v, iris_v, now_ms)
            self._print_stress_status(now_ms, zoom_v, focus_v, iris_v)
            _sleep_ms(UPDATE_MS)

    def _run_udp_gamepad_loop(self):
        self._open_udp_socket()
        now_ms = _ticks_ms()
        self._reset_axis_filters(self._zoom_target, now_ms)
        self._send_axes_triplet(self._zoom_target, self._focus_target, self._iris_target, now_ms)
        print("[CAL] UDP gamepad ingest on port {}".format(GAMEPAD_UDP_PORT))

        while True:
            now_ms = _ticks_ms()
            self._poll_watchdog(now_ms)
            if self._failed:
                return
            if now_ms >= self._next_ack_stats_print_ms:
                self._print_ack_stats()
                self._next_ack_stats_print_ms = now_ms + ACK_STATS_PRINT_MS

            pkt = self._recv_udp_packet()
            if pkt:
                zoom_d = pkt["zoom"]
                if zoom_d < -ZOOM_DEADBAND or zoom_d > ZOOM_DEADBAND:
                    self._zoom_target = _clamp_u16(self._zoom_target + (int(zoom_d) * ZOOM_DELTA_SCALE))
                self._focus_target = _normalize_input(pkt["focus"], 0xFFFF)
                self._iris_target = _normalize_input(pkt["iris"], 0xFFFF)
                print(
                    "[CAL] udp z_d={} -> {} f_raw={} -> {} i_raw={} -> {}".format(
                        int(zoom_d),
                        int(self._zoom_target),
                        int(pkt["focus"]),
                        int(self._focus_target),
                        int(pkt["iris"]),
                        int(self._iris_target),
                    )
                )

            self._send_axes_triplet(self._zoom_target, self._focus_target, self._iris_target, now_ms)
            _sleep_ms(UPDATE_MS)

    def _open_udp_socket(self):
        if self._udp_sock is not None:
            return
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind(("0.0.0.0", GAMEPAD_UDP_PORT))
        s.setblocking(False)
        self._udp_sock = s

    def _recv_udp_packet(self):
        if self._udp_sock is None:
            return None
        try:
            data, _addr = self._udp_sock.recvfrom(256)
        except OSError:
            return None
        if not data:
            return None
        pkt = _decode_fast_packet_v2(data)
        if pkt:
            return pkt
        return _decode_legacy_fast_packet(data)

    def _send_axes(self, value, now_ms):
        v = _clamp_u16(value)
        self._send_axes_triplet(v, v, v, now_ms)

    def _send_axes_triplet(self, zoom_target, focus_target, iris_target, now_ms):
        zoom_t = _clamp_u16(zoom_target)
        focus_t = _clamp_u16(focus_target)
        iris_t = _clamp_u16(iris_target)
        if FILTER_ENABLE:
            if AXIS_FILTER_ENABLE.get("zoom", True):
                zoom_v = self._apply_axis_filter("zoom", zoom_t, now_ms)
            else:
                zoom_v = zoom_t
            if AXIS_FILTER_ENABLE.get("focus", True):
                focus_v = self._apply_axis_filter("focus", focus_t, now_ms)
            else:
                focus_v = focus_t
            if AXIS_FILTER_ENABLE.get("iris", True):
                iris_v = self._apply_axis_filter("iris", iris_t, now_ms)
            else:
                iris_v = iris_t
        else:
            zoom_v = zoom_t
            focus_v = focus_t
            iris_v = iris_t
        self._send_control(build_zoom_control(zoom_v), "ZOOM_CONTROL", FUNC_ZOOM_CONTROL)
        self._send_control(build_focus_control(focus_v), "FOCUS_CONTROL", FUNC_FOCUS_CONTROL)
        self._send_control(build_iris_control(iris_v), "IRIS_CONTROL", FUNC_IRIS_CONTROL)

    def _print_stress_status(self, now_ms, zoom_v, focus_v, iris_v):
        if _ticks_diff(now_ms, self._last_status_print_ms) < 250:
            return
        self._last_status_print_ms = now_ms
        print("[CAL] stress z={} f={} i={}".format(int(zoom_v), int(focus_v), int(iris_v)))

    def _reset_axis_filters(self, initial_value, now_ms):
        v = _clamp_u16(initial_value)
        self._axis_filter_state = {
            "zoom": {"lp": v, "out": v, "t_ms": now_ms},
            "focus": {"lp": v, "out": v, "t_ms": now_ms},
            "iris": {"lp": v, "out": v, "t_ms": now_ms},
        }

    def _apply_axis_filter(self, axis, target_value, now_ms):
        cfg = AXIS_FILTER_CONFIG[axis]
        st = self._axis_filter_state[axis]
        dt_ms = _ticks_diff(now_ms, st["t_ms"])
        if dt_ms <= 0:
            dt_ms = 1
        st["t_ms"] = now_ms

        # Integer low-pass blend toward requested trajectory target.
        lp = st["lp"] + ((int(target_value) - int(st["lp"])) * int(cfg["lp_num"])) // int(cfg["lp_den"])
        lp = _clamp_u16(lp)
        st["lp"] = lp

        out = int(st["out"])
        desired = int(lp)
        deadband = int(cfg["deadband"])
        diff = desired - out
        if -deadband <= diff <= deadband:
            return out

        max_step = (int(cfg["max_rate"]) * int(dt_ms)) // 1000
        if max_step < 1:
            max_step = 1
        if diff > max_step:
            step = max_step
        elif diff < -max_step:
            step = -max_step
        else:
            step = diff

        min_step = int(cfg["min_step"])
        if 0 < step < min_step:
            step = min_step
        elif -min_step < step < 0:
            step = -min_step

        out = _clamp_u16(out + step)
        st["out"] = out
        return out

    def _send_control(self, frame, label, func_code):
        if FUJI_CONN_DEBUG and label == "FOCUS_CONTROL" and len(frame) >= 4:
            now_ms = _ticks_ms()
            if _ticks_diff(now_ms, getattr(self, "_last_focus_tx_log_ms", 0)) >= 500:
                self._last_focus_tx_log_ms = now_ms
                val = (frame[2] << 8) | frame[3]
                print("[LENS][Fuji][FOCUS] TX target=0x{:04X} ({})".format(val & 0xFFFF, val))
        self._write_frame(frame, label)
        self._last_control_tx_ms = _ticks_ms()
        if TX_MODE in ("strict", "semi_strict"):
            ack_wait_start_ms = _ticks_ms()
            ack = self._wait_for_funcs({func_code}, COMMAND_ACK_TIMEOUT_MS)
            if not ack:
                self._timeout_count += 1
                self._record_event("timeout", label)
                print("[CAL][PROTO] timeout waiting {} ACK".format(label))
                if TX_MODE == "strict" and FAIL_ON_COMMAND_TIMEOUT:
                    self._fail("Strict-mode ACK timeout on {}".format(label))
            else:
                latency_ms = _ticks_diff(_ticks_ms(), ack_wait_start_ms)
                self._record_ack_latency(latency_ms)
            if FUJI_CONN_DEBUG and label == "FOCUS_CONTROL":
                print("[LENS][Fuji][FOCUS] ack={}".format(ack is not None))

    def _send_connect(self):
        self._write_frame(build_connect(True), "CONNECT")
        self._last_connect_tx_ms = _ticks_ms()

    def _poll_watchdog(self, now_ms):
        self._consume_frames()

        if now_ms >= self._next_sw4_poll_ms:
            if FUJI_CONN_DEBUG and _ticks_diff(now_ms, getattr(self, "_last_sw4_poll_log_ms", 0)) >= 2000:
                self._last_sw4_poll_log_ms = now_ms
                print("[LENS][Fuji][CONN] SW4 poll req t={}".format(now_ms))
            self._write_frame(build_switch4_position_request(), "SW4_POSITION_REQ")
            self._next_sw4_poll_ms = now_ms + SW4_POLL_MS
        if now_ms >= self._next_connect_keepalive_ms:
            demand_active = (
                self._last_control_tx_ms != 0
                and _ticks_diff(now_ms, self._last_control_tx_ms) < DEMAND_ACTIVE_WINDOW_MS
            )
            if not demand_active:
                self._send_connect()
            self._next_connect_keepalive_ms = now_ms + CONNECT_KEEPALIVE_MS

    def _print_status(self, now_ms, phase, value, target, force=False):
        if not force and _ticks_diff(now_ms, self._last_status_print_ms) < 250:
            return
        self._last_status_print_ms = now_ms
        print("[CAL] phase={} value={} target={}".format(phase, int(value), int(target)))

    def _drain_rx(self):
        while True:
            data = self.transport.read()
            if not data:
                return

    def _wait_for_funcs(self, funcs, timeout_ms):
        start = _ticks_ms()
        while _ticks_diff(_ticks_ms(), start) < timeout_ms:
            frame = self._consume_frames(target_funcs=funcs)
            if frame:
                return frame
            _sleep_ms(10)
        return None

    def _consume_frames(self, target_funcs=None):
        for frame in self._poll_frames():
            self._handle_frame(frame)
            if target_funcs and len(frame) >= 2 and frame[1] in target_funcs:
                return frame
        return None

    def _handle_frame(self, frame):
        now_ms = _ticks_ms()
        if len(frame) < 2:
            return
        func = frame[1]
        self._rx_count += 1
        self._record_event("rx", "func=0x{:02X}".format(func))
        if len(frame) < 3:
            return
        payload = frame[2:-1]
        if func != FUNC_SWITCH_4_POSITION or not payload:
            return
        bits = payload[0] & 0xFF
        if FUJI_CONN_DEBUG and _ticks_diff(now_ms, getattr(self, "_last_sw4_log_ms", 0)) >= 1000:
            self._last_sw4_log_ms = now_ms
            print("[LENS][Fuji][CONN] SW4 readback=0x{:02X} desired=0x{:02X}".format(bits, SW4_DESIRED_BITS & 0xFF))
        if bits != self._last_sw4_bits:
            print("[CAL] SW4 readback={} desired={}".format(_format_bits(bits), _format_bits(SW4_DESIRED_BITS)))
        self._last_sw4_bits = bits
        if bits == SW4_DESIRED_BITS:
            return
        self._sw4_mismatch_count += 1
        since_connect_ms = _ticks_diff(now_ms, self._last_connect_tx_ms) if self._last_connect_tx_ms else -1
        since_control_ms = _ticks_diff(now_ms, self._last_control_tx_ms) if self._last_control_tx_ms else -1
        print(
            "[CAL][SW4] mismatch#{} readback={} desired={} since_connect_ms={} since_control_ms={}".format(
                self._sw4_mismatch_count,
                _format_bits(bits),
                _format_bits(SW4_DESIRED_BITS),
                int(since_connect_ms),
                int(since_control_ms),
            )
        )
        self._record_event(
            "sw4_mismatch",
            "bits={} desired={} sc={} ctl={}".format(
                _format_bits(bits), _format_bits(SW4_DESIRED_BITS), int(since_connect_ms), int(since_control_ms)
            ),
        )
        if RECOVER_ON_SW4_MISMATCH and self._sw4_recovery_attempts < MAX_SW4_RECOVERY_ATTEMPTS:
            self._sw4_recovery_attempts += 1
            self._attempt_sw4_recovery()
            return
        if FAIL_ON_SW4_MISMATCH:
            self._fail("SW4 source changed unexpectedly")

    def _attempt_sw4_recovery(self):
        print("[CAL][SW4] attempting recovery {}/{}".format(self._sw4_recovery_attempts, MAX_SW4_RECOVERY_ATTEMPTS))
        self._record_event("sw4_recovery", "attempt {}".format(self._sw4_recovery_attempts))
        self._connect()
        self._force_sw4_pc()

    def _write_frame(self, frame, label):
        self.transport.write(frame)
        self._tx_count += 1
        self._record_event("tx", label)

    def _record_event(self, kind, detail):
        event = "t={} {} {}".format(_ticks_ms(), kind, detail)
        self._events.append(event)
        if len(self._events) > EVENT_RING_SIZE:
            self._events = self._events[-EVENT_RING_SIZE:]

    def _next_noise(self, amplitude):
        self._rng_state = (1664525 * self._rng_state + 1013904223) & 0xFFFFFFFF
        ampl = int(amplitude)
        if ampl <= 0:
            return 0
        span = (2 * ampl) + 1
        return int(self._rng_state % span) - ampl

    def _fail(self, reason):
        if self._failed:
            return
        self._failed = True
        print("[CAL][FAIL]", reason)
        print(
            "[CAL][FAIL] counters tx={} rx={} timeouts={} frame_errors={} sw4_mismatch={}".format(
                self._tx_count,
                self._rx_count,
                self._timeout_count,
                self._frame_error_count,
                self._sw4_mismatch_count,
            )
        )
        print("[CAL][FAIL] recent protocol events (oldest->newest):")
        for event in self._events[-40:]:
            print("[CAL][FAIL]", event)
        self._print_ack_stats(prefix="[CAL][FAIL]")

    def _poll_frames(self):
        data = self.transport.read()
        if data:
            self._rx_buf.extend(data)

        frames = []
        while len(self._rx_buf) >= 3:
            data_len = self._rx_buf[0] & 0x0F
            frame_len = 3 + data_len
            if len(self._rx_buf) < frame_len:
                break

            frame = bytes(self._rx_buf[:frame_len])
            self._rx_buf = self._rx_buf[frame_len:]
            if checksum(frame[:-1]) != frame[-1]:
                # Drop bad frame and continue parsing remaining bytes.
                self._frame_error_count += 1
                self._record_event("frame_error", "checksum")
                continue
            frames.append(frame)
        return frames

    def _record_ack_latency(self, latency_ms):
        ms = int(latency_ms)
        if ms < 0:
            ms = 0
        if len(self._ack_latency_samples_ms) < 5000:
            self._ack_latency_samples_ms.append(ms)
        else:
            self._ack_latency_overflow += 1
        self._record_event("ack_ms", str(ms))

    def _print_ack_stats(self, prefix="[CAL][ACK]"):
        samples = self._ack_latency_samples_ms
        if not samples:
            print("{} no_samples".format(prefix))
            return
        ordered = sorted(samples)
        n = len(ordered)
        p95_index = (95 * (n - 1)) // 100
        p95 = ordered[p95_index]
        avg = sum(ordered) // n
        print(
            "{} n={} min={} avg={} p95={} max={} overflow={}".format(
                prefix,
                n,
                ordered[0],
                avg,
                p95,
                ordered[-1],
                self._ack_latency_overflow,
            )
        )


def _triangle_u16(elapsed_ms, period_ms, phase_ms):
    p = int(period_ms)
    if p <= 1:
        return AXIS_MIN
    half = p // 2
    if half <= 0:
        return AXIS_MIN
    t = (int(elapsed_ms) + int(phase_ms)) % p
    if t < half:
        return _clamp_u16((t * AXIS_MAX) // half)
    return _clamp_u16(((p - t) * AXIS_MAX) // half)


def _decode_fast_packet_v2(packet):
    # <BBBHhHHHHHH => magic, ver, type, seq, zoom, focus, iris, yaw, pitch, roll, reserved
    if len(packet) != 19:
        return None
    try:
        magic, ver, pkt_type, _seq, zoom, focus, iris, _yaw, _pitch, _roll, _ = struct.unpack(
            "<BBBHhHHHHHH", packet
        )
    except Exception:
        return None
    if magic != PKT_MAGIC or ver != PKT_VER or pkt_type != PKT_FAST_CTRL:
        return None
    return {"zoom": int(zoom), "focus": int(focus), "iris": int(iris)}


def _decode_legacy_fast_packet(packet):
    # Legacy 16-byte payload starting with 0xDE, 0xFD.
    if len(packet) != 16 or packet[0] != 0xDE or packet[1] != 0xFD:
        return None
    try:
        zoom = struct.unpack("<h", packet[2:4])[0]
        focus = (int(packet[4]) << 8) | int(packet[5])
        iris = (int(packet[6]) << 8) | int(packet[7])
    except Exception:
        return None
    return {"zoom": int(zoom), "focus": int(focus), "iris": int(iris)}


def _normalize_input(raw_value, out_max):
    v = int(raw_value)
    if v < 0:
        v = 0
    # Legacy controller path: 0..64
    if v <= 64:
        return int((v * out_max) // 64)
    # MVP/controller-main path observed on hardware: 0..16384
    if v <= 16384:
        return int((v * out_max) // 16384)
    if v <= out_max:
        return v
    if v > 0xFFFF:
        v = 0xFFFF
    return int((v * out_max) // 0xFFFF)


def main():
    transport = LensSerial(
        FUJI_BAUD,
        bits=FUJI_BITS,
        parity=FUJI_PARITY,
        stop=FUJI_STOP,
        uart_id=UART_ID,
        tx_pin=UART_TX_PIN,
        rx_pin=UART_RX_PIN,
    )
    app = FujiCalibration(transport)
    try:
        app.run()
    except KeyboardInterrupt:
        print("[CAL] Interrupted by user; exiting cleanly")


if __name__ == "__main__":
    main()
