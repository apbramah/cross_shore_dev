# Canon ENG lens protocol helpers for MicroPython

CTRL_CMD = bytes([0x80, 0xC6, 0xBF])  # Type-A keepalive/controller command
FINISH_INIT = bytes([0x86, 0xC0, 0x00, 0x00, 0x00, 0xBF])  # Type-B finish init
LENS_NAME_REQ = bytes([0xBE, 0x80, 0x81, 0x00, 0x00, 0x00, 0xBF])

SRC_OFF = 0x00
SRC_CAMERA = 0x08
SRC_PC = 0x10

SCMD_IRIS_SWITCH = 0x81
SCMD_ZOOM_SWITCH = 0x83
SCMD_FOCUS_SWITCH = 0x85

CMD_ZOOM_POS = 0x87
CMD_FOCUS_POS = 0x88
CMD_IRIS_POS = 0x96
SUBCMD_C0 = 0xC0
SUBCMD_C1 = 0xC1
ZOOM_SPEED_MAX = 18360
ZOOM_SPEED_STOP = 0x8000


def pack_type_b_value(v):
    v = int(v)
    if v < 0:
        v = 0
    if v > 60000:
        v = 60000
    return ((v >> 14) & 0x03, (v >> 7) & 0x7F, v & 0x7F)


def unpack_type_b_value(d1, d2, d3):
    return ((d1 & 0x03) << 14) | ((d2 & 0x7F) << 7) | (d3 & 0x7F)


def build_type_b(cmd, subcmd, v):
    d1, d2, d3 = pack_type_b_value(v)
    return bytes([cmd, subcmd, d1, d2, d3, 0xBF])


def build_zoom_speed_control_signed(signed_speed):
    """
    Canon zoom speed control (CMD=0x87, SUBCMD=0xC1).
    API range is signed speed around STOP at 0x8000:
      -18360 (wide max) .. 0 .. +18360 (tele max)
    """
    s = int(signed_speed)
    if s > ZOOM_SPEED_MAX:
        s = ZOOM_SPEED_MAX
    elif s < -ZOOM_SPEED_MAX:
        s = -ZOOM_SPEED_MAX
    v = ZOOM_SPEED_STOP + s
    return build_type_b(CMD_ZOOM_POS, SUBCMD_C1, v)


def build_type_c_switch(scmd, src_bits):
    # BE 85 <S-CMD> 01 00 02 00 <DATA1> BF
    return bytes([0xBE, 0x85, scmd, 0x01, 0x00, 0x02, 0x00, src_bits & 0x7F, 0xBF])


def _sanitize_lens_name(name):
    s = str(name or "").strip()
    if s.startswith("&"):
        s = s[1:]
    # Keep printable ASCII only; Canon labels we use are ASCII.
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
        if cp == 0:
            i += 2
            continue
        if 32 <= cp <= 126:
            chars.append(cp)
        i += 2
    if not chars:
        return None
    try:
        return bytes(chars).decode("ascii", errors="ignore")
    except Exception:
        return None


def _decode_pairs_ascii_be(payload):
    chars = []
    i = 0
    while i + 1 < len(payload):
        lo = payload[i]
        hi = payload[i + 1]
        cp = (lo << 8) | hi
        if cp == 0:
            i += 2
            continue
        if 32 <= cp <= 126:
            chars.append(cp)
        i += 2
    if not chars:
        return None
    try:
        return bytes(chars).decode("ascii", errors="ignore")
    except Exception:
        return None


def _decode_plain_ascii(payload):
    chars = []
    for b in payload:
        if 32 <= b <= 126:
            chars.append(b)
    if not chars:
        return None
    try:
        return bytes(chars).decode("ascii", errors="ignore")
    except Exception:
        return None


def _decode_plain_ascii_7bit(payload):
    chars = []
    for b in payload:
        c = b & 0x7F
        if 32 <= c <= 126:
            chars.append(c)
    if not chars:
        return None
    try:
        return bytes(chars).decode("ascii", errors="ignore")
    except Exception:
        return None


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
    # Prefer longest successful candidate (most descriptive model string).
    best = max(candidates, key=lambda s: len(s))
    return best or None
