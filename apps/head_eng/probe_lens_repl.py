# Probe lens from Thonny REPL on Pico (same UART as head_eng: UART0, TX=GP0, RX=GP1).
# In Thonny: open this file on the Pico, run it (F5), or paste the blocks into the REPL.
# Canon: 19200 8E1. Fuji: 38400 8N1.

from machine import UART, Pin
import time

UART_ID = 0
TX_PIN = 0
RX_PIN = 1

# Canon (match lens_serial / canon_protocol)
CANON_BAUD = 19200
CANON_PARITY = 0  # even
CTRL_CMD = bytes([0x80, 0xC6, 0xBF])
LENS_NAME_REQ = bytes([0xBE, 0x80, 0x81, 0x00, 0x00, 0x00, 0xBF])

# Fuji (for reference)
FUJI_BAUD = 38400
FUJI_PARITY = None


def hexdump(b):
    if not b:
        return "(none)"
    return " ".join("%02X" % x for x in b)


def make_uart(baud, parity=CANON_PARITY):
    return UART(UART_ID, baud, tx=Pin(TX_PIN), rx=Pin(RX_PIN), bits=8, parity=parity, stop=1)


def read_for(uart, timeout_ms=500):
    buf = bytearray()
    deadline = time.ticks_ms() + timeout_ms
    while time.ticks_diff(deadline, time.ticks_ms()) > 0:
        if uart.any():
            buf.extend(uart.read(256))
        else:
            time.sleep_ms(10)
    return bytes(buf)


def probe_canon():
    """Probe Canon: CTRL_CMD then LENS_NAME_REQ, print RX hex."""
    u = make_uart(CANON_BAUD, CANON_PARITY)
    time.sleep_ms(80)
    # Drain any stale data
    while u.any():
        u.read(256)
        time.sleep_ms(5)
    print("TX CTRL_CMD:", hexdump(CTRL_CMD))
    u.write(CTRL_CMD)
    rx = read_for(u, 500)
    print("RX (500ms):", hexdump(rx), "(%d bytes)" % len(rx))
    time.sleep_ms(50)
    while u.any():
        rx += u.read(256)
        time.sleep_ms(5)
    if rx:
        print("RX (drain):", hexdump(rx))
    print("TX LENS_NAME_REQ:", hexdump(LENS_NAME_REQ))
    u.write(LENS_NAME_REQ)
    rx2 = read_for(u, 2000)
    print("RX (2s):", hexdump(rx2), "(%d bytes)" % len(rx2))
    return rx2


def probe_canon_multi_baud():
    """Try 19200 8E1, 19200 8N1, 38400 8E1, 9600 8E1. Use when COM10/tester shows correct protocol but Pico gets wrong bytes (e.g. EE 30 / F8 FE 30); RP2 MicroPython parity bug at 19200 8E1 can cause corruption."""
    configs = [
        (19200, 0, "19200 8E1"),
        (19200, None, "19200 8N1"),
        (38400, 0, "38400 8E1"),
        (9600, 0, "9600 8E1"),
    ]
    for baud, par, name in configs:
        print("\n---", name, "---")
        u = make_uart(baud, par)
        time.sleep_ms(80)
        while u.any():
            u.read(256)
            time.sleep_ms(5)
        u.write(CTRL_CMD)
        r1 = read_for(u, 400)
        u.write(LENS_NAME_REQ)
        r2 = read_for(u, 1500)
        print("  CTRL_CMD rx:", hexdump(r1), "| LENS_NAME_REQ rx:", hexdump(r2))


# Run probe when file is executed
if __name__ == "__main__":
    print("Lens probe (Canon 19200 8E1, UART0 GP0/GP1)")
    print("---")
    probe_canon()
    print("\n(Optional: probe_canon_multi_baud() to try other baud/parity)")
    print("--- done")
