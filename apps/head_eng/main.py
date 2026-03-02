# =====================================
# MVP Head Firmware (Ethernet + Control)
# =====================================

import network
import machine
import socket
import struct
import time

from bgc import BGC
from lens_controller import LensController, LENS_FUJI

PKT_MAGIC = 0xDE
PKT_VER = 0x01
PKT_FAST_CTRL = 0x10
PKT_SLOW_CMD = 0x20
PKT_SLOW_ACK = 0x21
PKT_SLOW_TELEM = 0x30

FAST_PORT = 8888
SLOW_CMD_PORT = 8890
SLOW_TELEM_DST_PORT = 8892

FAST_WATCHDOG_MS = 250
TELEMETRY_PERIOD_MS = 500  # 2Hz

KEY_MOTORS_ON = 1
KEY_CONTROL_MODE = 13
KEY_LENS_SELECT = 20
KEY_SOURCE_ZOOM = 21
KEY_SOURCE_FOCUS = 22
KEY_SOURCE_IRIS = 23

SLOW_STATE = {
    "motors_on": 1,
    "pan_gain": 0,
    "tilt_gain": 0,
    "roll_gain": 0,
    "pan_acceleration": 0,
    "tilt_acceleration": 0,
    "roll_acceleration": 0,
    "expo": 0,
    "pan_top_speed": 0,
    "tilt_top_speed": 0,
    "roll_top_speed": 0,
    "gyro_drift_offset": 0,
    "control_mode": "speed",
}

# ---------- LED ----------
led = machine.Pin("LED", machine.Pin.OUT)
pulse_until = 0


def pulse(ms=20):
    global pulse_until
    led.on()
    pulse_until = time.ticks_add(time.ticks_ms(), ms)


def pulse_update():
    global pulse_until
    if pulse_until and time.ticks_diff(time.ticks_ms(), pulse_until) >= 0:
        led.off()
        pulse_until = 0


# ---------- Ethernet ----------
spi = machine.SPI(0, 2_000_000, mosi=machine.Pin(19), miso=machine.Pin(16), sck=machine.Pin(18))
nic = network.WIZNET5K(spi, machine.Pin(17), machine.Pin(20))
nic.active(True)
nic.ifconfig(("192.168.60.120", "255.255.255.0", "192.168.60.1", "8.8.8.8"))
while not nic.isconnected():
    time.sleep(0.2)
print("Ethernet ready:", nic.ifconfig())

# ---------- Hardware ----------
bgc = BGC()
lens = LensController(default_lens_type=LENS_FUJI)
print("BGC + ENG lens ready")
for remaining in range(8, 0, -1):
    print("Waiting for lens settle...", remaining, "s")
    time.sleep(1)
bit_ok = lens.startup_diagnostics()
print("LENS startup diagnostics:", "PASS" if bit_ok else "FAIL")

# ---------- UDP ----------
fast_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
fast_sock.bind(("0.0.0.0", FAST_PORT))
fast_sock.setblocking(False)

slow_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
slow_sock.bind(("0.0.0.0", SLOW_CMD_PORT))
slow_sock.setblocking(False)

print("Listening FAST UDP on", FAST_PORT)
print("Listening SLOW UDP on", SLOW_CMD_PORT)

last_fast_ms = time.ticks_ms()
last_fast_fields = {"yaw": 0, "pitch": 0, "roll": 0, "zoom": 0, "focus": 0, "iris": 0}
last_telem_ms = 0
slow_peer_ip = None
telem_seq = 0
last_fast_seq = 0


def decode_fast_packet(data):
    if len(data) != 19:
        return None
    try:
        magic, ver, pkt_type, seq, zoom, focus, iris, yaw, pitch, roll, _ = struct.unpack("<BBBHhHHHHHH", data)
    except Exception:
        return None
    if magic != PKT_MAGIC or ver != PKT_VER or pkt_type != PKT_FAST_CTRL:
        return None
    return {
        "seq": seq,
        "zoom": zoom,
        "focus": focus,
        "iris": iris,
        "yaw": yaw,
        "pitch": pitch,
        "roll": roll,
    }


def decode_slow_cmd_packet(data):
    if len(data) != 12:
        return None
    try:
        magic, ver, pkt_type, seq, apply_id, key_id, value = struct.unpack("<BBBHHBi", data)
    except Exception:
        return None
    if magic != PKT_MAGIC or ver != PKT_VER or pkt_type != PKT_SLOW_CMD:
        return None
    return {"seq": seq, "apply_id": apply_id, "key_id": key_id, "value": value}


def build_slow_ack_packet(seq, apply_id, key_id, status):
    return struct.pack("<BBBHHBB", PKT_MAGIC, PKT_VER, PKT_SLOW_ACK, seq & 0xFFFF, apply_id & 0xFFFF, key_id & 0xFF, status & 0xFF)


def _decode_source_enum(v):
    if int(v) == 1:
        return "camera"
    if int(v) == 2:
        return "off"
    return "pc"


def _decode_lens_enum(v):
    return "canon" if int(v) == 1 else "fuji"


def _decode_control_mode(v):
    return "angle" if int(v) == 1 else "speed"


def _encode_source_enum(v):
    s = str(v).lower()
    if s == "camera":
        return 1
    if s == "off":
        return 2
    return 0


def _encode_lens_enum(v):
    return 1 if str(v).lower() == "canon" else 0


def _encode_control_mode(v):
    return 1 if str(v).lower() == "angle" else 0


def _apply_slow_command(key_id, value):
    # status 0=ok, 1=invalid key/value, 2=apply failed
    if key_id == KEY_MOTORS_ON:
        SLOW_STATE["motors_on"] = 1 if int(value) else 0
        return 0
    if key_id == KEY_CONTROL_MODE:
        SLOW_STATE["control_mode"] = _decode_control_mode(value)
        return 0
    if key_id == KEY_LENS_SELECT:
        want = _decode_lens_enum(value)
        ok = lens.set_lens_type(want)
        if not ok:
            return 2
        print("Slow apply lens_select ->", want)
        return 0
    if key_id == KEY_SOURCE_ZOOM:
        src = _decode_source_enum(value)
        return 0 if lens.set_axis_source("zoom", src) else 2
    if key_id == KEY_SOURCE_FOCUS:
        src = _decode_source_enum(value)
        return 0 if lens.set_axis_source("focus", src) else 2
    if key_id == KEY_SOURCE_IRIS:
        src = _decode_source_enum(value)
        return 0 if lens.set_axis_source("iris", src) else 2

    # Generic numeric slow table parameters for BGC path (stored now, apply later).
    if key_id == 2:
        SLOW_STATE["pan_gain"] = int(value)
        return 0
    if key_id == 3:
        SLOW_STATE["tilt_gain"] = int(value)
        return 0
    if key_id == 4:
        SLOW_STATE["roll_gain"] = int(value)
        return 0
    if key_id == 5:
        SLOW_STATE["pan_acceleration"] = int(value)
        return 0
    if key_id == 6:
        SLOW_STATE["tilt_acceleration"] = int(value)
        return 0
    if key_id == 7:
        SLOW_STATE["roll_acceleration"] = int(value)
        return 0
    if key_id == 8:
        SLOW_STATE["expo"] = int(value)
        return 0
    if key_id == 9:
        SLOW_STATE["pan_top_speed"] = int(value)
        return 0
    if key_id == 10:
        SLOW_STATE["tilt_top_speed"] = int(value)
        return 0
    if key_id == 11:
        SLOW_STATE["roll_top_speed"] = int(value)
        return 0
    if key_id == 12:
        SLOW_STATE["gyro_drift_offset"] = int(value)
        return 0
    return 1


def build_telem_packet(seq):
    lens_status = lens.get_status()
    return struct.pack(
        "<BBBHBBHHHHBBBBHHH",
        PKT_MAGIC,
        PKT_VER,
        PKT_SLOW_TELEM,
        seq & 0xFFFF,
        1 if SLOW_STATE["motors_on"] else 0,
        _encode_control_mode(SLOW_STATE["control_mode"]),
        0,  # voltage_mv unknown in current firmware path
        0,  # pan position unknown here
        0,  # tilt position unknown here
        0,  # roll position unknown here
        _encode_lens_enum(lens_status["lens_select"]),
        _encode_source_enum(lens_status["source_zoom"]),
        _encode_source_enum(lens_status["source_focus"]),
        _encode_source_enum(lens_status["source_iris"]),
        int(lens_status["zoom_position"]) & 0xFFFF,
        int(lens_status["focus_position"]) & 0xFFFF,
        int(lens_status["iris_position"]) & 0xFFFF,
    )


# ---------- Main Loop ----------
while True:
    pulse_update()
    now_ms = time.ticks_ms()

    # Read all pending fast packets; only apply latest.
    got_fast = False
    while True:
        try:
            data, _ = fast_sock.recvfrom(1024)
        except OSError:
            break
        fields = decode_fast_packet(data)
        if not fields:
            continue
        last_fast_fields = fields
        last_fast_seq = fields["seq"]
        last_fast_ms = now_ms
        got_fast = True

    if got_fast:
        print(
            "CTRL seq/YPRZFI:",
            last_fast_seq,
            last_fast_fields["yaw"],
            last_fast_fields["pitch"],
            last_fast_fields["roll"],
            last_fast_fields["zoom"],
            last_fast_fields["focus"],
            last_fast_fields["iris"],
        )
        pulse(15)

    # Read all pending slow command packets and ACK each apply.
    while True:
        try:
            data, addr = slow_sock.recvfrom(1024)
        except OSError:
            break
        cmd = decode_slow_cmd_packet(data)
        if not cmd:
            continue
        slow_peer_ip = addr[0]
        status = _apply_slow_command(cmd["key_id"], cmd["value"])
        ack = build_slow_ack_packet(cmd["seq"], cmd["apply_id"], cmd["key_id"], status)
        try:
            slow_sock.sendto(ack, addr)
        except OSError:
            pass

    # Fast watchdog: ramp to neutral when stream goes stale.
    if time.ticks_diff(now_ms, last_fast_ms) > FAST_WATCHDOG_MS:
        stale = {"yaw": 0, "pitch": 0, "roll": 0, "zoom": 0, "focus": 0, "iris": 0}
        last_fast_fields = stale

    # Apply motion paths.
    bgc.send_joystick_control(last_fast_fields["yaw"], last_fast_fields["pitch"], last_fast_fields["roll"])
    if bit_ok:
        lens.move_zoom(last_fast_fields["zoom"])
        lens.set_focus_input(last_fast_fields["focus"])
        lens.set_iris_input(last_fast_fields["iris"])
    lens.periodic()

    # 2Hz telemetry from head -> bridge.
    if slow_peer_ip and time.ticks_diff(now_ms, last_telem_ms) >= TELEMETRY_PERIOD_MS:
        telem_seq = (telem_seq + 1) & 0xFFFF
        telem = build_telem_packet(telem_seq)
        try:
            slow_sock.sendto(telem, (slow_peer_ip, SLOW_TELEM_DST_PORT))
        except OSError:
            pass
        last_telem_ms = now_ms

    time.sleep(0.001)
