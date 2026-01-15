from machine import UART

UART_ID = 1           # 0 or 1
UART_BAUD = 9600
BUFFER_SIZE = 1024

class CameraSony:
    def __init__(self):
        self.uart = UART(UART_ID, UART_BAUD)

    def write_raw(self, data: bytes):
        self.uart.write(data)

    def read_raw(self, max_bytes: int = BUFFER_SIZE):
        return self.uart.read(max_bytes)
