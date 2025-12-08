try:
    import uasyncio as asyncio
except:
    import asyncio
import time

import json
try:
    import machine
    import ubinascii

    # Get the unique ID as bytes
    uid_bytes = machine.unique_id()

    # Convert to hex string
    uid_hex = ubinascii.hexlify(uid_bytes).decode()

    class MicroPythonWebSocket:
        def __init__(self, websocket):
            self.websocket = websocket

        async def recv(self):
            while True:
                msg = self.websocket.recv()
                if msg != "":
                    return msg
                else:
                    await asyncio.sleep(0)

        async def send(self, data):
            self.websocket.send(data)

    async def open_websocket(url):
        import uwebsockets.client
        ws = uwebsockets.client.connect(url)
        ws.sock.setblocking(False)
        return MicroPythonWebSocket(ws)

except:
    class CPythonWebSocket:
        def __init__(self, websocket):
            self.websocket = websocket

        async def recv(self):
            return await self.websocket.recv()

        async def send(self, data):
            await self.websocket.send(data)
    
    uid_hex = 'andy_is_unique'

    async def open_websocket(url):
        import websockets
        ws = await websockets.connect(url)
        return CPythonWebSocket(ws)

ota_present = False
try:
    import ota
    ota_present = True
except Exception as e:
    print("Couldn't import ota:", e)

def ota_trust():
    if ota_present:
        ota.trust()

# ==== CONFIGURATION ====
WS_URL = "ws://192.168.60.91:443/"
# ========================

ws = None

import builtins

# print function that also sends to websocket if available
# def ws_print(*args, **kwargs):
#     original_print(*args, **kwargs)

#     global ws
#     if ws and getattr(ws, 'open', True):
#         sep = kwargs.get("sep", " ")
#         end = kwargs.get("end", "\n")
#         message = sep.join(str(arg) for arg in args) + end

#         data = {"type": "PRINTF",
#                 "uid": uid_hex,
#                 "message": message.strip()}
#         ws.send(json.dumps(data))

# Override the built-in print function
# original_print = builtins.print
# builtins.print = ws_print

def get_manifest():
    with open('manifest.json') as f:
        manifest = json.load(f)
    return manifest

async def websocket_client():
    global ws
    try:
        print("Connecting to WebSocket server...")
        ws = await open_websocket(WS_URL)

        device_name = ota.registry_get('name', 'unknown')
        app_path = ota.registry_get('app_path', 'apps/base')
        network_configs = ota.registry_get('network_configs', [['dhcp', 'http://192.168.60.91:80']])
        manifest = get_manifest()

        data = {"type": "HEAD_CONNECTED",
                "uid": uid_hex,
                "name": device_name,
                "app_path": app_path,
                "network_configs": network_configs,
                "version": manifest["version"]}
        await ws.send(json.dumps(data))  # announce as device
        print("Connected!")

        ota_trust()

        while True:
            msg = await ws.recv()

            print("Received:", msg)
            try:
                my_dict = json.loads(msg)
                if my_dict["type"] == "REBOOT":
                    ota.reboot()
                elif my_dict["type"] == "SET_NAME":
                    new_name = my_dict.get("name")
                    if new_name:
                        ota.registry_set('name', new_name)
                elif my_dict["type"] == "SET_APP_PATH":
                    new_app_path = my_dict.get("app_path")
                    if new_app_path:
                        ota.registry_set('app_path', new_app_path)
                elif my_dict["type"] == "SET_NETWORK_CONFIGS":
                    new_network_configs = my_dict.get("network_configs")
                    if new_network_configs is not None:
                        ota.registry_set('network_configs', new_network_configs)
            except Exception as e:
                print("Error processing message:", e)

    except Exception as e:
        print("WebSocket error:", e)
    finally:
        if ws:
            ws.close()
            print("Connection closed")

async def websocket():
    while True:
        await websocket_client()
        print("Reconnecting in 1 seconds...")
        await asyncio.sleep(1)

async def as_main():
    tasks = [websocket()]

    # Run all tasks concurrently
    await asyncio.gather(*tasks)

def main():
    try:
        asyncio.run(as_main())
    finally:
        asyncio.new_event_loop()

if __name__ == "__main__":
    main()
