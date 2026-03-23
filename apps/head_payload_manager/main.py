# version: canon-min-debug-v34
import time
from machine import UART, Pin

try:
    from soft_uart_pio import SoftUART
except Exception:
    SoftUART = None

VERSION = "canon-min-debug-v34"

# Canon transport
u = UART(1, 19200, tx=Pin(8), rx=Pin(9), bits=8, parity=0, stop=1)

CTRL_CMD = bytes([0x80, 0xC6, 0xBF])
FINISH_INIT = bytes([0x86, 0xC0, 0x00, 0x00, 0x00, 0xBF])
LENS_NAME_REQ = bytes([0xBE, 0x80, 0x81, 0x00, 0x00, 0x00, 0xBF])

CMD_ZOOM_POS = 0x87
CMD_FOCUS_POS = 0x88
CMD_IRIS_POS = 0x96
SUBCMD_C0 = 0xC0

# Type-C source switch constants (for readback preconditions)
SCMD_IRIS_SWITCH = 0x81
SCMD_ZOOM_SWITCH = 0x83
SCMD_FOCUS_SWITCH = 0x85
SRC_PC = 0x10

FUJI_CONNECT_REQ = bytes([0x00, 0x01, 0xFF])  # build_connect(True)
FUJI_PROBE_TIMEOUT_MS = 1200
# Current payload mapping target: Fuji SoftUART TX=GP13 RX=GP14.
FUJI_TX_PIN = 13
FUJI_RX_PIN = 14
FUJI_BAUD = 38400
FUJI_DISCOVERY_FUNCS = (0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17)
FUJI_GAP_MS_CONNECT = 20
FUJI_GAP_MS_DISCOVERY = 5
FUJI_GAP_MS_DEFAULT = 15
FUJI_RX_WINDOW_MS_FINAL = 700
FUJI_HOST_KEEPALIVE_INTERVAL_MS = 100
FUJI_NAME_POLL_INTERVAL_MS = 300
FUJI_NAME_POLL_MAX_ATTEMPTS = 20
FUJI_POLL_SEQ = (0x54, 0x53, 0x52, 0x30, 0x31, 0x32, 0x33, 0x34, 0x35)
FUJI_BIT_DELAY_SHORT_MS = 350
FUJI_BIT_DELAY_CTRL_MS = 500
FUJI_DECISION_WINDOW_MS = 14000
FUJI_NAME_QUIET_WINDOW_MS = 320
FUJI_NAME_POLL_SEND_CONNECT = False
FUJI_PRE_NAME_ATTEMPTS = 3
FUJI_PRE_NAME_CONNECT_WAIT_MS = 120
FUJI_PRE_NAME_QUIET_MS = 900
FUJI_PRE_NAME_PART2_WAIT_MS = 450
FUJI_STARTUP_RX_SLICE_MS = 35
FUJI_POST_BIT_CONNECT_NAME_QUIET_MS = 700
FUJI_PARSER_MAX_BUFFER = 192
FUJI_NAME_HUNTER_BUFFER = 512
FUJI_BIT_CONNECT_NAME_TRIGGER_FUNCS = (0x52, 0x53)
FUJI_RELAXED_NAME_MIN_ASCII = 8
RUN_SINGLE_CYCLE = True
LOG_VERBOSE = False
CANON_LOOP_INTERVAL_MS = 250
FUJI_AXIS_STREAM_INTERVAL_MS = 300

_FUJI_UART = None


def sleep_ms(ms):
    if hasattr(time, "sleep_ms"):
        time.sleep_ms(ms)
    else:
        time.sleep(ms / 1000.0)


def vlog(*args):
    if LOG_VERBOSE:
        print(*args)


def drain():
    while u.any():
        _ = u.read()


def hex_bytes(b):
    if not b:
        return ""
    return " ".join("{:02X}".format(x) for x in b)


def unpack_type_b_value(d1, d2, d3):
    return ((d1 & 0x03) << 14) | ((d2 & 0x7F) << 7) | (d3 & 0x7F)


def build_type_b(cmd, v):
    v = max(0, min(60000, int(v)))
    d1 = (v >> 14) & 0x03
    d2 = (v >> 7) & 0x7F
    d3 = v & 0x7F
    return bytes([cmd, SUBCMD_C0, d1, d2, d3, 0xBF])


def build_type_c_switch(scmd, src_bits):
    # BE 85 <S-CMD> 01 00 02 00 <DATA1> BF
    return bytes([0xBE, 0x85, scmd, 0x01, 0x00, 0x02, 0x00, src_bits & 0x7F, 0xBF])


def parse_fuji_l10_frame(frame):
    if not frame or len(frame) < 3:
        return None
    data_len = frame[0] & 0x0F
    expected = 3 + data_len
    if len(frame) != expected:
        return None
    block = frame[:-1]
    csum = frame[-1]
    if ((sum(block) + csum) & 0xFF) != 0:
        return None
    func = frame[1]
    payload = frame[2:-1]
    return func, payload


def split_fuji_frames(buf):
    """SoftUART-tolerant L10 parser with bounded resync scanning."""
    out = []
    while len(buf) >= 3:
        found = False
        for start in range(len(buf) - 2):
            data_len = buf[start] & 0x0F
            need = 3 + data_len
            if start + need > len(buf):
                continue
            frame = bytes(buf[start : start + need])
            parsed = parse_fuji_l10_frame(frame)
            if parsed is not None:
                out.append((frame, parsed))
                buf[:] = buf[start + need :]
                found = True
                break
        if found:
            continue
        if len(buf) > FUJI_PARSER_MAX_BUFFER:
            buf[:] = buf[1:]
            continue
        break
    return out


def fuji_checksum(data):
    s = sum(data) & 0xFF
    return (0x100 - s) & 0xFF


def fuji_build_frame(func_code, payload=b""):
    payload = bytes(payload or b"")
    n = len(payload) & 0x0F
    block = bytes([n, int(func_code) & 0xFF]) + payload
    return block + bytes([fuji_checksum(block)])


def fuji_payload_u16(payload):
    if not payload or len(payload) < 2:
        return None
    return ((payload[0] & 0xFF) << 8) | (payload[1] & 0xFF)


def fuji_payload_ascii(payload):
    if not payload:
        return ""
    out = []
    for b in payload:
        if 32 <= b <= 126:
            out.append(chr(b))
    return "".join(out).strip()


def is_plausible_fuji_name_part1(s):
    s = str(s or "").strip()
    if len(s) < FUJI_RELAXED_NAME_MIN_ASCII or len(s) > 15:
        return False
    if len(s) < 3:
        return False
    if not ("A" <= s[0] <= "Z" and "A" <= s[1] <= "Z"):
        return False
    if not ("0" <= s[2] <= "9"):
        return False
    for ch in s:
        if ("A" <= ch <= "Z") or ("0" <= ch <= "9") or ch in (" ", ".", "-", "/"):
            continue
        return False
    return True


def decode_fuji_iris_source(sw4_bits):
    if sw4_bits is None:
        return "<unknown>"
    return "HOST" if (int(sw4_bits) & 0x04) == 0 else "CAMERA"


def print_bit_summary(lens_kind, name, axis, iris_src):
    axis = axis or {}
    lens_kind = str(lens_kind or "NONE")
    nm = str(name or "<none>")
    iris = axis.get("iris")
    zoom = axis.get("zoom")
    focus = axis.get("focus")
    src = str(iris_src or "<unknown>")
    print(
        "[CANON_MIN][{}] BIT_SUMMARY: lens={} name='{}' iris={} zoom={} focus={} iris_src={}".format(
            VERSION, lens_kind, nm, iris, zoom, focus, src
        )
    )


def print_axis_stream(lens_kind, axis, tag="AXIS_STREAM"):
    axis = axis or {}
    print(
        "[CANON_MIN][{}] {}: lens={} iris={} zoom={} focus={} raw_u16=1".format(
            VERSION,
            tag,
            str(lens_kind or "NONE"),
            axis.get("iris"),
            axis.get("zoom"),
            axis.get("focus"),
        )
    )


def stream_canon_positions():
    print("[CANON_MIN][{}] INFO: Canon post-BIT axis stream started.".format(VERSION))
    while True:
        pos, _raw_pos, _frames_pos = request_axis_readbacks()
        print_axis_stream("CANON", pos)
        sleep_ms(CANON_LOOP_INTERVAL_MS)


def parse_frames(buf):
    frames = []
    i = 0
    while i < len(buf):
        # Type-C style: starts 0xBE, ends 0xBF
        if buf[i] == 0xBE:
            j = i + 1
            while j < len(buf) and buf[j] != 0xBF:
                j += 1
            if j < len(buf):
                frames.append(bytes(buf[i : j + 1]))
                i = j + 1
                continue
            break
        # Type-A length 3 ending BF
        if i + 2 < len(buf) and buf[i + 2] == 0xBF:
            frames.append(bytes(buf[i : i + 3]))
            i += 3
            continue
        # Type-B length 6 ending BF
        if i + 5 < len(buf) and buf[i + 5] == 0xBF:
            frames.append(bytes(buf[i : i + 6]))
            i += 6
            continue
        i += 1
    return frames


def decode_name(frame):
    # Proven Type-C gate
    if not frame or len(frame) < 7:
        return None
    if frame[0] != 0xBE or frame[1] != 0x80 or frame[2] != 0x81 or frame[-1] != 0xBF:
        return None
    payload = frame[3:-1]

    def sanitize(s):
        s = str(s or "").strip()
        if s.startswith("&"):
            s = s[1:]
        out = []
        for ch in s:
            o = ord(ch)
            if 32 <= o <= 126:
                out.append(ch)
        s = "".join(out).strip()
        return s or None

    def dec_pairs_le(p):
        chars = []
        i = 0
        while i + 1 < len(p):
            lo = p[i]
            hi = p[i + 1]
            cp = lo | (hi << 8)
            if cp != 0 and 32 <= cp <= 126:
                chars.append(cp)
            i += 2
        return bytes(chars).decode("ascii", "ignore") if chars else None

    def dec_pairs_be(p):
        chars = []
        i = 0
        while i + 1 < len(p):
            lo = p[i]
            hi = p[i + 1]
            cp = (lo << 8) | hi
            if cp != 0 and 32 <= cp <= 126:
                chars.append(cp)
            i += 2
        return bytes(chars).decode("ascii", "ignore") if chars else None

    def dec_plain(p):
        chars = [x for x in p if 32 <= x <= 126]
        return bytes(chars).decode("ascii", "ignore") if chars else None

    def dec_plain_7(p):
        chars = []
        for x in p:
            c = x & 0x7F
            if 32 <= c <= 126:
                chars.append(c)
        return bytes(chars).decode("ascii", "ignore") if chars else None

    # Canon name payload can include metadata prefix bytes before character pairs.
    # Evaluate decoders from multiple offsets and keep the best candidate.
    best = None
    for off in (0, 1, 2, 3):
        if off >= len(payload):
            continue
        p = payload[off:]
        candidates = []
        for fn in (dec_pairs_le, dec_pairs_be, dec_plain, dec_plain_7):
            try:
                c = sanitize(fn(p))
            except Exception:
                c = None
            if c:
                candidates.append(c)
        if candidates:
            cmax = max(candidates, key=len)
            if (best is None) or (len(cmax) > len(best)):
                best = cmax
    return best


def read_window(ms):
    t0 = time.ticks_ms()
    raw = bytearray()
    while time.ticks_diff(time.ticks_ms(), t0) < ms:
        if u.any():
            d = u.read(256)
            if d:
                raw.extend(d)
        sleep_ms(5)
    return bytes(raw)


def request_name():
    # Proven order
    drain()
    u.write(CTRL_CMD)
    _ = read_window(180)
    sleep_ms(60)

    u.write(FINISH_INIT)
    _ = read_window(180)
    sleep_ms(60)

    u.write(LENS_NAME_REQ)
    raw = read_window(1400)

    frames = parse_frames(raw)
    if LOG_VERBOSE:
        print("[CANON_MIN][{}] NAME_RAW_HEX:".format(VERSION), hex_bytes(raw))
        for i, f in enumerate(frames):
            print("[CANON_MIN][{}] NAME_FRAME[{}]:".format(VERSION, i), hex_bytes(f))
    for f in frames:
        n = decode_name(f)
        if n:
            return n, raw, frames
    if (not LOG_VERBOSE) and raw:
        print("[CANON_MIN][{}] NAME_FAIL_RAW_HEX:".format(VERSION), hex_bytes(raw))
    return None, raw, frames


def set_sources_pc():
    # Zoom/focus/iris source -> PC
    u.write(build_type_c_switch(SCMD_ZOOM_SWITCH, SRC_PC))
    sleep_ms(30)
    u.write(build_type_c_switch(SCMD_FOCUS_SWITCH, SRC_PC))
    sleep_ms(30)
    u.write(build_type_c_switch(SCMD_IRIS_SWITCH, SRC_PC))
    sleep_ms(30)


def request_axis_readbacks():
    # Establish canonical preconditions for Type-B readback.
    drain()
    u.write(CTRL_CMD)
    sleep_ms(50)
    u.write(FINISH_INIT)
    sleep_ms(80)
    set_sources_pc()

    # Trigger readbacks by requesting midpoint per axis.
    u.write(build_type_b(CMD_ZOOM_POS, 30000))
    sleep_ms(20)
    u.write(build_type_b(CMD_FOCUS_POS, 30000))
    sleep_ms(20)
    u.write(build_type_b(CMD_IRIS_POS, 30000))
    raw = read_window(800)
    frames = parse_frames(raw)
    if LOG_VERBOSE:
        print("[CANON_MIN][{}] POS_RAW_HEX:".format(VERSION), hex_bytes(raw))
        for i, f in enumerate(frames):
            print("[CANON_MIN][{}] POS_FRAME[{}]:".format(VERSION, i), hex_bytes(f))

    out = {"zoom": None, "focus": None, "iris": None}
    for f in frames:
        if len(f) == 6 and f[-1] == 0xBF and f[1] == SUBCMD_C0:
            v = unpack_type_b_value(f[2], f[3], f[4])
            if f[0] == CMD_ZOOM_POS:
                out["zoom"] = v
            elif f[0] == CMD_FOCUS_POS:
                out["focus"] = v
            elif f[0] == CMD_IRIS_POS:
                out["iris"] = v
    if (not LOG_VERBOSE) and all(out.get(k) is None for k in ("zoom", "focus", "iris")) and raw:
        print("[CANON_MIN][{}] POS_FAIL_RAW_HEX:".format(VERSION), hex_bytes(raw))
    return out, raw, frames


def probe_fuji_if_no_canon():
    global _FUJI_UART
    if SoftUART is None:
        print("[CANON_MIN][{}] INFO: Fuji SoftUART unavailable".format(VERSION))
        return {
            "connected": False,
            "lens_kind": "NONE",
            "name": "<none>",
            "axis": {"iris": None, "zoom": None, "focus": None},
            "iris_src": "<unknown>",
            "ack": "FAIL_SOFTUART_UNAVAILABLE",
        }
    su = _FUJI_UART
    if su is None or (not getattr(su, "available", False)):
        su = SoftUART(tx_pin=FUJI_TX_PIN, rx_pin=FUJI_RX_PIN, baud=FUJI_BAUD, sm_tx_id=2, sm_rx_id=3)
        _FUJI_UART = su
    if not getattr(su, "available", False):
        print("[CANON_MIN][{}] INFO: Fuji SoftUART init failed".format(VERSION))
        return {
            "connected": False,
            "lens_kind": "NONE",
            "name": "<none>",
            "axis": {"iris": None, "zoom": None, "focus": None},
            "iris_src": "<unknown>",
            "ack": "FAIL_SOFTUART_INIT",
        }

    # Drain any stale RX bytes before probe.
    t0_drain = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), t0_drain) < 40:
        d = su.read()
        if not d:
            break

    def tx(label, frame, gap_ms=FUJI_GAP_MS_DEFAULT):
        su.write(frame)
        vlog("[CANON_MIN][{}] TX: {}:".format(VERSION, label), hex_bytes(frame))
        if gap_ms > 0:
            sleep_ms(gap_ms)

    rx_buf = bytearray()
    hunt_buf = bytearray()
    saw_valid_frame = False
    name_part1 = ""
    name_part2 = ""
    lens_name = ""
    name_poll_attempts = 0
    name_poll_enabled = True
    host_keepalive_tick_count = 0
    poll_idx = 0
    name_quiet_until = 0
    await_bit_connect_name_trigger = False
    parser_bytes_dropped = 0
    parser_frames_recovered = 0
    hunter_name1_hits = 0
    hunter_name2_hits = 0
    fuji_axis = {"iris": None, "zoom": None, "focus": None}
    sw4_bits = None
    next_fuji_axis_stream_ms = time.ticks_ms()

    sw4_host = fuji_build_frame(0x44, bytes([0xF8]))
    sw4_pos_req = fuji_build_frame(0x54)
    lens_name_1 = fuji_build_frame(0x11)
    lens_name_2 = fuji_build_frame(0x12)

    def tx_now(label, frame):
        su.write(frame)
        vlog("[CANON_MIN][{}] TX: {}:".format(VERSION, label), hex_bytes(frame))

    def build_u16(func_code, value):
        v = max(0, min(65535, int(value)))
        return fuji_build_frame(func_code, bytes([(v >> 8) & 0xFF, v & 0xFF]))

    # FujiBitRunner parity steps and delays.
    bit_steps = [
        ("CONNECT", FUJI_CONNECT_REQ, FUJI_BIT_DELAY_SHORT_MS),
        ("Switch4 Host", sw4_host, FUJI_BIT_DELAY_SHORT_MS),
        ("Read SW4", sw4_pos_req, FUJI_BIT_DELAY_SHORT_MS),
        ("Read initial Iris", fuji_build_frame(0x30), FUJI_BIT_DELAY_SHORT_MS),
        ("Read initial Zoom", fuji_build_frame(0x31), FUJI_BIT_DELAY_SHORT_MS),
        ("Read initial Focus", fuji_build_frame(0x32), FUJI_BIT_DELAY_SHORT_MS),
    ]
    for axis_label, ctrl_func, pos_func in (
        ("Iris", 0x20, 0x30),
        ("Zoom", 0x21, 0x31),
        ("Focus", 0x22, 0x32),
    ):
        for lim, v in (("MIN", 0), ("MAX", 65535), ("CENTER", 32768)):
            bit_steps.append(("{} -> {}".format(axis_label, lim), build_u16(ctrl_func, v), FUJI_BIT_DELAY_CTRL_MS))
            bit_steps.append(("{} position readback".format(axis_label), fuji_build_frame(pos_func), FUJI_BIT_DELAY_SHORT_MS))

    bit_idx = 0
    bit_running = True

    def handle_frame(frame, parsed):
        nonlocal saw_valid_frame, name_part1, name_part2, lens_name, name_poll_enabled, await_bit_connect_name_trigger, name_quiet_until, fuji_axis, sw4_bits, next_fuji_axis_stream_ms
        if frame == FUJI_CONNECT_REQ:
            return
        saw_valid_frame = True
        func = int(parsed[0])
        payload = parsed[1]
        vlog("[CANON_MIN][{}] RX:".format(VERSION), hex_bytes(frame))
        if func in (0x11, 0x12):
            s = fuji_payload_ascii(payload)
            if s:
                if func == 0x11:
                    name_part1 = s
                    lens_name = s
                    print("[CANON_MIN][{}] INFO: Lens name part1:".format(VERSION), s)
                    # Stop name polling only when first-half name is captured.
                    name_poll_enabled = False
                else:
                    # Ignore unsolicited part2 until part1 exists in this run.
                    if name_part1:
                        name_part2 = s
                        lens_name = (name_part1 + s).strip()[:30]
                        print("[CANON_MIN][{}] INFO: Lens name part2:".format(VERSION), s)
            if func == 0x11 and len(payload) == 15:
                tx_now("LENS_NAME_2 request", lens_name_2)
        elif func == 0x54 and payload:
            sw4_bits = int(payload[0])
            vlog("[CANON_MIN][{}] INFO: SW4=0x{:02X}".format(VERSION, sw4_bits))
        elif func in (0x30, 0x31, 0x32, 0x33, 0x34, 0x35):
            v = fuji_payload_u16(payload)
            if v is not None:
                if func == 0x30:
                    fuji_axis["iris"] = v
                elif func == 0x31:
                    fuji_axis["zoom"] = v
                elif func == 0x32:
                    fuji_axis["focus"] = v
                vlog("[CANON_MIN][{}] INFO: FUNC 0x{:02X} value={}".format(VERSION, func, v))
                now_ms = time.ticks_ms()
                if time.ticks_diff(now_ms, next_fuji_axis_stream_ms) >= 0:
                    print_axis_stream("FUJI", fuji_axis)
                    next_fuji_axis_stream_ms = time.ticks_add(now_ms, FUJI_AXIS_STREAM_INTERVAL_MS)

        # Tester timing parity: after BIT CONNECT, issue NAME_1 after first BIT status RX.
        if await_bit_connect_name_trigger and (func in FUJI_BIT_CONNECT_NAME_TRIGGER_FUNCS):
            await_bit_connect_name_trigger = False
            print("[CANON_MIN][{}] INFO: BIT trigger -> NAME_1 on RX 0x{:02X}".format(VERSION, func))
            tx_now("LENS_NAME_1 request", lens_name_1)
            name_quiet_until = time.ticks_add(time.ticks_ms(), FUJI_POST_BIT_CONNECT_NAME_QUIET_MS)

    def service_rx_once():
        nonlocal parser_bytes_dropped, parser_frames_recovered, hunter_name1_hits, hunter_name2_hits, name_part1, name_part2, lens_name, name_poll_enabled, hunt_buf
        d = su.read()
        if d:
            rx_buf.extend(d)
            hunt_buf.extend(d)
            if len(hunt_buf) > FUJI_NAME_HUNTER_BUFFER:
                hunt_buf = bytearray(hunt_buf[len(hunt_buf) - FUJI_NAME_HUNTER_BUFFER :])

            # Name hunter: recover valid name frames from raw stream even when
            # parser resync drops surrounding bytes.
            if not name_part1:
                start = max(0, len(hunt_buf) - 96)
                end = max(start, len(hunt_buf) - 17)
                for i in range(start, end):
                    if hunt_buf[i] != 0x0F or hunt_buf[i + 1] != 0x11:
                        continue
                    cand = bytes(hunt_buf[i : i + 18])
                    parsed = parse_fuji_l10_frame(cand)
                    if parsed is not None:
                        payload = cand[2:-1]
                        s = fuji_payload_ascii(payload)
                    else:
                        # SoftUART tolerance: if checksum is corrupted but the
                        # candidate has enough printable ASCII, still accept it
                        # as a name-part1 recovery.
                        payload = cand[2:-1]
                        ascii_count = 0
                        for b in payload:
                            if 32 <= b <= 126:
                                ascii_count += 1
                        if ascii_count < FUJI_RELAXED_NAME_MIN_ASCII:
                            continue
                        s = fuji_payload_ascii(payload)
                        if not is_plausible_fuji_name_part1(s):
                            continue
                    if s:
                        name_part1 = s
                        lens_name = s
                        name_poll_enabled = False
                        hunter_name1_hits += 1
                        if parsed is None:
                            print("[CANON_MIN][{}] HUNTER_RELAXED: Lens name part1:".format(VERSION), s)
                        else:
                            print("[CANON_MIN][{}] HUNTER: Lens name part1:".format(VERSION), s)
                        tx_now("LENS_NAME_2 request", lens_name_2)
                        break

            if name_part1 and (not name_part2):
                start = max(0, len(hunt_buf) - 64)
                end = max(start, len(hunt_buf) - 4)
                for i in range(start, end):
                    if hunt_buf[i] != 0x02 or hunt_buf[i + 1] != 0x12:
                        continue
                    cand = bytes(hunt_buf[i : i + 5])
                    if parse_fuji_l10_frame(cand) is None:
                        continue
                    payload = cand[2:-1]
                    s = fuji_payload_ascii(payload)
                    if s:
                        name_part2 = s
                        lens_name = (name_part1 + s).strip()[:30]
                        hunter_name2_hits += 1
                        print("[CANON_MIN][{}] HUNTER: Lens name part2:".format(VERSION), s)
                        break
        before_len = len(rx_buf)
        frames = split_fuji_frames(rx_buf)
        after_len = len(rx_buf)
        dropped = before_len - after_len
        if dropped > 0:
            parser_bytes_dropped += dropped
        if frames:
            parser_frames_recovered += len(frames)
        for frame, parsed in frames:
            handle_frame(frame, parsed)

    def service_rx_for(ms):
        t0 = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), t0) < int(ms):
            service_rx_once()
            sleep_ms(5)

    def pre_name_trigger_phase():
        """SoftUART bring-up adaptation: attempt name capture before bus flood."""
        nonlocal name_poll_enabled
        for i in range(FUJI_PRE_NAME_ATTEMPTS):
            if lens_name:
                break
            vlog(
                "[CANON_MIN][{}] INFO: Pre-name trigger {}/{}".format(
                    VERSION, i + 1, FUJI_PRE_NAME_ATTEMPTS
                )
            )
            tx_now("CONNECT", FUJI_CONNECT_REQ)
            service_rx_for(FUJI_PRE_NAME_CONNECT_WAIT_MS)
            tx_now("LENS_NAME_1 request", lens_name_1)
            service_rx_for(FUJI_PRE_NAME_QUIET_MS)
            if name_part1 and (not name_part2):
                service_rx_for(FUJI_PRE_NAME_PART2_WAIT_MS)
        if lens_name:
            name_poll_enabled = False

    def name_poll_tick():
        nonlocal name_poll_attempts, name_poll_enabled, name_quiet_until
        if not name_poll_enabled:
            return
        if name_poll_attempts >= FUJI_NAME_POLL_MAX_ATTEMPTS:
            print("[CANON_MIN][{}] WARN: Lens name read timed out.".format(VERSION))
            name_poll_enabled = False
            return
        name_poll_attempts += 1
        # Match observed successful trigger context: CONNECT before NAME_1.
        if FUJI_NAME_POLL_SEND_CONNECT:
            tx_now("CONNECT", FUJI_CONNECT_REQ)
        tx_now("LENS_NAME_1 request", lens_name_1)
        # SoftUART adaptation: hold a quiet RX window after name request.
        name_quiet_until = time.ticks_add(time.ticks_ms(), FUJI_NAME_QUIET_WINDOW_MS)

    def keepalive_tick():
        nonlocal host_keepalive_tick_count, poll_idx
        if host_keepalive_tick_count % 5 == 0:
            tx_now("Switch4 Host keepalive", sw4_host)
        func = FUJI_POLL_SEQ[poll_idx]
        poll_idx = (poll_idx + 1) % len(FUJI_POLL_SEQ)
        tx_now("REQ_{:02X}".format(func), fuji_build_frame(func))
        host_keepalive_tick_count += 1

    def bit_tick(now_ms):
        nonlocal bit_idx, bit_running, await_bit_connect_name_trigger
        if not bit_running:
            return now_ms
        if bit_idx >= len(bit_steps):
            bit_running = False
            print("[CANON_MIN][{}] INFO: BIT complete.".format(VERSION))
            return now_ms
        step_name, frame, delay_ms = bit_steps[bit_idx]
        vlog("[CANON_MIN][{}] INFO: BIT: {}".format(VERSION, step_name))
        tx_now("BIT_{}".format(step_name), frame)
        if step_name == "CONNECT":
            # Wait for first status RX (0x52/0x53), then request NAME_1.
            await_bit_connect_name_trigger = True
        bit_idx += 1
        return time.ticks_add(now_ms, int(delay_ms))

    def stream_fuji_positions(stream_name):
        nonlocal sw4_bits
        print("[CANON_MIN][{}] INFO: Fuji post-BIT axis stream started.".format(VERSION))
        poll_funcs = (0x30, 0x31, 0x32)
        poll_idx_local = 0
        now_ms = time.ticks_ms()
        next_axis_poll = now_ms
        next_sw4 = now_ms
        next_stream = now_ms
        while True:
            now_ms = time.ticks_ms()
            service_rx_once()
            if time.ticks_diff(now_ms, next_axis_poll) >= 0:
                func = poll_funcs[poll_idx_local]
                poll_idx_local = (poll_idx_local + 1) % len(poll_funcs)
                tx_now("STREAM_REQ_{:02X}".format(func), fuji_build_frame(func))
                next_axis_poll = time.ticks_add(now_ms, FUJI_AXIS_STREAM_INTERVAL_MS)
            if time.ticks_diff(now_ms, next_sw4) >= 0:
                tx_now("STREAM_SW4_HOST", sw4_host)
                tx_now("STREAM_SW4_POS_REQ", sw4_pos_req)
                next_sw4 = time.ticks_add(now_ms, 1000)
            if time.ticks_diff(now_ms, next_stream) >= 0:
                _ = stream_name
                print_axis_stream("FUJI", fuji_axis)
                next_stream = time.ticks_add(now_ms, FUJI_AXIS_STREAM_INTERVAL_MS)
            sleep_ms(5)

    print("[CANON_MIN][{}] INFO: Opened Fuji SoftUART GP{}/GP{} @ {} 8N1".format(VERSION, FUJI_TX_PIN, FUJI_RX_PIN, FUJI_BAUD))

    # ui_app connect sequence order: CONNECTx2, discovery, Switch4 Host, start name poll, start keepalive, read SW4, start BIT.
    tx_now("CONNECT", FUJI_CONNECT_REQ)
    service_rx_for(FUJI_STARTUP_RX_SLICE_MS)
    tx_now("CONNECT", FUJI_CONNECT_REQ)
    service_rx_for(FUJI_STARTUP_RX_SLICE_MS)
    for func in FUJI_DISCOVERY_FUNCS:
        tx_now("DISCOVERY_{:02X}".format(func), fuji_build_frame(func))
        service_rx_for(FUJI_STARTUP_RX_SLICE_MS)
    print("[CANON_MIN][{}] INFO: Discovery burst sent (10h..17h).".format(VERSION))
    tx_now("Switch4 Host", sw4_host)
    service_rx_for(FUJI_STARTUP_RX_SLICE_MS)
    pre_name_trigger_phase()

    now = time.ticks_ms()
    name_poll_tick()  # _fuji_start_name_poll -> immediate tick
    service_rx_for(FUJI_STARTUP_RX_SLICE_MS)
    tx_now("Switch4 Pos Req", sw4_pos_req)  # _fuji_read_switch4
    service_rx_for(FUJI_STARTUP_RX_SLICE_MS)
    next_name_poll = time.ticks_add(now, FUJI_NAME_POLL_INTERVAL_MS)
    next_keepalive = now  # _fuji_start_host_keepalive -> immediate tick (unless quiet window active)
    next_bit = now  # FujiBitRunner starts immediately

    deadline = time.ticks_add(now, FUJI_DECISION_WINDOW_MS)
    while time.ticks_diff(deadline, time.ticks_ms()) > 0:
        now = time.ticks_ms()
        service_rx_once()
        in_quiet_window = time.ticks_diff(name_quiet_until, now) > 0
        if (not in_quiet_window) and (time.ticks_diff(now, next_name_poll) >= 0):
            name_poll_tick()
            next_name_poll = time.ticks_add(now, FUJI_NAME_POLL_INTERVAL_MS)
        if (not in_quiet_window) and (time.ticks_diff(now, next_keepalive) >= 0):
            keepalive_tick()
            next_keepalive = time.ticks_add(now, FUJI_HOST_KEEPALIVE_INTERVAL_MS)
        if (not in_quiet_window) and (time.ticks_diff(now, next_bit) >= 0):
            next_bit = bit_tick(now)

        # Close enough to tester lifecycle: once name polling and BIT are done, settle and exit.
        if (not name_poll_enabled) and (not bit_running):
            break
        sleep_ms(5)

    service_rx_for(FUJI_RX_WINDOW_MS_FINAL)

    full_name = (name_part1 + name_part2).strip()
    print(
        "[CANON_MIN][{}] PARSER_STATS: frames={} dropped_bytes={} residual_buf={} hunter11={} hunter12={}".format(
            VERSION,
            parser_frames_recovered,
            parser_bytes_dropped,
            len(rx_buf),
            hunter_name1_hits,
            hunter_name2_hits,
        )
    )
    snapshot_name = full_name or (name_part1 + name_part2).strip() or "<none>"
    print(
        "[CANON_MIN][{}] FUJI_SNAPSHOT: name='{}' iris={} zoom={} focus={}".format(
            VERSION,
            snapshot_name,
            fuji_axis["iris"],
            fuji_axis["zoom"],
            fuji_axis["focus"],
        )
    )
    iris_src = decode_fuji_iris_source(sw4_bits)

    if name_part1 and name_part2 and full_name:
        print("[CANON_MIN][{}] INFO: Fuji lens name:".format(VERSION), full_name)
        print("[CANON_MIN][{}] FUJI_ACK: PASS_FULL_NAME".format(VERSION))
        print_bit_summary("FUJI", full_name, fuji_axis, iris_src)
        stream_fuji_positions(full_name)
        return {
            "connected": True,
            "lens_kind": "FUJI",
            "name": full_name,
            "axis": fuji_axis,
            "iris_src": iris_src,
            "ack": "PASS_FULL_NAME",
        }
    if name_part1 or name_part2:
        partial = (name_part1 + name_part2).strip() or name_part1 or name_part2
        print("[CANON_MIN][{}] INFO: Fuji partial name:".format(VERSION), partial)
        print("[CANON_MIN][{}] FUJI_ACK: PASS_LINK_ONLY".format(VERSION))
        print_bit_summary("FUJI", partial, fuji_axis, iris_src)
        stream_fuji_positions(partial)
        return {
            "connected": True,
            "lens_kind": "FUJI",
            "name": partial,
            "axis": fuji_axis,
            "iris_src": iris_src,
            "ack": "PASS_LINK_ONLY",
        }
    if saw_valid_frame:
        print("[CANON_MIN][{}] FUJI_ACK: PASS_LINK_ONLY".format(VERSION))
        print_bit_summary("FUJI", "<unknown>", fuji_axis, iris_src)
        stream_fuji_positions("<unknown>")
        return {
            "connected": True,
            "lens_kind": "FUJI",
            "name": "<unknown>",
            "axis": fuji_axis,
            "iris_src": iris_src,
            "ack": "PASS_LINK_ONLY",
        }
    print("[CANON_MIN][{}] FUJI_ACK: FAIL_NO_VALID_FRAMES rx_hex=".format(VERSION), hex_bytes(bytes(rx_buf)))
    return {
        "connected": False,
        "lens_kind": "NONE",
        "name": "<none>",
        "axis": fuji_axis,
        "iris_src": iris_src,
        "ack": "FAIL_NO_VALID_FRAMES",
    }


print("[CANON_MIN][{}] boot UART1 GP8/GP9 19200 8E1".format(VERSION))

name, raw_name, _frames_name = request_name()
canon_present = bool(name)
if name:
    print("[CANON_MIN][{}] NAME:".format(VERSION), name)
else:
    print("[CANON_MIN][{}] NAME: <none> raw_len=".format(VERSION), len(raw_name))

pos, raw_pos, _frames_pos = request_axis_readbacks()
print("[CANON_MIN][{}] POS:".format(VERSION), pos, "raw_len=", len(raw_pos))
summary = None
if canon_present:
    summary = {
        "connected": True,
        "lens_kind": "CANON",
        "name": name,
        "axis": pos,
        "iris_src": "PC",
        "ack": "PASS_FULL_NAME",
    }
if (not canon_present) and all(pos.get(k) is None for k in ("zoom", "focus", "iris")):
    summary = probe_fuji_if_no_canon()
if summary is None:
    summary = {
        "connected": False,
        "lens_kind": "NONE",
        "name": "<none>",
        "axis": pos,
        "iris_src": "<unknown>",
        "ack": "NO_LENS_CONFIRMED",
    }
print_bit_summary(summary.get("lens_kind"), summary.get("name"), summary.get("axis"), summary.get("iris_src"))

if summary.get("lens_kind") == "CANON":
    stream_canon_positions()
elif summary.get("lens_kind") == "NONE":
    print_axis_stream("NONE", summary.get("axis"))
    print("[CANON_MIN][{}] INFO: single-cycle complete".format(VERSION))
