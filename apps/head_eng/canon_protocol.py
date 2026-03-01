# Canon ENG lens protocol helpers for MicroPython

CTRL_CMD = bytes([0x80, 0xC6, 0xBF])  # Type-A keepalive/controller command
FINISH_INIT = bytes([0x86, 0xC0, 0x00, 0x00, 0x00, 0xBF])  # Type-B finish init

SRC_OFF = 0x00
SRC_CAMERA = 0x08
SRC_PC = 0x10

SCMD_IRIS_SWITCH = 0x81
SCMD_ZOOM_SWITCH = 0x83
SCMD_FOCUS_SWITCH = 0x85

CMD_ZOOM_POS = 0x87
CMD_FOCUS_POS = 0x88
CMD_IRIS_POS = 0x96
SUBCMD_C0 = 0xC0


def pack_type_b_value(v):
    v = int(v)
    if v < 0:
        v = 0
    if v > 60000:
        v = 60000
    return ((v >> 14) & 0x03, (v >> 7) & 0x7F, v & 0x7F)


def build_type_b(cmd, subcmd, v):
    d1, d2, d3 = pack_type_b_value(v)
    return bytes([cmd, subcmd, d1, d2, d3, 0xBF])


def build_type_c_switch(scmd, src_bits):
    # BE 85 <S-CMD> 01 00 02 00 <DATA1> BF
    return bytes([0xBE, 0x85, scmd, 0x01, 0x00, 0x02, 0x00, src_bits & 0x7F, 0xBF])
