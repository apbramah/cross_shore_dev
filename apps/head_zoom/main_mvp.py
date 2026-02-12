import uasyncio as asyncio
import usocket as socket
from bgc import BGC
from camera_sony import CameraSony

PORT = 8888

bgc = BGC()
camera = CameraSony()

async def udp_loop():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("0.0.0.0", PORT))
    s.setblocking(False)
    print("Listening UDP on", PORT)

    while True:
        try:
            data, addr = s.recvfrom(256)
        except OSError:
            await asyncio.sleep(0)
            continue

        fields = BGC.decode_udp_packet(data)
        if fields:
            bgc.send_joystick_control(fields["yaw"], fields["pitch"], fields["roll"])
            camera.move_zoom(fields["zoom"])

asyncio.run(udp_loop())
