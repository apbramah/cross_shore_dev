"""
Fujinon L10 frame parser: reassembles command blocks from byte stream.
Block = [DATA_LEN][FUNC][DATA 0..15][CHECK_SUM], total 3 + (DATA_LEN & 0x0F) bytes.
"""

from __future__ import annotations

from .fuji_protocol import checksum


class FujiL10FrameParser:
    def __init__(self) -> None:
        self.buf = bytearray()

    def feed(self, data: bytes) -> list[bytes]:
        self.buf += data
        frames: list[bytes] = []

        while len(self.buf) >= 3:
            n_data = self.buf[0] & 0x0F
            block_len = 3 + n_data
            if len(self.buf) < block_len:
                break
            block = bytes(self.buf[:block_len])
            if checksum(block[: block_len - 1]) != block[block_len - 1]:
                del self.buf[0]
                continue
            frames.append(block)
            del self.buf[:block_len]

        return frames
