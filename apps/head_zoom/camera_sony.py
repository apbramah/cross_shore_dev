from machine import UART, Pin

de = Pin(22, Pin.OUT)
de.value(1) # Default to receive mode

UART_ID = 0           # 0 or 1
UART_BAUD = 115200
BUFFER_SIZE = 1024

from rp2 import PIO, StateMachine, asm_pio

@asm_pio(sideset_init=PIO.OUT_HIGH, out_init=PIO.OUT_HIGH, out_shiftdir=PIO.SHIFT_RIGHT)
def uart_tx():
    # Block with TX deasserted until data available
    pull()
    # Initialise bit counter, assert start bit for 8 cycles
    set(x, 7)  .side(0)       [7]
    # Shift out 8 data bits, 8 execution cycles per bit
    label("bitloop")
    out(pins, 1)              [6]
    jmp(x_dec, "bitloop")
    # Assert stop bit for 8 cycles total (incl 1 for pull())
    nop()      .side(1)       [6]

@asm_pio(
    autopush=True,
    push_thresh=8,
    in_shiftdir=PIO.SHIFT_RIGHT,
    fifo_join=PIO.JOIN_RX,
)
def uart_rx():
    # fmt: off
    # Wait for start bit
    wait(0, pin, 0)
    # Preload bit counter, delay until eye of first data bit
    set(x, 7)                 [10]
    # Loop 8 times
    label("bitloop")
    # Sample data
    in_(pins, 1)
    # Each iteration is 8 cycles
    jmp(x_dec, "bitloop")     [6]
    # fmt: on

from machine import Pin

BAUD = 9600
tx_pin = 13
rx_pin = 14

sm_tx = StateMachine(
    0, uart_tx,
    freq=BAUD * 8,
    sideset_base=Pin(tx_pin),
    out_base=Pin(tx_pin)
)

sm_rx = StateMachine(
    1, uart_rx,
    freq=BAUD * 8,
    in_base=Pin(rx_pin, Pin.IN, Pin.PULL_UP)
)

sm_tx.active(1)
sm_rx.active(1)

def uart_write(data):
    for b in data:
        sm_tx.put(b)

def uart_read():
    my_list = []
    while sm_rx.rx_fifo():
        my_int = (sm_rx.get() >> 24) & 0xff
        my_list.append(my_int)

    if len(my_list) > 0:
        return bytearray(my_list)
    else:
        return None

class CameraSony:
    def __init__(self):
        self.zoom = 0

    def write_raw(self, data: bytes):
        print("write", data)
        uart_write(data)

    def read_raw(self, max_bytes: int = BUFFER_SIZE):
        buf = uart_read()
        if buf != None:
            print("read", buf)
        return buf

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