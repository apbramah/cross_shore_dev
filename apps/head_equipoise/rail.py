import odrive
from odrive.utils import dump_errors, request_state
from odrive.enums import AxisState, ControlMode
import time
import struct

POS_TO_METRES = 29.26789093017578 / 2.726

class Sled:
  def __init__(self):
    self.odrv0 = odrive.find_sync()
    self.ax = self.odrv0.axis0

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
      zoom, focus, iris, yaw, pitch, roll, _ = struct.unpack(">6h2s", data[2:16])
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

  def calibrate(self):
    self.ax.controller.config.control_mode = ControlMode.VELOCITY_CONTROL

    request_state(self.ax, AxisState.CLOSED_LOOP_CONTROL)

    self.ax.controller.input_vel = -3

    print("Moving left...")
    while self.ax.current_state != AxisState.IDLE:
      pass
    print("Done")

    print(self.ax.pos_estimate)

    dump_errors(self.odrv0, clear = True)

    self.ax.pos_estimate = 0

    request_state(self.ax, AxisState.CLOSED_LOOP_CONTROL)

    self.ax.controller.input_vel = 3

    print("Moving right...")
    while self.ax.current_state != AxisState.IDLE:
      pass
    print("Done")

    print(self.ax.pos_estimate)

    dump_errors(self.odrv0, clear = True)

    # 29.26789093017578 is the number we expect which is 2.726m

    pos_m = self.ax.pos_estimate / POS_TO_METRES
    pos_halfway = pos_m / 2

    print("Length:", pos_m)
    print("Halfway:", pos_halfway)

    self.ax.controller.config.control_mode = ControlMode.POSITION_CONTROL
    request_state(self.ax, AxisState.CLOSED_LOOP_CONTROL)

    self.ax.controller.config.vel_limit = 3
    self.ax.controller.input_pos = pos_halfway * POS_TO_METRES

    print("Centering...")
    while abs(self.ax.pos_estimate - pos_halfway * POS_TO_METRES) > 0.01 * POS_TO_METRES:
      pass
    print("Done")

    dump_errors(self.odrv0)

    self.ax.controller.config.control_mode = ControlMode.VELOCITY_CONTROL
    self.ax.controller.config.vel_limit = 20
    self.ax.controller.input_vel = 0

  def set_velocity(self, input_vel):
    self.ax.controller.input_vel = input_vel
    dump_errors(self.odrv0, clear = True)
    request_state(self.ax, AxisState.CLOSED_LOOP_CONTROL)
    self.ax.controller.config.control_mode = ControlMode.VELOCITY_CONTROL
    self.ax.controller.config.vel_limit = 20

if __name__ == "__main__":
  print("Calibrate...")

  sled = Sled()
  sled.calibrate()

  print("Yoyo...")

  while 1:
    sled.set_velocity(-1)
    time.sleep(1)
    sled.set_velocity(1)
    time.sleep(1)
