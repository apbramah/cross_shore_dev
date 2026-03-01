# Fujinon L10 protocol helpers for MicroPython

FUJI_BAUD = 38400
FUJI_BITS = 8
FUJI_PARITY = None
FUJI_STOP = 1

FUNC_CONNECT = 0x01
FUNC_IRIS_CONTROL = 0x20
FUNC_ZOOM_CONTROL = 0x21
FUNC_FOCUS_CONTROL = 0x22
FUNC_IRIS_POSITION = 0x30
FUNC_ZOOM_POSITION = 0x31
FUNC_FOCUS_POSITION = 0x32
FUNC_SWITCH_4_CONTROL = 0x44
FUNC_SWITCH_4_POSITION = 0x54

# Switch4: bit0 focus, bit1 zoom, bit2 iris. 0=host, 1=local
SW4_HOST_ALL = 0xF8


def checksum(data):
    s = sum(data) & 0xFF
    return (0x100 - s) & 0xFF


def build_l10_frame(func_code, data=None):
    payload = bytes(data) if data else b""
    n = len(payload)
    if n > 15:
        raise ValueError("L10 function data max 15 bytes")
    data_len = n & 0x0F
    block = bytes([data_len, func_code]) + payload
    return block + bytes([checksum(block)])


def build_connect(connection_request=True):
    if connection_request:
        return build_l10_frame(FUNC_CONNECT, b"")
    return build_l10_frame(FUNC_CONNECT, b"\x00")


def build_zoom_control(value):
    v = int(value)
    if v < 0:
        v = 0
    if v > 0xFFFF:
        v = 0xFFFF
    return build_l10_frame(FUNC_ZOOM_CONTROL, bytes([v >> 8, v & 0xFF]))


def build_focus_control(value):
    v = int(value)
    if v < 0:
        v = 0
    if v > 0xFFFF:
        v = 0xFFFF
    return build_l10_frame(FUNC_FOCUS_CONTROL, bytes([v >> 8, v & 0xFF]))


def build_iris_control(value):
    v = int(value)
    if v < 0:
        v = 0
    if v > 0xFFFF:
        v = 0xFFFF
    return build_l10_frame(FUNC_IRIS_CONTROL, bytes([v >> 8, v & 0xFF]))


def build_switch4_control(bits=SW4_HOST_ALL):
    return build_l10_frame(FUNC_SWITCH_4_CONTROL, bytes([bits & 0xFF]))


def build_position_request_zoom():
    return build_l10_frame(FUNC_ZOOM_POSITION, b"")


def build_position_request_focus():
    return build_l10_frame(FUNC_FOCUS_POSITION, b"")


def build_position_request_iris():
    return build_l10_frame(FUNC_IRIS_POSITION, b"")


def build_switch4_position_request():
    return build_l10_frame(FUNC_SWITCH_4_POSITION, b"")
