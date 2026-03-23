import json

MAGIC = "hpm1"


def encode_message(msg):
    data = dict(msg or {})
    data["magic"] = MAGIC
    return (json.dumps(data) + "\n").encode("utf-8")


def decode_lines_from_buffer(buf):
    out = []
    if not isinstance(buf, bytearray):
        return out
    while True:
        nl = _index_of(buf, 0x0A, 0)
        if nl < 0:
            break
        line = bytes(buf[:nl]).strip()
        # MicroPython compatibility: some builds don't support bytearray item deletion.
        # Use in-place slice replacement instead.
        buf[:] = buf[nl + 1 :]
        if not line:
            continue
        try:
            msg = json.loads(line.decode("utf-8"))
        except Exception:
            continue
        if not isinstance(msg, dict):
            continue
        if msg.get("magic") != MAGIC:
            continue
        out.append(msg)
    return out


def _index_of(buf, value, start):
    i = int(start)
    n = len(buf)
    while i < n:
        if buf[i] == value:
            return i
        i += 1
    return -1
