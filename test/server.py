import asyncio
from aiohttp import web, WSMsgType
import json
import os
import sys
import socket
import struct

heads = set()
controllers = set()
uid_to_head = dict()

# Base directory for serving files (cross_shore_dev)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# UDP discovery state: maps (from_uid, to_uid) -> {from_head: (ip, port), to_head: (ip, port)}
pending_udp_discoveries = {}

# UDP discovery port (default 8888)
UDP_DISCOVERY_PORT = 8888

async def websocket_handler(ws, ip_address, port):
    """Handle WebSocket connections"""
    # First message tells us who they are
    try:
        message = await ws.receive_str()
        msg = json.loads(message)
        if msg["type"] == "HEAD_CONNECTED":
            uid = msg.get("uid", "unknown")
            name = msg.get("name", "unknown")
            version = msg.get("version", "unknown")
            app_path = msg.get("app_path", "apps/base")
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

            ip = ip_address
            msg["ip"] = ip
            for ctrl in controllers:
                await ctrl.send_str(json.dumps(msg))
        elif msg["type"] == "BROWSER":
            print("Browser connected")
            controller = ws
            controllers.add(controller)

            for uid, head in uid_to_head.items():
                ip = getattr(head, 'ip', 'unknown')
                name = head.name
                version = head.version
                app_path = head.app_path
                network_configs = getattr(head, 'network_configs', [])
                local_ips = getattr(head, 'local_ips', [])
                notify = json.dumps({"type": "HEAD_CONNECTED", "uid": uid, "ip": ip, "name": name, "version": version, "app_path": app_path, "network_configs": network_configs, "local_ips": local_ips})
                await controller.send_str(notify)
                mode = getattr(head, 'mode', 'unknown')
                notify = json.dumps({"type": "CURRENT_MODE", "uid": uid, "mode": mode})
                await controller.send_str(notify)

        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                message = msg.data
                # If message came from browser → send to device
                if ws in controllers:
                    msg_data = json.loads(message)
                    if msg_data["type"] == "INITIATE_UDP_CONNECTION":
                        # Handle UDP connection initiation with server-reflexive port discovery
                        from_uid = msg_data.get("from_uid")
                        to_uid = msg_data.get("to_uid")
                        from_head = uid_to_head.get(from_uid)
                        to_head = uid_to_head.get(to_uid)
                        
                        if from_head and to_head:
                            # Initiate STUN-like discovery to get server-reflexive addresses
                            discovery_key = (from_uid, to_uid)
                            pending_udp_discoveries[discovery_key] = {
                                'from_head': None,
                                'to_head': None,
                                'from_ws': from_head,
                                'to_ws': to_head
                            }
                            
                            # Request both heads to send UDP packets for discovery
                            from_discover_msg = {
                                "type": "UDP_DISCOVER_REQUEST",
                                "discovery_id": f"{from_uid}_{to_uid}",
                                "server_port": UDP_DISCOVERY_PORT
                            }
                            to_discover_msg = {
                                "type": "UDP_DISCOVER_REQUEST",
                                "discovery_id": f"{from_uid}_{to_uid}",
                                "server_port": UDP_DISCOVERY_PORT
                            }
                            
                            await from_head.send_str(json.dumps(from_discover_msg))
                            await to_head.send_str(json.dumps(to_discover_msg))
                            
                            print(f"Sent UDP discovery requests for {from_uid} <-> {to_uid}")
                        else:
                            error_msg = json.dumps({
                                "type": "UDP_CONNECTION_RESULT",
                                "uid": from_uid,
                                "success": False,
                                "message": "One or both heads not found"
                            })
                            await ws.send_str(error_msg)
                    else:
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

                # If message came from device → broadcast to all browsers
                elif ws in heads:
                    head = ws
                    msg_data = json.loads(message)
                    if msg_data["type"] == "CURRENT_MODE":
                        head.mode = msg_data["mode"]
                    elif msg_data["type"] == "UDP_CONNECTION_RESULT":
                        # Forward UDP connection results to browsers
                        for ctrl in controllers:
                            await ctrl.send_str(message)
                        print(f"UDP connection result from {msg_data.get('uid')}: {msg_data.get('success')}")
                    elif msg_data["type"] == "UDP_DISCOVER_RESPONSE":
                        # Handle discovery response - head confirms it sent UDP packet
                        # The actual discovery happens when we receive the UDP packet
                        discovery_id = msg_data.get("discovery_id")
                        print(f"Received UDP_DISCOVER_RESPONSE for {discovery_id}")
                    for ctrl in controllers:
                        print("Server: Forwarding", message, "to browser")
                        await ctrl.send_str(message)
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
                notify = json.dumps({"type": "HEAD_DISCONNECTED", "uid": dead_uid})
                for ctrl in controllers:
                    await ctrl.send_str(notify)
        elif ws in controllers:
            print("Browser disconnected")
            controllers.remove(ws)

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

async def udp_discovery_listener():
    """Listen for UDP discovery packets and record server-reflexive addresses"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('0.0.0.0', UDP_DISCOVERY_PORT))
    sock.setblocking(False)
    
    print(f"UDP discovery listener started on port {UDP_DISCOVERY_PORT}")
    
    loop = asyncio.get_event_loop()
    
    while True:
        try:
            # Use asyncio-friendly way to wait for UDP data
            data, addr = await loop.sock_recvfrom(sock, 1024)
            
            # Parse discovery packet: format is "DISCOVER:<discovery_id>:<uid>"
            try:
                packet_str = data.decode('utf-8')
                if packet_str.startswith("DISCOVER:"):
                    parts = packet_str.split(":", 2)
                    if len(parts) == 3:
                        discovery_id = parts[1]
                        uid = parts[2]
                        
                        # Find which discovery this belongs to
                        for (from_uid, to_uid), discovery in list(pending_udp_discoveries.items()):
                            if discovery_id == f"{from_uid}_{to_uid}":
                                # Record the server-reflexive address
                                server_reflexive_ip, server_reflexive_port = addr
                                
                                if uid == from_uid:
                                    discovery['from_head'] = (server_reflexive_ip, server_reflexive_port)
                                    print(f"Discovered server-reflexive address for {from_uid}: {server_reflexive_ip}:{server_reflexive_port}")
                                elif uid == to_uid:
                                    discovery['to_head'] = (server_reflexive_ip, server_reflexive_port)
                                    print(f"Discovered server-reflexive address for {to_uid}: {server_reflexive_ip}:{server_reflexive_port}")
                                
                                # Check if both addresses are discovered
                                if discovery['from_head'] and discovery['to_head']:
                                    # Send UDP_CONNECTION_REQUEST to both heads with discovered addresses
                                    from_reflexive = discovery['from_head']
                                    to_reflexive = discovery['to_head']
                                    
                                    from_msg = {
                                        "type": "UDP_CONNECTION_REQUEST",
                                        "peer_uid": to_uid,
                                        "peer_ip": to_reflexive[0],  # Server-reflexive IP
                                        "peer_port": to_reflexive[1]  # Server-reflexive port
                                    }
                                    to_msg = {
                                        "type": "UDP_CONNECTION_REQUEST",
                                        "peer_uid": from_uid,
                                        "peer_ip": from_reflexive[0],  # Server-reflexive IP
                                        "peer_port": from_reflexive[1]  # Server-reflexive port
                                    }
                                    
                                    await discovery['from_ws'].send_str(json.dumps(from_msg))
                                    await discovery['to_ws'].send_str(json.dumps(to_msg))
                                    
                                    print(f"Sending UDP_CONNECTION_REQUEST with server-reflexive addresses: {from_reflexive} <-> {to_reflexive}")
                                    
                                    # Clean up
                                    del pending_udp_discoveries[(from_uid, to_uid)]
                                break
            except Exception as e:
                print(f"Error parsing discovery packet: {e}")
                
        except BlockingIOError:
            # No data available, yield to event loop
            await asyncio.sleep(0.1)
        except Exception as e:
            print(f"Error in UDP discovery listener: {e}")
            await asyncio.sleep(0.1)

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
    
    # Start UDP discovery listener
    asyncio.create_task(udp_discovery_listener())
    
    print(f"Server running on http://{host}:{port}")
    print(f"Serving files from: {BASE_DIR}")
    print(f"WebSocket endpoint: ws://{host}:{port}/ws")
    print(f"UDP discovery endpoint: udp://{host}:{UDP_DISCOVERY_PORT}")
    
    await asyncio.Future()  # run forever

if __name__ == '__main__':
    asyncio.run(main())
