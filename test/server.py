import asyncio
import websockets, json

heads = set()
controllers = set()
uid_to_head = dict()

async def handler(ws):
    # First message tells us who they are
    try:
        message = await ws.recv()
        msg = json.loads(message)
        if msg["type"] == "HEAD_CONNECTED":
            uid = msg.get("uid", "unknown")
            name = msg.get("name", "unknown")
            print("Head connected", uid)
            head = ws

            heads.add(head)
            uid_to_head[uid] = head
            head.name = name

            ip = head.remote_address[0]
            msg["ip"] = ip
            for ctrl in controllers:
                await ctrl.send(json.dumps(msg))
        elif msg["type"] == "BROWSER":
            print("Browser connected")
            controller = ws
            controllers.add(controller)

            for uid, head in uid_to_head.items():
                ip = head.remote_address[0]
                name = head.name
                notify = json.dumps({"type": "HEAD_CONNECTED", "uid": uid, "ip": ip, "name": name})
                await controller.send(notify)

        async for message in ws:
            # If message came from browser → send to device
            if ws in controllers:
                msg = json.loads(message)
                uid = msg["uid"]
                head = uid_to_head.get(uid)
                if head:
                    await head.send(message)
                    if msg["type"] == "SET_NAME":
                        head.name = msg.get("name", "unknown")

            # If message came from device → broadcast to all browsers
            elif ws in heads:
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
