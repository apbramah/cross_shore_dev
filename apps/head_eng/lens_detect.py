# Lens detection: probe shared UART for Fuji or Canon (one connected at a time).
# Does not modify Fuji/Canon runtime; additive probe only. MicroPython-safe.

from fuji_protocol import (
    FUJI_BAUD,
    FUJI_BITS,
    FUJI_PARITY,
    FUJI_STOP,
    FUNC_CONNECT,
    build_connect,
    parse_l10_frame,
)
from canon_protocol import CTRL_CMD, LENS_NAME_REQ

# Canon UART settings (match canon_lens.CanonLens and CanonLensTester: 19200 8E1).
# RP2040: MicroPython had a parity bug at 19200 8E1 (wrong timing); fixed in later builds (see micropython PR #10987). If Pico gets corrupt RX (e.g. EE 30 / F8 FE 30 instead of 80 C6 BF / BE 80 81 ... BF), try upgrading MicroPython or probe_canon_multi_baud() to test 8N1.
CANON_BAUD = 19200
CANON_BITS = 8
CANON_PARITY = 0  # even
CANON_STOP = 1

FUJI_PROBE_TIMEOUT_MS = 1200
CANON_PROBE_TIMEOUT_MS = 2000  # match tester timeout for LENS_NAME_REQ
CANON_SETTLE_MS = 80  # settle after UART reconfig before first Canon TX


def _ticks_ms():
    import time
    if hasattr(time, "ticks_ms"):
        return time.ticks_ms()
    return int(time.time() * 1000)


def _ticks_diff(a, b):
    import time
    if hasattr(time, "ticks_diff"):
        return time.ticks_diff(a, b)
    return a - b


def _drain(transport):
    """Discard all bytes currently in the transport RX buffer."""
    while True:
        data = transport.read()
        if not data:
            return


def _probe_fuji(transport):
    """Configure for Fuji, send connect, wait for CONNECT ACK. Returns True if ACK received."""
    transport.configure(FUJI_BAUD, bits=FUJI_BITS, parity=FUJI_PARITY, stop=FUJI_STOP)
    _drain(transport)
    connect_req = build_connect(True)  # 00 01 FF
    transport.write(connect_req)
    buf = bytearray()
    deadline = _ticks_ms() + FUJI_PROBE_TIMEOUT_MS
    while _ticks_diff(deadline, _ticks_ms()) > 0:
        data = transport.read()
        if data:
            buf.extend(data)
        while len(buf) >= 3:
            data_len = buf[0] & 0x0F
            need = 3 + data_len
            if len(buf) < need:
                break
            frame = bytes(buf[:need])
            buf = buf[need:]
            parsed = parse_l10_frame(frame)
            if parsed and parsed[0] == FUNC_CONNECT:
                # Reject echo: Canon can echo our 00 01 FF back; real Fuji sends a different ACK (e.g. 01 01 00 FE).
                if frame == connect_req:
                    continue
                return True
        # Small yield so we don't spin
        if not data:
            try:
                import time
                time.sleep_ms(5)
            except Exception:
                pass
    return False


def _probe_canon(transport):
    """Configure for Canon, send LENS_NAME_REQ, wait for 0xBE 0x80 0x81 ... 0xBF. Returns True if seen."""
    transport.configure(CANON_BAUD, bits=CANON_BITS, parity=CANON_PARITY, stop=CANON_STOP)
    try:
        import time
        if hasattr(time, "sleep_ms"):
            time.sleep_ms(CANON_SETTLE_MS)
        else:
            time.sleep(CANON_SETTLE_MS / 1000.0)
    except Exception:
        pass
    _drain(transport)
    # Match tester: send CTRL_CMD first so lens is ready; it may echo 0x80 0xC6 0xBF (Type-A).
    transport.write(CTRL_CMD)
    try:
        import time
        if hasattr(time, "sleep_ms"):
            time.sleep_ms(80)
        else:
            time.sleep(0.08)
    except Exception:
        pass
    _drain(transport)
    transport.write(LENS_NAME_REQ)
    buf = bytearray()
    deadline = _ticks_ms() + CANON_PROBE_TIMEOUT_MS
    prefix = (0xBE, 0x80, 0x81)
    terminator = 0xBF
    while _ticks_diff(deadline, _ticks_ms()) > 0:
        data = transport.read()
        if data:
            buf.extend(data)
        # Canon protocol: response starts BE 80 81, ends BF (per tester / canon_protocol)
        if len(buf) >= len(prefix):
            for i in range(len(buf) - len(prefix) + 1):
                if (buf[i], buf[i + 1], buf[i + 2]) == prefix:
                    for j in range(i + 3, len(buf)):
                        if buf[j] == terminator:
                            return True
                    break
        if not data:
            try:
                import time
                time.sleep_ms(5)
            except Exception:
                pass
    # Debug: show what we got (often 0x80 0xC6 0xBF = Type-A echo; lens may need CTRL_CMD before LENS_NAME_REQ)
    try:
        hex_str = " ".join("%02X" % b for b in buf)
        print("[DETECT] Canon probe: rx", len(buf), "bytes:", hex_str)
    except Exception:
        print("[DETECT] Canon probe: rx", len(buf), "bytes")
    return False


def detect_lens(transport):
    """
    Probe transport for Fuji then Canon. Only one lens is connected at a time (shared UART).
    Returns "fuji", "canon", or None. Leaves transport configured for the detected type.
    """
    print("[DETECT] probing Fuji (38400 8N1, connect ACK)...")
    if _probe_fuji(transport):
        print("[DETECT] Fuji: ACK -> fuji")
        return "fuji"
    print("[DETECT] Fuji: no ACK, probing Canon (19200 8E1, LENS_NAME_REQ)...")
    if _probe_canon(transport):
        print("[DETECT] Canon: lens name response -> canon")
        return "canon"
    print("[DETECT] Canon: no response -> none (leave as Fuji)")
    # No response: leave as Fuji so existing default behaviour is unchanged
    transport.configure(FUJI_BAUD, bits=FUJI_BITS, parity=FUJI_PARITY, stop=FUJI_STOP)
    return None
