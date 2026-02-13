# =====================================
# MVP Head Firmware (Ethernet + Control)
# =====================================

import network
import machine
import time
import socket

from bgc import BGC
from camera_sony import CameraSony

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
camera = CameraSony()

print("BGC + Sony ready")

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

    print("YPRZ:", fields["yaw"], fields["pitch"], fields["roll"], fields["zoom"])
    pulse(15)

    # Send directly to BGC
    bgc.send_joystick_control(
        fields["yaw"],
        fields["pitch"],
        fields["roll"]
    )

    # Send zoom to Sony
    camera.move_zoom(fields["zoom"])

