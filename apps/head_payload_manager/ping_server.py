from machine import UART, Pin
import time
import json

u = UART(0, 115200, tx=Pin(0), rx=Pin(1), bits=8, parity=None, stop=1)
buf = bytearray()

print("[PING_SERVER] start UART0 GP0/GP1 115200 8N1")


def idx_of(b, v):
    i = 0
    n = len(b)
    while i < n:
        if b[i] == v:
            return i
        i += 1
    return -1


while True:
    if u.any():
        d = u.read(256)
        if d:
            buf.extend(d)

    while True:
        nl = idx_of(buf, 0x0A)
        if nl < 0:
            break
        line = bytes(buf[:nl]).strip()
        buf = buf[nl + 1 :]
        if not line:
            continue

        try:
            msg = json.loads(line.decode("utf-8"))
        except Exception:
            continue

        print("[PING_SERVER][RX]", msg)

        if isinstance(msg, dict) and msg.get("type") == "cmd" and msg.get("cmd") == "ping":
            resp = {
                "magic": "hpm1",
                "type": "resp",
                "id": int(msg.get("id", 0)),
                "ok": 1,
                "result": {"pong": 1},
                "error": "",
            }
            out = (json.dumps(resp) + "\n").encode("utf-8")
            u.write(out)
            print("[PING_SERVER][TX]", resp)

    time.sleep_ms(5)
