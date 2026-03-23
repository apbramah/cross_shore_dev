"""
Fuji port adapter for payload manager.

Uses a dedicated software UART path by default so Fuji and Canon buses stay
electrically independent.
"""

from soft_uart_pio import SoftUART


class FujiPort:
    def __init__(self, tx_pin=13, rx_pin=14, baud=38400, sm_tx_id=2, sm_rx_id=3):
        self.soft_uart = SoftUART(
            tx_pin=int(tx_pin),
            rx_pin=int(rx_pin),
            baud=int(baud),
            sm_tx_id=int(sm_tx_id),
            sm_rx_id=int(sm_rx_id),
        )
        self.lens_name = ""
        self.zoom = 32768
        self.focus = 32768
        self.iris = 32768

    def probe(self):
        if not self.soft_uart.available:
            return False
        data = self.soft_uart.read()
        return bool(data)

    def read_name(self):
        return self.lens_name or None

    def set_positions(self, zoom=None, focus=None, iris=None):
        if zoom is not None:
            self.zoom = int(zoom)
        if focus is not None:
            self.focus = int(focus)
        if iris is not None:
            self.iris = int(iris)

    def get_positions(self):
        return {
            "zoom": int(self.zoom),
            "focus": int(self.focus),
            "iris": int(self.iris),
        }
