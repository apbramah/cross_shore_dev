import struct
import time


MAGIC0 = 0x48  # 'H'
MAGIC1 = 0x56  # 'V'
PROTO_VERSION = 1
PAYLOAD_LEN = 20
FRAME_LEN = 28

FLAG_LINK_UP = 1 << 0
FLAG_NETWORK_MODE_KNOWN = 1 << 1
FLAG_NETWORK_MODE_DHCP = 1 << 2
FLAG_VOLTAGE_MAIN_VALID = 1 << 3
FLAG_VOLTAGE_AUX_VALID = 1 << 4

VOLTAGE_UNAVAILABLE_MV = 0xFFFF


def _crc16_ibm(data):
    crc = 0x0000
    poly = 0x8005
    for byte in data:
        for bit in range(8):
            data_bit = (byte >> bit) & 1
            crc_bit = (crc >> 15) & 1
            crc = (crc << 1) & 0xFFFF
            if data_bit != crc_bit:
                crc ^= poly
    return crc & 0xFFFF


def _ipv4_to_bytes(ip_text):
    try:
        parts = [int(p) for p in str(ip_text or "").split(".")]
        if len(parts) != 4:
            return (0, 0, 0, 0)
        for p in parts:
            if p < 0 or p > 255:
                return (0, 0, 0, 0)
        return tuple(parts)
    except Exception:
        return (0, 0, 0, 0)


def _mv_from_optional(value):
    if value is None:
        return VOLTAGE_UNAVAILABLE_MV, False
    try:
        iv = int(value)
        if iv < 0:
            return VOLTAGE_UNAVAILABLE_MV, False
        if iv > 65534:
            iv = 65534
        return iv, True
    except Exception:
        return VOLTAGE_UNAVAILABLE_MV, False


def build_status_frame(
    ifconfig_tuple,
    link_up,
    network_mode_dhcp,
    network_mode_known,
    v_main_mv,
    v_aux_mv,
    source_age_ms,
):
    ip = _ipv4_to_bytes(ifconfig_tuple[0] if ifconfig_tuple and len(ifconfig_tuple) > 0 else "")
    mask = _ipv4_to_bytes(ifconfig_tuple[1] if ifconfig_tuple and len(ifconfig_tuple) > 1 else "")
    gateway = _ipv4_to_bytes(ifconfig_tuple[2] if ifconfig_tuple and len(ifconfig_tuple) > 2 else "")

    flags = 0
    if bool(link_up):
        flags |= FLAG_LINK_UP
    if bool(network_mode_known):
        flags |= FLAG_NETWORK_MODE_KNOWN
    if bool(network_mode_dhcp):
        flags |= FLAG_NETWORK_MODE_DHCP

    main_mv, main_ok = _mv_from_optional(v_main_mv)
    aux_mv, aux_ok = _mv_from_optional(v_aux_mv)
    if main_ok:
        flags |= FLAG_VOLTAGE_MAIN_VALID
    if aux_ok:
        flags |= FLAG_VOLTAGE_AUX_VALID

    try:
        age = int(source_age_ms)
    except Exception:
        age = 0
    if age < 0:
        age = 0
    if age > 0xFFFFFFFF:
        age = 0xFFFFFFFF

    without_crc = struct.pack(
        "<BBBBH4B4B4BHHI",
        MAGIC0,
        MAGIC1,
        PROTO_VERSION,
        PAYLOAD_LEN,
        flags & 0xFFFF,
        ip[0],
        ip[1],
        ip[2],
        ip[3],
        mask[0],
        mask[1],
        mask[2],
        mask[3],
        gateway[0],
        gateway[1],
        gateway[2],
        gateway[3],
        main_mv & 0xFFFF,
        aux_mv & 0xFFFF,
        age & 0xFFFFFFFF,
    )
    crc = _crc16_ibm(without_crc)
    return without_crc + struct.pack("<H", crc)


def build_status_frame_from_runtime(nic, v_main_mv=None, v_aux_mv=None):
    try:
        ifconfig_tuple = nic.ifconfig()
    except Exception:
        ifconfig_tuple = ("0.0.0.0", "0.0.0.0", "0.0.0.0", "0.0.0.0")
    try:
        link_up = bool(nic.isconnected())
    except Exception:
        link_up = False

    # Current runtime applies a static ifconfig during startup, so this is known/manual.
    network_mode_known = True
    network_mode_dhcp = False
    return build_status_frame(
        ifconfig_tuple=ifconfig_tuple,
        link_up=link_up,
        network_mode_dhcp=network_mode_dhcp,
        network_mode_known=network_mode_known,
        v_main_mv=v_main_mv,
        v_aux_mv=v_aux_mv,
        source_age_ms=0,
    )


def now_ms():
    return time.ticks_ms()
