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
FUJI_DEBUG = True


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
        self._rx_buf = bytearray()
        self._last_sw4_readback = None
        self._next_sw4_reassert_ms = 0

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

    def move_zoom(self, delta):
        if self.axis_sources["zoom"] != SOURCE_PC:
            return
        d = int(delta)
        if -ZOOM_DEADBAND <= d <= ZOOM_DEADBAND:
            return
        self.zoom = _clamp_u16(self.zoom + (d * ZOOM_DELTA_SCALE))
        self.transport.write(build_zoom_control(self.zoom))

    def set_focus_input(self, raw_value):
        if self.axis_sources["focus"] != SOURCE_PC:
            return
        v = _normalize_input(raw_value, 0xFFFF)
        if abs(v - self.focus) < AXIS_HOLD_THRESHOLD:
            return
        self.focus = v
        self.transport.write(build_focus_control(self.focus))

    def set_iris_input(self, raw_value):
        if self.axis_sources["iris"] != SOURCE_PC:
            return
        v = _normalize_input(raw_value, 0xFFFF)
        if abs(v - self.iris) < AXIS_HOLD_THRESHOLD:
            return
        self.iris = v
        self.transport.write(build_iris_control(self.iris))

    def periodic(self, now_ms):
        for frame in self._poll_frames():
            self._handle_runtime_frame(frame, now_ms)

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

    def startup_diagnostics(self):
        print("[LENS][Fuji] startup diagnostics begin")
        # Prime handshake first; many lenses return name only after link setup.
        self._send_and_wait(lambda: build_connect(True), {FUNC_CONNECT}, retries=3, timeout_ms=1500)
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
        if not self._send_and_wait(lambda: build_connect(True), {FUNC_CONNECT}, retries=3, timeout_ms=1500):
            print("[LENS][Fuji][BIT] WARN: no connect ACK")
        _sleep_ms(200)

        self._send_switch4()
        _sleep_ms(200)
        if not self._send_and_wait(build_switch4_position_request, {FUNC_SWITCH_4_POSITION}, retries=3, timeout_ms=1500):
            print("[LENS][Fuji][BIT] WARN: no SW4 readback")
        _sleep_ms(200)

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
                print("[LENS][Fuji][BIT]", axis, "target", target, "readback", value)
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
                self._rx_buf = self._rx_buf[1:]
                continue
            frames.append(frame)
            self._rx_buf = self._rx_buf[frame_len:]
        return frames

    def _send_switch4(self):
        bits = self._current_sw4_bits()
        if FUJI_DEBUG:
            print("[LENS][Fuji] TX SW4_CONTROL bits=0x{:02X}".format(bits))
        self.transport.write(build_switch4_control(bits))

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
            if bits != self._last_sw4_readback and FUJI_DEBUG:
                print(
                    "[LENS][Fuji] RX SW4_POSITION bits=0x{:02X} desired=0x{:02X}".format(
                        bits, desired
                    )
                )
            self._last_sw4_readback = bits
            if bits != desired and _time_after(now_ms, self._next_sw4_reassert_ms):
                if FUJI_DEBUG:
                    print("[LENS][Fuji] SW4 mismatch -> reassert host control")
                self._send_switch4()
                self._next_sw4_reassert_ms = now_ms + 150


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
