"""
Sony VISCA port hook for payload manager.

This is an integration stub for future Sony testing. It intentionally keeps a
stable API surface (probe/read_name/set_positions/get_positions) so boot
discovery and command routing can include Sony now without impacting current
Canon/Fuji behavior.
"""

from machine import UART, Pin


class SonyViscaPort:
    def __init__(self, uart_id=1, tx_pin=8, rx_pin=9, baud=9600, bits=8, parity=None, stop=1):
        self.uart = UART(
            int(uart_id),
            int(baud),
            tx=Pin(int(tx_pin)),
            rx=Pin(int(rx_pin)),
            bits=int(bits),
            parity=parity,
            stop=int(stop),
        )
        self.device_name = ""
        self.zoom = 0
        self.focus = 0
        self.iris = 0

    def probe(self):
        # Hook only: return False until Sony probe logic is integrated.
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
