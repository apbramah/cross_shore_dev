from fuji_protocol import (
    FUJI_BAUD,
    FUJI_BITS,
    FUJI_PARITY,
    FUJI_STOP,
    SW4_HOST_ALL,
    build_connect,
    build_focus_control,
    build_iris_control,
    build_position_request_focus,
    build_position_request_iris,
    build_position_request_zoom,
    build_switch4_control,
    build_switch4_position_request,
    build_zoom_control,
)

SOURCE_PC = "pc"
SOURCE_CAMERA = "camera"
SOURCE_OFF = "off"
AXES = ("zoom", "focus", "iris")


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

    def on_activate(self):
        self.transport.write(build_connect(True))
        self._send_switch4()
        self._next_keepalive_ms = 0
        self._next_poll_ms = 0

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
        self._send_switch4()
        return True

    def move_zoom(self, delta):
        if self.axis_sources["zoom"] != SOURCE_PC:
            return
        self.zoom = _clamp_u16(self.zoom + int(delta))
        self.transport.write(build_zoom_control(self.zoom))

    def set_focus_input(self, raw_value):
        if self.axis_sources["focus"] != SOURCE_PC:
            return
        self.focus = _normalize_input(raw_value, 0xFFFF)
        self.transport.write(build_focus_control(self.focus))

    def set_iris_input(self, raw_value):
        if self.axis_sources["iris"] != SOURCE_PC:
            return
        self.iris = _normalize_input(raw_value, 0xFFFF)
        self.transport.write(build_iris_control(self.iris))

    def periodic(self, now_ms):
        if _time_after(now_ms, self._next_keepalive_ms):
            self._send_switch4()
            self._next_keepalive_ms = now_ms + 250
        if _time_after(now_ms, self._next_poll_ms):
            # Match tester behavior: keep light polling alive while owning controls.
            self.transport.write(build_switch4_position_request())
            self.transport.write(build_position_request_zoom())
            self.transport.write(build_position_request_focus())
            self.transport.write(build_position_request_iris())
            self._next_poll_ms = now_ms + 500

    def _send_switch4(self):
        self.transport.write(build_switch4_control(self._current_sw4_bits()))

    def _current_sw4_bits(self):
        bits = SW4_HOST_ALL
        if self.axis_sources["focus"] != SOURCE_PC:
            bits |= 0x01
        if self.axis_sources["zoom"] != SOURCE_PC:
            bits |= 0x02
        if self.axis_sources["iris"] != SOURCE_PC:
            bits |= 0x04
        return bits & 0xFF


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
    # Existing controller map for focus/iris is 0..64. Scale that to lens range.
    if v <= 64:
        return int((v * out_max) // 64)
    if v <= out_max:
        return v
    # Treat out-of-range as 16-bit and rescale.
    if v > 0xFFFF:
        v = 0xFFFF
    return int((v * out_max) // 0xFFFF)


def _time_after(now_ms, target_ms):
    return now_ms >= target_ms
