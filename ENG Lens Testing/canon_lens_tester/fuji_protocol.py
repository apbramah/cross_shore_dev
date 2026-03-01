"""
Fujinon L10 Protocol (Ver 1.90) — Lens Control Computer ↔ Lens.
Serial: 38.4k bps, 8 bit, 1 stop, NO parity, RS-232C.
Frame: [DATA_LENGTH][FUNCTION_CODE][FUNCTION_DATA 0..15 bytes][CHECK_SUM]
DATA_LENGTH: D3~D0 = function data length (0–15), D7~D4 = 0000.
CHECK_SUM: (DATA_LENGTH + FUNCTION_CODE + sum(FUNCTION_DATA) + CHECK_SUM) & 0xFF == 0.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

import serial

# L10 serial settings (per spec)
FUJI_BAUD = 38400
FUJI_BITS = serial.EIGHTBITS
FUJI_PARITY = serial.PARITY_NONE
FUJI_STOP = serial.STOPBITS_ONE

# Function codes (host → lens / lens → host same code)
FUNC_CONNECT = 0x01
FUNC_LENS_NAME_1 = 0x11
FUNC_LENS_NAME_2 = 0x12
FUNC_IRIS_CONTROL = 0x20
FUNC_ZOOM_CONTROL = 0x21
FUNC_FOCUS_CONTROL = 0x22
FUNC_IRIS_POSITION = 0x30
FUNC_ZOOM_POSITION = 0x31
FUNC_FOCUS_POSITION = 0x32
FUNC_SWITCH_4_CONTROL = 0x44
FUNC_SWITCH_4_POSITION = 0x54

# Switch 4: bit0=Focus, bit1=Zoom, bit2=Iris, bit4=F.f.  0=host, 1=local/camera
# Fuji app traces use 0xF8 for "host all axes".
SW4_HOST_ALL = 0xF8
SW4_RELEASE_FOCUS = 0xF9
SW4_RELEASE_ZOOM = 0xFA
SW4_RELEASE_IRIS = 0xFC
SW4_RELEASE_ALL = 0xFF


def checksum(data: bytes) -> int:
    """Sum of bytes mod 256; checksum byte is (0x100 - sum) & 0xFF so total sum == 0."""
    s = sum(data) & 0xFF
    return (0x100 - s) & 0xFF


def build_l10_frame(func_code: int, data: Optional[bytes] = None) -> bytes:
    """Build one L10 command block: [data_len][func][data...][checksum]."""
    payload = bytes(data) if data else b""
    n = len(payload)
    if n > 15:
        raise ValueError("L10 function data max 15 bytes")
    data_len_byte = n & 0x0F  # D7–D4 = 0000
    block = bytes([data_len_byte, func_code]) + payload
    block += bytes([checksum(block)])
    return block


def parse_l10_frame(frame: bytes) -> Optional[Tuple[int, int, bytes]]:
    """
    Parse one L10 frame. Returns (func_code, data_length, data_bytes) or None if invalid.
    """
    if len(frame) < 3:
        return None
    data_len_byte = frame[0]
    n = data_len_byte & 0x0F
    if len(frame) != 3 + n:
        return None
    func = frame[1]
    payload = frame[2 : 2 + n]
    block_for_sum = frame[: 2 + n]
    if checksum(block_for_sum) != frame[2 + n]:
        return None
    return (func, n, payload)


def hexdump(b: bytes) -> str:
    return " ".join(f"{x:02X}" for x in b)


# ----- Convenience builders -----

def build_connect(connection_request: bool = True) -> bytes:
    """Connection request: data len 0. Reset request: data len 1, data 0."""
    if connection_request:
        return build_l10_frame(FUNC_CONNECT, b"")
    return build_l10_frame(FUNC_CONNECT, b"\x00")


def build_lens_name_request(first_half: bool = True) -> bytes:
    return build_l10_frame(FUNC_LENS_NAME_1 if first_half else FUNC_LENS_NAME_2, b"")


def build_position_request_iris() -> bytes:
    return build_l10_frame(FUNC_IRIS_POSITION, b"")


def build_position_request_zoom() -> bytes:
    return build_l10_frame(FUNC_ZOOM_POSITION, b"")


def build_position_request_focus() -> bytes:
    return build_l10_frame(FUNC_FOCUS_POSITION, b"")


def build_iris_control(value: int) -> bytes:
    """value 0x0000 = close, 0xFFFF = open. 16-bit big-endian."""
    v = max(0, min(0xFFFF, value))
    return build_l10_frame(FUNC_IRIS_CONTROL, bytes([v >> 8, v & 0xFF]))


def build_zoom_control(value: int) -> bytes:
    """value 0x0000 = wide, 0xFFFF = tele."""
    v = max(0, min(0xFFFF, value))
    return build_l10_frame(FUNC_ZOOM_CONTROL, bytes([v >> 8, v & 0xFF]))


def build_focus_control(value: int) -> bytes:
    """value 0x0000 = MOD, 0xFFFF = infinity."""
    v = max(0, min(0xFFFF, value))
    return build_l10_frame(FUNC_FOCUS_CONTROL, bytes([v >> 8, v & 0xFF]))


def build_switch4_control(bits: int = SW4_HOST_ALL) -> bytes:
    """bits: bit0 Focus host, bit1 Zoom host, bit2 Iris host, bit4 F.f. host. 0=host, 1=local."""
    return build_l10_frame(FUNC_SWITCH_4_CONTROL, bytes([bits & 0xFF]))


def build_request(func_code: int) -> bytes:
    """Build a no-data request frame for any function code."""
    return build_l10_frame(func_code, b"")


def build_switch4_position_request() -> bytes:
    return build_l10_frame(FUNC_SWITCH_4_POSITION, b"")


def decode_position_response(data: bytes) -> Optional[int]:
    """Decode 2-byte big-endian position (0x0000–0xFFFF)."""
    if len(data) < 2:
        return None
    return (data[0] << 8) | data[1]


def decode_lens_name_chunk(data: bytes) -> str:
    """Lens name is up to 30 ASCII chars; 11H = first 0–15, 12H = second 0–15."""
    return bytes(data).decode("ascii", errors="ignore").strip()
