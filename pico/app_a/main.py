import uasyncio as asyncio
import time
import uwebsockets.client

ota_present = False
try:
    import ota
    ota_present = True
except Exception as e:
    print("Couldn't import ota:", e)

import json
import machine
import ubinascii
from uwebsockets.protocol import ConnectionClosed

REGISTRY_PATH = "/registry.json"

def get_device_name():
    try:
        with open(REGISTRY_PATH) as f:
            data = json.load(f)
        name = data.get("name")
        if name:
            return name
    except Exception as e:
        print("Error reading registry:", e)
    data = {"name": "unknown"}
    try:
        with open(REGISTRY_PATH, "w") as f:
            json.dump(data, f)
    except Exception as e:
        print("Error writing default registry:", e)
    return "unknown"

def set_device_name(name):
    try:
        data = {"name": name}
        with open(REGISTRY_PATH, "w") as f:
            json.dump(data, f)
    except Exception as e:
        print("Error updating registry:", e)

def ota_trust():
    if ota_present:
        ota.trust()

# ==== CONFIGURATION ====
WS_URL = "ws://192.168.60.91:443/"
# ========================

ws = None

import builtins

# Get the unique ID as bytes
uid_bytes = machine.unique_id()

# Convert to hex string
uid_hex = ubinascii.hexlify(uid_bytes).decode()

# print function that also sends to websocket if available
def ws_print(*args, **kwargs):
    original_print(*args, **kwargs)

    global ws
    if ws and ws.open:
        sep = kwargs.get("sep", " ")
        end = kwargs.get("end", "\n")
        message = sep.join(str(arg) for arg in args) + end

        data = {"type": "PRINTF",
                "uid": uid_hex,
                "message": message.strip()}
        ws.send(json.dumps(data))

# Override the built-in print function
original_print = builtins.print
builtins.print = ws_print

def get_manifest():
    with open('manifest.json') as f:
        manifest = json.load(f)
    return manifest

async def websocket_client():
    global ws
    try:
        print("Connecting to WebSocket server...")
        ws = uwebsockets.client.connect(WS_URL)
        ws.sock.setblocking(False)

        device_name = get_device_name()
        manifest = get_manifest()

        data = {"type": "HEAD_CONNECTED",
                "uid": uid_hex,
                "name": device_name,
                "version": manifest["version"]}
        ws.send(json.dumps(data))  # announce as device
        print("Connected!")

        while True:

            # Check for incoming messages
            try:
                msg = ws.recv()
            except ConnectionClosed:
                print("WebSocket ConnectionClosed")
                break

            # None means a close frame; empty string means "no data yet" on non-blocking socket
            if msg is None:
                print("WebSocket server closed")
                break
            if msg == "":
                await asyncio.sleep(0)
                continue

            print("Received:", msg)
            try:
                my_dict = json.loads(msg)
                if my_dict["type"] == "REBOOT":
                    print("Rebooting as requested...")
                    time.sleep(1)
                    ws.close()
                    machine.reset()
                elif my_dict["type"] == "SET_NAME":
                    new_name = my_dict.get("name")
                    if new_name:
                        set_device_name(new_name)
            except Exception as e:
                print("Error processing message:", e)

            ota_trust()
            await asyncio.sleep(0)

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
