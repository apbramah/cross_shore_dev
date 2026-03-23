"""
PIO-backed software UART helper for RP2040.

Use this for the third UART path on payload manager when two hardware UARTs
are already used (head link + one lens bus).
"""

from machine import Pin

try:
    from rp2 import PIO, StateMachine, asm_pio
except Exception:  # pragma: no cover (host-side tools/lints)
    PIO = None
    StateMachine = None
    asm_pio = None


if asm_pio is not None:
    @asm_pio(sideset_init=PIO.OUT_HIGH, out_init=PIO.OUT_HIGH, out_shiftdir=PIO.SHIFT_RIGHT)
    def _uart_tx():
        pull()
        set(x, 7).side(0)[7]
        label("bitloop")
        out(pins, 1)[6]
        jmp(x_dec, "bitloop")
        nop().side(1)[6]


    @asm_pio(
        autopush=True,
        push_thresh=8,
        in_shiftdir=PIO.SHIFT_RIGHT,
        fifo_join=PIO.JOIN_RX,
    )
    def _uart_rx():
        wait(0, pin, 0)
        set(x, 7)[10]
        label("bitloop")
        in_(pins, 1)
        jmp(x_dec, "bitloop")[6]


class SoftUART:
    def __init__(self, tx_pin, rx_pin, baud=9600, sm_tx_id=0, sm_rx_id=1):
        self.available = False
        self._sm_tx = None
        self._sm_rx = None
        if StateMachine is None or asm_pio is None:
            return
        self._sm_tx = StateMachine(
            int(sm_tx_id),
            _uart_tx,
            freq=int(baud) * 8,
            sideset_base=Pin(int(tx_pin)),
            out_base=Pin(int(tx_pin)),
        )
        self._sm_rx = StateMachine(
            int(sm_rx_id),
            _uart_rx,
            freq=int(baud) * 8,
            in_base=Pin(int(rx_pin), Pin.IN, Pin.PULL_UP),
        )
        self._sm_tx.active(1)
        self._sm_rx.active(1)
        self.available = True

    def write(self, data):
        if not self.available or not data:
            return
        for b in data:
            self._sm_tx.put(int(b) & 0xFF)

    def read(self):
        if not self.available:
            return None
        out = []
        while self._sm_rx.rx_fifo():
            out.append((self._sm_rx.get() >> 24) & 0xFF)
        if out:
            return bytes(out)
        return None
