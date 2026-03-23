from machine import UART, Pin
import time

UART_ID = 0
BAUD = 115200
TX_PIN = 0
RX_PIN = 1

u = UART(UART_ID, BAUD, tx=Pin(TX_PIN), rx=Pin(RX_PIN), bits=8, parity=None, stop=1)


def hexdump(b):
    return " ".join("%02X" % x for x in b) if b else "(none)"


print("[PAYLOAD] UART test start")
print("[PAYLOAD] UART0 TX=GP0 RX=GP1 @ 115200 8N1")

next_hb = time.ticks_ms()
hb_seq = 0

while True:
    # Echo responder
    if u.any():
        rx = u.read(256)
        if rx:
            try:
                txt = rx.decode("utf-8", "ignore").strip()
            except Exception:
                txt = ""
            print("[PAYLOAD][RX] HEX:", hexdump(rx), "| TXT:", txt)

            ack = "ACK_FROM_PAYLOAD %d for: %s\n" % (hb_seq, txt if txt else "(binary)")
            data = ack.encode("utf-8")
            u.write(data)
            print("[PAYLOAD][TX]", ack.strip(), "| HEX:", hexdump(data))
            hb_seq += 1

    # Optional payload heartbeat every 2000 ms
    now = time.ticks_ms()
    if time.ticks_diff(now, next_hb) >= 0:
        hb = "PAYLOAD_HEARTBEAT %d\n" % hb_seq
        d = hb.encode("utf-8")
        u.write(d)
        print("[PAYLOAD][TX]", hb.strip(), "| HEX:", hexdump(d))
        hb_seq += 1
        next_hb = time.ticks_add(now, 2000)

    time.sleep_ms(10)
