import asyncio
from aiohttp import web, WSMsgType
import json
import os
import sys

heads = set()
browsers = set()
uid_to_head = dict()

# Base directory for serving files (cross_shore_dev)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def build_heads_list():
    """Build a list of all connected heads with uid and name"""
    heads_list = []
    for uid, head in uid_to_head.items():
        name = getattr(head, 'name', 'unknown')
        heads_list.append({"uid": uid, "name": name})
    return heads_list


async def send_heads_list_to_all():
    """Send the current heads list to all browsers and devices"""
    heads_list = build_heads_list()
    message = json.dumps({"type": "HEADS_LIST", "heads": heads_list})
    
    # Send to all heads (devices/controllers)
    for head in heads:
        await head.send_str(message)


async def websocket_handler(ws, ip_address, port):
    """Handle WebSocket connections"""
    # First message tells us who they are
    try:
        message = await ws.receive_str()
        msg = json.loads(message)
        if msg["type"] == "DEVICE_CONNECT":
            uid = msg.get("uid", "unknown")
            name = msg.get("name", "unknown")
            version = msg.get("version", "unknown")
            app_path = msg.get("app_path", "apps/base")
            device_type = msg.get("device_type", "unknown")
            network_configs = msg.get("network_configs", [])
            local_ips = msg.get("local_ips", [])
            print("Head connected", uid)
            head = ws

            heads.add(head)
            uid_to_head[uid] = head
            head.name = name
            head.version = version
            head.app_path = app_path
            head.network_configs = network_configs
            head.ip = ip_address
            head.local_ips = local_ips
            head.device_type = device_type

            ip = ip_address
            msg["ip"] = ip
            for browser in browsers:
                await browser.send_str(json.dumps(msg))
            
            # Send updated heads list to all clients
            await send_heads_list_to_all()
        elif msg["type"] == "BROWSER":
            print("Browser connected")
            browser = ws
            browsers.add(browser)

            for uid, head in uid_to_head.items():
                ip = getattr(head, 'ip', 'unknown')
                name = head.name
                version = head.version
                app_path = head.app_path
                network_configs = getattr(head, 'network_configs', [])
                local_ips = getattr(head, 'local_ips', [])
                device_type = getattr(head, 'device_type', "unknown")
                notify = json.dumps({"type": "DEVICE_CONNECT", "uid": uid, "ip": ip, "name": name, "version": version, "app_path": app_path, "network_configs": network_configs, "local_ips": local_ips, "device_type": device_type})
                await browser.send_str(notify)
                mode = getattr(head, 'mode', 'unknown')
                notify = json.dumps({"type": "CURRENT_MODE", "uid": uid, "mode": mode})
                await browser.send_str(notify)

        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                message = msg.data
                # Message came from a browser
                if ws in browsers:
                    msg_data = json.loads(message)
                    print("From browser:", message)
                    uid = msg_data.get("uid")
                    head = uid_to_head.get(uid)
                    if head:
                        await head.send_str(message)
                        if msg_data["type"] == "SET_NAME":
                            head.name = msg_data.get("name", "unknown")
                        elif msg_data["type"] == "SET_APP_PATH":
                            head.app_path = msg_data.get("app_path", "apps/base")
                        elif msg_data["type"] == "SET_NETWORK_CONFIGS":
                            head.network_configs = msg_data.get("network_configs", [])

                # Message came from a head
                elif ws in heads:
                    head = ws
                    print("From head:", message)
                    msg_data = json.loads(message)
                    to_uid = msg_data.get("to_uid")
                    if to_uid:
                        # Message is for a particular head
                        to_head = uid_to_head.get(to_uid)
                        if to_head:
                            await to_head.send_str(message)
                            print(f"Forward {message} to to_head {to_uid}")
                    else:
                        # Message is for browsers
                        if msg_data["type"] == "CURRENT_MODE":
                            head.mode = msg_data["mode"]
                        for browser in browsers:
                            await browser.send_str(message)
            elif msg.type == WSMsgType.ERROR:
                print('WebSocket connection closed with exception %s' % ws.exception())
                break

    except Exception as e:
        print("Connection error:", e)

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
                notify = json.dumps({"type": "DEVICE_DISCONNECT", "uid": dead_uid})
                for browser in browsers:
                    await browser.send_str(notify)
                
                # Send updated heads list to all clients
                await send_heads_list_to_all()
        elif ws in browsers:
            print("Browser disconnected")
            browsers.remove(ws)

async def http_handler(request):
    print('http_handler', request)

    """Handle HTTP requests - serve files from cross_shore_dev directory"""
    path = request.path.strip('/')

    # Build full file path
    file_path = os.path.join(BASE_DIR, path)
    
    # Security: ensure the file is within BASE_DIR
    file_path = os.path.normpath(file_path)
    if not file_path.startswith(BASE_DIR):
        return web.Response(status=403, text="Forbidden")
    
    # Check if file exists
    if os.path.isfile(file_path):
        # Determine content type
        content_type = 'text/plain'
        if file_path.endswith('.html'):
            content_type = 'text/html'
        elif file_path.endswith('.json'):
            content_type = 'application/json'
        elif file_path.endswith('.js'):
            content_type = 'application/javascript'
        elif file_path.endswith('.css'):
            content_type = 'text/css'
        elif file_path.endswith('.png'):
            content_type = 'image/png'
        elif file_path.endswith('.jpg') or file_path.endswith('.jpeg'):
            content_type = 'image/jpeg'
        
        with open(file_path, 'rb') as f:
            content = f.read()
        return web.Response(body=content, content_type=content_type)
    elif os.path.isdir(file_path):
        # Return directory listing or index
        index_file = os.path.join(file_path, 'index.html')
        if os.path.isfile(index_file):
            with open(index_file, 'rb') as f:
                content = f.read()
            return web.Response(body=content, content_type='text/html')
    
    return web.Response(status=404, text="Not Found")

async def websocket_upgrade_handler(request):
    """Handle WebSocket upgrade requests"""
    ws = web.WebSocketResponse(heartbeat=2)
    peer = request.transport.get_extra_info("peername")
    ip_address, port = peer[:2]
    await ws.prepare(request)
    await websocket_handler(ws, ip_address, port)
    return ws


async def init_app():
    app = web.Application()
    
    # Add route for WebSocket upgrades
    app.router.add_get('/', http_handler)
    app.router.add_get('/ws', websocket_upgrade_handler)
    app.router.add_get('/{path:.*}', http_handler)
    
    return app

async def main():
    host = sys.argv[1] if len(sys.argv) > 1 else '0.0.0.0'
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 80
    
    app = await init_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    
    print(f"Server running on http://{host}:{port}")
    print(f"Serving files from: {BASE_DIR}")
    print(f"WebSocket endpoint: ws://{host}:{port}/ws")
    
    await asyncio.Future()  # run forever

if __name__ == '__main__':
    asyncio.run(main())
