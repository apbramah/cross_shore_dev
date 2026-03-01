class CanonFrameParser:
    """
    Reassembles frames from arbitrary byte chunks.
    Handles:
      - Type-A: 3 bytes, ends with BF
      - Type-B: 6 bytes, ends with BF
      - Type-C: BE ... BF (variable length)
    """

    def __init__(self):
        self.buf = bytearray()

    def feed(self, data: bytes) -> list[bytes]:
        self.buf += data
        frames: list[bytes] = []

        while True:
            if not self.buf:
                break

            # Type-C: starts with BE, ends with BF
            if self.buf[0] == 0xBE:
                try:
                    end_i = self.buf.index(0xBF, 1)
                except ValueError:
                    break  # wait for more bytes
                frames.append(bytes(self.buf[: end_i + 1]))
                del self.buf[: end_i + 1]
                continue

            # Wait until we have enough bytes to decide
            if len(self.buf) < 3:
                break

            # Type-A: 3 bytes ending BF
            if self.buf[2] == 0xBF:
                frames.append(bytes(self.buf[:3]))
                del self.buf[:3]
                continue

            if len(self.buf) < 6:
                break

            # Type-B: 6 bytes ending BF
            if self.buf[5] == 0xBF:
                frames.append(bytes(self.buf[:6]))
                del self.buf[:6]
                continue

            # Resync: drop one byte and try again
            del self.buf[0]

        return frames
