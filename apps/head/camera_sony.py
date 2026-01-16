from machine import UART

UART_ID = 1           # 0 or 1
UART_BAUD = 9600
BUFFER_SIZE = 1024

def hexdump(data: bytes) -> str:
    """Return a hex dump string for given bytes."""
    return " ".join(f"{b:02X}" for b in data)

class CameraSony:
    def __init__(self):
        self.uart = UART(UART_ID, UART_BAUD)
        self.zoom = 0

    def write_raw(self, data: bytes):
        print("Writing:", hexdump(data))
        self.uart.write(data)

    def read_raw(self, max_bytes: int = BUFFER_SIZE):
        if self.uart.any():
            data = self.uart.read(max_bytes)
            print("Reading:", hexdump(data))
            return data
        return None

    # === High-level helpers ===

    def set_zoom(self):
        zoom = self.zoom
        payload = bytearray([0x81, 0x01, 0x04, 0x47, (zoom >> 12) & 0xF, (zoom >> 8) & 0xF, (zoom >> 4) & 0xF, (zoom >> 0) & 0xF, 0xFF])
        self.write_raw(payload)

    def move_zoom(self, delta):
        zoom = self.zoom
        zoom += delta
        if zoom > 0x4000:
            zoom = 0x4000
        if zoom < 0:
            zoom = 0
        if zoom != self.zoom:
            self.zoom = zoom
            self.set_zoom()