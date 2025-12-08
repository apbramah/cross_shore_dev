try:
    import uasyncio as asyncio
except ImportError:
    import asyncio
import time

import json
try:
    import machine
    import ubinascii
    import usocket as socket
    
    # Get the unique ID as bytes
    uid_bytes = machine.unique_id()

    # Convert to hex string
    uid_hex = ubinascii.hexlify(uid_bytes).decode()
    
    MICROPYTHON = True

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
    
    async def upgrade_http_to_websocket(http_url):
        """Upgrade an HTTP connection to WebSocket"""
        import uwebsockets.client
        ws_url = http_to_ws_url(http_url) + '/ws'
        ws = uwebsockets.client.connect(ws_url)
        ws.sock.setblocking(False)
        return MicroPythonWebSocket(ws)

except ImportError:
    import socket
    MICROPYTHON = False
    
    class CPythonWebSocket:
        def __init__(self, websocket):
            self.websocket = websocket

        async def recv(self):
            return await self.websocket.recv()

        async def send(self, data):
            await self.websocket.send(data)
    
    uid_hex = 'andy_is_unique'

    async def upgrade_http_to_websocket(http_url):
        """Upgrade an HTTP connection to WebSocket"""
        import websockets
        ws_url = http_to_ws_url(http_url) + '/ws'
        ws = await websockets.connect(ws_url)
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

ws = None
udp_sockets = {}  # Track UDP sockets: peer_uid -> socket

def http_to_ws_url(http_url):
    """Convert HTTP URL to WebSocket URL for upgrading the connection"""
    if http_url.startswith('http://'):
        return http_url.replace('http://', 'ws://', 1)
    elif http_url.startswith('https://'):
        return http_url.replace('https://', 'wss://', 1)
    else:
        # If it's already a WebSocket URL, return as is
        return http_url

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

async def perform_udp_hole_punch(peer_ip, peer_port, local_port=8889):
    """
    Perform UDP hole-punching to establish a connection with a peer.
    Returns (success: bool, message: str)
    """
    try:
        # Create UDP socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        # Bind to a local port (or let OS assign one)
        sock.bind(('0.0.0.0', local_port))
        
        # Get the actual local port we're using
        # local_addr = sock.getsockname()
        # actual_local_port = local_addr[1] if isinstance(local_addr, tuple) else local_addr
        
        # Set socket to non-blocking
        # if MICROPYTHON:
        #     sock.setblocking(False)
        # else:
        sock.settimeout(0.1)
        
        print(f"Starting UDP hole-punching to {peer_ip}:{peer_port} from port {local_port}")
        
        # Send multiple packets to punch through NAT
        # Both peers should do this simultaneously
        andy_success = False
        for i in range(10):
            test_data = f"HOLE_PUNCH_{i}".encode('utf-8')
            sock.sendto(test_data, (peer_ip, peer_port))
            print(f"Sent hole-punch packet {i} to {peer_ip}:{peer_port}")
            
            # Small delay between packets
            await asyncio.sleep(0.1)
            
            # Try to receive a response (peer should be sending packets too)
            try:
                if MICROPYTHON:
                    # MicroPython non-blocking recv
                    data, addr = sock.recvfrom(1024)
                else:
                    data, addr = sock.recvfrom(1024)
                
                print(f"Received response from {addr}: {data.decode('utf-8')}")
                # Connection appears successful
                # sock.setblocking(True) if MICROPYTHON else sock.settimeout(None)
                andy_success = True
            except Exception as e:
                # No response yet, continue
                print('andy exception', e)
                pass
        
        # If we get here, we sent packets but didn't receive confirmation
        # Still return success since packets were sent (hole may be punched)
        # sock.setblocking(True) if MICROPYTHON else sock.settimeout(None)
        return (andy_success, f"Hole-punching packets sent to {peer_ip}:{peer_port}, awaiting confirmation")
        
    except Exception as e:
        error_msg = f"UDP hole-punching failed: {str(e)}"
        print(error_msg)
        try:
            sock.close()
        except:
            pass
        return (False, error_msg)

async def websocket_client(ws_connection):
    """Handle WebSocket client logic with an upgraded connection"""
    global ws
    ws = ws_connection
    try:
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
                elif my_dict["type"] == "UDP_CONNECTION_REQUEST":
                    # Handle UDP connection request - perform hole-punching
                    peer_uid = my_dict.get("peer_uid")
                    peer_ip = my_dict.get("peer_ip")
                    peer_port = int(my_dict.get("peer_port", 8889))
                    
                    print(f"UDP connection request: connecting to {peer_uid} at {peer_ip}:{peer_port}")
                    
                    # Perform hole-punching in a task so it doesn't block
                    async def do_hole_punch():
                        success, message = await perform_udp_hole_punch(peer_ip, peer_port)
                        
                        # Report result back to server
                        result_msg = {
                            "type": "UDP_CONNECTION_RESULT",
                            "uid": uid_hex,
                            "peer_uid": peer_uid,
                            "success": success,
                            "message": message
                        }
                        await ws.send(json.dumps(result_msg))
                        print(f"UDP connection result sent: {success} - {message}")
                    
                    # Start hole-punching task
                    asyncio.create_task(do_hole_punch())
                    
            except Exception as e:
                print("Error processing message:", e)

    except Exception as e:
        print("WebSocket error:", e)
    finally:
        if ws:
            ws.close()
            print("Connection closed")

async def websocket(server_url):
    """Upgrade the HTTP connection to WebSocket using the provided server_url"""
    while True:
        try:
            print("Upgrading HTTP connection to WebSocket...")
            ws_connection = await upgrade_http_to_websocket(server_url)
            
            await websocket_client(ws_connection)
        except Exception as e:
            print("WebSocket connection error:", e)
        print("Reconnecting in 1 seconds...")
        await asyncio.sleep(1)

async def as_main(server_url):
    tasks = [websocket(server_url)]

    # Run all tasks concurrently
    await asyncio.gather(*tasks)

def main(server_url):
    """Main entry point - receives server_url from ota_update.py"""
    try:
        asyncio.run(as_main(server_url))
    finally:
        asyncio.new_event_loop()

if __name__ == "__main__":
    main()
