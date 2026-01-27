from machine import UART, Pin

de = Pin(22, Pin.OUT)
de.value(1) # Default to receive mode

UART_ID = 0           # 0 or 1
UART_BAUD = 115200
BUFFER_SIZE = 1024

class CameraSony:
    def __init__(self):
        self.uart = UART(UART_ID, UART_BAUD, timeout=0)
        self.zoom = 0

    def write_raw(self, data: bytes):
        de.value(0)
        self.uart.write(data)
        self.uart.flush()
        de.value(1)

    def read_raw(self, max_bytes: int = BUFFER_SIZE):
        return self.uart.read(max_bytes)

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