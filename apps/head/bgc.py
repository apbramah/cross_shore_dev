from machine import UART
import struct


class BGC:
    """Encapsulate BGC UART communication and related helpers."""

    UART_ID = 0           # 0 or 1
    UART_BAUD = 115200
    BUFFER_SIZE = 1024

    PACKET_START = 0x24

    CMD_SET_ADJ_VARS_VAL = 31
    CMD_API_VIRT_CH_CONTROL = 45
    CMD_CONTROL_EXT = 121
    CMD_CONTROL = 67
    CMD_BEEP_SOUND = 89

    def __init__(self):
        self.uart = UART(self.UART_ID, self.UART_BAUD)

    @staticmethod
    def hexdump(data: bytes) -> str:
        """Return a hex dump string for given bytes."""
        return " ".join(f"{b:02X}" for b in data)

    @staticmethod
    def decode_udp_packet(data: bytes):
        """Decode a 16-byte control packet into fields."""
        if len(data) != 16:
            print("Unexpected length:", len(data))
            return None

        if data[0] != 0xDE:
            print("Invalid header:", data[0])
            return None

        data_type = data[1]

        if data_type == 0xFD:
            zoom, focus, iris, yaw, pitch, roll, _ = struct.unpack("<6H2s", data[2:16])
            return {
                "zoom": zoom,
                "focus": focus,
                "iris": iris,
                "yaw": yaw,
                "pitch": pitch,
                "roll": roll,
            }
        elif data_type == 0xF3:
            pitch, roll, yaw, zoom, focus, iris, _ = struct.unpack("<6H2s", data[2:16])
            return {
                "zoom": zoom,
                "focus": focus,
                "iris": iris,
                "yaw": yaw,
                "pitch": pitch,
                "roll": roll,
            }

    @staticmethod
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

    def create_packet(self, command_id, payload):
        payload_size = len(payload)
        header_checksum = (command_id + payload_size) % 256
        header = bytearray([command_id, payload_size, header_checksum])
        header_and_payload = header + payload
        crc = self.crc16_calculate(header_and_payload)
        crc_bytes = bytearray([crc & 0xFF, (crc >> 8) & 0xFF])
        return bytearray([self.PACKET_START]) + header_and_payload + crc_bytes

    # === High-level helpers corresponding to specific CMD_ values ===

    def set_gyro_heading_adjustment(self):
        payload = bytearray([0x01, 0x26, 0x00, 0x15, 0x00, 0x00])
        packet = self.create_packet(self.CMD_SET_ADJ_VARS_VAL, payload)
        self.uart.write(packet)

    def disable_angle_mode(self):
        payload = bytearray([
            0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00
        ])
        packet = self.create_packet(self.CMD_CONTROL, payload)
        self.uart.write(packet)

    def beep(self):
        payload = bytearray([0x02, 0x00, 0x00, 0x00, 0x00, 0x00,
                             0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
        packet = self.create_packet(self.CMD_BEEP_SOUND, payload)
        self.uart.write(packet)

    def send_joystick_control(self, yaw, pitch, roll):
        payload = struct.pack(">3H", yaw, pitch, roll)
        packet = self.create_packet(self.CMD_API_VIRT_CH_CONTROL, payload)
        print("UART joystick -->", self.hexdump(packet))
        self.uart.write(packet)


