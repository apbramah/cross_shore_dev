import odrive
from odrive.utils import dump_errors, request_state
from odrive.enums import AxisState, ControlMode
import time

POS_TO_METRES = 29.26789093017578 / 2.726

odrv0 = odrive.find_sync()

odrv0.axis0.controller.config.control_mode = ControlMode.VELOCITY_CONTROL

request_state(odrv0.axis0, AxisState.CLOSED_LOOP_CONTROL)

odrv0.axis0.controller.input_vel = -3

print("Moving left...")
while odrv0.axis0.current_state != AxisState.IDLE:
  pass
print("Done")

print(odrv0.axis0.pos_estimate)

dump_errors(odrv0, clear = True)

odrv0.axis0.pos_estimate = 0

request_state(odrv0.axis0, AxisState.CLOSED_LOOP_CONTROL)

odrv0.axis0.controller.input_vel = 3

print("Moving right...")
while odrv0.axis0.current_state != AxisState.IDLE:
  pass
print("Done")

print(odrv0.axis0.pos_estimate)

dump_errors(odrv0, clear = True)

# 29.26789093017578 is the number we expect which is 2.726m

pos_m = odrv0.axis0.pos_estimate / POS_TO_METRES
pos_halfway = pos_m / 2

print("Length:", pos_m)
print("Halfway:", pos_halfway)

odrv0.axis0.controller.config.control_mode = ControlMode.POSITION_CONTROL
request_state(odrv0.axis0, AxisState.CLOSED_LOOP_CONTROL)

odrv0.axis0.controller.config.vel_limit = 3
odrv0.axis0.controller.input_pos = pos_halfway * POS_TO_METRES

print("Centering...")
while abs(odrv0.axis0.pos_estimate - pos_halfway * POS_TO_METRES) > 0.01 * POS_TO_METRES:
  pass
print("Done")

dump_errors(odrv0)

print("Yoyo mode")

odrv0.axis0.controller.config.control_mode = ControlMode.VELOCITY_CONTROL
while 1:
  odrv0.axis0.controller.input_vel = -1
  time.sleep(1)
  odrv0.axis0.controller.input_vel = 1
  time.sleep(1)

