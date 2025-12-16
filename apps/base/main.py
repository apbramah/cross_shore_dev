from udp_con import *
from stun_query import query_stun_server

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
pending_udp_connections = {}  # Store pending UDP connection info: peer_uid -> {socket, is_server, local_candidates}

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

async def evaluate_candidate_pairs(sock, local_candidates, remote_candidates, peer_uid, onOpen=None, onClose=None):
    """
    Evaluate candidate pairs using ICE-like connectivity checks.
    If successful, creates and returns a fully-formed UDPConnection with reliable and unreliable channels.
    Returns: UDPConnection instance or None on failure
    """
    try:
        # Create UDPConnection with candidates - evaluation and channel creation happen inside start()
        connection = UDPConnection(sock, local_candidates, remote_candidates, peer_uid, onOpen=onOpen, onClose=onClose)
        
        # Start the connection (performs evaluation and creates channels internally)
        await connection.start()
        
        print(f"Created UDP connection with channels for {peer_uid}")
        return connection
    except Exception as e:
        print(f"Failed to create UDP connection: {e}")
        return None

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
                elif my_dict["type"] == "INITIATE_UDP_CONNECTION":
                    # from_head receives this - act as UDP server
                    to_uid = my_dict.get("to_uid")
                    
                    async def handle_initiate():
                        try:
                            if MICROPYTHON:
                                import usocket as socket
                            else:
                                import socket
                            
                            # Create and bind UDP socket (from_head acts as server)
                            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                            sock.bind(('0.0.0.0', 8888))
                            
                            # Gather host candidates from local_ips
                            local_ips = ota.get_local_ips()
                            candidates = []
                            for ip in local_ips:
                                candidates.append({
                                    "type": "host",
                                    "address": ip,
                                    "port": 8888
                                })
                            
                            # Query STUN server for srflx candidates
                            srflx_candidates = await query_stun_server(sock, timeout=0.25)
                            candidates.extend(srflx_candidates)
                            
                            # Store socket and local candidates for later use when ANSWER arrives
                            pending_udp_connections[to_uid] = {
                                "socket": sock,
                                "is_server": True,
                                "local_candidates": candidates
                            }
                            
                            # Send OFFER message via WebSocket
                            offer_msg = {
                                "type": "OFFER",
                                "to_uid": to_uid,
                                "from_uid": uid_hex,
                                "candidates": candidates
                            }
                            await ws.send(json.dumps(offer_msg))
                            print(f"Sent OFFER to {to_uid} with {len(candidates)} candidates")
                            
                        except Exception as e:
                            print(f"Error handling INITIATE_UDP_CONNECTION: {e}")
                    
                    asyncio.create_task(handle_initiate())
                    
                elif my_dict["type"] == "OFFER":
                    # to_head receives this - act as UDP client
                    from_uid = my_dict.get("from_uid")
                    candidates = my_dict.get("candidates", [])
                    print(f"OFFER received from {from_uid} with {len(candidates)} candidates")
                    
                    async def handle_offer(from_uid, candidates):
                        try:
                            if MICROPYTHON:
                                import usocket as socket
                            else:
                                import socket
                            
                            # Create and bind UDP socket (to_head acts as client)
                            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                            sock.bind(('0.0.0.0', 8888))
                            
                            # Gather host candidates from local_ips
                            local_ips = ota.get_local_ips()
                            answer_candidates = []
                            for ip in local_ips:
                                answer_candidates.append({
                                    "type": "host",
                                    "address": ip,
                                    "port": 8888
                                })
                            
                            # Query STUN server for srflx candidates
                            srflx_candidates = await query_stun_server(sock, timeout=0.25)
                            answer_candidates.extend(srflx_candidates)
                            
                            # Store socket and candidates for candidate pair evaluation
                            pending_udp_connections[from_uid] = {
                                "socket": sock,
                                "is_server": False,
                                "local_candidates": answer_candidates,
                                "remote_candidates": candidates
                            }
                            
                            # Send ANSWER message via WebSocket
                            answer_msg = {
                                "type": "ANSWER",
                                "from_uid": uid_hex,
                                "to_uid": from_uid,
                                "candidates": answer_candidates
                            }
                            print(f"Answer message: {answer_msg}")
                            await ws.send(json.dumps(answer_msg))
                            print(f"Sent ANSWER to {from_uid} with {len(answer_candidates)} candidates")
                            
                            # Now evaluate candidate pairs (client side - connect to server)
                            if not candidates:
                                print("No peer candidates in OFFER")
                                return
                            
                            print(f"Client: Evaluating candidate pairs for connection to {from_uid}")
                            
                            # Store occasional_send task on connection
                            connection = None
                            occasional_send_task = None
                            
                            async def occasional_send(channel, my_string):
                                while True:
                                    print('sending', my_string)
                                    await channel.send(my_string.encode('utf-8'))
                                    await asyncio.sleep(1)
                            
                            async def onOpen():
                                nonlocal connection, occasional_send_task
                                print("Client: Connection opened (onOpen callback)")
                                # Store the connection
                                udp_connections[from_uid] = connection
                                
                                # Access channels from connection
                                reliable_channel = connection.reliable_channel
                                
                                # Start occasional_send task
                                print("Starting occasional_send (client)")
                                occasional_send_task = asyncio.create_task(occasional_send(reliable_channel, uid_hex + 'rel'))
                                connection._occasional_send_task = occasional_send_task
                                
                                # Report success
                                result_msg = {
                                    "type": "UDP_CONNECTION_RESULT",
                                    "uid": uid_hex,
                                    "peer_uid": from_uid,
                                    "success": True,
                                    "message": "UDP connection established"
                                }
                                await ws.send(json.dumps(result_msg))
                            
                            async def onClose():
                                nonlocal connection
                                print("Client: Connection closed (onClose callback)")
                                # Kill occasional_send task
                                if connection and hasattr(connection, '_occasional_send_task') and connection._occasional_send_task:
                                    connection._occasional_send_task.cancel()
                                    try:
                                        await connection._occasional_send_task
                                    except asyncio.CancelledError:
                                        pass
                                
                                # Report closed
                                result_msg = {
                                    "type": "UDP_CONNECTION_RESULT",
                                    "uid": uid_hex,
                                    "peer_uid": from_uid,
                                    "success": False,
                                    "message": "UDP connection closed"
                                }
                                await ws.send(json.dumps(result_msg))
                            
                            connection = await evaluate_candidate_pairs(
                                sock, answer_candidates, candidates, from_uid,
                                onOpen=onOpen, onClose=onClose
                            )
                            
                            if connection is None:
                                print("Client: Failed to establish connection via candidate pair evaluation")
                                del pending_udp_connections[from_uid]
                                result_msg = {
                                    "type": "UDP_CONNECTION_RESULT",
                                    "uid": uid_hex,
                                    "peer_uid": from_uid,
                                    "success": False,
                                    "message": "Candidate pair evaluation failed"
                                }
                                await ws.send(json.dumps(result_msg))
                                return

                            # Clean up pending connection
                            del pending_udp_connections[from_uid]
                            
                        except Exception as e:
                            print(f"Error handling OFFER: {e}")
                            # Report failure if we have from_uid
                            from_uid = my_dict.get("from_uid")
                            if from_uid:
                                result_msg = {
                                    "type": "UDP_CONNECTION_RESULT",
                                    "uid": uid_hex,
                                    "peer_uid": from_uid,
                                    "success": False,
                                    "message": str(e)
                                }
                                await ws.send(json.dumps(result_msg))
                    
                    asyncio.create_task(handle_offer(from_uid, candidates))
                    
                elif my_dict["type"] == "ANSWER":
                    # from_head receives this - establish connection (server side)
                    from_uid = my_dict.get("from_uid")  # This is the to_head's uid (the one who sent ANSWER)
                    candidates = my_dict.get("candidates", [])
                    print(f"ANSWER received from {from_uid} with {len(candidates)} candidates")
                    
                    async def handle_answer_server():
                        try:
                            # Retrieve the stored socket from INITIATE_UDP_CONNECTION (we're the server)
                            # The peer_uid we stored is the to_uid, which is from_uid in this message
                            if from_uid not in pending_udp_connections:
                                print(f"No pending connection found for {from_uid}")
                                return
                            
                            conn_info = pending_udp_connections[from_uid]
                            if not conn_info.get("is_server"):
                                print(f"Connection info for {from_uid} is not marked as server, skipping server handler")
                                return
                            
                            sock = conn_info["socket"]
                            local_candidates = conn_info.get("local_candidates", [])
                            
                            if not candidates:
                                print("No candidates in ANSWER message")
                                return
                            
                            if not local_candidates:
                                print("No local candidates stored")
                                return
                            
                            print(f"Server: Evaluating candidate pairs for connection to {from_uid}")
                            
                            # Store occasional_send task on connection
                            connection = None
                            occasional_send_task = None
                            
                            async def occasional_send(channel, my_string):
                                while True:
                                    print('sending', my_string)
                                    await channel.send(my_string.encode('utf-8'))
                                    await asyncio.sleep(1)
                            
                            async def onOpen():
                                nonlocal connection, occasional_send_task
                                print("Server: Connection opened (onOpen callback)")
                                # Store the connection
                                udp_connections[from_uid] = connection
                                
                                # Access channels from connection
                                reliable_channel = connection.reliable_channel
                                
                                # Start occasional_send task
                                print("Starting occasional_send (server)")
                                occasional_send_task = asyncio.create_task(occasional_send(reliable_channel, uid_hex + 'rel'))
                                connection._occasional_send_task = occasional_send_task
                                
                                # Report success
                                result_msg = {
                                    "type": "UDP_CONNECTION_RESULT",
                                    "uid": uid_hex,
                                    "peer_uid": from_uid,
                                    "success": True,
                                    "message": "UDP connection established"
                                }
                                await ws.send(json.dumps(result_msg))
                            
                            async def onClose():
                                nonlocal connection
                                print("Server: Connection closed (onClose callback)")
                                # Kill occasional_send task
                                if connection and hasattr(connection, '_occasional_send_task') and connection._occasional_send_task:
                                    connection._occasional_send_task.cancel()
                                    try:
                                        await connection._occasional_send_task
                                    except asyncio.CancelledError:
                                        pass
                                
                                # Report closed
                                result_msg = {
                                    "type": "UDP_CONNECTION_RESULT",
                                    "uid": uid_hex,
                                    "peer_uid": from_uid,
                                    "success": False,
                                    "message": "UDP connection closed"
                                }
                                await ws.send(json.dumps(result_msg))
                            
                            connection = await evaluate_candidate_pairs(
                                sock, local_candidates, candidates, from_uid,
                                onOpen=onOpen, onClose=onClose
                            )
                            
                            if connection is None:
                                print("Server: Failed to establish connection via candidate pair evaluation")
                                del pending_udp_connections[from_uid]
                                result_msg = {
                                    "type": "UDP_CONNECTION_RESULT",
                                    "uid": uid_hex,
                                    "peer_uid": from_uid,
                                    "success": False,
                                    "message": "Candidate pair evaluation failed"
                                }
                                await ws.send(json.dumps(result_msg))
                                return

                            # Clean up pending connection
                            del pending_udp_connections[from_uid]
                            
                        except Exception as e:
                            print(f"Error handling ANSWER (server side): {e}")
                            # Report failure
                            result_msg = {
                                "type": "UDP_CONNECTION_RESULT",
                                "uid": uid_hex,
                                "peer_uid": from_uid,
                                "success": False,
                                "message": str(e)
                            }
                            await ws.send(json.dumps(result_msg))
                    
                    asyncio.create_task(handle_answer_server())
                    
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
