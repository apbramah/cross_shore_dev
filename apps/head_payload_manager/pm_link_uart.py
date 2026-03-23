from machine import UART, Pin


class PMLinkUART:
    def __init__(self, uart_id=0, tx_pin=0, rx_pin=1, baud=115200):
        self.uart = UART(
            int(uart_id),
            int(baud),
            tx=Pin(int(tx_pin)),
            rx=Pin(int(rx_pin)),
            bits=8,
            parity=None,
            stop=1,
        )

    def write(self, data):
        if data:
            self.uart.write(data)

    def read(self, max_bytes=256):
        if self.uart.any():
            return self.uart.read(int(max_bytes))
        return None
