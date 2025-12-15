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
pending_udp_connections = {}  # Store pending UDP connection info: peer_uid -> {socket, is_server, local_candidates}

# Candidate pair evaluation constants
STUN_CHECK_MAGIC = b"STUN_CHECK"
STUN_RESPONSE_MAGIC = b"STUN_RESPONSE"

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

async def evaluate_candidate_pairs(sock, local_candidates, remote_candidates):
    """
    Evaluate candidate pairs using ICE-like connectivity checks.
    Returns: (successful_candidate_pair, peer_addr) or (None, None) on failure
    A candidate pair is (local_candidate, remote_candidate)
    """
    if MICROPYTHON:
        import usocket as socket_module
        import utime as time_module
    else:
        import socket as socket_module
        import time as time_module
    
    # All remote candidates we know about (including discovered prflx ones)
    all_remote_candidates = remote_candidates.copy()
    evaluated_pairs = set()  # Track pairs we've already evaluated
    successful_pair = None
    peer_addr = None
    
    # Remember original socket blocking state
    original_blocking = sock.getblocking() if hasattr(sock, 'getblocking') else True
    
    # Set socket to non-blocking for async receive
    try:
        sock.setblocking(False)
    except:
        pass  # Some socket implementations might not support setblocking
    
    max_evaluation_rounds = 10  # Prevent infinite loops
    round_num = 0
    
    while round_num < max_evaluation_rounds and not successful_pair:
        round_num += 1
        print(f"Candidate pair evaluation round {round_num}")
        
        # Form candidate pairs from local socket and all remote candidates
        # For now, we use the single socket for all local candidates
        new_pairs = []
        for local_cand in local_candidates:
            for remote_cand in all_remote_candidates:
                # Create a hashable representation of the pair
                pair_key = (local_cand["address"], local_cand["port"], 
                           remote_cand["address"], remote_cand["port"])
                if pair_key not in evaluated_pairs:
                    new_pairs.append((local_cand, remote_cand))
                    evaluated_pairs.add(pair_key)
        
        if not new_pairs:
            print("No new candidate pairs to evaluate")
            break
        
        # Evaluate pairs by sending connectivity checks
        checks_sent = {}
        for local_cand, remote_cand in new_pairs:
            remote_addr = (remote_cand["address"], remote_cand["port"])
            try:
                # Send connectivity check
                check_packet = STUN_CHECK_MAGIC + json.dumps({
                    "local": local_cand,
                    "remote": remote_cand
                }).encode('utf-8')
                sock.sendto(check_packet, remote_addr)
                checks_sent[remote_addr] = (local_cand, remote_cand)
                print(f"Sent connectivity check to {remote_addr}")
            except Exception as e:
                print(f"Error sending connectivity check to {remote_addr}: {e}")
        
        # Wait for responses
        timeout_duration = 0.5  # 500ms timeout per round
        check_interval = 0.05  # Check every 50ms
        start_time = time_module.time()
        
        while (time_module.time() - start_time) < timeout_duration and not successful_pair:
            try:
                if MICROPYTHON:
                    # MicroPython: use timeout-based approach (socket already non-blocking)
                    try:
                        data, addr = sock.recvfrom(2048)
                    except OSError:
                        # No data available, sleep and continue
                        await asyncio.sleep(check_interval)
                        continue
                else:
                    # CPython: use asyncio sock_recvfrom
                    loop = asyncio.get_event_loop()
                    remaining_time = timeout_duration - (time_module.time() - start_time)
                    if remaining_time <= 0:
                        break
                    try:
                        data, addr = await asyncio.wait_for(
                            loop.sock_recvfrom(sock, 2048),
                            timeout=min(check_interval, remaining_time)
                        )
                    except asyncio.TimeoutError:
                        continue
                
                # Check if this is a response to one of our connectivity checks
                if data.startswith(STUN_RESPONSE_MAGIC) or data.startswith(STUN_CHECK_MAGIC):
                    # This is a connectivity check response or check from peer
                    
                    # Check if response is from an expected address
                    expected_addr = None
                    expected_pair = None
                    for check_addr, (local_cand, remote_cand) in checks_sent.items():
                        if addr == check_addr:
                            expected_addr = check_addr
                            expected_pair = (local_cand, remote_cand)
                            break
                    
                    if expected_addr:
                        # Response from expected address - pair is successful!
                        print(f"Received response from expected address {addr}, pair successful!")
                        successful_pair = expected_pair
                        peer_addr = addr
                        break
                    else:
                        # Response from unexpected address - discover prflx candidate
                        print(f"Received response from unexpected address {addr}, creating prflx candidate")
                        prflx_candidate = {
                            "type": "prflx",
                            "address": addr[0],
                            "port": addr[1]
                        }
                        
                        # Check if we already know about this candidate
                        already_known = False
                        for known_cand in all_remote_candidates:
                            if (known_cand["address"] == prflx_candidate["address"] and
                                known_cand["port"] == prflx_candidate["port"]):
                                already_known = True
                                break
                        
                        if not already_known:
                            all_remote_candidates.append(prflx_candidate)
                            print(f"Added new prflx candidate: {prflx_candidate}")
                            # Will form new pairs in next round
                    
                    # If it's a check from peer, respond
                    if data.startswith(STUN_CHECK_MAGIC):
                        response_packet = STUN_RESPONSE_MAGIC + data[len(STUN_CHECK_MAGIC):]
                        try:
                            sock.sendto(response_packet, addr)
                            print(f"Sent connectivity check response to {addr}")
                        except Exception as e:
                            print(f"Error sending response to {addr}: {e}")
                
            except Exception as e:
                print(f"Error receiving during candidate evaluation: {e}")
                await asyncio.sleep(check_interval)
                continue
    
    # Restore original socket blocking state
    try:
        sock.setblocking(original_blocking)
    except:
        pass
    
    if successful_pair:
        print(f"Successful candidate pair found: {successful_pair[0]} <-> {successful_pair[1]}")
        print(f"Using peer address: {peer_addr}")
        return successful_pair, peer_addr
    else:
        print("No successful candidate pair found")
        return None, None

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
                    print(f"INITIATE_UDP_CONNECTION: acting as server for connection to {to_uid}")
                    
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
                    
                    async def handle_offer():
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
                            print(f"Local IPs: {local_ips}")
                            answer_candidates = []
                            for ip in local_ips:
                                answer_candidates.append({
                                    "type": "host",
                                    "address": ip,
                                    "port": 8888
                                })
                            
                            print(f"Candidates: {candidates}")
                            print(f"Answer candidates: {answer_candidates}")

                            global pending_udp_connections
                            # Store socket and candidates for candidate pair evaluation
                            pending_udp_connections[from_uid] = {
                                "socket": sock,
                                "is_server": False,
                                "local_candidates": answer_candidates,
                                "remote_candidates": candidates
                            }
                            
                            print(f"Pending UDP connections: {pending_udp_connections}")

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
                            successful_pair, peer_addr = await evaluate_candidate_pairs(
                                sock, answer_candidates, candidates
                            )
                            
                            if not successful_pair or not peer_addr:
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
                            
                            print(f"Client: Successful candidate pair found, establishing connection to {peer_addr}")
                            
                            # Create UDPConnection (client side) using successful pair
                            connection = UDPConnection(sock, peer_addr, from_uid)
                            udp_connections[from_uid] = connection
                            await connection.start()
                            
                            # Create channels
                            reliable_channel = connection.create_channel('reliable')
                            await reliable_channel.start()
                            
                            unreliable_channel = connection.create_channel('unreliable')
                            
                            # Set up message handlers
                            async def on_reliable_message(data):
                                print(f"Reliable channel received: {data}")
                            async def on_unreliable_message(data):
                                print(f"Unreliable channel received: {data}")
                            
                            reliable_channel.on_message = on_reliable_message
                            unreliable_channel.on_message = on_unreliable_message
                            
                            print(f"Created UDP connection with channels for {from_uid} (client side)")
                            
                            async def occasional_send(channel, my_string):
                                while True:
                                    print('sending', my_string)
                                    await channel.send(my_string.encode('utf-8'))
                                    await asyncio.sleep(1)
                            
                            print("Starting occasional_send (client)")
                            asyncio.create_task(occasional_send(unreliable_channel, uid_hex + 'unrel'))
                            asyncio.create_task(occasional_send(reliable_channel, uid_hex + 'rel'))
                            
                            # Clean up pending connection
                            del pending_udp_connections[from_uid]
                            
                            # Report success
                            result_msg = {
                                "type": "UDP_CONNECTION_RESULT",
                                "uid": uid_hex,
                                "peer_uid": from_uid,
                                "success": True,
                                "message": "UDP connection established"
                            }
                            await ws.send(json.dumps(result_msg))
                            
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
                    
                    asyncio.create_task(handle_offer())
                    
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
                            successful_pair, peer_addr = await evaluate_candidate_pairs(
                                sock, local_candidates, candidates
                            )
                            
                            if not successful_pair or not peer_addr:
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
                            
                            print(f"Server: Successful candidate pair found, establishing connection to {peer_addr}")
                            
                            # Create UDPConnection (server side) using successful pair
                            connection = UDPConnection(sock, peer_addr, from_uid)
                            udp_connections[from_uid] = connection
                            await connection.start()
                            
                            # Create channels
                            reliable_channel = connection.create_channel('reliable')
                            await reliable_channel.start()
                            
                            unreliable_channel = connection.create_channel('unreliable')
                            
                            # Set up message handlers
                            async def on_reliable_message(data):
                                print(f"Reliable channel received: {data}")
                            async def on_unreliable_message(data):
                                print(f"Unreliable channel received: {data}")
                            
                            reliable_channel.on_message = on_reliable_message
                            unreliable_channel.on_message = on_unreliable_message
                            
                            print(f"Created UDP connection with channels for {from_uid} (server side)")
                            
                            async def occasional_send(channel, my_string):
                                while True:
                                    print('sending', my_string)
                                    await channel.send(my_string.encode('utf-8'))
                                    await asyncio.sleep(1)
                            
                            print("Starting occasional_send (server)")
                            asyncio.create_task(occasional_send(unreliable_channel, uid_hex + 'unrel'))
                            asyncio.create_task(occasional_send(reliable_channel, uid_hex + 'rel'))
                            
                            # Clean up pending connection
                            del pending_udp_connections[from_uid]
                            
                            # Report success
                            result_msg = {
                                "type": "UDP_CONNECTION_RESULT",
                                "uid": uid_hex,
                                "peer_uid": from_uid,
                                "success": True,
                                "message": "UDP connection established"
                            }
                            await ws.send(json.dumps(result_msg))
                            
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
