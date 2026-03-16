from machine import UART, Pin
import struct
import time

UART_ID = 1           # 0 or 1
UART_BAUD = 115200
BUFFER_SIZE = 1024

PACKET_START = 0x24

CMD_SET_ADJ_VARS_VAL = 31
CMD_REALTIME_DATA_4 = 25
CMD_GET_ANGLES_EXT = 61
CMD_GET_ANGLES = 73
CMD_API_VIRT_CH_CONTROL = 45
CMD_CONTROL = 67
CMD_MOTORS_ON = 77
CMD_BEEP_SOUND = 89
CMD_MOTORS_OFF = 109
ADJ_VAR_ID_GYRO_HEADING_CORRECTION = 0x26
ADJ_VAR_ID_ACC_LIMITER_ROLL = 39
ADJ_VAR_ID_ACC_LIMITER_PITCH = 40
ADJ_VAR_ID_ACC_LIMITER_YAW = 41
ADJ_VAR_ID_PID_GAIN_ROLL = 42
ADJ_VAR_ID_PID_GAIN_PITCH = 43
ADJ_VAR_ID_PID_GAIN_YAW = 44
BGC_ANGLE_COUNT_TO_DEG = 0.02197265625  # 360 / 16384
RT4_IMU_OFFSET = 32
RT3_BAT_LEVEL_OFFSET = 50
IMU_DEBUG = True
IMU_DEBUG_INTERVAL_MS = 500
RT4_POLL_INTERVAL_MS = 40
GET_ANGLES_FALLBACK_TIMEOUT_MS = 500
GET_ANGLES_REQUEST_INTERVAL_MS = 200


def hexdump(data: bytes) -> str:
    """Return a hex dump string for given bytes."""
    return " ".join(f"{b:02X}" for b in data)


class BGC:
    """Encapsulate BGC UART communication and related helpers."""

    def __init__(self):
        self.uart = UART(UART_ID, UART_BAUD, tx=Pin(8), rx=Pin(9))
        self._rx_buf = bytearray()
        self._last_imu = None
        self._last_rt4_req_ms = 0
        self._last_get_angles_req_ms = 0
        self._last_imu_update_ms = 0
        self._last_battery_voltage_v = None
        self._last_battery_update_ms = 0
        # Fixed install corrections (can be tuned later if needed).
        self._yaw_sign = 1.0
        self._pitch_sign = 1.0
        self._roll_sign = 1.0
        self._yaw_offset_deg = 0.0
        self._pitch_offset_deg = 0.0
        self._roll_offset_deg = 0.0
        self._last_imu_debug_ms = 0

    def write_raw(self, data: bytes):
        # The "FCB Control Software" application discovers the correct COM port by sending data to all the COM ports.
        # This has the effect of sending raw camera packets to the BGC. Now we ought to filter these erroneous packets out
        # earlier, but as a belt-and-braces measure, we'll filter it out here also. We can now be _reasonably_ sure that all
        # packets sent to the BGC are correctly formatted. Further checks for packet format could be added, but probably
        # are not worth the effort/workload.
        # if data[0] != PACKET_START:
        #     return
        self.uart.write(data)

    def read_raw(self, max_bytes: int = BUFFER_SIZE):
        if self.uart.any():
            data = self.uart.read(max_bytes)
            return data
        return None

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
        ctrl0 = data[14]
        ctrl1 = data[15]
        lens_control = _decode_lens_control(ctrl0, ctrl1)

        if data_type == 0xFD:
            zoom, focus, iris, yaw, pitch, roll, _ = struct.unpack("<h5H2s", data[2:16])
            return {
                "zoom": zoom,
                "focus": focus,
                "iris": iris,
                "yaw": yaw,
                "pitch": pitch,
                "roll": roll,
                "lens_control": lens_control,
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
                "lens_control": lens_control,
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

    @staticmethod
    def _norm360(v: float) -> float:
        out = float(v) % 360.0
        if out < 0.0:
            out += 360.0
        return out

    def _update_imu_angles(self, raw_roll: int, raw_pitch: int, raw_yaw: int, source: str):
        roll_deg = float(raw_roll) * BGC_ANGLE_COUNT_TO_DEG
        pitch_deg = float(raw_pitch) * BGC_ANGLE_COUNT_TO_DEG
        yaw_deg = float(raw_yaw) * BGC_ANGLE_COUNT_TO_DEG

        corrected_roll = (self._roll_sign * roll_deg) + self._roll_offset_deg
        corrected_pitch = (self._pitch_sign * pitch_deg) + self._pitch_offset_deg
        corrected_yaw = (self._yaw_sign * yaw_deg) + self._yaw_offset_deg

        self._last_imu = {
            "source": str(source),
            "raw_roll": int(raw_roll),
            "raw_pitch": int(raw_pitch),
            "raw_yaw": int(raw_yaw),
            "roll_deg": self._norm360(corrected_roll),
            "tilt_deg": self._norm360(corrected_pitch),
            "heading_deg": self._norm360(corrected_yaw),
            "updated_at_ms": int(time.ticks_ms()),
        }
        self._last_imu_update_ms = int(self._last_imu["updated_at_ms"])

    def _parse_rt4_payload(self, payload: bytes) -> bool:
        # RT4 payload begins with full REALTIME_DATA_3 structure.
        # IMU_ANGLE[3] starts at byte offset 32 (2s*3, order ROLL,PITCH,YAW).
        if not payload or len(payload) < (RT4_IMU_OFFSET + 6):
            return False
        try:
            raw_roll, raw_pitch, raw_yaw = struct.unpack("<hhh", payload[RT4_IMU_OFFSET : RT4_IMU_OFFSET + 6])
        except Exception:
            return False
        if IMU_DEBUG:
            now = int(time.ticks_ms())
            if time.ticks_diff(now, self._last_imu_debug_ms) >= IMU_DEBUG_INTERVAL_MS:
                self._last_imu_debug_ms = now
                print("[IMU_DEBUG][RT4] len=", len(payload), "off=", RT4_IMU_OFFSET, "head=", hexdump(payload[:24]))
                # Show candidate triplets around expected IMU region.
                for off in (24, 26, 28, 30, 32, 34, 36, 38, 40):
                    if (off + 6) > len(payload):
                        break
                    try:
                        c0, c1, c2 = struct.unpack("<hhh", payload[off : off + 6])
                    except Exception:
                        continue
                    d0 = c0 * BGC_ANGLE_COUNT_TO_DEG
                    d1 = c1 * BGC_ANGLE_COUNT_TO_DEG
                    d2 = c2 * BGC_ANGLE_COUNT_TO_DEG
                    print(
                        "[IMU_DEBUG][RT4][off={}] raw=({},{},{}) deg=({:.2f},{:.2f},{:.2f})".format(
                            off, c0, c1, c2, d0, d1, d2
                        )
                    )
        self._update_imu_angles(raw_roll, raw_pitch, raw_yaw, "CMD_REALTIME_DATA_4")
        # RT4 begins with full RT3 payload; BAT_LEVEL is a RT3 field at offset 50.
        # Units are 0.01V per count.
        if len(payload) >= (RT3_BAT_LEVEL_OFFSET + 2):
            try:
                bat_raw = struct.unpack("<H", payload[RT3_BAT_LEVEL_OFFSET : RT3_BAT_LEVEL_OFFSET + 2])[0]
                bat_v = float(bat_raw) / 100.0
                if 0.0 < bat_v < 100.0:
                    self._last_battery_voltage_v = bat_v
                    self._last_battery_update_ms = int(time.ticks_ms())
            except Exception:
                pass
        return True

    def _parse_get_angles_payload(self, payload: bytes, source_cmd: str) -> bool:
        if not payload or len(payload) < 6:
            return False
        try:
            raw_roll, raw_pitch, raw_yaw = struct.unpack("<hhh", payload[:6])
        except Exception:
            return False
        if IMU_DEBUG:
            now = int(time.ticks_ms())
            if time.ticks_diff(now, self._last_imu_debug_ms) >= IMU_DEBUG_INTERVAL_MS:
                self._last_imu_debug_ms = now
                print(
                    "[IMU_DEBUG][{}] raw=({},{},{}) deg=({:.2f},{:.2f},{:.2f})".format(
                        source_cmd,
                        raw_roll,
                        raw_pitch,
                        raw_yaw,
                        raw_roll * BGC_ANGLE_COUNT_TO_DEG,
                        raw_pitch * BGC_ANGLE_COUNT_TO_DEG,
                        raw_yaw * BGC_ANGLE_COUNT_TO_DEG,
                    )
                )
        self._update_imu_angles(raw_roll, raw_pitch, raw_yaw, source_cmd)
        return True

    def _drain_uart_packets(self):
        data = self.read_raw(BUFFER_SIZE)
        if data:
            self._rx_buf.extend(data)
        packets = []
        buf = self._rx_buf
        n = len(buf)
        i = 0
        while (n - i) >= 6:
            # Find packet start without mutating buffer in-place.
            while i < n and buf[i] != PACKET_START:
                i += 1
            if (n - i) < 6:
                break
            cmd_id = int(buf[i + 1])
            payload_size = int(buf[i + 2])
            header_ck = int(buf[i + 3])
            if ((cmd_id + payload_size) & 0xFF) != header_ck:
                i += 1
                continue
            total = 1 + 3 + payload_size + 2
            if (n - i) < total:
                break
            body_start = i + 1
            body_end = body_start + 3 + payload_size
            body = bytes(buf[body_start:body_end])
            rx_crc_l = int(buf[body_end])
            rx_crc_h = int(buf[body_end + 1])
            rx_crc = rx_crc_l | (rx_crc_h << 8)
            calc_crc = self.crc16_calculate(body)
            if calc_crc != rx_crc:
                i += 1
                continue
            payload_start = i + 4
            payload_end = payload_start + payload_size
            payload = bytes(buf[payload_start:payload_end])
            packets.append((cmd_id, payload))
            i += total
        # Keep any trailing partial bytes for next poll cycle.
        if i > 0:
            self._rx_buf = bytearray(buf[i:])
        return packets

    def poll_imu_attitude(self):
        now = int(time.ticks_ms())
        if time.ticks_diff(now, self._last_rt4_req_ms) >= RT4_POLL_INTERVAL_MS:
            self._last_rt4_req_ms = now
            self.send_cmd(CMD_REALTIME_DATA_4, bytearray())
        # Fallback angle request if RT4 response is absent.
        if (
            time.ticks_diff(now, self._last_imu_update_ms) >= GET_ANGLES_FALLBACK_TIMEOUT_MS
            and time.ticks_diff(now, self._last_get_angles_req_ms) >= GET_ANGLES_REQUEST_INTERVAL_MS
        ):
            self._last_get_angles_req_ms = now
            self.send_cmd(CMD_GET_ANGLES, bytearray())

        for cmd_id, payload in self._drain_uart_packets():
            if cmd_id == CMD_REALTIME_DATA_4:
                self._parse_rt4_payload(payload)
            elif cmd_id == CMD_GET_ANGLES:
                self._parse_get_angles_payload(payload, "CMD_GET_ANGLES")
            elif cmd_id == CMD_GET_ANGLES_EXT:
                self._parse_get_angles_payload(payload, "CMD_GET_ANGLES_EXT")
        return self.get_imu_attitude()

    def get_imu_attitude(self):
        if not isinstance(self._last_imu, dict):
            return None
        return dict(self._last_imu)

    def get_battery_voltage_v(self):
        if self._last_battery_voltage_v is None:
            return None
        return float(self._last_battery_voltage_v)

    # === High-level helpers corresponding to specific CMD_ values ===

    def _set_adj_var_int(self, var_id: int, value_raw: int, *, debug_label: str = ""):
        # CMD_SET_ADJ_VARS_VAL (#31): NUM_PARAMS=1, PARAM_ID=<u8>, PARAM_VALUE=<int32 LE>
        payload = bytearray(struct.pack("<BBi", 1, int(var_id) & 0xFF, int(value_raw)))
        if debug_label:
            print(f"BGC set {debug_label} id={int(var_id)} value={int(value_raw)} payload:", hexdump(payload))
        self.send_cmd(CMD_SET_ADJ_VARS_VAL, payload)

    def set_gyro_heading_adjustment(self, value_raw: int = 0x00001500):
        self._set_adj_var_int(
            ADJ_VAR_ID_GYRO_HEADING_CORRECTION,
            int(value_raw),
            debug_label="gyro_heading_correction",
        )

    def set_gyro_heading_correction(self, value_raw: int):
        self.set_gyro_heading_adjustment(value_raw)

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
        # SimpleBGC CMD 45 Speed mode: int16 little-endian, center=0, range -500..+500
        payload = struct.pack("<3h", int(yaw), int(pitch), int(roll))
        self.send_cmd(CMD_API_VIRT_CH_CONTROL, payload)

    def motors_on(self):
        # CMD_MOTORS_ON (#77): no payload.
        self.send_cmd(CMD_MOTORS_ON, bytearray())

    def motors_off(self, mode: int = 0):
        # CMD_MOTORS_OFF (#109): optional 1-byte mode (0 normal, 1 brake, 2 safe stop).
        mode_i = int(mode)
        if mode_i < 0:
            mode_i = 0
        if mode_i > 2:
            mode_i = 2
        self.send_cmd(CMD_MOTORS_OFF, bytearray([mode_i]))

    def set_motors_enabled(self, enabled: bool):
        if bool(enabled):
            self.motors_on()
        else:
            self.motors_off(0)

    def set_wash_wipe_mode(self, mode_raw: int):
        """
        Requested mode:
          0 => parked
          1 => wiping

        NOTE: Servo PWM1 command mapping is platform-specific and must be
        finalized against the active BGC profile/adj-var IDs.
        """
        mode_i = 1 if int(mode_raw) != 0 else 0
        print("BGC wash_wipe mode requested:", mode_i, "(TODO: map to Servo PWM1 command path)")

    def set_axis_accel(self, axis: str, value_raw: int):
        axis_name = str(axis or "").strip().lower()
        axis_name = axis_name if axis_name in ("yaw", "pitch", "roll") else "yaw"
        v = int(value_raw)
        if v < 0:
            v = 0
        if v > 255:
            v = 255
        var_id_by_axis = {
            "roll": ADJ_VAR_ID_ACC_LIMITER_ROLL,
            "pitch": ADJ_VAR_ID_ACC_LIMITER_PITCH,
            "yaw": ADJ_VAR_ID_ACC_LIMITER_YAW,
        }
        var_id = int(var_id_by_axis[axis_name])
        self._set_adj_var_int(var_id, v, debug_label=f"{axis_name}_acc_limiter")

    def set_axis_gain(self, axis: str, value_raw: int):
        axis_name = str(axis or "").strip().lower()
        axis_name = axis_name if axis_name in ("yaw", "pitch", "roll") else "yaw"
        v = int(value_raw)
        if v < 0:
            v = 0
        if v > 255:
            v = 255
        var_id_by_axis = {
            "roll": ADJ_VAR_ID_PID_GAIN_ROLL,
            "pitch": ADJ_VAR_ID_PID_GAIN_PITCH,
            "yaw": ADJ_VAR_ID_PID_GAIN_YAW,
        }
        var_id = int(var_id_by_axis[axis_name])
        self._set_adj_var_int(var_id, v, debug_label=f"{axis_name}_pid_gain")


def _decode_lens_control(ctrl0: int, ctrl1: int):
    if ctrl1 != 0xA5:
        return None

    lens_bits = ctrl0 & 0x03
    zoom_bits = (ctrl0 >> 2) & 0x03
    focus_bits = (ctrl0 >> 4) & 0x03
    iris_bits = (ctrl0 >> 6) & 0x03

    def decode_src(bits: int):
        if bits == 1:
            return "camera"
        if bits == 2:
            return "off"
        return "pc"

    lens_type = "canon" if lens_bits == 1 else "fuji"
    return {
        "lens_type": lens_type,
        "axis_sources": {
            "zoom": decode_src(zoom_bits),
            "focus": decode_src(focus_bits),
            "iris": decode_src(iris_bits),
        },
    }
