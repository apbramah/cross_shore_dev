"""
VISCA stream parser: frames are terminated by 0xFF.
"""

from __future__ import annotations


class SonyViscaFrameParser:
    def __init__(self) -> None:
        self.buf = bytearray()

    def feed(self, data: bytes) -> list[bytes]:
        self.buf += data
        frames: list[bytes] = []

        while True:
            try:
                i = self.buf.index(0xFF)
            except ValueError:
                break

            frame = bytes(self.buf[: i + 1])
            del self.buf[: i + 1]
            if frame:
                frames.append(frame)

        return frames
