# =====================================
# MVP Head Firmware (Ethernet + Control)
# =====================================

import network
import machine
import time
import socket

from bgc import BGC
from lens_controller import LensController, LENS_FUJI

# Local debug override when running MVP without websocket source controls.
# Set to one of: "pc", "camera", "off"
TEST_FUJI_SOURCE_MODE = "pc"

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
last_applied_lens_type = None
last_applied_sources = {"zoom": None, "focus": None, "iris": None}

print("BGC + ENG lens ready")
# Lens startup is timing-sensitive on real hardware; give it a short settle window.
for remaining in range(8, 0, -1):
    print("Waiting for lens settle...", remaining, "s")
    time.sleep(1)
bit_ok = lens.startup_diagnostics()
print("LENS startup diagnostics:", "PASS" if bit_ok else "FAIL")

def apply_fuji_source_override():
    mode = str(TEST_FUJI_SOURCE_MODE).lower().strip()
    if lens.get_lens_type() != LENS_FUJI:
        print("Fuji source override skipped (active lens is not Fuji)")
        return
    if mode not in ("pc", "camera", "off"):
        print("Fuji source override ignored (invalid mode):", mode)
        return
    for axis in ("zoom", "focus", "iris"):
        ok = lens.set_axis_source(axis, mode)
        print("Fuji source override", axis, "->", mode, "ok=" + str(ok))

apply_fuji_source_override()

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
        # Keep lens ownership/keepalive alive even without incoming UDP packets.
        lens.periodic()
        time.sleep(0.001)
        continue

    if not data:
        lens.periodic()
        continue

    fields = BGC.decode_udp_packet(data)
    if not fields:
        lens.periodic()
        continue

    print(
        "CTRL YPRZFI:",
        fields["yaw"],
        fields["pitch"],
        fields["roll"],
        fields["zoom"],
        fields["focus"],
        fields["iris"],
    )
    pulse(15)

    # Send directly to BGC
    bgc.send_joystick_control(
        fields["yaw"],
        fields["pitch"],
        fields["roll"]
    )

    # Gate runtime lens commands until startup BIT passes.
    lens_control = fields.get("lens_control")
    if lens_control:
        requested_type = lens_control.get("lens_type")
        if requested_type and requested_type != last_applied_lens_type:
            changed = lens.set_lens_type(requested_type)
            if changed:
                last_applied_lens_type = requested_type
                print("Applied lens_type from packet:", requested_type)

        requested_sources = lens_control.get("axis_sources", {}) or {}
        for axis in ("zoom", "focus", "iris"):
            req_src = requested_sources.get(axis)
            if req_src and req_src != last_applied_sources.get(axis):
                ok = lens.set_axis_source(axis, req_src)
                if ok:
                    last_applied_sources[axis] = req_src
                    print("Applied source from packet:", axis, "->", req_src)

    if bit_ok:
        lens.move_zoom(fields["zoom"])
        lens.set_focus_input(fields["focus"])
        lens.set_iris_input(fields["iris"])
    lens.periodic()
