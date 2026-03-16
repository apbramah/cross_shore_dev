# =====================================
# MVP Head Firmware (Ethernet + Control)
# =====================================

import network
import machine
import time
import socket
import struct
import json

from bgc import BGC
from lens_controller import LensController, LENS_FUJI
import fuji_lens_from_calibration
import fuji_control_calibration
from i2c_status_payload import build_status_frame_from_runtime
from i2c_status_slave import I2CStatusSlave

# Set False for BGC-only hardware variants with no lens connected.
ENABLE_LENS = True

# Explicit startup Fuji ownership mode (applied once).
# - "pc_all": zoom/focus/iris on host
# - "pc_zf_camera_i": zoom/focus host, iris camera
FUJI_OWNERSHIP_MODE = "pc_all"
FAST_CHANNEL_MODE = "v2"  # Set to "legacy" for immediate rollback.
ENABLE_DUAL_CHANNEL = FAST_CHANNEL_MODE == "v2"
ENABLE_SLOW_CHANNEL = True   # Slow receive/apply remains active in both modes.
CTRL_DEBUG = False
CTRL_DEBUG_INTERVAL_MS = 250
ENABLE_STARTUP_BIT = True
MVP_FAST_DEBUG = False
MVP_FAST_DEBUG_INTERVAL_MS = 5000
SLOW_DEBUG = False
# Set True to log Fuji focus input/target and UART connection (SW4 poll, FOCUS TX).
FUJI_DEBUG = False
I2C_STATUS_ENABLE = True
I2C_STATUS_BUS_ID = 1
I2C_STATUS_SDA_PIN = 4
I2C_STATUS_SCL_PIN = 5
I2C_STATUS_ADDRESS = 0x3A
I2C_STATUS_FREQ_HZ = 100_000
HEAD_NETWORK_CONFIG_FILE = "head_network_config.json"

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
spi = machine.SPI(
    0,
    2_000_000,
    mosi=machine.Pin(19),
    miso=machine.Pin(16),
    sck=machine.Pin(18)
)

nic = network.WIZNET5K(  # type: ignore[attr-defined]
    spi,
    machine.Pin(17),  # CS
    machine.Pin(20)   # RESET
)

nic.active(True)

DEFAULT_ETHERNET_CONFIG = {
    "ip": "192.168.111.14",
    "prefix": 24,
    "gateway": "192.168.111.1",
    "dns": "8.8.8.8",
}


def _parse_ipv4_parts(value):
    raw = str(value or "").strip()
    parts = raw.split(".")
    if len(parts) != 4:
        return False, []
    out = []
    for p in parts:
        if not p or (not p.isdigit()):
            return False, []
        n = int(p)
        if n < 0 or n > 255:
            return False, []
        out.append(n)
    if out[0] == 0 or out[0] >= 224 or out[0] == 127:
        return False, []
    if out[3] <= 0 or out[3] >= 255:
        return False, []
    return True, out


def _ip_parts_to_u32(parts):
    return (
        ((int(parts[0]) & 0xFF) << 24)
        | ((int(parts[1]) & 0xFF) << 16)
        | ((int(parts[2]) & 0xFF) << 8)
        | (int(parts[3]) & 0xFF)
    )


def _u32_to_ip_str(value):
    v = int(value) & 0xFFFFFFFF
    return "{}.{}.{}.{}".format((v >> 24) & 0xFF, (v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF)


def _prefix_to_mask(prefix):
    p = int(prefix)
    if p <= 0:
        return "0.0.0.0"
    if p >= 32:
        return "255.255.255.255"
    mask = ((0xFFFFFFFF << (32 - p)) & 0xFFFFFFFF)
    return _u32_to_ip_str(mask)


def _prefix_mask_u32(prefix):
    p = int(prefix)
    if p <= 0:
        return 0
    if p >= 32:
        return 0xFFFFFFFF
    return ((0xFFFFFFFF << (32 - p)) & 0xFFFFFFFF)


def _same_subnet(ip_u32, gw_u32, prefix):
    mask = _prefix_mask_u32(prefix)
    return (int(ip_u32) & mask) == (int(gw_u32) & mask)


def _sanitize_network_config(raw):
    if not isinstance(raw, dict):
        return None
    try:
        prefix = int(raw.get("prefix", 24))
    except Exception:
        return None
    if prefix < 1 or prefix > 30:
        return None
    ok_ip, ip_parts = _parse_ipv4_parts(raw.get("ip", ""))
    ok_gw, gw_parts = _parse_ipv4_parts(raw.get("gateway", ""))
    if not ok_ip or not ok_gw:
        return None
    ip_u32 = _ip_parts_to_u32(ip_parts)
    gw_u32 = _ip_parts_to_u32(gw_parts)
    if ip_u32 == gw_u32:
        return None
    if not _same_subnet(ip_u32, gw_u32, prefix):
        return None
    ok_dns, dns_parts = _parse_ipv4_parts(raw.get("dns", DEFAULT_ETHERNET_CONFIG["dns"]))
    dns_ip = _u32_to_ip_str(_ip_parts_to_u32(dns_parts)) if ok_dns else DEFAULT_ETHERNET_CONFIG["dns"]
    return {
        "ip": _u32_to_ip_str(ip_u32),
        "prefix": prefix,
        "gateway": _u32_to_ip_str(gw_u32),
        "dns": dns_ip,
    }


def _load_head_network_config():
    cfg = None
    try:
        with open(HEAD_NETWORK_CONFIG_FILE, "r") as f:
            cfg = json.load(f)
    except Exception:
        cfg = None
    if cfg is None:
        cfg = DEFAULT_ETHERNET_CONFIG
    normalized = _sanitize_network_config(cfg)
    if normalized is None:
        normalized = dict(DEFAULT_ETHERNET_CONFIG)
    return normalized


def _save_head_network_config(cfg):
    try:
        with open(HEAD_NETWORK_CONFIG_FILE, "w") as f:
            json.dump(cfg, f)
        return True
    except Exception as exc:
        print("Failed to save head network config:", exc)
        return False


def _apply_nic_config(cfg):
    ip = str(cfg.get("ip", "")).strip()
    gateway = str(cfg.get("gateway", "")).strip()
    dns = str(cfg.get("dns", DEFAULT_ETHERNET_CONFIG["dns"])).strip() or DEFAULT_ETHERNET_CONFIG["dns"]
    prefix = int(cfg.get("prefix", 24))
    mask = _prefix_to_mask(prefix)
    try:
        nic.ifconfig((ip, mask, gateway, dns))
        return True, "nic_config_applied"
    except Exception as exc:
        return False, str(exc)


active_network_config = _load_head_network_config()
_ok_nic, _nic_msg = _apply_nic_config(active_network_config)
if not _ok_nic:
    # No fallback behavior after push; keep running and allow manual controller subnet match.
    print("NIC config apply failed:", _nic_msg)

while not nic.isconnected():
    time.sleep(0.2)

print("Ethernet ready:", nic.ifconfig())

i2c_status_slave = None
if I2C_STATUS_ENABLE:
    try:
        i2c_status_slave = I2CStatusSlave(
            bus_id=I2C_STATUS_BUS_ID,
            sda_pin=I2C_STATUS_SDA_PIN,
            scl_pin=I2C_STATUS_SCL_PIN,
            address=I2C_STATUS_ADDRESS,
            freq=I2C_STATUS_FREQ_HZ,
        )
        print(
            "[I2C_STATUS] enabled=",
            i2c_status_slave.available,
            "backend=",
            i2c_status_slave.backend_name,
            "addr=0x{:02X}".format(I2C_STATUS_ADDRESS),
        )
        if not i2c_status_slave.available and i2c_status_slave.last_error:
            print("[I2C_STATUS] init warning:", i2c_status_slave.last_error)
    except Exception as exc:
        i2c_status_slave = None
        print("[I2C_STATUS] init failed:", exc)

# ---------- Hardware ----------
bgc = BGC()
if ENABLE_LENS:
    lens = LensController(default_lens_type=LENS_FUJI)
    detected = lens.detect_and_switch_lens_type()
    print("[LENS] detection:", lens.get_lens_type() if detected else "none (no reply, left as fuji)")
else:
    lens = None
last_applied_lens_type = None
last_applied_sources = {"zoom": "pc", "focus": "pc", "iris": "pc"}
_last_slow_apply_id = None
_last_slow_seq = None
slow_motors_on = True
slow_control_mode = "speed"
_last_ctrl_debug_ms = 0
_fast_recv_count = 0
_last_fast_fields = None
_last_fast_debug_ms = 0
_last_slow_sender_ip = None
_last_telem_ms = 0
_lens_name_last_try_ms = 0
_last_bgc_imu_attitude = None
pending_network_push = {
    "ip_hi": None,
    "ip_lo": None,
    "gw_hi": None,
    "gw_lo": None,
    "prefix": None,
}
NETWORK_CONFIG_MODE_HOLD_MS = 5000
network_config_mode_until_ms = 0

if lens is not None:
    print("BGC + ENG lens ready")
else:
    print("BGC-only mode (lens disabled)")

if FUJI_DEBUG and lens is not None:
    fuji_lens_from_calibration.FUJI_FOCUS_DEBUG = True
    fuji_control_calibration.FUJI_CONN_DEBUG = True
    print("Fuji focus/connection debug ON")

if lens is not None and lens.get_lens_type() == "canon":
    import canon_lens
    canon_lens.CANON_DEBUG = True
    print("Canon control debug ON")

if lens is not None:
    # Lens startup is timing-sensitive on real hardware; give it a short settle window.
    for remaining in range(8, 0, -1):
        print("Waiting for lens settle...", remaining, "s")
        time.sleep(1)
if ENABLE_STARTUP_BIT and lens is not None:
    bit_ok = lens.startup_diagnostics()
    print("LENS startup diagnostics:", "PASS" if bit_ok else "FAIL")
else:
    bit_ok = True
    print("LENS startup diagnostics: SKIPPED")

def _fuji_sw4_bits_from_sources(sources):
    bits = 0xF8
    if sources.get("focus") != "pc":
        bits |= 0x01
    if sources.get("zoom") != "pc":
        bits |= 0x02
    if sources.get("iris") != "pc":
        bits |= 0x04
    return bits & 0xFF


def apply_fuji_ownership_mode_once():
    if lens is None:
        print("Fuji ownership mode skipped (lens disabled)")
        return
    mode = str(FUJI_OWNERSHIP_MODE).lower().strip()
    if lens.get_lens_type() != LENS_FUJI:
        print("Fuji ownership mode skipped (active lens is not Fuji)")
        return
    mode_map = {
        "pc_all": {"zoom": "pc", "focus": "pc", "iris": "pc"},
        "pc_zf_camera_i": {"zoom": "pc", "focus": "pc", "iris": "camera"},
    }
    desired_sources = mode_map.get(mode)
    if desired_sources is None:
        print("Fuji ownership mode ignored (invalid mode):", mode)
        return
    for axis in ("zoom", "focus", "iris"):
        source = desired_sources[axis]
        ok = lens.set_axis_source(axis, source)
        print("Fuji ownership apply", axis, "->", source, "ok=" + str(ok))
    effective_sources = lens.get_axis_sources()
    print(
        "Fuji ownership mode effective:",
        mode,
        "sources=" + str(effective_sources),
        "desired_sw4=0x{:02X}".format(_fuji_sw4_bits_from_sources(effective_sources)),
    )

apply_fuji_ownership_mode_once()
if lens is not None:
    last_applied_lens_type = lens.get_lens_type()
    last_applied_sources = lens.get_axis_sources()
    name = lens.get_lens_full_name()
    if name:
        print("[LENS] Connected lens:", name)
    else:
        print("[LENS] Connected lens:", lens.get_lens_type(), "(name not available)")

# ---------- UDP ----------
FAST_UDP_PORT = 8888
SLOW_UDP_PORT = 8890

PKT_MAGIC = 0xDE
PKT_VER = 0x01
PKT_FAST_CTRL = 0x10
PKT_SLOW_CMD = 0x20
PKT_SLOW_ACK = 0x21
PKT_SLOW_TELEM = 0x30
SLOW_TELEM_PORT = 8891
SLOW_KEY_MOTORS_ON = 1
SLOW_KEY_CONTROL_MODE = 2
SLOW_KEY_LENS_SELECT = 3
SLOW_KEY_SOURCE_ZOOM = 4
SLOW_KEY_SOURCE_FOCUS = 5
SLOW_KEY_SOURCE_IRIS = 6
SLOW_KEY_FILTER_ENABLE_FOCUS = 7
SLOW_KEY_FILTER_ENABLE_IRIS = 8
SLOW_KEY_FILTER_NUM = 9
SLOW_KEY_FILTER_DEN = 10
SLOW_KEY_GYRO_HEADING_CORRECTION = 11
SLOW_KEY_WASH_WIPE = 12
SLOW_KEY_PAN_ACCEL = 13
SLOW_KEY_TILT_ACCEL = 14
SLOW_KEY_ROLL_ACCEL = 15
SLOW_KEY_PAN_GAIN = 16
SLOW_KEY_TILT_GAIN = 17
SLOW_KEY_ROLL_GAIN = 18
SLOW_KEY_NETCFG_IP_HI = 40
SLOW_KEY_NETCFG_IP_LO = 41
SLOW_KEY_NETCFG_GW_HI = 42
SLOW_KEY_NETCFG_GW_LO = 43
SLOW_KEY_NETCFG_PREFIX = 44
SLOW_KEY_NETCFG_APPLY = 45
SLOW_KEY_NETCFG_ENTER = 46
SLOW_KEY_NETCFG_EXIT = 47
SLOW_KEY_NAMES = {
    SLOW_KEY_MOTORS_ON: "motors_on",
    SLOW_KEY_CONTROL_MODE: "control_mode",
    SLOW_KEY_LENS_SELECT: "lens_select",
    SLOW_KEY_SOURCE_ZOOM: "source_zoom",
    SLOW_KEY_SOURCE_FOCUS: "source_focus",
    SLOW_KEY_SOURCE_IRIS: "source_iris",
    SLOW_KEY_FILTER_ENABLE_FOCUS: "filter_enable_focus",
    SLOW_KEY_FILTER_ENABLE_IRIS: "filter_enable_iris",
    SLOW_KEY_FILTER_NUM: "filter_num",
    SLOW_KEY_FILTER_DEN: "filter_den",
    SLOW_KEY_GYRO_HEADING_CORRECTION: "gyro_heading_correction",
    SLOW_KEY_WASH_WIPE: "wash_wipe",
    SLOW_KEY_PAN_ACCEL: "pan_accel",
    SLOW_KEY_TILT_ACCEL: "tilt_accel",
    SLOW_KEY_ROLL_ACCEL: "roll_accel",
    SLOW_KEY_PAN_GAIN: "pan_gain",
    SLOW_KEY_TILT_GAIN: "tilt_gain",
    SLOW_KEY_ROLL_GAIN: "roll_gain",
    SLOW_KEY_NETCFG_IP_HI: "netcfg_ip_hi",
    SLOW_KEY_NETCFG_IP_LO: "netcfg_ip_lo",
    SLOW_KEY_NETCFG_GW_HI: "netcfg_gw_hi",
    SLOW_KEY_NETCFG_GW_LO: "netcfg_gw_lo",
    SLOW_KEY_NETCFG_PREFIX: "netcfg_prefix",
    SLOW_KEY_NETCFG_APPLY: "netcfg_apply",
    SLOW_KEY_NETCFG_ENTER: "netcfg_enter",
    SLOW_KEY_NETCFG_EXIT: "netcfg_exit",
}

sock_fast = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock_fast.bind(("0.0.0.0", FAST_UDP_PORT))
sock_fast.setblocking(False)

sock_slow = None
if ENABLE_SLOW_CHANNEL:
    sock_slow = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock_slow.bind(("0.0.0.0", SLOW_UDP_PORT))
    sock_slow.setblocking(False)
sock_telem = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

print("Listening FAST UDP on", FAST_UDP_PORT)
print("Fast channel mode:", FAST_CHANNEL_MODE)
if ENABLE_SLOW_CHANNEL:
    print("Listening SLOW UDP on", SLOW_UDP_PORT)


def decode_fast_packet_v2(packet):
    # <BBBHhHHHHHH => magic, ver, type, seq, zoom, focus, iris, yaw, pitch, roll, reserved
    if len(packet) != 19:
        return None
    try:
        magic, ver, pkt_type, seq, zoom, focus, iris, yaw, pitch, roll, _ = struct.unpack("<BBBHhHHHHHH", packet)
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


def decode_slow_cmd_packet(packet):
    # <BBBHHBi => magic, ver, type, seq, apply_id, key_id, value
    if len(packet) != 12:
        return None
    try:
        magic, ver, pkt_type, seq, apply_id, key_id, value = struct.unpack("<BBBHHBi", packet)
    except Exception:
        return None
    if magic != PKT_MAGIC or ver != PKT_VER or pkt_type != PKT_SLOW_CMD:
        return None
    return {
        "seq": seq,
        "apply_id": apply_id,
        "key_id": key_id,
        "value": value,
    }


def _slow_key_name(key_id):
    return SLOW_KEY_NAMES.get(int(key_id), "unknown")


def poll_slow_command_once():
    """Read one slow command packet if available."""
    if not ENABLE_SLOW_CHANNEL or sock_slow is None:
        return None, None
    try:
        data, addr = sock_slow.recvfrom(256)
    except OSError:
        return None, None
    if not data:
        return None, None
    cmd = decode_slow_cmd_packet(data)
    if SLOW_DEBUG and cmd:
        print(
            "[SLOW][RX] from={} seq={} apply_id={} key={}({}) value={}".format(
                addr[0],
                cmd.get("seq"),
                cmd.get("apply_id"),
                cmd.get("key_id"),
                _slow_key_name(cmd.get("key_id")),
                cmd.get("value"),
            )
        )
    return cmd, addr


def _send_slow_ack(target_ip, seq, apply_id, key_id, status=1):
    if not target_ip:
        return
    try:
        pkt = struct.pack(
            "<BBBHHBB",
            PKT_MAGIC,
            PKT_VER,
            PKT_SLOW_ACK,
            int(seq) & 0xFFFF,
            int(apply_id) & 0xFFFF,
            int(key_id) & 0xFF,
            int(status) & 0xFF,
        )
        sock_telem.sendto(pkt, (target_ip, SLOW_TELEM_PORT))
        if SLOW_DEBUG:
            print(
                "[SLOW][ACK] to={} seq={} apply_id={} key={}({}) status={}".format(
                    target_ip,
                    int(seq) & 0xFFFF,
                    int(apply_id) & 0xFFFF,
                    int(key_id) & 0xFF,
                    _slow_key_name(key_id),
                    int(status) & 0xFF,
                )
            )
    except Exception:
        pass


def _update_i2c_status_frame():
    if i2c_status_slave is None:
        return
    try:
        frame = build_status_frame_from_runtime(
            nic=nic,
            v_main_mv=None,
            v_aux_mv=None,
        )
        i2c_status_slave.set_frame(frame)
    except Exception:
        pass


def _send_slow_telem():
    global _last_telem_ms, _lens_name_last_try_ms, _last_bgc_imu_attitude
    if not _last_slow_sender_ip:
        return
    now = time.ticks_ms()
    if time.ticks_diff(now, _last_telem_ms) < 500:
        return
    _last_telem_ms = now
    try:
        if lens is not None:
            lens_name = lens.get_lens_full_name()
            if not lens_name and time.ticks_diff(now, _lens_name_last_try_ms) >= 5000:
                _lens_name_last_try_ms = now
                lens_name = lens.get_lens_full_name()
            active_lens = getattr(lens, "active_lens", None)
            zoom_mode = str(getattr(active_lens, "zoom_mode", "position"))
            zoom_velocity_cmd = int((_last_fast_fields or {}).get("zoom", 0))
            zoom_speed_raw = int(getattr(active_lens, "zoom_speed", 0))
            zoom_feedback = getattr(active_lens, "_last_zoom_feedback", None)
            focus_feedback = getattr(active_lens, "_last_focus_feedback", None)
            iris_feedback = getattr(active_lens, "_last_iris_feedback", None)
            zoom_pos = int(zoom_feedback) if zoom_feedback is not None else int(getattr(active_lens, "zoom", 0))
            focus_pos = int(focus_feedback) if focus_feedback is not None else int(getattr(active_lens, "focus", 0))
            iris_pos = int(iris_feedback) if iris_feedback is not None else int(getattr(active_lens, "iris", 0))
            lens_id = lens.get_lens_type()
        else:
            lens_name = ""
            zoom_mode = "disabled"
            zoom_velocity_cmd = int((_last_fast_fields or {}).get("zoom", 0))
            zoom_speed_raw = 0
            zoom_pos = 0
            focus_pos = 0
            iris_pos = 0
            lens_id = "disabled"

        bgc_payload = {
            "power_level_main": None,
            "power_level_aux": None,
        }
        imu_att = bgc.get_imu_attitude()
        if isinstance(imu_att, dict):
            _last_bgc_imu_attitude = dict(imu_att)
        if isinstance(_last_bgc_imu_attitude, dict):
            bgc_payload["imu_attitude"] = dict(_last_bgc_imu_attitude)

        payload = {
            "slow": {
                "motors_on": 1 if slow_motors_on else 0,
                "control_mode": slow_control_mode,
                "sources": dict(last_applied_sources),
            },
            "lens": {
                "lens_id": lens_id,
                "lens_full_name": lens_name or "",
                "zoom_control_mode": zoom_mode,
                "zoom_velocity_cmd": zoom_velocity_cmd,
                "zoom_speed_raw": zoom_speed_raw,
                "positions": {
                    "zoom": zoom_pos,
                    "focus": focus_pos,
                    "iris": iris_pos,
                },
                "zoom_position": zoom_pos,
                "focus_position": focus_pos,
                "iris_position": iris_pos,
            },
            "bgc": bgc_payload,
            "i2c_status": {
                "enabled": bool(i2c_status_slave is not None),
                "available": bool(i2c_status_slave and i2c_status_slave.available),
                "backend": str(i2c_status_slave.backend_name) if i2c_status_slave else "",
                "address": int(I2C_STATUS_ADDRESS),
                "freq_hz": int(I2C_STATUS_FREQ_HZ),
                "last_error": str(i2c_status_slave.last_error) if i2c_status_slave else "",
            },
        }
        body = json.dumps(payload).encode("utf-8")
        if len(body) > 65535:
            body = body[:65535]
        pkt = struct.pack("<BBBH", PKT_MAGIC, PKT_VER, PKT_SLOW_TELEM, len(body)) + body
        sock_telem.sendto(pkt, (_last_slow_sender_ip, SLOW_TELEM_PORT))
    except Exception:
        pass


def recv_latest_fast_packet():
    """Drain fast socket and return the most recent packet."""
    latest_data = None
    latest_addr = None
    while True:
        try:
            data, addr = sock_fast.recvfrom(1024)
        except OSError:
            break
        if not data:
            continue
        latest_data = data
        latest_addr = addr
    return latest_data, latest_addr


def _decode_lens_select(v):
    return "canon" if int(v) == 1 else "fuji"


def _decode_source(v):
    iv = int(v)
    if iv == 1:
        return "camera"
    if iv == 2:
        return "off"
    return "pc"


def _network_push_u32_from_hi_lo(hi, lo):
    return (((int(hi) & 0xFFFF) << 16) | (int(lo) & 0xFFFF)) & 0xFFFFFFFF


def _network_config_mode_active():
    return time.ticks_diff(network_config_mode_until_ms, time.ticks_ms()) > 0


def _touch_network_config_mode():
    global network_config_mode_until_ms
    network_config_mode_until_ms = time.ticks_add(time.ticks_ms(), NETWORK_CONFIG_MODE_HOLD_MS)


def _clear_network_config_mode():
    global network_config_mode_until_ms
    network_config_mode_until_ms = 0


def _clear_pending_network_push():
    pending_network_push["ip_hi"] = None
    pending_network_push["ip_lo"] = None
    pending_network_push["gw_hi"] = None
    pending_network_push["gw_lo"] = None
    pending_network_push["prefix"] = None


def _apply_network_slow_command(seq, apply_id, key, value):
    global active_network_config
    if key == SLOW_KEY_NETCFG_ENTER:
        _clear_pending_network_push()
        _touch_network_config_mode()
        _send_slow_ack(_last_slow_sender_ip, seq, apply_id, key, 1)
        return
    if key == SLOW_KEY_NETCFG_EXIT:
        _clear_network_config_mode()
        _clear_pending_network_push()
        _send_slow_ack(_last_slow_sender_ip, seq, apply_id, key, 1)
        return
    if key == SLOW_KEY_NETCFG_IP_HI:
        _touch_network_config_mode()
        pending_network_push["ip_hi"] = int(value) & 0xFFFF
        _send_slow_ack(_last_slow_sender_ip, seq, apply_id, key, 1)
        return
    if key == SLOW_KEY_NETCFG_IP_LO:
        _touch_network_config_mode()
        pending_network_push["ip_lo"] = int(value) & 0xFFFF
        _send_slow_ack(_last_slow_sender_ip, seq, apply_id, key, 1)
        return
    if key == SLOW_KEY_NETCFG_GW_HI:
        _touch_network_config_mode()
        pending_network_push["gw_hi"] = int(value) & 0xFFFF
        _send_slow_ack(_last_slow_sender_ip, seq, apply_id, key, 1)
        return
    if key == SLOW_KEY_NETCFG_GW_LO:
        _touch_network_config_mode()
        pending_network_push["gw_lo"] = int(value) & 0xFFFF
        _send_slow_ack(_last_slow_sender_ip, seq, apply_id, key, 1)
        return
    if key == SLOW_KEY_NETCFG_PREFIX:
        _touch_network_config_mode()
        p = int(value)
        if p < 1 or p > 30:
            _send_slow_ack(_last_slow_sender_ip, seq, apply_id, key, 0)
            _clear_network_config_mode()
            return
        pending_network_push["prefix"] = p
        _send_slow_ack(_last_slow_sender_ip, seq, apply_id, key, 1)
        return
    if key == SLOW_KEY_NETCFG_APPLY:
        _touch_network_config_mode()
        required = ("ip_hi", "ip_lo", "gw_hi", "gw_lo", "prefix")
        for field in required:
            if pending_network_push.get(field) is None:
                _send_slow_ack(_last_slow_sender_ip, seq, apply_id, key, 0)
                _clear_network_config_mode()
                return
        ip_u32 = _network_push_u32_from_hi_lo(pending_network_push["ip_hi"], pending_network_push["ip_lo"])
        gw_u32 = _network_push_u32_from_hi_lo(pending_network_push["gw_hi"], pending_network_push["gw_lo"])
        prefix = int(pending_network_push["prefix"])
        dns = DEFAULT_ETHERNET_CONFIG["dns"]
        try:
            dns = str(nic.ifconfig()[3])
        except Exception:
            pass
        proposed = {
            "ip": _u32_to_ip_str(ip_u32),
            "prefix": prefix,
            "gateway": _u32_to_ip_str(gw_u32),
            "dns": dns,
        }
        normalized = _sanitize_network_config(proposed)
        if normalized is None:
            _send_slow_ack(_last_slow_sender_ip, seq, apply_id, key, 0)
            _clear_pending_network_push()
            _clear_network_config_mode()
            return
        ok_apply, msg_apply = _apply_nic_config(normalized)
        if not ok_apply:
            print("Network push apply failed:", msg_apply)
            _send_slow_ack(_last_slow_sender_ip, seq, apply_id, key, 0)
            _clear_pending_network_push()
            _clear_network_config_mode()
            return
        active_network_config = normalized
        _save_head_network_config(active_network_config)
        print("Network push applied:", active_network_config)
        _send_slow_ack(_last_slow_sender_ip, seq, apply_id, key, 1)
        _clear_pending_network_push()
        _clear_network_config_mode()
        return


def apply_slow_command(cmd):
    global last_applied_lens_type, last_applied_sources, _last_slow_apply_id, _last_slow_seq
    global slow_motors_on, slow_control_mode
    apply_id = cmd.get("apply_id")
    seq = cmd.get("seq")
    if apply_id == _last_slow_apply_id and seq == _last_slow_seq:
        if SLOW_DEBUG:
            print(
                "[SLOW][DROP] duplicate seq={} apply_id={} key={}({}) value={}".format(
                    seq,
                    apply_id,
                    cmd.get("key_id"),
                    _slow_key_name(cmd.get("key_id")),
                    cmd.get("value"),
                )
            )
        return
    _last_slow_apply_id = apply_id
    _last_slow_seq = seq
    key = cmd.get("key_id")
    value = cmd.get("value")
    if SLOW_DEBUG:
        print(
            "[SLOW][APPLY] seq={} apply_id={} key={}({}) value={}".format(
                seq, apply_id, key, _slow_key_name(key), value
            )
        )
    if key in (
        SLOW_KEY_NETCFG_IP_HI,
        SLOW_KEY_NETCFG_IP_LO,
        SLOW_KEY_NETCFG_GW_HI,
        SLOW_KEY_NETCFG_GW_LO,
        SLOW_KEY_NETCFG_PREFIX,
        SLOW_KEY_NETCFG_APPLY,
        SLOW_KEY_NETCFG_ENTER,
        SLOW_KEY_NETCFG_EXIT,
    ):
        _apply_network_slow_command(seq, apply_id, key, value)
        return
    if _network_config_mode_active():
        # During config transaction, reject non-config slow keys to preserve deterministic apply.
        _send_slow_ack(_last_slow_sender_ip, seq, apply_id, key, 0)
        return
    _send_slow_ack(_last_slow_sender_ip, seq, apply_id, key, 1)
    if key == SLOW_KEY_LENS_SELECT:
        # Ignore: lens type is determined by head at boot (Fuji/Canon detection). Controller must not override.
        return

    if key == SLOW_KEY_SOURCE_ZOOM:
        if lens is None:
            return
        src = _decode_source(value)
        if src != last_applied_sources.get("zoom"):
            if lens.set_axis_source("zoom", src):
                last_applied_sources["zoom"] = src
                print("Slow apply source_zoom ->", src)
        return

    if key == SLOW_KEY_SOURCE_FOCUS:
        if lens is None:
            return
        src = _decode_source(value)
        if src != last_applied_sources.get("focus"):
            if lens.set_axis_source("focus", src):
                last_applied_sources["focus"] = src
                print("Slow apply source_focus ->", src)
        return

    if key == SLOW_KEY_SOURCE_IRIS:
        if lens is None:
            return
        src = _decode_source(value)
        if src != last_applied_sources.get("iris"):
            if lens.set_axis_source("iris", src):
                last_applied_sources["iris"] = src
                print("Slow apply source_iris ->", src)
        return

    if key == SLOW_KEY_FILTER_ENABLE_FOCUS:
        if lens is None:
            return
        enabled = int(value) != 0
        if lens.set_input_filter_enabled("focus", enabled):
            print("Slow apply focus_filter_enabled ->", enabled)
        return

    if key == SLOW_KEY_FILTER_ENABLE_IRIS:
        if lens is None:
            return
        enabled = int(value) != 0
        if lens.set_input_filter_enabled("iris", enabled):
            print("Slow apply iris_filter_enabled ->", enabled)
        return

    if key == SLOW_KEY_FILTER_NUM:
        if lens is None:
            return
        if lens.set_input_filter_num(int(value)):
            print("Slow apply input_filter_num ->", int(value))
        return

    if key == SLOW_KEY_FILTER_DEN:
        if lens is None:
            return
        if lens.set_input_filter_den(int(value)):
            print("Slow apply input_filter_den ->", int(value))
        return

    if key == SLOW_KEY_MOTORS_ON:
        enabled = int(value) != 0
        if enabled != slow_motors_on:
            slow_motors_on = enabled
            bgc.set_motors_enabled(enabled)
            print("Slow apply motors_on ->", 1 if enabled else 0, "(BGC CMD sent)")
        return

    if key == SLOW_KEY_CONTROL_MODE:
        mode = "angle" if int(value) == 1 else "speed"
        if mode != slow_control_mode:
            slow_control_mode = mode
            if mode == "speed":
                bgc.disable_angle_mode()
                print("Slow apply control_mode -> speed (angle mode disabled)")
            else:
                print("Slow apply control_mode -> angle (accepted; apply pending)")
        return

    if key == SLOW_KEY_GYRO_HEADING_CORRECTION:
        v = int(value)
        print("Slow recv gyro_heading_correction key/value:", key, v)
        bgc.set_gyro_heading_correction(v)
        print("Slow apply gyro_heading_correction ->", v, "(BGC CMD sent)")
        return

    if key == SLOW_KEY_WASH_WIPE:
        v = 1 if int(value) != 0 else 0
        bgc.set_wash_wipe_mode(v)
        print("Slow apply wash_wipe ->", "wiping" if v else "parked")
        return

    if key == SLOW_KEY_PAN_ACCEL:
        v = max(0, min(255, int(value)))
        bgc.set_axis_accel("yaw", v)
        print("Slow apply pan_accel ->", v)
        return

    if key == SLOW_KEY_TILT_ACCEL:
        v = max(0, min(255, int(value)))
        bgc.set_axis_accel("pitch", v)
        print("Slow apply tilt_accel ->", v)
        return

    if key == SLOW_KEY_ROLL_ACCEL:
        v = max(0, min(255, int(value)))
        bgc.set_axis_accel("roll", v)
        print("Slow apply roll_accel ->", v)
        return

    if key == SLOW_KEY_PAN_GAIN:
        v = max(0, min(255, int(value)))
        bgc.set_axis_gain("yaw", v)
        print("Slow apply pan_gain ->", v)
        return

    if key == SLOW_KEY_TILT_GAIN:
        v = max(0, min(255, int(value)))
        bgc.set_axis_gain("pitch", v)
        print("Slow apply tilt_gain ->", v)
        return

    if key == SLOW_KEY_ROLL_GAIN:
        v = max(0, min(255, int(value)))
        bgc.set_axis_gain("roll", v)
        print("Slow apply roll_gain ->", v)
        return

# ---------- Main Loop ----------
while True:
    pulse_update()
    bgc.poll_imu_attitude()
    _update_i2c_status_frame()
    if i2c_status_slave is not None:
        i2c_status_slave.poll()
    slow_poll_budget = 8 if _network_config_mode_active() else 1
    for _ in range(slow_poll_budget):
        _slow_cmd, _slow_addr = poll_slow_command_once()
        if not _slow_cmd:
            break
        if _slow_addr:
            _last_slow_sender_ip = _slow_addr[0]
        apply_slow_command(_slow_cmd)
    _send_slow_telem()

    data, addr = recv_latest_fast_packet()

    if not data:
        # Keep lens ownership/keepalive alive even without incoming UDP packets.
        if lens is not None:
            lens.periodic()
        time.sleep(0.001)
        continue

    if ENABLE_DUAL_CHANNEL:
        fields = decode_fast_packet_v2(data)
        if not fields:
            if lens is not None:
                lens.periodic()
            continue
    else:
        fields = BGC.decode_udp_packet(data)
    if not fields:
        if lens is not None:
            lens.periodic()
        continue

    _fast_recv_count += 1
    _last_fast_fields = fields
    if MVP_FAST_DEBUG:
        now_fd = time.ticks_ms()
        if time.ticks_diff(now_fd, _last_fast_debug_ms) >= MVP_FAST_DEBUG_INTERVAL_MS:
            _last_fast_debug_ms = now_fd
            print(
                "[FAST_DEBUG] recvs=",
                _fast_recv_count,
                "seq=",
                fields.get("seq"),
                "yaw pitch roll zoom focus iris:",
                fields.get("yaw"),
                fields.get("pitch"),
                fields.get("roll"),
                fields.get("zoom"),
                fields.get("focus"),
                fields.get("iris"),
            )

    if CTRL_DEBUG:
        now_dbg = time.ticks_ms()
        if time.ticks_diff(now_dbg, _last_ctrl_debug_ms) >= CTRL_DEBUG_INTERVAL_MS:
            _last_ctrl_debug_ms = now_dbg
            print(
                "CTRL YPRZFI:",
                fields["yaw"],
                fields["pitch"],
                fields["roll"],
                fields["zoom"],
                fields["focus"],
                fields["iris"],
            )
    pulse(15)

    # Apply slow gate to BGC joystick stream.
    if slow_motors_on:
        # SimpleBGC CMD 45 Speed: u16 0 -> -500, 32768 -> 0, 65535 -> +500; int16 LE
        def u16_to_bgc_speed(u):
            u = max(0, min(65535, int(u)))
            s = round((u - 32768) / 32768.0 * 500.0)
            return max(-500, min(500, s))
        yaw_s = u16_to_bgc_speed(fields["yaw"])
        pitch_s = u16_to_bgc_speed(fields["pitch"])
        roll_s = u16_to_bgc_speed(fields["roll"])
        bgc.send_joystick_control(yaw_s, pitch_s, roll_s)

    # Runtime lens commands are not gated by startup BIT. Lens type is fixed at head boot (detection); do not apply from controller.
    lens_control = fields.get("lens_control") or {}
    if lens is not None and lens_control:
        requested_sources = lens_control.get("axis_sources", {}) or {}
        for axis in ("zoom", "focus", "iris"):
            req_src = requested_sources.get(axis)
            if req_src and req_src != last_applied_sources.get(axis):
                ok = lens.set_axis_source(axis, req_src)
                if ok:
                    last_applied_sources[axis] = req_src
                    print("Applied source from packet:", axis, "->", req_src)

    if lens is not None:
        lens.move_zoom(fields["zoom"])
        lens.set_focus_input(fields["focus"])
        lens.set_iris_input(fields["iris"])
        lens.periodic()
