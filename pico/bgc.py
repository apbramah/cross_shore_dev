import uasyncio as asyncio
from machine import Pin, UART

cmd_dict = {
    82: "CMD_READ_PARAMS",
    87: "CMD_WRITE_PARAMS",
    68: "CMD_REALTIME_DATA",
    86: "CMD_BOARD_INFO",
    65: "CMD_CALIB_ACC",
    103: "CMD_CALIB_GYRO",
    71: "CMD_CALIB_EXT_GAIN",
    70: "CMD_USE_DEFAULTS",
    80: "CMD_CALIB_POLES",
    114: "CMD_RESET",
    72: "CMD_HELPER_DATA",
    79: "CMD_CALIB_OFFSET",
    66: "CMD_CALIB_BAT",
    77: "CMD_MOTORS_ON",
    109: "CMD_MOTORS_OFF",
    67: "CMD_CONTROL",
    84: "CMD_TRIGGER_PIN",
    69: "CMD_EXECUTE_MENU",
    73: "CMD_GET_ANGLES",
    67: "CMD_CONFIRM",
    20: "CMD_BOARD_INFO_3",
    21: "CMD_READ_PARAMS_3",
    22: "CMD_WRITE_PARAMS_3",
    23: "CMD_REALTIME_DATA_3",
    25: "CMD_REALTIME_DATA_4",
    24: "CMD_SELECT_IMU_3",
    28: "CMD_READ_PROFILE_NAMES",
    29: "CMD_WRITE_PROFILE_NAMES",
    30: "CMD_QUEUE_PARAMS_INFO_3",
    31: "CMD_SET_ADJ_VARS_VAL",
    32: "CMD_SAVE_PARAMS_3",
    33: "CMD_READ_PARAMS_EXT",
    34: "CMD_WRITE_PARAMS_EXT",
    35: "CMD_AUTO_PID",
    36: "CMD_SERVO_OUT",
    37: "CMD_BODE_TEST_START_STOP",
    39: "CMD_I2C_WRITE_REG_BUF",
    40: "CMD_I2C_READ_REG_BUF",
    41: "CMD_WRITE_EXTERNAL_DATA",
    42: "CMD_READ_EXTERNAL_DATA",
    43: "CMD_READ_ADJ_VARS_CFG",
    44: "CMD_WRITE_ADJ_VARS_CFG",
    45: "CMD_API_VIRT_CH_CONTROL",
    46: "CMD_ADJ_VARS_STATE",
    47: "CMD_EEPROM_WRITE",
    48: "CMD_EEPROM_READ",
    49: "CMD_CALIB_INFO",
    50: "CMD_SIGN_MESSAGE",
    51: "CMD_BOOT_MODE_3",
    52: "CMD_SYSTEM_STATE",
    53: "CMD_READ_FILE",
    54: "CMD_WRITE_FILE",
    55: "CMD_FS_CLEAR_ALL",
    56: "CMD_AHRS_HELPER",
    57: "CMD_RUN_SCRIPT",
    58: "CMD_SCRIPT_DEBUG",
    59: "CMD_CALIB_MAG",
    61: "CMD_GET_ANGLES_EXT",
    62: "CMD_READ_PARAMS_EXT2",
    63: "CMD_WRITE_PARAMS_EXT2",
    64: "CMD_GET_ADJ_VARS_VAL",
    74: "CMD_CALIB_MOTOR_MAG_LINK",
    75: "CMD_GYRO_CORRECTION",
    76: "CMD_MODULE_LIST",
    85: "CMD_DATA_STREAM_INTERVAL",
    88: "CMD_REALTIME_DATA_CUSTOM",
    89: "CMD_BEEP_SOUND",
    26: "CMD_ENCODERS_CALIB_OFFSET_4",
    27: "CMD_ENCODERS_CALIB_FLD_OFFSET_4",
    90: "CMD_CONTROL_CONFIG",
    91: "CMD_CALIB_ORIENT_CORR",
    92: "CMD_COGGING_CALIB_INFO",
    93: "CMD_CALIB_COGGING",
    94: "CMD_CALIB_ACC_EXT_REF",
    95: "CMD_PROFILE_SET",
    96: "CMD_CAN_DEVICE_SCAN",
    97: "CMD_CAN_DRV_HARD_PARAMS",
    98: "CMD_CAN_DRV_STATE",
    99: "CMD_CAN_DRV_CALIBRATE",
    100: "CMD_READ_RC_INPUTS",
    101: "CMD_REALTIME_DATA_CAN_DRV",
    102: "CMD_EVENT",
    104: "CMD_READ_PARAMS_EXT3",
    105: "CMD_WRITE_PARAMS_EXT3",
    106: "CMD_EXT_IMU_DEBUG_INFO",
    107: "CMD_SET_DEVICE_ADDR",
    108: "CMD_AUTO_PID2",
    110: "CMD_EXT_IMU_CMD",
    111: "CMD_READ_STATE_VARS",
    112: "CMD_WRITE_STATE_VARS",
    113: "CMD_SERIAL_PROXY",
    115: "CMD_IMU_ADVANCED_CALIB",
    116: "CMD_API_VIRT_CH_HIGH_RES",
    117: "CMD_CALIB_ENCODER_LUT",
    118: "CMD_CALIB_ENCODER_LUT_RES",
    119: "CMD_WRITE_PARAMS_SET",
    120: "CMD_CALIB_CUR_SENS",
    121: "CMD_CONTROL_EXT",
    122: "CMD_ENC_INT_CALIB",
    123: "CMD_SYNC_MOTORS",
    124: "CMD_EXT_LICENSE_INFO",
    125: "CMD_VIBRATION_TEST_START_STOP",
    126: "CMD_VIBRATION_TEST_DATA",
    127: "CMD_CAN_DRV_TELEMETRY",
    128: "CMD_EXT_MOTORS_ACTION",
    129: "CMD_EXT_MOTORS_CONTROL",
    130: "CMD_EXT_MOTORS_CONTROL_CONFIG",
    131: "CMD_EXT_MOTORS_STATE",
    132: "CMD_ADJ_VARS_INFO",
    133: "CMD_SERVO_OUT_EXT",
    134: "CMD_SET_ADJ_VARS_VAL_F",
    135: "CMD_GET_ADJ_VARS_VAL_F",
    140: "CMD_CONTROL_QUAT",
    141: "CMD_CONTROL_QUAT_STATUS",
    142: "CMD_CONTROL_QUAT_CONFIG",
    150: "CMD_EXT_SENS_CMD",
    151: "CMD_TRANSPARENT_SAPI",
    249: "CMD_SET_DEBUG_PORT",
    250: "CMD_MAVLINK_INFO",
    251: "CMD_MAVLINK_DEBUG",
    253: "CMD_DEBUG_VARS_INFO_3",
    254: "CMD_DEBUG_VARS_3",
    255: "CMD_ERROR",
}

# CRC calculation function
def crc16_calculate(data):
    polynomial = 0x8005
    crc_register = 0
    for byte in data:
        for shift_register in range(8):
            data_bit = (byte >> shift_register) & 1
            crc_bit = (crc_register >> 15) & 1
            crc_register = (crc_register << 1) & 0xFFFF
            if data_bit != crc_bit:
                crc_register ^= polynomial
    return crc_register

PACKET_START = 0x24
HEADER_LEN = 3
CRC_LEN = 2

# Generate a test packet with proper CRC
def create_test_packet(command_id=0x56, payload=b'\x00\x00'):
    header = bytearray([command_id, len(payload), 0x58])  # header checksum placeholder
    header_and_payload = header + payload
    crc = crc16_calculate(header_and_payload)
    crc_bytes = bytearray([crc & 0xFF, (crc >> 8) & 0xFF])
    return bytearray([PACKET_START]) + header_and_payload + crc_bytes

async def monitor(uart, name="UART"):
    buffer = bytearray()
    while True:
        # Read all available bytes
        if uart.any():
            data = uart.read()
            if data:
                buffer.extend(data)

        # Process buffer for packets
        while True:
            # Look for the start byte
            try:
                start_index = buffer.index(bytes([PACKET_START]))
            except ValueError:
                # Start byte not found, clear buffer
                buffer = bytearray()
                break

            # Remove any bytes before the start byte
            if start_index > 0:
                buffer = buffer[start_index:]

            # Minimum length check
            if len(buffer) < 1 + HEADER_LEN + CRC_LEN:
                break  # wait for more data

            payload_len = buffer[2]
            total_len = 1 + HEADER_LEN + payload_len + CRC_LEN

            # Wait until full packet is received
            if len(buffer) < total_len:
                break

            # Extract packet
            packet = buffer[:total_len]
            header_and_payload = packet[1:-2]
            received_crc = (packet[-1] << 8) | packet[-2]
            calc_crc = crc16_calculate(header_and_payload)

            command_id = packet[1]
            command_name = cmd_dict.get(command_id, "UNKNOWN_CMD")
            if received_crc == calc_crc:
                print(f"{name}: Valid {command_name}", [hex(x) for x in packet])
            else:
                print(f"{name}: CRC error:", [hex(x) for x in packet])

            # Remove processed packet from buffer
            buffer = buffer[total_len:]

        await asyncio.sleep(0.01)

# Periodic test packet sender
async def test(uart, interval=2.0):
    while True:
        packet = create_test_packet()
        uart.write(packet)
        await asyncio.sleep(interval)

async def main():
    uart0 = UART(0, baudrate=115200, tx=Pin(0), rx=Pin(1))
    uart1 = UART(1, baudrate=115200, tx=Pin(4), rx=Pin(5))
    await asyncio.gather(
        monitor(uart0, "UART0"),
        monitor(uart1, "UART1"),
        test(uart0, interval=0.01),
        test(uart1, interval=0.01)
    )

if __name__ == "__main__":
    asyncio.run(main())
