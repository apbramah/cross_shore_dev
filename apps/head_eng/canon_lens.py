from canon_protocol import (
    CTRL_CMD,
    FINISH_INIT,
    LENS_NAME_REQ,
    SRC_CAMERA,
    SRC_OFF,
    SRC_PC,
    SCMD_FOCUS_SWITCH,
    SCMD_IRIS_SWITCH,
    SCMD_ZOOM_SWITCH,
    CMD_ZOOM_POS,
    CMD_FOCUS_POS,
    CMD_IRIS_POS,
    SUBCMD_C0,
    ZOOM_SPEED_MAX,
    build_type_b,
    build_zoom_speed_control_signed,
    build_type_c_switch,
    decode_lens_name_type_c,
    unpack_type_b_value,
)

SOURCE_PC = "pc"
SOURCE_CAMERA = "camera"
SOURCE_OFF = "off"
AXES = ("zoom", "focus", "iris")
ZOOM_DELTA_SCALE = 10
ZOOM_INPUT_MAX = 64
ZOOM_DEADBAND = 1
AXIS_HOLD_THRESHOLD = 120
CONTROL_TX_PERIOD_MS = 10
CONTROL_KEEPALIVE_MS = 200
SOURCE_REFRESH_MS = 1500
FILTER_DEFAULT_NUM = 1
FILTER_DEFAULT_DEN = 8
FILTER_MAX_RATE_PER_S = 6000

# Set True from main to log zoom/focus/iris when we send to the lens (like Fuji FOCUS debug).
CANON_DEBUG = False


class CanonLens:
    baud = 19200
    bits = 8
    parity = 0  # even parity in MicroPython
    stop = 1

    def __init__(self, transport):
        self.transport = transport
        self.zoom = 30000
        self.focus = 30000
        self.iris = 30000
        self.zoom_target = self.zoom
        self.focus_target = self.focus
        self.iris_target = self.iris
        self.zoom_velocity_cmd = 0
        self.zoom_speed_raw = 0x8000
        self.zoom_mode = "speed_native"
        self.control_tx_period_ms = CONTROL_TX_PERIOD_MS
        self.lens_name_cached = None
        self.axis_sources = {"zoom": SOURCE_PC, "focus": SOURCE_PC, "iris": SOURCE_PC}
        self._next_keepalive_ms = 0
        self._next_source_refresh_ms = 0
        self._next_control_tx_ms = 0
        self._last_control_update_ms = 0
        self._last_control_tx_ms = 0
        self._rx_buf = bytearray()
        # Default-on smoothing for Canon to suppress input jitter and command oscillation.
        self._filter_enabled = {"focus": True, "iris": True}
        self._filter_num = FILTER_DEFAULT_NUM
        self._filter_den = FILTER_DEFAULT_DEN

    def on_activate(self):
        # Match tester order: CTRL_CMD then FINISH_INIT then source switch (keepalive runs in periodic).
        self.transport.write(CTRL_CMD)
        try:
            import time
            if hasattr(time, "sleep_ms"):
                time.sleep_ms(50)
            else:
                time.sleep(0.05)
        except Exception:
            pass
        self.transport.write(FINISH_INIT)
        try:
            import time
            if hasattr(time, "sleep_ms"):
                time.sleep_ms(80)
            else:
                time.sleep(0.08)
        except Exception:
            pass
        self._apply_all_sources()
        self._next_keepalive_ms = 0
        self._next_source_refresh_ms = 0
        self._next_control_tx_ms = 0
        self._last_control_update_ms = 0
        self._last_control_tx_ms = 0
        print(
            "[LENS][Canon] source policy: zoom=pc focus=pc iris={}".format(
                self.axis_sources.get("iris", SOURCE_PC)
            )
        )

    def write_raw(self, data):
        self.transport.write(data)

    def read_raw(self):
        return self.transport.read()

    def get_axis_sources(self):
        return dict(self.axis_sources)

    def set_axis_source(self, axis, source):
        if axis not in self.axis_sources:
            return False
        s = str(source).lower().strip()
        # Canon policy: zoom/focus are always host-driven; only iris is switchable.
        if axis in ("zoom", "focus"):
            if s != SOURCE_PC:
                return False
            self.axis_sources[axis] = SOURCE_PC
            self._send_axis_source(axis)
            return True
        if s not in (SOURCE_PC, SOURCE_CAMERA):
            return False
        self.axis_sources[axis] = s
        self._send_axis_source(axis)
        return True

    def move_zoom(self, delta):
        if self.axis_sources["zoom"] != SOURCE_PC:
            self.zoom_velocity_cmd = 0
            return
        d = int(delta)
        if -ZOOM_DEADBAND <= d <= ZOOM_DEADBAND:
            self.zoom_velocity_cmd = 0
            return
        if d > ZOOM_INPUT_MAX:
            d = ZOOM_INPUT_MAX
        elif d < -ZOOM_INPUT_MAX:
            d = -ZOOM_INPUT_MAX
        self.zoom_velocity_cmd = d

    def set_focus_input(self, raw_value):
        if self.axis_sources["focus"] != SOURCE_PC:
            return
        v = _normalize_input(raw_value, 60000)
        if abs(v - self.focus_target) < AXIS_HOLD_THRESHOLD:
            return
        self.focus_target = v

    def set_iris_input(self, raw_value):
        if self.axis_sources["iris"] != SOURCE_PC:
            return
        v = _normalize_input(raw_value, 60000)
        if abs(v - self.iris_target) < AXIS_HOLD_THRESHOLD:
            return
        self.iris_target = v

    def periodic(self, now_ms):
        if _time_after(now_ms, self._next_keepalive_ms):
            self.transport.write(CTRL_CMD)
            self._next_keepalive_ms = now_ms + CONTROL_KEEPALIVE_MS
        if _time_after(now_ms, self._next_source_refresh_ms):
            self._apply_all_sources()
            self._next_source_refresh_ms = now_ms + SOURCE_REFRESH_MS
        if _time_after(now_ms, self._next_control_tx_ms):
            self._update_control_targets(now_ms)
            self._send_axis_controls(now_ms)
            self._next_control_tx_ms = now_ms + CONTROL_TX_PERIOD_MS

    def set_input_filter_enabled(self, axis, enabled):
        if axis not in ("focus", "iris"):
            return False
        self._filter_enabled[axis] = bool(enabled)
        return True

    def set_input_filter_ratio(self, num, den):
        n = int(num)
        d = int(den)
        if n < 0:
            n = 0
        if d < 1:
            return False
        if n > d:
            n = d
        self._filter_num = n
        self._filter_den = d
        return True

    def set_input_filter_num(self, num):
        return self.set_input_filter_ratio(num, self._filter_den)

    def set_input_filter_den(self, den):
        return self.set_input_filter_ratio(self._filter_num, den)

    def startup_diagnostics(self):
        print("[LENS][Canon] startup diagnostics begin")
        lens_name = self.read_lens_name()
        if lens_name:
            print("[LENS][Canon] Lens ID:", lens_name)
        else:
            print("[LENS][Canon] Lens ID unavailable")
        ok = self.run_bit()
        if ok:
            print("[LENS][Canon] BIT PASS")
        else:
            print("[LENS][Canon] BIT FAIL")
        return ok

    def read_lens_name(self):
        self._drain_rx()
        self.transport.write(LENS_NAME_REQ)
        frame = self._wait_for_prefix((0xBE, 0x80, 0x81), 1200)
        if not frame:
            return None
        name = decode_lens_name_type_c(frame)
        if name:
            self.lens_name_cached = name
        return name

    def run_bit(self):
        # Similar to tester: init, source PC for all axes, sweep and expect Type-B feedback.
        self.transport.write(CTRL_CMD)
        self.transport.write(FINISH_INIT)
        if not self._wait_for_prefix((0x86, 0xC0), 1000):
            print("[LENS][Canon][BIT] WARN: no FINISH_INIT readback")

        self._apply_all_sources()

        targets = (0, 60000, 30000)
        for axis in ("zoom", "focus", "iris"):
            for target in targets:
                if axis == "zoom":
                    cmd = CMD_ZOOM_POS
                elif axis == "focus":
                    cmd = CMD_FOCUS_POS
                else:
                    cmd = CMD_IRIS_POS
                self.transport.write(build_type_b(cmd, SUBCMD_C0, target))
                frame = self._wait_for_prefix((cmd, SUBCMD_C0), 1200)
                if not frame:
                    print("[LENS][Canon][BIT] FAIL:", axis, "target", target, "no readback")
                    return False
                value = unpack_type_b_value(frame[2], frame[3], frame[4])
                print("[LENS][Canon][BIT]", axis, "target", target, "readback", value)
        return True

    def _apply_all_sources(self):
        for axis in AXES:
            self._send_axis_source(axis)

    def _send_axis_source(self, axis):
        src = self.axis_sources.get(axis, SOURCE_PC)
        if src == SOURCE_PC:
            src_bits = SRC_PC
        elif src == SOURCE_CAMERA:
            src_bits = SRC_CAMERA
        else:
            src_bits = SRC_OFF

        if axis == "zoom":
            scmd = SCMD_ZOOM_SWITCH
        elif axis == "focus":
            scmd = SCMD_FOCUS_SWITCH
        else:
            scmd = SCMD_IRIS_SWITCH

        self.transport.write(build_type_c_switch(scmd, src_bits))

    def _drain_rx(self):
        while True:
            data = self.transport.read()
            if not data:
                return

    def _update_control_targets(self, now_ms):
        if self._last_control_update_ms == 0:
            dt_ms = CONTROL_TX_PERIOD_MS
        else:
            dt_ms = _ticks_diff(now_ms, self._last_control_update_ms)
            if dt_ms < 1:
                dt_ms = 1
            if dt_ms > 200:
                dt_ms = 200
        self._last_control_update_ms = now_ms
        self._update_zoom_speed_from_velocity()
        self.focus = self._apply_axis_filter("focus", self.focus, self.focus_target, dt_ms)
        self.iris = self._apply_axis_filter("iris", self.iris, self.iris_target, dt_ms)

    def _update_zoom_speed_from_velocity(self):
        d = int(self.zoom_velocity_cmd)
        if d > ZOOM_INPUT_MAX:
            d = ZOOM_INPUT_MAX
        elif d < -ZOOM_INPUT_MAX:
            d = -ZOOM_INPUT_MAX
        if -ZOOM_DEADBAND <= d <= ZOOM_DEADBAND:
            signed_speed = 0
        else:
            signed_speed = int(round((d / float(ZOOM_INPUT_MAX)) * float(ZOOM_SPEED_MAX)))
        self.zoom_speed_raw = 0x8000 + signed_speed

    def _apply_axis_filter(self, axis, current, target, dt_ms):
        cur = int(current)
        tgt = int(target)
        if axis in ("focus", "iris") and self._filter_enabled.get(axis, False):
            num = int(self._filter_num)
            den = int(self._filter_den)
            if den > 0:
                cur = cur + ((tgt - cur) * num) // den
        max_step = int((FILTER_MAX_RATE_PER_S * int(dt_ms)) / 1000)
        if max_step < 1:
            max_step = 1
        delta = tgt - cur
        if delta > max_step:
            delta = max_step
        elif delta < -max_step:
            delta = -max_step
        return _clamp_u16_60000(cur + delta)

    def _send_axis_controls(self, now_ms):
        if self.axis_sources["zoom"] == SOURCE_PC:
            d = int(self.zoom_velocity_cmd)
            if d > ZOOM_INPUT_MAX:
                d = ZOOM_INPUT_MAX
            elif d < -ZOOM_INPUT_MAX:
                d = -ZOOM_INPUT_MAX
            if -ZOOM_DEADBAND <= d <= ZOOM_DEADBAND:
                signed_speed = 0
            else:
                signed_speed = int(round((d / float(ZOOM_INPUT_MAX)) * float(ZOOM_SPEED_MAX)))
            self.transport.write(build_zoom_speed_control_signed(signed_speed))
        if self.axis_sources["focus"] == SOURCE_PC:
            self.transport.write(build_type_b(CMD_FOCUS_POS, SUBCMD_C0, self.focus))
        if self.axis_sources["iris"] == SOURCE_PC:
            self.transport.write(build_type_b(CMD_IRIS_POS, SUBCMD_C0, self.iris))
        self._last_control_tx_ms = int(now_ms)
        if CANON_DEBUG:
            print(
                "[LENS][Canon] periodic zoom_speed_raw=%d vel=%d focus=%d/%d iris=%d/%d filt(f=%d i=%d %d/%d)"
                % (
                    self.zoom_speed_raw,
                    self.zoom_velocity_cmd,
                    self.focus,
                    self.focus_target,
                    self.iris,
                    self.iris_target,
                    1 if self._filter_enabled.get("focus", False) else 0,
                    1 if self._filter_enabled.get("iris", False) else 0,
                    self._filter_num,
                    self._filter_den,
                )
            )

    def _wait_for_prefix(self, prefix, timeout_ms):
        start = _ticks_ms()
        while _ticks_diff(_ticks_ms(), start) < timeout_ms:
            for frame in self._poll_frames():
                if frame.startswith(bytes(prefix)):
                    return frame
            self.periodic(_ticks_ms())
            _sleep_ms(10)
        return None

    def _poll_frames(self):
        data = self.transport.read()
        if data:
            self._rx_buf.extend(data)
        frames = []
        while self._rx_buf:
            if self._rx_buf[0] == 0xBE:
                end_i = _index_of(self._rx_buf, 0xBF, 1)
                if end_i < 0:
                    break
                frames.append(bytes(self._rx_buf[: end_i + 1]))
                self._rx_buf = self._rx_buf[end_i + 1 :]
                continue
            if len(self._rx_buf) >= 3 and self._rx_buf[2] == 0xBF:
                frames.append(bytes(self._rx_buf[:3]))
                self._rx_buf = self._rx_buf[3:]
                continue
            if len(self._rx_buf) >= 6 and self._rx_buf[5] == 0xBF:
                frames.append(bytes(self._rx_buf[:6]))
                self._rx_buf = self._rx_buf[6:]
                continue
            if len(self._rx_buf) < 6:
                break
            self._rx_buf = self._rx_buf[1:]
        return frames


def _clamp_u16_60000(v):
    if v < 0:
        return 0
    if v > 60000:
        return 60000
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
    if v > 0xFFFF:
        v = 0xFFFF
    return int((v * out_max) // 0xFFFF)


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


def _index_of(buf, value, start):
    i = start
    while i < len(buf):
        if buf[i] == value:
            return i
        i += 1
    return -1
