from canon_protocol import (
    CTRL_CMD,
    FINISH_INIT,
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
)

SOURCE_PC = "pc"
SOURCE_CAMERA = "camera"
SOURCE_OFF = "off"
AXES = ("zoom", "focus", "iris")


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
        self.zoom = _clamp_u16_60000(self.zoom + int(delta))
        self.transport.write(build_type_b(CMD_ZOOM_POS, SUBCMD_C0, self.zoom))

    def set_focus_input(self, raw_value):
        if self.axis_sources["focus"] != SOURCE_PC:
            return
        self.focus = _normalize_input(raw_value, 60000)
        self.transport.write(build_type_b(CMD_FOCUS_POS, SUBCMD_C0, self.focus))

    def set_iris_input(self, raw_value):
        if self.axis_sources["iris"] != SOURCE_PC:
            return
        self.iris = _normalize_input(raw_value, 60000)
        self.transport.write(build_type_b(CMD_IRIS_POS, SUBCMD_C0, self.iris))

    def periodic(self, now_ms):
        if _time_after(now_ms, self._next_keepalive_ms):
            self.transport.write(CTRL_CMD)
            self._next_keepalive_ms = now_ms + 200
        if _time_after(now_ms, self._next_source_refresh_ms):
            self._apply_all_sources()
            self._next_source_refresh_ms = now_ms + 1500

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
    if v <= 64:
        return int((v * out_max) // 64)
    if v <= out_max:
        return v
    if v > 0xFFFF:
        v = 0xFFFF
    return int((v * out_max) // 0xFFFF)


def _time_after(now_ms, target_ms):
    return now_ms >= target_ms
