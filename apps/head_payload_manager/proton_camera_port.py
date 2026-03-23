"""
Proton camera port hook for payload manager.

Includes GPIO direction control hook for UART/485 transceiver enable.
"""

from machine import UART, Pin


class ProtonCameraPort:
    def __init__(
        self,
        uart_id=1,
        tx_pin=8,
        rx_pin=9,
        baud=115200,
        bits=8,
        parity=None,
        stop=1,
        dir_pin=14,
        dir_tx_level=1,
        dir_rx_level=0,
    ):
        self.uart = UART(
            int(uart_id),
            int(baud),
            tx=Pin(int(tx_pin)),
            rx=Pin(int(rx_pin)),
            bits=int(bits),
            parity=parity,
            stop=int(stop),
        )
        self._dir = Pin(int(dir_pin), Pin.OUT)
        self._dir_tx_level = 1 if int(dir_tx_level) else 0
        self._dir_rx_level = 1 if int(dir_rx_level) else 0
        self.set_rx_mode()
        self.device_name = ""
        self.zoom = 0
        self.focus = 0
        self.iris = 0

    def set_tx_mode(self):
        self._dir.value(self._dir_tx_level)

    def set_rx_mode(self):
        self._dir.value(self._dir_rx_level)

    def probe(self):
        # Hook only: return False until Proton probe logic is integrated.
        self.set_rx_mode()
        return False

    def read_name(self):
        return self.device_name or None

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
