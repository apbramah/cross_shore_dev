"""
Canon port adapter for payload manager.

Implements the proven startup transaction policy used on head:
CTRL_CMD -> FINISH_INIT -> LENS_NAME_REQ with bounded retries, echo-aware
parsing, and strict validation gate (decoded name or Type-B readback).
"""

import time
from machine import UART, Pin

CTRL_CMD = bytes([0x80, 0xC6, 0xBF])
FINISH_INIT = bytes([0x86, 0xC0, 0x00, 0x00, 0x00, 0xBF])
LENS_NAME_REQ = bytes([0xBE, 0x80, 0x81, 0x00, 0x00, 0x00, 0xBF])

LENS_NAME_PREP_WAIT_MS = 180
LENS_NAME_STEP_GAP_MS = 60
LENS_NAME_WAIT_MS = 1400
LENS_NAME_RETRY_BACKOFF_MS = 120
LENS_NAME_MINIMAL_ATTEMPTS = 2
LENS_NAME_READ_ATTEMPTS = 3
LENS_NAME_REQS_PER_PASS = 2
LENS_NAME_UART_CONFIGS = (
    (19200, 0),    # 8E1 canonical
    (19200, None), # 8N1 fallback (RP2040 parity edge cases)
)
CONTROL_READBACK_TIMEOUT_MS = 120
CONTROL_KEEPALIVE_MS = 200
ACTIVATE_STEP_GAP_MS = 60
CONTROL_TX_PERIOD_MS = 10
SOURCE_REFRESH_MS = 1500
ZOOM_INPUT_MAX = 64
ZOOM_DEADBAND = 1
ZOOM_SPEED_MAX = 18360
SUBCMD_C1 = 0xC1

CMD_ZOOM_POS = 0x87
CMD_FOCUS_POS = 0x88
CMD_IRIS_POS = 0x96
SUBCMD_C0 = 0xC0
SRC_CAMERA = 0x08
SRC_PC = 0x10
SCMD_IRIS_SWITCH = 0x81
SCMD_ZOOM_SWITCH = 0x83
SCMD_FOCUS_SWITCH = 0x85


def _sleep_ms(ms):
    if hasattr(time, "sleep_ms"):
        time.sleep_ms(int(ms))
    else:
        time.sleep(float(ms) / 1000.0)


def _ticks_ms():
    if hasattr(time, "ticks_ms"):
        return time.ticks_ms()
    return int(time.time() * 1000)


def _ticks_diff(a, b):
    if hasattr(time, "ticks_diff"):
        return time.ticks_diff(a, b)
    return int(a) - int(b)


def _index_of(buf, value, start):
    i = int(start)
    n = len(buf)
    while i < n:
        if buf[i] == value:
            return i
        i += 1
    return -1


def _sanitize_lens_name(name):
    s = str(name or "").strip()
    if s.startswith("&"):
        s = s[1:]
    out = []
    for ch in s:
        o = ord(ch)
        if 32 <= o <= 126:
            out.append(ch)
    s = "".join(out).strip()
    return s or None


def _decode_pairs_ascii_le(payload):
    chars = []
    i = 0
    while i + 1 < len(payload):
        lo = payload[i]
        hi = payload[i + 1]
        cp = lo | (hi << 8)
        if cp != 0 and 32 <= cp <= 126:
            chars.append(cp)
        i += 2
    if not chars:
        return None
    return bytes(chars).decode("ascii", errors="ignore")


def _decode_pairs_ascii_be(payload):
    chars = []
    i = 0
    while i + 1 < len(payload):
        lo = payload[i]
        hi = payload[i + 1]
        cp = (lo << 8) | hi
        if cp != 0 and 32 <= cp <= 126:
            chars.append(cp)
        i += 2
    if not chars:
        return None
    return bytes(chars).decode("ascii", errors="ignore")


def _decode_plain_ascii(payload):
    chars = []
    for b in payload:
        if 32 <= b <= 126:
            chars.append(b)
    if not chars:
        return None
    return bytes(chars).decode("ascii", errors="ignore")


def _decode_plain_ascii_7bit(payload):
    chars = []
    for b in payload:
        c = b & 0x7F
        if 32 <= c <= 126:
            chars.append(c)
    if not chars:
        return None
    return bytes(chars).decode("ascii", errors="ignore")


def decode_lens_name_type_c(frame):
    if not frame or len(frame) < 7:
        return None
    if frame[0] != 0xBE or frame[1] != 0x80 or frame[2] != 0x81 or frame[-1] != 0xBF:
        return None
    payload = frame[3:-1]
    candidates = []
    for decoder in (
        _decode_pairs_ascii_le,
        _decode_pairs_ascii_be,
        _decode_plain_ascii,
        _decode_plain_ascii_7bit,
    ):
        try:
            c = decoder(payload)
        except Exception:
            c = None
        c = _sanitize_lens_name(c)
        if c:
            candidates.append(c)
    if not candidates:
        return None
    return max(candidates, key=lambda s: len(s))


def _extract_lens_name_from_bytes(buf):
    if not buf or len(buf) < 7:
        return None
    i = 0
    n = len(buf)
    while i + 3 <= n:
        if not (buf[i] == 0xBE and (i + 2) < n and buf[i + 1] == 0x80 and buf[i + 2] == 0x81):
            i += 1
            continue
        j = _index_of(buf, 0xBF, i + 3)
        if j < 0:
            break
        frame = bytes(buf[i : j + 1])
        name = decode_lens_name_type_c(frame)
        if name:
            return name
        i = j + 1
    return None


def _clamp_u16_60000(v):
    x = int(v)
    if x < 0:
        return 0
    if x > 60000:
        return 60000
    return x


def pack_type_b_value(v):
    x = _clamp_u16_60000(v)
    return ((x >> 14) & 0x03, (x >> 7) & 0x7F, x & 0x7F)


def unpack_type_b_value(d1, d2, d3):
    return ((d1 & 0x03) << 14) | ((d2 & 0x7F) << 7) | (d3 & 0x7F)


def build_type_b(cmd, subcmd, value):
    d1, d2, d3 = pack_type_b_value(value)
    return bytes([int(cmd) & 0xFF, int(subcmd) & 0xFF, d1, d2, d3, 0xBF])


def build_zoom_speed_control_signed(signed_speed):
    s = int(signed_speed)
    if s > ZOOM_SPEED_MAX:
        s = ZOOM_SPEED_MAX
    elif s < -ZOOM_SPEED_MAX:
        s = -ZOOM_SPEED_MAX
    raw = 0x8000 + s
    return build_type_b(CMD_ZOOM_POS, SUBCMD_C1, raw)


def build_type_c_switch(scmd, src_bits):
    # BE 85 <S-CMD> 01 00 02 00 <DATA1> BF
    return bytes([0xBE, 0x85, int(scmd) & 0xFF, 0x01, 0x00, 0x02, 0x00, int(src_bits) & 0x7F, 0xBF])


class CanonPort:
    def __init__(
        self,
        uart_id=1,
        tx_pin=8,
        rx_pin=9,
        baud=19200,
        bits=8,
        parity=0,
        stop=1,
        debug=False,
    ):
        self.uart_id = int(uart_id)
        self.tx_pin = int(tx_pin)
        self.rx_pin = int(rx_pin)
        self.baud = int(baud)
        self.bits = int(bits)
        self.parity = parity
        self.stop = int(stop)
        self.uart = UART(
            self.uart_id,
            self.baud,
            tx=Pin(self.tx_pin),
            rx=Pin(self.rx_pin),
            bits=self.bits,
            parity=self.parity,
            stop=self.stop,
        )
        self.lens_name = ""
        self.zoom = 30000
        self.focus = 30000
        self.iris = 30000
        self.zoom_target = self.zoom
        self.focus_target = self.focus
        self.iris_target = self.iris
        self.zoom_velocity_cmd = 0
        self.zoom_speed_raw = 0x8000
        self.control_tx_period_ms = CONTROL_TX_PERIOD_MS
        self.debug = bool(debug)
        self._rx_buf = bytearray()
        self._activated = False
        self._next_keepalive_ms = 0
        self._next_source_refresh_ms = 0
        self._next_control_tx_ms = 0
        self._last_control_tx_ms = 0
        self._last_zoom_feedback = None
        self._last_focus_feedback = None
        self._last_iris_feedback = None
        if self.debug:
            print(
                "[CANON_PORT] uart={} tx=GP{} rx=GP{} baud={} bits={} parity={} stop={}".format(
                    self.uart_id,
                    self.tx_pin,
                    self.rx_pin,
                    self.baud,
                    self.bits,
                    self.parity,
                    self.stop,
                )
            )

    def _hex_preview(self, data, max_len=24):
        if not data:
            return ""
        view = data[: int(max_len)]
        return " ".join("{:02X}".format(b) for b in view)

    def _configure_uart(self):
        try:
            self.uart.init(self.baud, bits=self.bits, parity=self.parity, stop=self.stop)
        except Exception:
            # Keep pre-configured UART if init() is not available in this build.
            pass

    def _drain_rx(self):
        while True:
            data = self.uart.read()
            if not data:
                return

    def _poll_frames(self):
        data = self.uart.read()
        if data:
            self._rx_buf.extend(data)
        frames = []
        while self._rx_buf:
            if self._rx_buf[0] == 0xBE:
                end_i = _index_of(self._rx_buf, 0xBF, 1)
                if end_i < 0:
                    break
                frames.append(bytes(self._rx_buf[: end_i + 1]))
                self._rx_buf[:] = self._rx_buf[end_i + 1 :]
                continue
            if len(self._rx_buf) >= 3 and self._rx_buf[2] == 0xBF:
                frames.append(bytes(self._rx_buf[:3]))
                self._rx_buf[:] = self._rx_buf[3:]
                continue
            if len(self._rx_buf) >= 6 and self._rx_buf[5] == 0xBF:
                frames.append(bytes(self._rx_buf[:6]))
                self._rx_buf[:] = self._rx_buf[6:]
                continue
            if len(self._rx_buf) < 6:
                break
            self._rx_buf[:] = self._rx_buf[1:]
        return frames

    def _read_name_frames(self, wait_ms, ignore_frame=None):
        deadline = _ticks_ms() + int(wait_ms)
        raw = bytearray()
        ignore = bytes(ignore_frame) if ignore_frame else None
        saw_rx = False
        while _ticks_diff(deadline, _ticks_ms()) > 0:
            frames = self._poll_frames()
            if frames:
                saw_rx = True
                for frame in frames:
                    if not frame:
                        continue
                    raw.extend(frame)
                    # Ignore local echo of the frame we just wrote.
                    if ignore is not None and frame == ignore:
                        continue
                    name = decode_lens_name_type_c(frame)
                    if name:
                        return name, saw_rx
                name = _extract_lens_name_from_bytes(raw)
                if name:
                    return name, saw_rx
            else:
                _sleep_ms(5)
        return None, saw_rx

    def _send_axis_source(self, axis, source):
        src = SRC_PC if str(source).lower().strip() == "pc" else SRC_CAMERA
        if axis == "zoom":
            scmd = SCMD_ZOOM_SWITCH
        elif axis == "focus":
            scmd = SCMD_FOCUS_SWITCH
        else:
            scmd = SCMD_IRIS_SWITCH
        self.uart.write(build_type_c_switch(scmd, src))

    def _apply_all_sources(self):
        self._send_axis_source("zoom", "pc")
        self._send_axis_source("focus", "pc")
        self._send_axis_source("iris", "pc")

    def _activate_session(self):
        self._configure_uart()
        self._drain_rx()
        self._rx_buf = bytearray()
        # Canon policy: startup handshake before control/readback.
        self.uart.write(CTRL_CMD)
        _sleep_ms(ACTIVATE_STEP_GAP_MS)
        self.uart.write(FINISH_INIT)
        _sleep_ms(ACTIVATE_STEP_GAP_MS)
        self._apply_all_sources()
        self._next_keepalive_ms = 0
        self._next_source_refresh_ms = 0
        self._next_control_tx_ms = 0
        self._activated = True
        if self.debug:
            print("[CANON_PORT] session activated (ctrl/init/sources)")

    def _maybe_keepalive(self):
        now = _ticks_ms()
        if _ticks_diff(self._next_keepalive_ms, now) > 0:
            return
        self.uart.write(CTRL_CMD)
        self._next_keepalive_ms = now + CONTROL_KEEPALIVE_MS

    def read_lens_name_minimal(self):
        self._configure_uart()
        self._drain_rx()
        self._rx_buf = bytearray()

        saw_any_rx = False
        for idx in range(LENS_NAME_MINIMAL_ATTEMPTS):
            self.uart.write(CTRL_CMD)
            name, saw_rx = self._read_name_frames(LENS_NAME_PREP_WAIT_MS, ignore_frame=CTRL_CMD)
            saw_any_rx = saw_any_rx or saw_rx
            if name:
                self.lens_name = str(name)
                return self.lens_name, True
            _sleep_ms(LENS_NAME_STEP_GAP_MS)

            self.uart.write(FINISH_INIT)
            name, saw_rx = self._read_name_frames(LENS_NAME_PREP_WAIT_MS, ignore_frame=FINISH_INIT)
            saw_any_rx = saw_any_rx or saw_rx
            if name:
                self.lens_name = str(name)
                return self.lens_name, True
            _sleep_ms(LENS_NAME_STEP_GAP_MS)

            self.uart.write(LENS_NAME_REQ)
            name, saw_rx = self._read_name_frames(LENS_NAME_WAIT_MS, ignore_frame=LENS_NAME_REQ)
            saw_any_rx = saw_any_rx or saw_rx
            if name:
                self.lens_name = str(name)
                return self.lens_name, True

            if idx + 1 < LENS_NAME_MINIMAL_ATTEMPTS:
                _sleep_ms(LENS_NAME_RETRY_BACKOFF_MS)

        return None, saw_any_rx

    def on_activate(self):
        self._activate_session()

    def read_lens_name(self):
        self._configure_uart()
        self._rx_buf = bytearray()
        for outer_idx in range(LENS_NAME_READ_ATTEMPTS):
            for baud, parity in LENS_NAME_UART_CONFIGS:
                try:
                    self.uart.init(baudrate=int(baud), bits=self.bits, parity=parity, stop=self.stop)
                except Exception:
                    try:
                        self.uart.init(int(baud), bits=self.bits, parity=parity, stop=self.stop)
                    except Exception:
                        pass
                self._drain_rx()
                self._rx_buf = bytearray()

                self.uart.write(CTRL_CMD)
                name, _ = self._read_name_frames(LENS_NAME_PREP_WAIT_MS, ignore_frame=CTRL_CMD)
                if name:
                    self.lens_name = str(name)
                    self._configure_uart()
                    return self.lens_name

                _sleep_ms(LENS_NAME_STEP_GAP_MS)
                self.uart.write(FINISH_INIT)
                name, _ = self._read_name_frames(LENS_NAME_PREP_WAIT_MS, ignore_frame=FINISH_INIT)
                if name:
                    self.lens_name = str(name)
                    self._configure_uart()
                    return self.lens_name

                _sleep_ms(LENS_NAME_STEP_GAP_MS)
                for req_idx in range(LENS_NAME_REQS_PER_PASS):
                    self.uart.write(LENS_NAME_REQ)
                    name, _ = self._read_name_frames(LENS_NAME_WAIT_MS, ignore_frame=LENS_NAME_REQ)
                    if name:
                        self.lens_name = str(name)
                        self._configure_uart()
                        return self.lens_name
                    if req_idx + 1 < LENS_NAME_REQS_PER_PASS:
                        _sleep_ms(LENS_NAME_STEP_GAP_MS)

                if outer_idx + 1 < LENS_NAME_READ_ATTEMPTS:
                    _sleep_ms(LENS_NAME_RETRY_BACKOFF_MS)
        self._configure_uart()
        return None

    def probe(self):
        self._activated = False
        name, saw_activity = self.read_lens_name_minimal()
        if not name:
            name = self.read_lens_name()
            if name:
                saw_activity = True
        if self.debug:
            if name:
                print("[CANON_PORT] probe name={}".format(name))
            elif saw_activity:
                print("[CANON_PORT] probe activity_detected (no name)")
            else:
                print("[CANON_PORT] probe no_rx")
        if name:
            self._activate_session()
            return True
        if not saw_activity:
            return False
        # Strict gate: activity alone is not enough; require validated Type-B readback.
        ok = bool(self.run_bit())
        if self.debug:
            print("[CANON_PORT] probe type-b readback:", "OK" if ok else "FAIL")
        if ok:
            self._activate_session()
        else:
            self._activated = False
        return bool(ok)

    def read_name(self):
        if self.lens_name:
            return self.lens_name
        name, _ = self.read_lens_name_minimal()
        if not name:
            name = self.read_lens_name()
        return name or None

    def _wait_for_prefix(self, prefix, timeout_ms):
        deadline = _ticks_ms() + int(timeout_ms)
        while _ticks_diff(deadline, _ticks_ms()) > 0:
            for frame in self._poll_frames():
                if frame.startswith(bytes(prefix)):
                    return frame
            _sleep_ms(5)
        return None

    def _send_axis_and_readback(self, cmd, value, timeout_ms=CONTROL_READBACK_TIMEOUT_MS):
        target = _clamp_u16_60000(value)
        tx = build_type_b(cmd, SUBCMD_C0, target)
        self.uart.write(tx)
        frame = self._wait_for_prefix((cmd, SUBCMD_C0), timeout_ms)
        if frame and len(frame) == 6 and frame[-1] == 0xBF:
            readback = unpack_type_b_value(frame[2], frame[3], frame[4])
            return int(readback), True
        return target, False

    def move_zoom(self, delta):
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
        self.focus_target = _clamp_u16_60000(raw_value)

    def set_iris_input(self, raw_value):
        self.iris_target = _clamp_u16_60000(raw_value)

    def _send_axis_controls(self):
        self.uart.write(build_zoom_speed_control_signed(self.zoom_velocity_cmd * ZOOM_SPEED_MAX // ZOOM_INPUT_MAX))
        self.uart.write(build_type_b(CMD_FOCUS_POS, SUBCMD_C0, self.focus_target))
        self.uart.write(build_type_b(CMD_IRIS_POS, SUBCMD_C0, self.iris_target))
        self._last_control_tx_ms = int(_ticks_ms())

    def periodic(self, now_ms):
        if not self._activated:
            return
        if _ticks_diff(self._next_keepalive_ms, now_ms) <= 0:
            self.uart.write(CTRL_CMD)
            self._next_keepalive_ms = now_ms + CONTROL_KEEPALIVE_MS
        if _ticks_diff(self._next_source_refresh_ms, now_ms) <= 0:
            self._apply_all_sources()
            self._next_source_refresh_ms = now_ms + SOURCE_REFRESH_MS
        if _ticks_diff(self._next_control_tx_ms, now_ms) <= 0:
            self._send_axis_controls()
            self._next_control_tx_ms = now_ms + CONTROL_TX_PERIOD_MS
        self._consume_runtime_feedback()

    def _consume_runtime_feedback(self):
        for frame in self._poll_frames():
            if not frame:
                continue
            if len(frame) == 6 and frame[-1] == 0xBF and frame[1] == SUBCMD_C0:
                value = unpack_type_b_value(frame[2], frame[3], frame[4])
                if frame[0] == CMD_ZOOM_POS:
                    self._last_zoom_feedback = int(value)
                    self.zoom = int(value)
                elif frame[0] == CMD_FOCUS_POS:
                    self._last_focus_feedback = int(value)
                    self.focus = int(value)
                elif frame[0] == CMD_IRIS_POS:
                    self._last_iris_feedback = int(value)
                    self.iris = int(value)
                continue
            # Opportunistic async name capture.
            if not self.lens_name:
                name = decode_lens_name_type_c(frame)
                if name:
                    self.lens_name = str(name)
                    if self.debug:
                        print("[CANON_PORT] async lens name:", self.lens_name)

    def run_bit(self):
        self._configure_uart()
        self._drain_rx()
        self._rx_buf = bytearray()
        self.uart.write(CTRL_CMD)
        _sleep_ms(ACTIVATE_STEP_GAP_MS)
        self.uart.write(FINISH_INIT)
        _ = self._wait_for_prefix((0x86, 0xC0), 1000)
        self._apply_all_sources()
        targets = (0, 60000, 30000)
        for cmd in (CMD_ZOOM_POS, CMD_FOCUS_POS, CMD_IRIS_POS):
            for target in targets:
                _v, ok = self._send_axis_and_readback(cmd, target, timeout_ms=1200)
                if not ok:
                    return False
        return True

    def set_positions(self, zoom=None, focus=None, iris=None):
        if not self._activated:
            self._activate_session()
        if zoom is not None:
            # Payload API carries Canon zoom intent as signed delta.
            self.move_zoom(zoom)
        if focus is not None:
            self.set_focus_input(focus)
        if iris is not None:
            self.set_iris_input(iris)
        self.periodic(_ticks_ms())

    def get_positions(self):
        return {
            "zoom": int(self.zoom),
            "focus": int(self.focus),
            "iris": int(self.iris),
        }
