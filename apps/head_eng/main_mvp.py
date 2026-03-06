# =====================================
# MVP Head Firmware (Ethernet + Control)
# =====================================

import network
import machine
import time
import socket

from bgc import BGC
from lens_controller import LensController, LENS_FUJI

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

nic = network.WIZNET5K(
    spi,
    machine.Pin(17),  # CS
    machine.Pin(20)   # RESET
)

nic.active(True)

nic.ifconfig((
    "192.168.60.120",
    "255.255.255.0",
    "192.168.60.1",
    "8.8.8.8"
))

while not nic.isconnected():
    time.sleep(0.2)

print("Ethernet ready:", nic.ifconfig())

# ---------- Hardware ----------
bgc = BGC()
lens = LensController(default_lens_type=LENS_FUJI)

print("BGC + ENG lens ready")

# ---------- UDP ----------
UDP_PORT = 8888
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("0.0.0.0", UDP_PORT))
sock.setblocking(False)

print("Listening UDP on", UDP_PORT)

# ---------- Main Loop ----------
while True:
    pulse_update()

    try:
        data, addr = sock.recvfrom(1024)
    except OSError:
        time.sleep(0.001)
        continue

    if not data:
        continue

    fields = BGC.decode_udp_packet(data)
    if not fields:
        continue

    # SimpleBGC CMD 45 Speed: u16 0 -> -500, 32768 -> 0, 65535 -> +500
    def u16_to_bgc_speed(u):
        u = max(0, min(65535, int(u)))
        s = round((u - 32768) / 32768.0 * 500.0)
        return max(-500, min(500, s))
    yaw_s = u16_to_bgc_speed(fields["yaw"])
    pitch_s = u16_to_bgc_speed(fields["pitch"])
    roll_s = u16_to_bgc_speed(fields["roll"])

    print("YPRZ:", fields["yaw"], fields["pitch"], fields["roll"], fields["zoom"])
    pulse(15)

    # Send to BGC (int16 LE, -500..+500)
    bgc.send_joystick_control(yaw_s, pitch_s, roll_s)

    # Send zoom/focus/iris to the active ENG lens protocol
    lens.move_zoom(fields["zoom"])
    lens.set_focus_input(fields["focus"])
    lens.set_iris_input(fields["iris"])
    lens.periodic()
