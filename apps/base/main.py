from udp_con import *

import json
try:
    MICROPYTHON = True
    import uasyncio as asyncio
    import machine
    import ubinascii
    from uwebsockets.protocol import ConnectionClosed

    # Get the unique ID as bytes
    uid_bytes = machine.unique_id()

    # Convert to hex string
    uid_hex = ubinascii.hexlify(uid_bytes).decode()
    
    class MicroPythonWebSocket:
        def __init__(self, websocket, heartbeat_interval=30.0, heartbeat_timeout=5.0):
            self.websocket = websocket
            self.heartbeat_interval = heartbeat_interval
            self.heartbeat_task = None
            self.running = True
            
            # Enable heartbeat tracking on underlying websocket
            self.websocket.heartbeat_enabled = True
            self.websocket.heartbeat_timeout = heartbeat_timeout

        async def _heartbeat_loop(self):
            """Periodically send PING messages"""
            while self.running:
                try:
                    await asyncio.sleep(self.heartbeat_interval)
                    if self.running and self.websocket.open:
                        try:
                            self.websocket.ping()
                        except Exception as e:
                            print(f"Error sending PING: {e}")
                            break
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    print(f"Error in heartbeat loop: {e}")
                    break

        def start_heartbeat(self):
            """Start the heartbeat task"""
            if self.heartbeat_task is None:
                self.heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        def stop_heartbeat(self):
            """Stop the heartbeat task"""
            self.running = False
            if self.heartbeat_task:
                self.heartbeat_task.cancel()
                try:
                    # Note: can't await in synchronous method, task will be cleaned up
                    pass
                except:
                    pass

        async def recv(self):
            while True:
                try:
                    msg = self.websocket.recv()
                    if msg != "":
                        return msg
                    else:
                        await asyncio.sleep(0)
                except ConnectionClosed as e:
                    # Re-raise ConnectionClosed exceptions (includes heartbeat timeout)
                    raise
                except Exception as e:
                    # Handle other exceptions
                    if "Heartbeat timeout" in str(e):
                        raise ConnectionClosed("Heartbeat timeout")
                    raise

        async def send(self, data):
            self.websocket.send(data)

        def send_sync(self, data):
            self.websocket.send(data)

        def close(self):
            self.stop_heartbeat()
            self.websocket.close()
        
    async def upgrade_http_to_websocket(http_url):
        """Upgrade an HTTP connection to WebSocket"""
        import uwebsockets.client
        ws_url = http_to_ws_url(http_url) + '/ws'
        ws = uwebsockets.client.connect(ws_url)
        ws.sock.setblocking(False)
        ws_wrapper = MicroPythonWebSocket(ws, heartbeat_interval=4.0, heartbeat_timeout=1.0)
        ws_wrapper.start_heartbeat()
        return ws_wrapper

except ImportError:
    MICROPYTHON = False
    import asyncio
    uid_hex = 'andyunique'

    class CPythonWebSocket:
        def __init__(self, websocket):
            self.websocket = websocket

        async def recv(self):
            return await self.websocket.recv()

        async def send(self, data):
            await self.websocket.send(data)
    
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
current_server_url = None  # Store server URL for UDP discovery
pending_udp_sockets = {}  # Store sockets between discovery and hole-punching: discovery_id -> socket

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

if not MICROPYTHON:
    print_queue = asyncio.Queue()

    async def ws_sender(ws):
        while True:
            message = await print_queue.get()
            data = {"type": "PRINTF",
                    "uid": uid_hex,
                    "message": message.strip()}
            await ws.send(json.dumps(data))

# print function that also sends to websocket if available
def ws_print(*args, **kwargs):
    original_print(*args, **kwargs)

    global ws
    if ws and getattr(ws, 'open', True):
        sep = kwargs.get("sep", " ")
        end = kwargs.get("end", "\n")
        message = sep.join(str(arg) for arg in args) + end

        if MICROPYTHON:
            data = {"type": "PRINTF",
                    "uid": uid_hex,
                    "message": message.strip()}
            ws.send_sync(json.dumps(data))
        else:            
            print_queue.put_nowait(message)

# Override the built-in print function
# original_print = builtins.print
# builtins.print = ws_print

def get_manifest():
    with open('manifest.json') as f:
        manifest = json.load(f)
    return manifest

async def websocket_client(ws_connection, server_url=None):
    """Handle WebSocket client logic with an upgraded connection"""
    global ws, current_server_url
    ws = ws_connection
    if server_url:
        current_server_url = server_url
    try:
        device_name = ota.registry_get('name', 'unknown')
        app_path = ota.registry_get('app_path', 'apps/base')
        network_configs = ota.registry_get('network_configs', [['dhcp', 'http://192.168.60.91:80']])
        local_ips = ota.get_local_ips()
        manifest = get_manifest()

        data = {"type": "HEAD_CONNECTED",
                "uid": uid_hex,
                "name": device_name,
                "app_path": app_path,
                "network_configs": network_configs,
                "version": manifest["version"],
                "local_ips": local_ips}
        await ws.send(json.dumps(data))  # announce as device
        if not MICROPYTHON:
            asyncio.create_task(ws_sender(ws))
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
                elif my_dict["type"] == "UDP_DISCOVER_REQUEST":
                    # Handle UDP discovery request - send UDP packet to server
                    discovery_id = my_dict.get("discovery_id")
                    server_port = int(my_dict.get("server_port", 8888))
                    
                    async def send_discovery_packet():
                        try:
                            # Get server IP from current_server_url
                            if current_server_url:
                                # Parse server URL (e.g., "http://192.168.60.91:80")
                                import re
                                match = re.match(r'https?://([^:/]+)', current_server_url)
                                if match:
                                    server_ip = match.group(1)
                                    
                                    # Create UDP socket (DO NOT CLOSE - will be reused for hole-punching)
                                    # Format: "DISCOVER:<discovery_id>:<uid>"
                                    discovery_data = f"DISCOVER:{discovery_id}:{uid_hex}".encode('utf-8')
                                    
                                    if MICROPYTHON:
                                        import usocket as socket
                                    else:
                                        import socket
                                    
                                    # Create and bind socket (same port that will be used for hole-punching)
                                    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                                    try:
                                        sock.bind(('0.0.0.0', 8888))  # Bind to same port as hole-punching
                                    except OSError:
                                        sock.bind(('0.0.0.0', 0))  # Use any available port if 8888 is taken
                                    
                                    # Send discovery packet
                                    sock.sendto(discovery_data, (server_ip, server_port))
                                    
                                    # Store socket for later use in hole-punching (keyed by discovery_id)
                                    pending_udp_sockets[discovery_id] = sock
                                    
                                    print(f"Sent UDP discovery packet to {server_ip}:{server_port} for {discovery_id}, socket stored")
                                    
                                    # Send confirmation back to server
                                    response = {
                                        "type": "UDP_DISCOVER_RESPONSE",
                                        "discovery_id": discovery_id
                                    }
                                    await ws.send(json.dumps(response))
                        except Exception as e:
                            print(f"Error sending UDP discovery packet: {e}")
                    
                    asyncio.create_task(send_discovery_packet())
                elif my_dict["type"] == "UDP_CONNECTION_REQUEST":
                    # Handle UDP connection request - perform hole-punching
                    peer_uid = my_dict.get("peer_uid")
                    peer_ip = my_dict.get("peer_ip")
                    peer_port = int(my_dict.get("peer_port", 8889))
                    
                    print(f"UDP connection request: connecting to {peer_uid} at {peer_ip}:{peer_port}")
                    
                    # Perform hole-punching in a task so it doesn't block
                    async def do_hole_punch():
                        # Find the socket that was created during discovery
                        # Parse discovery_id format: "from_uid_to_uid" - find which one matches this peer_uid
                        sock = None
                        discovery_id_to_remove = None
                        
                        for discovery_id, stored_sock in pending_udp_sockets.items():
                            # discovery_id format is "from_uid_to_uid"
                            parts = discovery_id.split('_', 1)
                            if len(parts) == 2:
                                from_uid = parts[0]
                                to_uid = parts[1]
                                # Check if peer_uid matches either side (and we're the other side)
                                if (from_uid == peer_uid and to_uid == uid_hex) or (to_uid == peer_uid and from_uid == uid_hex):
                                    sock = stored_sock
                                    discovery_id_to_remove = discovery_id
                                    break
                        
                        if discovery_id_to_remove:
                            del pending_udp_sockets[discovery_id_to_remove]
                            print(f"Retrieved stored socket for {peer_uid}")
                        
                        connection, success, message = await perform_udp_hole_punch(
                            peer_ip, peer_port, peer_uid, existing_socket=sock
                        )
                        
                        if success and connection:
                            # Example: Create a reliable and unreliable channel
                            reliable_channel = connection.create_channel('reliable')
                            await reliable_channel.start()
                            
                            unreliable_channel = connection.create_channel('unreliable')
                            
                            # Set up message handlers (optional)
                            async def on_reliable_message(data):
                                pass
                                # print(f"Reliable channel received: {data}")
                            async def on_unreliable_message(data):
                                pass
                                # print(f"Unreliable channel received: {data}")
                            
                            reliable_channel.on_message = on_reliable_message
                            unreliable_channel.on_message = on_unreliable_message
                            
                            print(f"Created UDP connection with channels for {peer_uid}")

                            async def occasional_send(channel, my_string):
                                while True:
                                    # print('sending', my_string)
                                    await channel.send(my_string.encode('utf-8'))
                                    await asyncio.sleep(1)

                            print("Starting occasional_send")
                            asyncio.create_task(occasional_send(unreliable_channel, uid_hex + 'unrel'))
                            asyncio.create_task(occasional_send(reliable_channel, uid_hex + 'rel'))
                        
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

    except ConnectionClosed as e:
        ws.close()
        ws = None
        print("WebSocket connection closed:", e)
        raise  # Re-raise to trigger reconnection
    except Exception as e:
        ws.close()
        ws = None
        print("WebSocket error:", e)
        raise  # Re-raise to trigger reconnection
    finally:
        if ws:
            ws.close()
            print("Connection closed")

async def websocket(server_url):
    """Upgrade the HTTP connection to WebSocket using the provided server_url"""
    print("Upgrading HTTP connection to WebSocket...")
    ws_connection = await upgrade_http_to_websocket(server_url)
    await websocket_client(ws_connection, server_url)

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
