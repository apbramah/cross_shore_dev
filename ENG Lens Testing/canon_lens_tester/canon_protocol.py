from __future__ import annotations

from typing import Optional, Tuple

import serial


# ===== Canon Serial Settings (per protocol) =====
BAUD = 19200
PARITY = serial.PARITY_EVEN
BITS = serial.EIGHTBITS
STOP = serial.STOPBITS_ONE

# ===== Canon Frames we already used =====
CTRL_CMD = bytes.fromhex("80 C6 BF")  # Type-A controller command
FINISH_INIT = bytes.fromhex("86 C0 00 00 00 BF")  # Type-B finish init
LENS_NAME_REQ = bytes.fromhex("BE 80 81 00 00 00 BF")  # Type-C lens name request

# ===== Control switching (Type-C) =====
# Bits: b4=PC, b3=Camera, b2=Digital demand, b1=Analog demand, b0=Ext (per table)
SRC_OFF = 0x00
SRC_CAMERA = 0x08
SRC_PC = 0x10

# S-CMD mapping (per Canon table)
SCMD_IRIS_SWITCH = 0x81
SCMD_ZOOM_SWITCH = 0x83
SCMD_FOCUS_SWITCH = 0x85

# ===== Motion commands (Type-B) =====
CMD_ZOOM_POS = 0x87  # 87 C0 ...
CMD_FOCUS_POS = 0x88  # 88 C0 ...
CMD_IRIS_POS = 0x96  # 96 C0 ...
SUBCMD_C0 = 0xC0


def hexdump(b: bytes) -> str:
    return " ".join(f"{x:02X}" for x in b)


def pack_type_b_value(v: int) -> Tuple[int, int, int]:
    """
    Canon Type-B 3-byte packing (bit7 always 0):
      DATA1 = (v >> 14) & 0x03
      DATA2 = (v >> 7) & 0x7F
      DATA3 = v & 0x7F
    """
    v = max(0, min(60000, int(v)))
    return ((v >> 14) & 0x03, (v >> 7) & 0x7F, v & 0x7F)


def unpack_type_b_value(d1: int, d2: int, d3: int) -> int:
    return ((d1 & 0x03) << 14) | ((d2 & 0x7F) << 7) | (d3 & 0x7F)


def build_type_b(cmd: int, subcmd: int, v: int) -> bytes:
    d1, d2, d3 = pack_type_b_value(v)
    return bytes([cmd, subcmd, d1, d2, d3, 0xBF])


def build_type_c_switch(scmd: int, src_bits: int) -> bytes:
    # Minimal form consistent with Canon examples:
    # BE 85 <S-CMD> 01 00 02 00 <DATA1> BF
    return bytes([0xBE, 0x85, scmd, 0x01, 0x00, 0x02, 0x00, src_bits & 0x7F, 0xBF])


def decode_lens_name_type_c(frame: bytes) -> Optional[str]:
    if not (
        len(frame) >= 7
        and frame[0] == 0xBE
        and frame[1] == 0x80
        and frame[2] == 0x81
        and frame[-1] == 0xBF
    ):
        return None

    payload = frame[3:-1]
    chars = []
    i = 0
    while i + 1 < len(payload):
        lo = payload[i]
        hi = payload[i + 1]
        if hi == 0x00 and 32 <= lo <= 126:
            chars.append(lo)
        i += 2

    if not chars:
        return None

    name = bytes(chars).decode("ascii", errors="ignore").strip()
    name = name.lstrip("&")  # remove leading '&' if present
    return name or None
