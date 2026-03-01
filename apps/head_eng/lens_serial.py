from machine import UART, Pin

BUFFER_SIZE = 1024

# Default lens UART config (separate from BGC UART1)
DEFAULT_UART_ID = 0
DEFAULT_TX_PIN = 12
DEFAULT_RX_PIN = 13


class LensSerial:
    def __init__(
        self,
        baud,
        bits=8,
        parity=None,
        stop=1,
        uart_id=DEFAULT_UART_ID,
        tx_pin=DEFAULT_TX_PIN,
        rx_pin=DEFAULT_RX_PIN,
    ):
        self.uart_id = uart_id
        self.tx_pin = tx_pin
        self.rx_pin = rx_pin
        self.uart = None
        self.configure(baud, bits=bits, parity=parity, stop=stop)

    def configure(self, baud, bits=8, parity=None, stop=1):
        self.baud = int(baud)
        self.bits = int(bits)
        self.parity = parity
        self.stop = int(stop)
        self.uart = UART(
            self.uart_id,
            self.baud,
            tx=Pin(self.tx_pin),
            rx=Pin(self.rx_pin),
            bits=self.bits,
            parity=self.parity,
            stop=self.stop,
        )

    def write(self, data):
        if data:
            self.uart.write(data)

    def read(self, max_bytes=BUFFER_SIZE):
        if self.uart.any():
            return self.uart.read(max_bytes)
        return None
