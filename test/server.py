import asyncio
from aiohttp import web, WSMsgType
import json
import os
import sys

devices = set()
browsers = set()
uid_to_device = dict()

# Base directory for serving files (cross_shore_dev)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def build_heads_list():
    """Build a list of all connected heads with uid and name"""
    heads_list = []
    for uid, device in uid_to_device.items():
        device_type = getattr(device, "device_type", "unknown")
        if device_type != "head":
            continue
        name = getattr(device, "name", "unknown")
        heads_list.append({"uid": uid, "name": name})
    return heads_list


async def send_heads_list_to_all():
    """Send the current heads list to all controllers"""
    heads_list = build_heads_list()
    message = json.dumps({"type": "HEADS_LIST", "heads": heads_list})
    
    # Send to all controller devices
    for device in devices:
        if getattr(device, "device_type", "unknown") == "controller":
            await device.send_str(message)


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
            print("Device connected", uid)
            device = ws

            devices.add(device)
            uid_to_device[uid] = device
            device.name = name
            device.version = version
            device.app_path = app_path
            device.network_configs = network_configs
            device.ip = ip_address
            device.local_ips = local_ips
            device.device_type = device_type

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

            for uid, device in uid_to_device.items():
                ip = getattr(device, 'ip', 'unknown')
                name = device.name
                version = device.version
                app_path = device.app_path
                network_configs = getattr(device, 'network_configs', [])
                local_ips = getattr(device, 'local_ips', [])
                device_type = getattr(device, 'device_type', "unknown")
                notify = json.dumps({"type": "DEVICE_CONNECT", "uid": uid, "ip": ip, "name": name, "version": version, "app_path": app_path, "network_configs": network_configs, "local_ips": local_ips, "device_type": device_type})
                await browser.send_str(notify)
                mode = getattr(device, 'mode', 'unknown')
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
                    device = uid_to_device.get(uid)
                    if device:
                        await device.send_str(message)
                        if msg_data["type"] == "SET_NAME":
                            device.name = msg_data.get("name", "unknown")
                        elif msg_data["type"] == "SET_APP_PATH":
                            device.app_path = msg_data.get("app_path", "apps/base")
                        elif msg_data["type"] == "SET_NETWORK_CONFIGS":
                            device.network_configs = msg_data.get("network_configs", [])

                # Message came from a device
                elif ws in devices:
                    device = ws
                    print("From device:", message)
                    msg_data = json.loads(message)
                    to_uid = msg_data.get("to_uid")
                    if to_uid:
                        # Message is for a particular device
                        to_device = uid_to_device.get(to_uid)
                        if to_device:
                            await to_device.send_str(message)
                            print(f"Forward {message} to to_device {to_uid}")
                    else:
                        # Message is for browsers
                        if msg_data["type"] == "CURRENT_MODE":
                            device.mode = msg_data["mode"]
                        for browser in browsers:
                            await browser.send_str(message)
            elif msg.type == WSMsgType.ERROR:
                print('WebSocket connection closed with exception %s' % ws.exception())
                break

    except Exception as e:
        print("Connection error:", e)

    finally:
        if ws in devices:
            print("Device disconnected")
            devices.remove(ws)

            # find UID that belonged to this ws
            dead_uid = None
            for uid, sock in uid_to_device.items():
                if sock == ws:
                    dead_uid = uid
                    break

            if dead_uid:
                del uid_to_device[dead_uid]
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
