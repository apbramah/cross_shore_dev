import asyncio
import websockets
import socket

# Helper: get LAN IP
def get_lan_ip():
    try:
        # connect to an external address (doesn't actually send data)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

device = None        # Pico W
controllers = set()  # Browsers

async def handler(ws):
    global device

    # First message tells us who they are
    try:
        hello = await ws.recv()
        if hello == "DEVICE":
            print("Pico W connected")
            device = ws
        else:
            print("Browser connected")
            controllers.add(ws)

        async for message in ws:
            # If message came from browser → send to device
            if ws in controllers and device:
                await device.send(message)

            # If message came from device → broadcast to all browsers
            elif ws == device:
                if 'get:' in message:
                    filename = message.split('get:')[1]
                    print("Server: Sending file to device:", filename)
                    f = open(filename, 'r')
                    data = f.read()
                    f.close()
                    await device.send(data)
                elif 'log:' in message:
                    log_msg = message.split('log:')[1]
                    print("Device:", log_msg)
                else:
                    for ctrl in controllers:
                        print("Server: Forwarding", message, "to browser")
                        await ctrl.send(message)

    except websockets.ConnectionClosed:
        print("Connection closed")

    finally:
        if ws == device:
            print("Device disconnected")
            device = None
        elif ws in controllers:
            print("Browser disconnected")
            controllers.remove(ws)

async def main():
    host_ip = get_lan_ip()
    async with websockets.serve(handler, "192.168.1.52", 80, compression=None):
        print(f"WebSocket server listening on ws://{host_ip}:80")
        await asyncio.Future()  # run forever

asyncio.run(main())
