"""
Sony VISCA helpers for FCB-ES8230 bring-up testing.

This module focuses on:
- command builders for initial controls (iris/saturation/red/blue)
- utility helpers for nibble packing
- basic response classification (ACK / completion / error)
"""

from __future__ import annotations

from typing import Optional

import serial

SONY_BAUD = 9600
SONY_BITS = serial.EIGHTBITS
SONY_PARITY = serial.PARITY_NONE
SONY_STOP = serial.STOPBITS_ONE


def hexdump(b: bytes) -> str:
    return " ".join(f"{x:02X}" for x in b)


def _camera_addr(address: int = 1) -> int:
    addr = int(address)
    if addr < 1 or addr > 7:
        raise ValueError("VISCA camera address must be 1..7")
    return 0x80 | addr


def _u8_to_nibbles(value: int) -> tuple[int, int]:
    v = max(0, min(0xFF, int(value)))
    return ((v >> 4) & 0x0F, v & 0x0F)


def _u16_to_nibbles(value: int) -> tuple[int, int, int, int]:
    v = max(0, min(0xFFFF, int(value)))
    return ((v >> 12) & 0x0F, (v >> 8) & 0x0F, (v >> 4) & 0x0F, v & 0x0F)


def build_interface_clear() -> bytes:
    # Broadcast command
    return bytes([0x88, 0x01, 0x00, 0x01, 0xFF])


def build_address_set(address: int = 1) -> bytes:
    # Broadcast command with one camera expected on the bus.
    addr = max(1, min(7, int(address)))
    return bytes([0x88, 0x30, addr & 0x07, 0xFF])


def build_cam_iris_direct(value: int, address: int = 1) -> bytes:
    # FCB-ES8230 iris direct is a bounded position index.
    # Practical supported range is 01h..11h. 00h is rejected by camera.
    hi, lo = _u8_to_nibbles(max(0x01, min(0x11, int(value))))
    # FCB-ES8230 manual: 8x 01 04 4B 00 00 0p 0q FF
    return bytes([_camera_addr(address), 0x01, 0x04, 0x4B, 0x00, 0x00, hi, lo, 0xFF])


def build_cam_iris_inquiry(address: int = 1) -> bytes:
    return bytes([_camera_addr(address), 0x09, 0x04, 0x4B, 0xFF])


def build_cam_r_gain_direct(value: int, address: int = 1) -> bytes:
    hi, lo = _u8_to_nibbles(value)
    # FCB-ES8230 manual: 8x 01 04 43 00 00 0p 0q FF
    return bytes([_camera_addr(address), 0x01, 0x04, 0x43, 0x00, 0x00, hi, lo, 0xFF])


def build_cam_r_gain_inquiry(address: int = 1) -> bytes:
    return bytes([_camera_addr(address), 0x09, 0x04, 0x43, 0xFF])


def build_cam_b_gain_direct(value: int, address: int = 1) -> bytes:
    hi, lo = _u8_to_nibbles(value)
    # FCB-ES8230 manual: 8x 01 04 44 00 00 0p 0q FF
    return bytes([_camera_addr(address), 0x01, 0x04, 0x44, 0x00, 0x00, hi, lo, 0xFF])


def build_cam_b_gain_inquiry(address: int = 1) -> bytes:
    return bytes([_camera_addr(address), 0x09, 0x04, 0x44, 0xFF])


def build_cam_saturation(value: int, address: int = 1) -> bytes:
    # VISCA "Color Gain" is commonly used as saturation.
    v = max(0, min(0x0E, int(value)))
    # FCB-ES8230 manual: 8x 01 04 49 00 00 00 0p FF
    return bytes([_camera_addr(address), 0x01, 0x04, 0x49, 0x00, 0x00, 0x00, v & 0x0F, 0xFF])


def build_cam_zoom_direct(value: int, address: int = 1) -> bytes:
    # FCB-ES8230 manual: 8x 01 04 47 0p 0q 0r 0s FF
    # Optical range is up to 0x4000 in standard separate mode.
    p, q, r, s = _u16_to_nibbles(max(0, min(0x4000, int(value))))
    return bytes([_camera_addr(address), 0x01, 0x04, 0x47, p, q, r, s, 0xFF])


def build_cam_nd_filter(mode: int, address: int = 1) -> bytes:
    # FCB-ES8230 manual: 8x 01 7E 01 53 0p FF
    # p=0 OFF, p=1 ND1, p=2 ND2, p=3 ND3
    p = max(0, min(3, int(mode)))
    return bytes([_camera_addr(address), 0x01, 0x7E, 0x01, 0x53, p & 0x0F, 0xFF])


def build_cam_ae_manual(address: int = 1) -> bytes:
    return bytes([_camera_addr(address), 0x01, 0x04, 0x39, 0x03, 0xFF])


def build_cam_wb_manual(address: int = 1) -> bytes:
    return bytes([_camera_addr(address), 0x01, 0x04, 0x35, 0x05, 0xFF])


def build_cam_version_inquiry(address: int = 1) -> bytes:
    return bytes([_camera_addr(address), 0x09, 0x00, 0x02, 0xFF])


def build_cam_saturation_inquiry(address: int = 1) -> bytes:
    return bytes([_camera_addr(address), 0x09, 0x04, 0x49, 0xFF])


def decode_u8_from_inquiry_payload(payload: bytes) -> Optional[int]:
    if len(payload) == 1:
        return payload[0] & 0x0F
    if len(payload) < 2:
        return None
    hi = payload[-2] & 0x0F
    lo = payload[-1] & 0x0F
    return (hi << 4) | lo


def parse_visca_response(frame: bytes) -> Optional[dict]:
    if not frame or frame[-1] != 0xFF or len(frame) < 3:
        return None
    if frame[0] < 0x90 or frame[0] > 0x9F:
        return {"kind": "other", "frame": frame}

    kind = "other"
    socket = None
    code = None

    b1 = frame[1]
    if (b1 & 0xF0) == 0x40:
        kind = "ack"
        socket = b1 & 0x0F
    elif (b1 & 0xF0) == 0x50:
        kind = "completion"
        socket = b1 & 0x0F
    elif b1 in (0x60, 0x61, 0x62) and len(frame) >= 4:
        kind = "error"
        # Error frame format is typically: z0 6y zz FF
        # where zz carries the error/detail code.
        code = frame[2]

    payload = bytes(frame[2:-1]) if len(frame) > 3 else b""
    return {"kind": kind, "socket": socket, "code": code, "payload": payload, "frame": frame}
