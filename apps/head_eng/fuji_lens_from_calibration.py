from fuji_protocol import (
    FUJI_BAUD,
    FUJI_BITS,
    FUJI_PARITY,
    FUJI_STOP,
    FUNC_FOCUS_CONTROL,
    FUNC_IRIS_CONTROL,
    FUNC_ZOOM_CONTROL,
    FUNC_ZOOM_SPEED_CONTROL,
    build_focus_control,
    build_iris_control,
    build_zoom_control,
    build_zoom_speed_control,
)

from fuji_control_calibration_copy import (
    CONNECT_KEEPALIVE_MS,
    SW4_POLL_MS,
    UPDATE_MS,
    FujiCalibration,
)

SOURCE_PC = "pc"
SOURCE_CAMERA = "camera"
SOURCE_OFF = "off"
AXES = ("zoom", "focus", "iris")
ZOOM_DELTA_SCALE = 16
# Set True to log focus input and periodic target (Fuji connection debug).
FUJI_FOCUS_DEBUG = False
FUJI_FOCUS_DEBUG_INTERVAL_MS = 500
# Baseline mode: no deadband/expo hold so fast path preserves full resolution (ADC Fast Path Cleanup).
BASELINE_ZOOM_DEADBAND = 0
BASELINE_ZOOM_EXPO_PCT = 0
BASELINE_AXIS_HOLD_THRESHOLD = 0
# Legacy defaults (use for non-baseline if needed).
ZOOM_DEADBAND = BASELINE_ZOOM_DEADBAND
ZOOM_EXPO_PCT = BASELINE_ZOOM_EXPO_PCT
AXIS_HOLD_THRESHOLD = BASELINE_AXIS_HOLD_THRESHOLD
ZOOM_INPUT_MAX = 64
CONTROL_TX_PERIOD_MS = 20
ZOOM_MODE_POSITION = "position"
ZOOM_MODE_SPEED = "speed"
DEFAULT_ZOOM_MODE = ZOOM_MODE_SPEED


class FujiLens(FujiCalibration):
    baud = FUJI_BAUD
    bits = FUJI_BITS
    parity = FUJI_PARITY
    stop = FUJI_STOP

    def __init__(self, transport):
        super().__init__(transport)
        self.zoom = 0x7FFF
        self.zoom_speed = 0x8000
        self.focus = 0x7FFF
        self.iris = 0x7FFF
        self.zoom_mode = DEFAULT_ZOOM_MODE
        self.axis_sources = {axis: SOURCE_PC for axis in AXES}
        self._next_control_tx_ms = 0
        self._faulted = False
        self._fault_reason = ""
        self._last_zoom_input = 0

    def on_activate(self):
        self._failed = False
        self._faulted = False
        self._fault_reason = ""
        self._sw4_mismatch_count = 0
        self._sw4_recovery_attempts = 0
        self._connect()
        self._force_sw4_pc()
        now_ms = _ticks_ms()
        self._next_sw4_poll_ms = now_ms + SW4_POLL_MS
        self._next_connect_keepalive_ms = now_ms + CONNECT_KEEPALIVE_MS
        self._next_control_tx_ms = now_ms + CONTROL_TX_PERIOD_MS
        self._last_control_tx_ms = 0

    def get_axis_sources(self):
        return dict(self.axis_sources)

    def set_axis_source(self, axis, source):
        if axis not in self.axis_sources:
            return False
        if source not in (SOURCE_PC, SOURCE_CAMERA, SOURCE_OFF):
            return False
        self.axis_sources[axis] = source
        return True

    def set_zoom_mode(self, mode):
        """Hook for future slow-message zoom mode selection."""
        m = str(mode).lower().strip()
        if m not in (ZOOM_MODE_SPEED, ZOOM_MODE_POSITION):
            return False
        self.zoom_mode = m
        return True

    def move_zoom(self, delta):
        if self.axis_sources["zoom"] != SOURCE_PC:
            return
        d = int(delta)
        if -ZOOM_DEADBAND <= d <= ZOOM_DEADBAND:
            if self.zoom_mode == ZOOM_MODE_SPEED:
                self.zoom_speed = 0x8000
                return
            return
        d = _shape_zoom_input_expo(d, ZOOM_EXPO_PCT, ZOOM_INPUT_MAX)
        if self.zoom_mode == ZOOM_MODE_SPEED:
            # Map signed demand to Fuji speed domain: 0x0000 wide, 0x8000 stop, 0xFFFF tele.
            if d > ZOOM_INPUT_MAX:
                d = ZOOM_INPUT_MAX
            elif d < -ZOOM_INPUT_MAX:
                d = -ZOOM_INPUT_MAX
            span = 32767.0
            self.zoom_speed = _clamp_u16(round(0x8000 + (d / float(ZOOM_INPUT_MAX)) * span))
            return
        # Position-mode hook (future slow-message selection); keeps prior behavior.
        self.zoom = _clamp_u16(self.zoom + (d * ZOOM_DELTA_SCALE))

    def set_focus_input(self, raw_value):
        if self.axis_sources["focus"] != SOURCE_PC:
            if FUJI_FOCUS_DEBUG:
                print("[LENS][Fuji][FOCUS] set_focus_input SKIP axis_sources[focus] != PC")
            return
        v = _normalize_input(raw_value, 0xFFFF)
        if abs(v - self.focus) < AXIS_HOLD_THRESHOLD:
            if FUJI_FOCUS_DEBUG:
                _log_focus_input(raw_value, v, "hold_skip", self.focus)
            return
        prev = self.focus
        self.focus = v
        if FUJI_FOCUS_DEBUG:
            _log_focus_input(raw_value, v, "updated", prev)

    def set_iris_input(self, raw_value):
        if self.axis_sources["iris"] != SOURCE_PC:
            return
        v = _normalize_input(raw_value, 0xFFFF)
        if abs(v - self.iris) < AXIS_HOLD_THRESHOLD:
            return
        self.iris = v

    def write_raw(self, data):
        self.transport.write(data)

    def read_raw(self):
        return self.transport.read()

    def periodic(self, now_ms):
        if self._faulted:
            return
        self._poll_watchdog(now_ms)
        if self._failed:
            self._set_fault("SW4 ownership mismatch (calibration baseline runtime)")
            return
        if now_ms >= self._next_control_tx_ms:
            self._send_runtime_controls()
            self._next_control_tx_ms = now_ms + CONTROL_TX_PERIOD_MS

    def startup_diagnostics(self):
        # Telemetry-only path; runtime loop is intentionally ungated.
        lens_name = self._read_lens_name()
        if lens_name:
            print("[LENS][Fuji] Lens ID:", lens_name)
        return True

    def _send_runtime_controls(self):
        if FUJI_FOCUS_DEBUG:
            now_ms = _ticks_ms()
            if not hasattr(self, "_last_focus_log_ms"):
                self._last_focus_log_ms = 0
            if now_ms - self._last_focus_log_ms >= FUJI_FOCUS_DEBUG_INTERVAL_MS:
                self._last_focus_log_ms = now_ms
                print(
                    "[LENS][Fuji][FOCUS] periodic zoom_mode={} zoom_pos=0x{:04X} zoom_speed=0x{:04X} focus=0x{:04X} iris=0x{:04X} faulted={}".format(
                        self.zoom_mode, self.zoom, self.zoom_speed, self.focus, self.iris, self._faulted
                    )
                )
        if self.axis_sources["zoom"] == SOURCE_PC:
            if self.zoom_mode == ZOOM_MODE_SPEED:
                self._send_control(
                    build_zoom_speed_control(self.zoom_speed),
                    "ZOOM_SPEED_CONTROL",
                    FUNC_ZOOM_SPEED_CONTROL,
                )
            else:
                self._send_control(build_zoom_control(self.zoom), "ZOOM_CONTROL", FUNC_ZOOM_CONTROL)
        if self.axis_sources["focus"] == SOURCE_PC:
            self._send_control(build_focus_control(self.focus), "FOCUS_CONTROL", FUNC_FOCUS_CONTROL)
        if self.axis_sources["iris"] == SOURCE_PC:
            self._send_control(build_iris_control(self.iris), "IRIS_CONTROL", FUNC_IRIS_CONTROL)

    def _set_fault(self, reason):
        if self._faulted:
            return
        self._faulted = True
        self._fault_reason = str(reason)
        print("[LENS][Fuji][FAULT]", self._fault_reason)
        self._print_ack_stats(prefix="[LENS][Fuji][ACK]")


def _ticks_ms():
    import time

    if hasattr(time, "ticks_ms"):
        return time.ticks_ms()
    return int(time.time() * 1000)


def _clamp_u16(v):
    if v < 0:
        return 0
    if v > 0xFFFF:
        return 0xFFFF
    return int(v)


def _log_focus_input(raw_value, normalized_v, reason, current_focus):
    t = _ticks_ms()
    print(
        "[LENS][Fuji][FOCUS] set_focus_input raw={} norm=0x{:04X} {} focus=0x{:04X} t={}".format(
            raw_value, normalized_v & 0xFFFF, reason, current_focus & 0xFFFF, t
        )
    )


def _normalize_input(raw_value, out_max):
    # Runtime fast path already provides u16-domain values. Keep passthrough clamp only.
    _ = out_max
    v = int(raw_value)
    if v < 0:
        return 0
    if v > 0xFFFF:
        return 0xFFFF
    return v


def _shape_zoom_input_expo(value, expo_pct, input_max):
    v = int(value)
    p = int(expo_pct)
    if p <= 0:
        return v
    if p > 100:
        p = 100
    m = int(input_max)
    if m < 1:
        return v
    if v > m:
        v = m
    elif v < -m:
        v = -m
    linear = v
    cubic = (v * v * v) // (m * m)
    return ((linear * (100 - p)) + (cubic * p)) // 100
