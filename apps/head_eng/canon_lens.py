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
    build_type_b,
    build_type_c_switch,
    decode_lens_name_type_c,
    unpack_type_b_value,
)

SOURCE_PC = "pc"
SOURCE_CAMERA = "camera"
SOURCE_OFF = "off"
AXES = ("zoom", "focus", "iris")
ZOOM_DELTA_SCALE = 10
ZOOM_DEADBAND = 1
AXIS_HOLD_THRESHOLD = 120


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
        self.axis_sources = {axis: SOURCE_PC for axis in AXES}
        self._next_keepalive_ms = 0
        self._next_source_refresh_ms = 0
        self._rx_buf = bytearray()

    def on_activate(self):
        self.transport.write(FINISH_INIT)
        self._apply_all_sources()
        self._next_keepalive_ms = 0
        self._next_source_refresh_ms = 0

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
        self.axis_sources[axis] = source
        self._send_axis_source(axis)
        return True

    def move_zoom(self, delta):
        if self.axis_sources["zoom"] != SOURCE_PC:
            return
        d = int(delta)
        if -ZOOM_DEADBAND <= d <= ZOOM_DEADBAND:
            return
        self.zoom = _clamp_u16_60000(self.zoom + (d * ZOOM_DELTA_SCALE))
        self.transport.write(build_type_b(CMD_ZOOM_POS, SUBCMD_C0, self.zoom))

    def set_focus_input(self, raw_value):
        if self.axis_sources["focus"] != SOURCE_PC:
            return
        v = _normalize_input(raw_value, 60000)
        if abs(v - self.focus) < AXIS_HOLD_THRESHOLD:
            return
        self.focus = v
        self.transport.write(build_type_b(CMD_FOCUS_POS, SUBCMD_C0, self.focus))

    def set_iris_input(self, raw_value):
        if self.axis_sources["iris"] != SOURCE_PC:
            return
        v = _normalize_input(raw_value, 60000)
        if abs(v - self.iris) < AXIS_HOLD_THRESHOLD:
            return
        self.iris = v
        self.transport.write(build_type_b(CMD_IRIS_POS, SUBCMD_C0, self.iris))

    def periodic(self, now_ms):
        if _time_after(now_ms, self._next_keepalive_ms):
            self.transport.write(CTRL_CMD)
            self._next_keepalive_ms = now_ms + 200
        if _time_after(now_ms, self._next_source_refresh_ms):
            self._apply_all_sources()
            self._next_source_refresh_ms = now_ms + 1500

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
        return decode_lens_name_type_c(frame)

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
