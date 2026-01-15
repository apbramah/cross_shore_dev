from machine import UART
import struct

UART_ID = 0           # 0 or 1
UART_BAUD = 115200
BUFFER_SIZE = 1024

PACKET_START = 0x24

CMD_SET_ADJ_VARS_VAL = 31
CMD_API_VIRT_CH_CONTROL = 45
CMD_CONTROL = 67
CMD_BEEP_SOUND = 89

class BGC:
    """Encapsulate BGC UART communication and related helpers."""

    def __init__(self):
        self.uart = UART(UART_ID, UART_BAUD)

    def write_raw(self, data: bytes):
        # The "FCB Control Software" application discovers the correct COM port by sending data to all the COM ports.
        # This has the effect of sending raw camera packets to the BGC. Now we ought to filter these erroneous packets out
        # earlier, but as a belt-and-braces measure, we'll filter it out here also. We can now be _reasonably_ sure that all
        # packets sent to the BGC are correctly formatted. Further checks for packet format could be added, but probably
        # are not worth the effort/workload.
        if data[0] != PACKET_START:
            print("Invalid header:", data[0])
            return
        
        self.uart.write(data)

    def read_raw(self, max_bytes: int = BUFFER_SIZE):
        return self.uart.read(max_bytes)

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

    def send_cmd(self, command_id, payload):
        payload_size = len(payload)
        header_checksum = (command_id + payload_size) % 256
        header = bytearray([command_id, payload_size, header_checksum])
        header_and_payload = header + payload
        crc = self.crc16_calculate(header_and_payload)
        crc_bytes = bytearray([crc & 0xFF, (crc >> 8) & 0xFF])
        packet = bytearray([PACKET_START]) + header_and_payload + crc_bytes
        self.write_raw(packet)

    # === High-level helpers corresponding to specific CMD_ values ===

    def set_gyro_heading_adjustment(self):
        payload = bytearray([0x01, 0x26, 0x00, 0x15, 0x00, 0x00])
        self.send_cmd(CMD_SET_ADJ_VARS_VAL, payload)

    def disable_angle_mode(self):
        payload = bytearray([
            0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00
        ])
        self.send_cmd(CMD_CONTROL, payload)

    def beep(self):
        payload = bytearray([0x02, 0x00, 0x00, 0x00, 0x00, 0x00,
                             0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
        self.send_cmd(CMD_BEEP_SOUND, payload)

    def send_joystick_control(self, yaw, pitch, roll):
        payload = struct.pack(">3H", yaw, pitch, roll)
        print("UART joystick -->", yaw, pitch, roll)
        self.send_cmd(CMD_API_VIRT_CH_CONTROL, payload)


