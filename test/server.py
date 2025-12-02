import asyncio
import websockets, json

heads = set()
controllers = set()
uid_to_head = dict()
uid_to_name = dict()

async def handler(ws):
    # First message tells us who they are
    try:
        hello = await ws.recv()
        hello = json.loads(hello)
        if hello["type"] == "DEVICE":
            uid = hello.get("uid", "unknown")
            name = hello.get("name", "unknown")
            print("Head connected", uid)
            head = ws

            heads.add(head)
            uid_to_head[uid] = head
            uid_to_name[uid] = name

            ip = head.remote_address[0]
            notify = json.dumps({"type": "HEAD_CONNECTED", "uid": uid, "ip": ip, "name": name})
            for ctrl in controllers:
                await ctrl.send(notify)
        else:
            print("Browser connected")
            controller = ws
            controllers.add(controller)

            for uid, head in uid_to_head.items():
                ip = head.remote_address[0]
                name = uid_to_name.get(uid, "unknown")
                notify = json.dumps({"type": "HEAD_CONNECTED", "uid": uid, "ip": ip, "name": name})
                await controller.send(notify)

        async for message in ws:
            # If message came from browser → send to device
            if ws in controllers:
                msg = json.loads(message)
                if msg["type"] == "SET_MODE":
                    uid = msg["uid"]
                    head = uid_to_head.get(uid)
                    if head:
                        await head.send(message)
                elif msg["type"] == "REBOOT":
                    uid = msg["uid"]
                    head = uid_to_head.get(uid)
                    if head:
                        await head.send(message)
                elif msg["type"] == "SET_NAME":
                    uid = msg["uid"]
                    name = msg.get("name", "unknown")
                    head = uid_to_head.get(uid)
                    if head:
                        await head.send(json.dumps({"type": "SET_NAME", "name": name}))
                    uid_to_name[uid] = name

            # If message came from device → broadcast to all browsers
            elif ws in heads:
                if 'get:' in message:
                    filename = message.split('get:')[1]
                    print("Server: Sending file to device:", filename)
                    f = open(filename, 'r')
                    data = f.read()
                    f.close()
                    await ws.send(data)
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
        if ws in heads:
            print("Head disconnected")
            heads.remove(ws)

            # find UID that belonged to this ws
            dead_uid = None
            for uid, sock in uid_to_head.items():
                if sock == ws:
                    dead_uid = uid
                    break

            if dead_uid:
                del uid_to_head[dead_uid]
                if dead_uid in uid_to_name:
                    del uid_to_name[dead_uid]
                notify = json.dumps({"type": "HEAD_DISCONNECTED", "uid": dead_uid})
                for ctrl in controllers:
                    await ctrl.send(notify)
        elif ws in controllers:
            print("Browser disconnected")
            controllers.remove(ws)

import sys

async def main():
    async with websockets.serve(handler, sys.argv[1], 443, compression=None):
        await asyncio.Future()  # run forever

asyncio.run(main())
