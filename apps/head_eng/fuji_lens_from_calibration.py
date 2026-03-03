from fuji_protocol import (
    FUJI_BAUD,
    FUJI_BITS,
    FUJI_PARITY,
    FUJI_STOP,
    FUNC_FOCUS_CONTROL,
    FUNC_IRIS_CONTROL,
    FUNC_ZOOM_CONTROL,
    build_focus_control,
    build_iris_control,
    build_zoom_control,
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


class FujiLens(FujiCalibration):
    baud = FUJI_BAUD
    bits = FUJI_BITS
    parity = FUJI_PARITY
    stop = FUJI_STOP

    def __init__(self, transport):
        super().__init__(transport)
        self.zoom = 0x7FFF
        self.focus = 0x7FFF
        self.iris = 0x7FFF
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

    def move_zoom(self, delta):
        if self.axis_sources["zoom"] != SOURCE_PC:
            return
        d = int(delta)
        if -ZOOM_DEADBAND <= d <= ZOOM_DEADBAND:
            return
        d = _shape_zoom_input_expo(d, ZOOM_EXPO_PCT, ZOOM_INPUT_MAX)
        self.zoom = _clamp_u16(self.zoom + (d * ZOOM_DELTA_SCALE))

    def set_focus_input(self, raw_value):
        if self.axis_sources["focus"] != SOURCE_PC:
            return
        v = _normalize_input(raw_value, 0xFFFF)
        if abs(v - self.focus) < AXIS_HOLD_THRESHOLD:
            return
        self.focus = v

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
        if self.axis_sources["zoom"] == SOURCE_PC:
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


def _normalize_input(raw_value, out_max):
    v = int(raw_value)
    if v < 0:
        v = 0
    if v <= 64:
        return int((v * out_max) // 64)
    if v <= 16384:
        return int((v * out_max) // 16384)
    if v <= out_max:
        return v
    if v > 0xFFFF:
        v = 0xFFFF
    return int((v * out_max) // 0xFFFF)


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
