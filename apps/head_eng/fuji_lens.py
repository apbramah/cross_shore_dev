from fuji_protocol import (
    FUJI_BAUD,
    FUJI_BITS,
    FUJI_PARITY,
    FUJI_STOP,
    FUNC_CONNECT,
    FUNC_LENS_NAME_1,
    FUNC_LENS_NAME_2,
    FUNC_IRIS_POSITION,
    FUNC_ZOOM_POSITION,
    FUNC_FOCUS_POSITION,
    FUNC_SWITCH_4_POSITION,
    SW4_HOST_ALL,
    build_connect,
    build_lens_name_request,
    build_focus_control,
    build_iris_control,
    build_l10_frame,
    build_position_request_focus,
    build_position_request_iris,
    build_position_request_zoom,
    build_switch4_control,
    build_switch4_position_request,
    build_zoom_control,
    checksum,
    decode_lens_name_chunk,
    decode_position_response,
)

SOURCE_PC = "pc"
SOURCE_CAMERA = "camera"
SOURCE_OFF = "off"
AXES = ("zoom", "focus", "iris")
ZOOM_DELTA_SCALE = 12
ZOOM_DEADBAND = 1
AXIS_HOLD_THRESHOLD = 128
CONTROL_TX_PERIOD_MS = 50
FUJI_TX_MODE = "scheduled"  # "scheduled" (calibrator-style) or "event"
FUJI_DEBUG = False
FUJI_ZOOM_DEBUG = False
FUJI_FOCUS_DEBUG = False
ZOOM_ACTIVE_WINDOW_MS = 300
CONNECT_KEEPALIVE_MS = 1000
CONNECT_KEEPALIVE_DEFER_MS = 250
DEMAND_ACTIVE_WINDOW_MS = 800
CONTROL_KEEPALIVE_MS = 700
CONTROL_DEMAND_ACTIVE_WINDOW_MS = 250
INPUT_DEMAND_ACTIVE_WINDOW_MS = 250
POLL_INTERVAL_MS_IDLE = 500
POLL_INTERVAL_MS_ACTIVE_ZOOM = 700
SW4_POLL_MS = 300
SW4_RECOVERY_COOLDOWN_MS = 800
SW4_RECOVERY_CONNECT_RETRIES = 3
SW4_RECOVERY_CONNECT_TIMEOUT_MS = 800
SW4_RECOVERY_VERIFY_RETRIES = 3
SW4_RECOVERY_VERIFY_TIMEOUT_MS = 300
SW4_RECOVERY_MAX_CONSECUTIVE_FAILS = 3
CONNECT_VERIFY_RETRIES = 3
CONNECT_VERIFY_TIMEOUT_MS = 1200
DIAG_EVENT_RING_SIZE = 48
SW4_MISMATCH_HARD_FAIL = True
STARTUP_SW4_VERIFY_RETRIES = 3
STARTUP_SW4_VERIFY_TIMEOUT_MS = 800
STARTUP_TRACE_WINDOW_MS = 2000
FUJI_RUNTIME_TX_PROFILE = "normal"  # "normal" or "sw4_watchdog_only"
# Recovery policy:
# - False: SW4 mismatch is logged as a failure signal only (no auto-recovery)
# - True: reconnect + SW4 reapply on mismatch (best-effort self-heal)
SW4_RECOVERY_ENABLED = True
BIT_POSITION_TOLERANCE_U16 = 2500
# Optional lightweight filtering for noisy absolute inputs (gamepad path).
DEFAULT_ENABLE_FOCUS_INPUT_FILTER = False
DEFAULT_ENABLE_IRIS_INPUT_FILTER = True
DEFAULT_INPUT_FILTER_NUM = 1
DEFAULT_INPUT_FILTER_DEN = 3


class FujiLens:
    baud = FUJI_BAUD
    bits = FUJI_BITS
    parity = FUJI_PARITY
    stop = FUJI_STOP

    def __init__(self, transport):
        self.transport = transport
        self.zoom = 0x7FFF
        self.focus = 0x7FFF
        self.iris = 0x7FFF
        self.axis_sources = {axis: SOURCE_PC for axis in AXES}
        self._next_keepalive_ms = 0
        self._next_poll_ms = 0
        self._next_sw4_poll_ms = 0
        self._next_control_tx_ms = 0
        self._next_control_keepalive_ms = 0
        self._rx_buf = bytearray()
        self._last_sw4_readback = None
        self._next_sw4_reassert_ms = 0
        self._sw4_mismatch_count = 0
        self._sw4_recovery_count = 0
        self._sw4_recovery_fail_streak = 0
        self._faulted = False
        self._fault_reason = ""
        self._last_control_tx_ms = 0
        self._last_zoom_feedback = None
        self._last_focus_feedback = None
        self._last_iris_feedback = None
        self._zoom_active_until_ms = 0
        self._last_input_delta_ms = 0
        self._last_zoom_input = 0
        self._last_focus_input = None
        self._last_iris_input = None
        self._focus_filtered = self.focus
        self._iris_filtered = self.iris
        self._focus_filter_enabled = DEFAULT_ENABLE_FOCUS_INPUT_FILTER
        self._iris_filter_enabled = DEFAULT_ENABLE_IRIS_INPUT_FILTER
        self._input_filter_num = DEFAULT_INPUT_FILTER_NUM
        self._input_filter_den = DEFAULT_INPUT_FILTER_DEN
        self.last_connect_tx_ms = 0
        self.last_connect_ack_ms = 0
        self.connect_tx_count = 0
        self.connect_ack_count = 0
        self.connect_timeout_count = 0
        self.connect_fail_streak = 0
        self._diag_events = []
        self._last_sw4_commanded_bits = None
        self._startup_trace_until_ms = 0

    def on_activate(self):
        now_ms = _ticks_ms()
        self._faulted = False
        self._fault_reason = ""
        self._diag_events = []
        self._startup_trace_until_ms = now_ms + STARTUP_TRACE_WINDOW_MS
        self._record_diag_event("activate_begin", "profile={}".format(FUJI_RUNTIME_TX_PROFILE))
        self._next_keepalive_ms = now_ms + CONNECT_KEEPALIVE_MS
        self._next_poll_ms = now_ms
        self._next_sw4_poll_ms = now_ms + SW4_POLL_MS
        self._next_control_tx_ms = now_ms + CONTROL_TX_PERIOD_MS
        self._next_control_keepalive_ms = now_ms + CONTROL_KEEPALIVE_MS
        self._last_control_tx_ms = 0
        self._last_input_delta_ms = 0
        self._sw4_recovery_fail_streak = 0
        if not self.connect_verified(now_ms, CONNECT_VERIFY_RETRIES, CONNECT_VERIFY_TIMEOUT_MS):
            self._set_fault("activate connect verify failed")
            return
        _sleep_ms(40)
        self._send_switch4(force=True)
        _sleep_ms(40)
        desired_bits = self._current_sw4_bits()
        if not self._verify_sw4_position(
            desired_bits,
            retries=STARTUP_SW4_VERIFY_RETRIES,
            timeout_ms=STARTUP_SW4_VERIFY_TIMEOUT_MS,
        ):
            self._set_fault(
                "activate SW4 verify failed read=0x{:02X} desired=0x{:02X}".format(
                    int(self._last_sw4_readback or 0x00), desired_bits
                )
            )
            return
        self._record_diag_event("activate_sw4_verified", "bits=0x{:02X}".format(desired_bits))

    def write_raw(self, data):
        self.transport.write(data)

    def read_raw(self):
        return self.transport.read()

    def get_axis_sources(self):
        return dict(self.axis_sources)

    def set_axis_source(self, axis, source):
        if axis not in self.axis_sources:
            return False
        if source not in (SOURCE_PC, SOURCE_CAMERA, SOURCE_OFF):
            return False
        if self.axis_sources[axis] == source:
            return True
        self.axis_sources[axis] = source
        if FUJI_DEBUG:
            print(
                "[LENS][Fuji] set source",
                axis,
                "->",
                source,
                "desired SW4=0x{:02X}".format(self._current_sw4_bits()),
            )
        self._send_switch4()
        return True

    def set_input_filter_enabled(self, axis, enabled):
        axis_name = str(axis).lower().strip()
        value = bool(enabled)
        if axis_name == "focus":
            self._focus_filter_enabled = value
            return True
        if axis_name == "iris":
            self._iris_filter_enabled = value
            return True
        return False

    def set_input_filter_ratio(self, num, den):
        n = int(num)
        d = int(den)
        if n < 0:
            n = 0
        if d < 1:
            d = 1
        if n > d:
            n = d
        self._input_filter_num = n
        self._input_filter_den = d
        return True

    def set_input_filter_num(self, num):
        return self.set_input_filter_ratio(num, self._input_filter_den)

    def set_input_filter_den(self, den):
        return self.set_input_filter_ratio(self._input_filter_num, den)

    def move_zoom(self, delta):
        if self.axis_sources["zoom"] != SOURCE_PC:
            return
        d = int(delta)
        if -ZOOM_DEADBAND <= d <= ZOOM_DEADBAND:
            return
        now_ms = _ticks_ms()
        if d != self._last_zoom_input:
            self._last_input_delta_ms = now_ms
            self._last_zoom_input = d
        self._zoom_active_until_ms = now_ms + ZOOM_ACTIVE_WINDOW_MS
        self.zoom = _clamp_u16(self.zoom + (d * ZOOM_DELTA_SCALE))
        if FUJI_TX_MODE == "event":
            self.transport.write(build_zoom_control(self.zoom))
            self._last_control_tx_ms = now_ms
        if FUJI_ZOOM_DEBUG:
            print(
                "[LENS][Fuji][ZOOM] {} t={} delta={} target={}".format(
                    "TX" if FUJI_TX_MODE == "event" else "SET",
                    now_ms, d, self.zoom
                )
            )

    def set_focus_input(self, raw_value):
        if self.axis_sources["focus"] != SOURCE_PC:
            return
        v = _normalize_input(raw_value, 0xFFFF)
        now_ms = _ticks_ms()
        if self._last_focus_input is None or v != self._last_focus_input:
            self._last_input_delta_ms = now_ms
            self._last_focus_input = v
        if self._focus_filter_enabled:
            self._focus_filtered = _lp_u16(self._focus_filtered, v, self._input_filter_num, self._input_filter_den)
            v = self._focus_filtered
        if abs(v - self.focus) < AXIS_HOLD_THRESHOLD:
            return
        self.focus = v
        if FUJI_TX_MODE == "event":
            self._send_focus_control(now_ms)

    def set_iris_input(self, raw_value):
        if self.axis_sources["iris"] != SOURCE_PC:
            return
        v = _normalize_input(raw_value, 0xFFFF)
        now_ms = _ticks_ms()
        if self._last_iris_input is None or v != self._last_iris_input:
            self._last_input_delta_ms = now_ms
            self._last_iris_input = v
        if self._iris_filter_enabled:
            self._iris_filtered = _lp_u16(self._iris_filtered, v, self._input_filter_num, self._input_filter_den)
            v = self._iris_filtered
        if abs(v - self.iris) < AXIS_HOLD_THRESHOLD:
            return
        self.iris = v
        if FUJI_TX_MODE == "event":
            self.transport.write(build_iris_control(self.iris))
            self._last_control_tx_ms = now_ms

    def periodic(self, now_ms):
        for frame in self._poll_frames():
            self._handle_runtime_frame(frame, now_ms)
        if self._faulted:
            return

        zoom_active = not _time_after(now_ms, self._zoom_active_until_ms)

        if FUJI_TX_MODE == "scheduled":
            # Match calibrator loop ordering: watchdog (SW4 poll + optional connect)
            # first, then deterministic axis controls.
            if _time_after(now_ms, self._next_sw4_poll_ms):
                self.transport.write(build_switch4_position_request())
                self._next_sw4_poll_ms = now_ms + SW4_POLL_MS
            if _time_after(now_ms, self._next_keepalive_ms):
                demand_active = (
                    self._last_control_tx_ms != 0
                    and _ticks_diff(now_ms, self._last_control_tx_ms) < DEMAND_ACTIVE_WINDOW_MS
                )
                if not demand_active:
                    self.connect_best_effort(now_ms)
                self._next_keepalive_ms = now_ms + CONNECT_KEEPALIVE_MS
            if _time_after(now_ms, self._next_control_tx_ms):
                if FUJI_RUNTIME_TX_PROFILE == "normal":
                    self._send_axis_controls(now_ms)
                self._next_control_tx_ms = now_ms + CONTROL_TX_PERIOD_MS
            if _time_after(now_ms, self._next_poll_ms):
                self.transport.write(build_position_request_zoom())
                if not zoom_active:
                    self.transport.write(build_position_request_focus())
                    self.transport.write(build_position_request_iris())
                    self._next_poll_ms = now_ms + POLL_INTERVAL_MS_IDLE
                else:
                    self._next_poll_ms = now_ms + POLL_INTERVAL_MS_ACTIVE_ZOOM
        else:
            if _time_after(now_ms, self._next_keepalive_ms):
                demand_active = (
                    self._last_control_tx_ms != 0
                    and _ticks_diff(now_ms, self._last_control_tx_ms) < DEMAND_ACTIVE_WINDOW_MS
                )
                if not demand_active:
                    self.connect_best_effort(now_ms)
                    self._next_keepalive_ms = now_ms + CONNECT_KEEPALIVE_MS
                else:
                    self._next_keepalive_ms = now_ms + CONNECT_KEEPALIVE_DEFER_MS
            if _time_after(now_ms, self._next_poll_ms):
                self.transport.write(build_switch4_position_request())
                self.transport.write(build_position_request_zoom())
                if not zoom_active:
                    self.transport.write(build_position_request_focus())
                    self.transport.write(build_position_request_iris())
                    self._next_poll_ms = now_ms + POLL_INTERVAL_MS_IDLE
                else:
                    self._next_poll_ms = now_ms + POLL_INTERVAL_MS_ACTIVE_ZOOM

        if FUJI_TX_MODE == "event" and _time_after(now_ms, self._next_control_keepalive_ms):
            control_demand_active = (
                self._last_control_tx_ms != 0
                and _ticks_diff(now_ms, self._last_control_tx_ms) < CONTROL_DEMAND_ACTIVE_WINDOW_MS
            )
            input_demand_active = (
                self._last_input_delta_ms != 0
                and _ticks_diff(now_ms, self._last_input_delta_ms) < INPUT_DEMAND_ACTIVE_WINDOW_MS
            )
            if not control_demand_active and not input_demand_active:
                self._send_control_keepalive(now_ms)
                self._next_control_keepalive_ms = now_ms + CONTROL_KEEPALIVE_MS
            else:
                self._next_control_keepalive_ms = now_ms + CONTROL_DEMAND_ACTIVE_WINDOW_MS


    def startup_diagnostics(self):
        print("[LENS][Fuji] startup diagnostics begin")
        # Prime handshake first; many lenses return name only after link setup.
        self.connect_verified(_ticks_ms(), CONNECT_VERIFY_RETRIES, CONNECT_VERIFY_TIMEOUT_MS)
        _sleep_ms(120)
        self._send_switch4()
        _sleep_ms(120)
        lens_name = self.read_lens_name()
        if lens_name:
            print("[LENS][Fuji] Lens ID:", lens_name)
        else:
            print("[LENS][Fuji] Lens ID unavailable")
        ok = self.run_bit()
        if ok:
            print("[LENS][Fuji] BIT PASS")
        else:
            print("[LENS][Fuji] BIT FAIL")
        return ok

    def read_lens_name(self):
        self._drain_rx()
        frame1 = None
        frame2 = None

        # Match tester behavior: repeatedly poll NAME_1 until we get content.
        for _ in range(20):
            self.transport.write(build_lens_name_request(True))
            got = self._wait_for_func({FUNC_LENS_NAME_1, FUNC_LENS_NAME_2}, 300)
            if got:
                if got[1] == FUNC_LENS_NAME_1:
                    frame1 = got
                    print("[LENS][Fuji] RX NAME_1:", _hexdump(got))
                elif got[1] == FUNC_LENS_NAME_2:
                    frame2 = got
                    print("[LENS][Fuji] RX NAME_2:", _hexdump(got))
            if frame1 is not None:
                break

        # If NAME_1 has full first chunk (15 bytes), request NAME_2 like tester.
        if frame1 is not None and ((frame1[0] & 0x0F) == 15):
            self.transport.write(build_lens_name_request(False))
            got2 = self._wait_for_func({FUNC_LENS_NAME_2}, 1200)
            if got2:
                frame2 = got2
                print("[LENS][Fuji] RX NAME_2:", _hexdump(got2))

        name = ""
        if frame1:
            name += decode_lens_name_chunk(frame1)
        if frame2:
            name += decode_lens_name_chunk(frame2)
        name = name.strip()
        return name or None

    def run_bit(self):
        # Mirrors tester intent: connect, own controls, sweep each axis with readback.
        if not self.connect_verified(_ticks_ms(), CONNECT_VERIFY_RETRIES, CONNECT_VERIFY_TIMEOUT_MS):
            print("[LENS][Fuji][BIT] WARN: no connect ACK")
        _sleep_ms(200)

        desired_sw4 = self._current_sw4_bits()
        self._send_switch4(force=True)
        _sleep_ms(120)
        if not self._verify_sw4_position(desired_sw4, retries=3, timeout_ms=1500):
            print(
                "[LENS][Fuji][BIT] FAIL: SW4 ownership verify failed desired=0x{:02X}".format(
                    desired_sw4
                )
            )
            return False
        _sleep_ms(120)

        targets = (0, 65535, 32768)
        for axis in ("iris", "zoom", "focus"):
            for target in targets:
                if axis == "iris":
                    ctl = lambda v=target: build_iris_control(v)
                    req = build_position_request_iris
                    func = FUNC_IRIS_POSITION
                elif axis == "zoom":
                    ctl = lambda v=target: build_zoom_control(v)
                    req = build_position_request_zoom
                    func = FUNC_ZOOM_POSITION
                else:
                    ctl = lambda v=target: build_focus_control(v)
                    req = build_position_request_focus
                    func = FUNC_FOCUS_POSITION
                frame = self._command_and_readback(ctl, req, {func}, retries=3, timeout_ms=1800)
                if not frame:
                    print("[LENS][Fuji][BIT] FAIL:", axis, "target", target, "no readback")
                    return False
                value = decode_position_response(frame[2:-1])
                if value is None:
                    print("[LENS][Fuji][BIT] FAIL:", axis, "target", target, "invalid readback")
                    return False
                print("[LENS][Fuji][BIT]", axis, "target", target, "readback", value)
                if abs(int(value) - int(target)) > BIT_POSITION_TOLERANCE_U16:
                    print(
                        "[LENS][Fuji][BIT] FAIL:",
                        axis,
                        "target",
                        target,
                        "readback",
                        value,
                        "tol",
                        BIT_POSITION_TOLERANCE_U16,
                    )
                    return False
                _sleep_ms(120)
        return True

    def _drain_rx(self):
        while True:
            data = self.transport.read()
            if not data:
                return

    def _wait_for_func(self, funcs, timeout_ms):
        start = _ticks_ms()
        while _ticks_diff(_ticks_ms(), start) < timeout_ms:
            for frame in self._poll_frames():
                if len(frame) >= 3 and frame[1] in funcs:
                    return frame
            _sleep_ms(10)
        return None

    def _send_and_wait(self, frame_builder, funcs, retries=2, timeout_ms=1200):
        for _ in range(retries):
            self.transport.write(frame_builder())
            frame = self._wait_for_func(funcs, timeout_ms)
            if frame:
                return frame
            _sleep_ms(80)
        return None

    def connect_best_effort(self, now_ms):
        self.transport.write(build_connect(True))
        self.last_connect_tx_ms = int(now_ms)
        self.connect_tx_count += 1
        self._record_diag_event("connect_tx", "mode=best_effort")

    def connect_verified(self, now_ms, retries, timeout_ms):
        retry_count = int(retries)
        if retry_count < 1:
            retry_count = 1
        for attempt in range(1, retry_count + 1):
            tx_ms = _ticks_ms() if attempt > 1 else int(now_ms)
            self.connect_best_effort(tx_ms)
            frame = self._wait_for_func({FUNC_CONNECT}, int(timeout_ms))
            if frame:
                ack_ms = _ticks_ms()
                self.last_connect_ack_ms = ack_ms
                self.connect_ack_count += 1
                self.connect_fail_streak = 0
                latency_ms = _ticks_diff(ack_ms, self.last_connect_tx_ms)
                self._record_diag_event("connect_ack", "attempt={} dt_ms={}".format(attempt, int(latency_ms)))
                return frame
            self.connect_timeout_count += 1
            self._record_diag_event("connect_timeout", "attempt={}".format(attempt))
            _sleep_ms(80)
        self.connect_fail_streak += 1
        return None

    def _verify_sw4_position(self, desired_bits, retries, timeout_ms):
        retry_count = int(retries)
        if retry_count < 1:
            retry_count = 1
        for attempt in range(1, retry_count + 1):
            self.transport.write(build_switch4_position_request())
            self._record_diag_event("sw4_req", "attempt={}".format(attempt))
            frame = self._wait_for_func({FUNC_SWITCH_4_POSITION}, int(timeout_ms))
            if not frame or len(frame) < 4:
                self._record_diag_event("sw4_verify_timeout", "attempt={}".format(attempt))
                continue
            bits = frame[2] & 0xFF
            self._last_sw4_readback = bits
            if bits == (desired_bits & 0xFF):
                self._record_diag_event(
                    "sw4_verify_ok",
                    "attempt={} bits=0x{:02X}".format(attempt, bits),
                )
                return True
            self._record_diag_event(
                "sw4_verify_mismatch",
                "attempt={} bits=0x{:02X} desired=0x{:02X}".format(attempt, bits, desired_bits & 0xFF),
            )
        return False

    def _command_and_readback(self, control_builder, request_builder, funcs, retries=2, timeout_ms=1200):
        for _ in range(retries):
            self.transport.write(control_builder())
            _sleep_ms(60)
            self.transport.write(request_builder())
            frame = self._wait_for_func(funcs, timeout_ms)
            if frame:
                return frame
            _sleep_ms(120)
        return None

    def _poll_frames(self):
        data = self.transport.read()
        if data:
            self._rx_buf.extend(data)
        frames = []
        while len(self._rx_buf) >= 3:
            n = self._rx_buf[0] & 0x0F
            frame_len = 3 + n
            if len(self._rx_buf) < frame_len:
                break
            frame = bytes(self._rx_buf[:frame_len])
            if checksum(frame[:-1]) != frame[-1]:
                # Match calibrator behavior: drop full malformed frame-sized chunk.
                self._rx_buf = self._rx_buf[frame_len:]
                continue
            frames.append(frame)
            self._rx_buf = self._rx_buf[frame_len:]
        return frames

    def _send_switch4(self, force=False):
        bits = self._current_sw4_bits()
        if not force and self._last_sw4_commanded_bits == bits:
            return False
        if FUJI_DEBUG:
            print("[LENS][Fuji] TX SW4_CONTROL bits=0x{:02X}".format(bits))
        self.transport.write(build_switch4_control(bits))
        self._record_diag_event("sw4_control_tx", "bits=0x{:02X}".format(bits))
        self._last_sw4_commanded_bits = bits
        return True

    def _current_sw4_bits(self):
        bits = SW4_HOST_ALL
        if self.axis_sources["focus"] != SOURCE_PC:
            bits |= 0x01
        if self.axis_sources["zoom"] != SOURCE_PC:
            bits |= 0x02
        if self.axis_sources["iris"] != SOURCE_PC:
            bits |= 0x04
        return bits & 0xFF

    def _handle_runtime_frame(self, frame, now_ms):
        if len(frame) < 3:
            return
        func = frame[1]
        payload = frame[2:-1]
        if func == FUNC_SWITCH_4_POSITION and payload:
            bits = payload[0] & 0xFF
            desired = self._current_sw4_bits()
            if not _time_after(now_ms, self._startup_trace_until_ms):
                self._record_diag_event("sw4_rx", "bits=0x{:02X} desired=0x{:02X}".format(bits, desired))
            if bits != self._last_sw4_readback and FUJI_DEBUG:
                print(
                    "[LENS][Fuji] RX SW4_POSITION bits=0x{:02X} desired=0x{:02X}".format(
                        bits, desired
                    )
                )
            self._last_sw4_readback = bits
            if bits != desired:
                self._sw4_mismatch_count += 1
                print(
                    "[LENS][Fuji][FAIL] SW4 mismatch#{} read=0x{:02X} desired=0x{:02X} recovery={}".format(
                        self._sw4_mismatch_count,
                        bits,
                        desired,
                        "on" if SW4_RECOVERY_ENABLED else "off",
                    )
                )
                if SW4_MISMATCH_HARD_FAIL:
                    self._record_diag_event(
                        "sw4_hard_fail",
                        "read=0x{:02X} desired=0x{:02X}".format(bits, desired),
                    )
                    self._set_fault("SW4 ownership mismatch read=0x{:02X} desired=0x{:02X}".format(bits, desired))
                    return
                if SW4_RECOVERY_ENABLED and _time_after(now_ms, self._next_sw4_reassert_ms):
                    self._sw4_recovery_count += 1
                    recovered = self._recover_sw4_ownership(now_ms, desired)
                    if recovered:
                        self._sw4_recovery_fail_streak = 0
                    else:
                        was_zero = self._sw4_recovery_fail_streak == 0
                        self._sw4_recovery_fail_streak += 1
                        print(
                            "[LENS][Fuji][RECOVERY] fail streak={}/{}".format(
                                self._sw4_recovery_fail_streak,
                                SW4_RECOVERY_MAX_CONSECUTIVE_FAILS,
                            )
                        )
                        if was_zero:
                            self._dump_diag_events("SW4 recovery failure transition")
                        if self._sw4_recovery_fail_streak >= SW4_RECOVERY_MAX_CONSECUTIVE_FAILS:
                            self._set_fault("SW4 recovery failed repeatedly")
                    self._next_sw4_reassert_ms = now_ms + SW4_RECOVERY_COOLDOWN_MS
        elif func == FUNC_ZOOM_POSITION and payload:
            value = decode_position_response(payload)
            if value is None:
                return
            if FUJI_ZOOM_DEBUG and value != self._last_zoom_feedback:
                print(
                    "[LENS][Fuji][ZOOM] RX t={} pos={}".format(
                        _ticks_ms(), value
                    )
                )
            self._last_zoom_feedback = value
        elif func == FUNC_FOCUS_POSITION and payload:
            value = decode_position_response(payload)
            if value is None:
                return
            if FUJI_FOCUS_DEBUG and value != self._last_focus_feedback:
                focus_err = int(self.focus) - int(value)
                print(
                    "[LENS][Fuji][FOCUS] RX t={} pos={} target={} err={}".format(
                        _ticks_ms(), value, self.focus, focus_err
                    )
                )
            self._last_focus_feedback = value
        elif func == FUNC_IRIS_POSITION and payload:
            value = decode_position_response(payload)
            if value is None:
                return
            self._last_iris_feedback = value

    def _send_focus_control(self, now_ms):
        self.transport.write(build_focus_control(self.focus))
        self._last_control_tx_ms = now_ms
        if FUJI_FOCUS_DEBUG:
            print(
                "[LENS][Fuji][FOCUS] TX t={} target={}".format(
                    now_ms, self.focus
                )
            )

    def _send_control_keepalive(self, now_ms):
        sent = False
        if self.axis_sources["zoom"] == SOURCE_PC:
            self.transport.write(build_zoom_control(self.zoom))
            sent = True
        if self.axis_sources["focus"] == SOURCE_PC:
            self.transport.write(build_focus_control(self.focus))
            sent = True
        if self.axis_sources["iris"] == SOURCE_PC:
            self.transport.write(build_iris_control(self.iris))
            sent = True
        if sent and FUJI_DEBUG:
            print(
                "[LENS][Fuji] TX CTRL_KEEPALIVE t={} z={} f={} i={}".format(
                    now_ms, int(self.zoom), int(self.focus), int(self.iris)
                )
            )

    def _send_axis_controls(self, now_ms):
        sent = False
        if self.axis_sources["zoom"] == SOURCE_PC:
            self.transport.write(build_zoom_control(self.zoom))
            sent = True
        if self.axis_sources["focus"] == SOURCE_PC:
            self.transport.write(build_focus_control(self.focus))
            if FUJI_FOCUS_DEBUG:
                print("[LENS][Fuji][FOCUS] TX t={} target={}".format(now_ms, self.focus))
            sent = True
        if self.axis_sources["iris"] == SOURCE_PC:
            self.transport.write(build_iris_control(self.iris))
            sent = True
        if sent:
            self._last_control_tx_ms = now_ms

    def _recover_sw4_ownership(self, now_ms, desired_bits):
        print(
            "[LENS][Fuji][RECOVERY] start attempt={} desired=0x{:02X}".format(
                self._sw4_recovery_count, desired_bits & 0xFF
            )
        )
        self._record_diag_event("sw4_recovery_start", "desired=0x{:02X}".format(desired_bits & 0xFF))
        ack = self.connect_verified(now_ms, SW4_RECOVERY_CONNECT_RETRIES, SW4_RECOVERY_CONNECT_TIMEOUT_MS)
        if not ack:
            print("[LENS][Fuji][RECOVERY] connect verified timeout")
            self._record_diag_event("sw4_recovery_connect_timeout", "retries={}".format(SW4_RECOVERY_CONNECT_RETRIES))
            return False
        print("[LENS][Fuji][RECOVERY] connect verified ok")
        _sleep_ms(40)
        self._send_switch4(force=True)
        _sleep_ms(40)
        verified = self._verify_sw4_position(
            desired_bits,
            retries=SW4_RECOVERY_VERIFY_RETRIES,
            timeout_ms=SW4_RECOVERY_VERIFY_TIMEOUT_MS,
        )
        if verified:
            print("[LENS][Fuji][RECOVERY] SW4 verify ok bits=0x{:02X}".format(desired_bits & 0xFF))
            return True
        print("[LENS][Fuji][RECOVERY] SW4 verify fail")
        return False

    def _set_fault(self, reason):
        if self._faulted:
            return
        self._faulted = True
        self._fault_reason = str(reason)
        print("[LENS][Fuji][FAULT] latched reason={}".format(self._fault_reason))
        self._record_diag_event("fault_latched", self._fault_reason)
        self._dump_diag_events("fault latch")

    def _record_diag_event(self, event_type, detail):
        evt = "t={} {} {}".format(_ticks_ms(), str(event_type), str(detail))
        self._diag_events.append(evt)
        if len(self._diag_events) > DIAG_EVENT_RING_SIZE:
            self._diag_events = self._diag_events[-DIAG_EVENT_RING_SIZE:]

    def _dump_diag_events(self, reason):
        print("[LENS][Fuji][DIAG] dump reason={}".format(reason))
        for evt in self._diag_events[-24:]:
            print("[LENS][Fuji][DIAG]", evt)


def _clamp_u16(v):
    if v < 0:
        return 0
    if v > 0xFFFF:
        return 0xFFFF
    return int(v)


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
    # Treat out-of-range as 16-bit and rescale.
    if v > 0xFFFF:
        v = 0xFFFF
    return int((v * out_max) // 0xFFFF)


def _lp_u16(prev, target, num, den):
    p = int(prev)
    t = int(target)
    n = int(num)
    d = int(den)
    if d <= 0:
        return _clamp_u16(t)
    if n <= 0:
        return _clamp_u16(p)
    if n > d:
        n = d
    return _clamp_u16(p + ((t - p) * n) // d)


def _time_after(now_ms, target_ms):
    return now_ms >= target_ms


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


def _hexdump(data):
    return " ".join("{:02X}".format(b) for b in data)
