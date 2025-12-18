from udp_con import UDPConnection

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

        # def send_sync(self, data):
        #     self.websocket.send(data)

        async def close(self):
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

        async def close(self):
            await self.websocket.close()
    
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

# ==== CONFIGURATION ====
from machine import UART, Pin
import struct
import socket

TCP_PORT   = 8080
TCP_PORT2   = 8081
UART_ID    = 0           # 0 or 1
UART_ID1    = 1           # 0 or 1
UART_BAUD  = 115200
UART_BAUD1  = 9600
LISTEN_PORT_JOYSTICK = 8890
LISTEN_PORT_AUTOCAM = 8889
BUFFER_SIZE = 1024
WS_URL = "ws://192.168.60.91:443/"
# ========================

# Setup UART
uart = UART(UART_ID, UART_BAUD)
uart1 = UART(UART_ID1, UART_BAUD1)
led = Pin(25, Pin.OUT)

led.value(0)
mode = "joystick"  # "joystick" or "auto_cam"

def hexdump(data: bytes) -> str:
    """Return a hex dump string for given bytes."""
    return " ".join(f"{b:02X}" for b in data)

def decode_udp_packet(data: bytes):
    """Decode a 16-byte control packet into fields."""
    if len(data) != 16:
        print("Unexpected length:", len(data))
        return None

    if data[0] != 0xDE:
        print("Invalid header:", data[0])
        return None

    data_type = data[1]

    if data_type == 0xFD:
        zoom, focus, iris, yaw, pitch, roll, _ = struct.unpack("<6H2s", data[2:16])
        return {
            "zoom": zoom,
            "focus": focus,
            "iris": iris,
            "yaw": yaw,
            "pitch": pitch,
            "roll": roll,
        }
    elif data_type == 0xF3:
        pitch, roll, yaw, zoom, focus, iris, _ = struct.unpack("<6H2s", data[2:16])
        return {
            "zoom": zoom,
            "focus": focus,
            "iris": iris,
            "yaw": yaw,
            "pitch": pitch,
            "roll": roll,
        }

def crc16_calculate(data):
    polynomial = 0x8005
    crc_register = 0
    for byte in data:
        for shift_register in range(8):
            data_bit = (byte >> shift_register) & 1
            crc_bit = (crc_register >> 15) & 1
            crc_register = (crc_register << 1) & 0xFFFF
            if data_bit != crc_bit:
                crc_register ^= polynomial
    return crc_register

PACKET_START = 0x24

def create_packet(command_id, payload):
    payload_size = len(payload)
    header_checksum = (command_id + payload_size) % 256
    header = bytearray([command_id, payload_size, header_checksum])
    header_and_payload = header + payload
    crc = crc16_calculate(header_and_payload)
    crc_bytes = bytearray([crc & 0xFF, (crc >> 8) & 0xFF])
    return bytearray([PACKET_START]) + header_and_payload + crc_bytes

CMD_SET_ADJ_VARS_VAL = 31
CMD_API_VIRT_CH_CONTROL = 45
CMD_CONTROL_EXT = 121
CMD_CONTROL = 67

async def joystick():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)
    sock.bind(("0.0.0.0", LISTEN_PORT_JOYSTICK))
    print("Listening for joystick UDP packets on port", LISTEN_PORT_JOYSTICK)

    while True:
        try:
            data, addr = sock.recvfrom(BUFFER_SIZE)  # non-blocking
        except OSError:
            # No data available
            await asyncio.sleep(0)  # yield to scheduler
            continue

        if mode != "joystick":
            continue

        fields = decode_udp_packet(data)
        if fields:
            payload = struct.pack(">3H", fields["yaw"], fields["pitch"], fields["roll"])
            packet = create_packet(CMD_API_VIRT_CH_CONTROL, payload)
            print("UART joystick -->", hexdump(packet))
            uart.write(packet)

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

# import builtins

# if not MICROPYTHON:
#     print_queue = asyncio.Queue()

#     async def ws_sender(ws):
#         while True:
#             message = await print_queue.get()
#             data = {"type": "PRINTF",
#                     "uid": uid_hex,
#                     "message": message.strip()}
#             await ws.send(json.dumps(data))

# print function that also sends to websocket if available
# def ws_print(*args, **kwargs):
#     original_print(*args, **kwargs)

#     global ws
#     if ws and getattr(ws, 'open', True):
#         sep = kwargs.get("sep", " ")
#         end = kwargs.get("end", "\n")
#         message = sep.join(str(arg) for arg in args) + end

#         if MICROPYTHON:
#             data = {"type": "PRINTF",
#                     "uid": uid_hex,
#                     "message": message.strip()}
#             ws.send_sync(json.dumps(data))
#         else:            
#             print_queue.put_nowait(message)

# Override the built-in print function
# original_print = builtins.print
# builtins.print = ws_print

def get_manifest():
    with open('manifest.json') as f:
        manifest = json.load(f)
    return manifest

async def occasional_send(channel, my_string):
    while True:
        print('sending', my_string)
        await channel.send(my_string.encode('utf-8'))
        await asyncio.sleep(1)

async def onOpen(connection):
    print("Connection opened (onOpen callback)")
    
    # Access channels from connection
    reliable_channel = connection.reliable_channel
    
    # Start occasional_send task
    occasional_send_task = asyncio.create_task(occasional_send(reliable_channel, uid_hex + 'rel'))
    connection._occasional_send_task = occasional_send_task

async def onClose(connection):
    print("Connection closed (onClose callback)")
    # Kill occasional_send task
    if connection and hasattr(connection, '_occasional_send_task') and connection._occasional_send_task:
        connection._occasional_send_task.cancel()
        try:
            await connection._occasional_send_task
        except asyncio.CancelledError:
            pass

async def on_reliable_message(data):
    global mode, ws
    # Reliable channel payload is bytes; attempt to interpret as JSON messages.
    try:
        if isinstance(data, (bytes, bytearray)):
            text = data.decode("utf-8")
        else:
            text = str(data)
        msg = json.loads(text)
    except Exception:
        # Fallback: just print raw payload
        print(f"Reliable channel received: {data}")
        return

    if msg.get("type") != "SET_MODE":
        print(f"Reliable channel received (json): {msg}")
        return

    try:
        requested_mode = msg.get("mode")
        if requested_mode == "auto_cam":
            led.value(1)
            mode = "auto_cam"
        elif requested_mode == "joystick":
            led.value(0)
            mode = "joystick"

            payload = bytearray([0x01, 0x26, 0x00, 0x15, 0x00, 0x00])
            packet = create_packet(CMD_SET_ADJ_VARS_VAL, payload)
            uart.write(packet)

            # When switching to joystick mode, ensure that the angle mode is disabled
            payload = bytearray([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
            packet = create_packet(CMD_CONTROL, payload)
            uart.write(packet)
        elif requested_mode == "fixed":
            led.value(0)
            mode = "fixed"
        else:
            print(f"Unknown mode requested over reliable channel: {requested_mode}")
            return

        # Announce updated mode back over WebSocket (if connected)
        if ws:
            data = {"type": "CURRENT_MODE", "uid": uid_hex, "mode": mode}
            await ws.send(json.dumps(data))
        print(f"SET_MODE handled over reliable channel -> mode={mode}")
    except Exception as e:
        print(f"Error handling SET_MODE over reliable channel: {e}")

async def on_unreliable_message(data):
    print(f"Unreliable channel received: {data}")
                        
async def websocket_client(ws_connection, server_url=None):
    """Handle WebSocket client logic with an upgraded connection"""
    global mode, ws, current_server_url
    ws = ws_connection
    if server_url:
        current_server_url = server_url
    try:
        device_name = ota.registry_get('name', 'unknown')
        app_path = ota.registry_get('app_path', 'apps/base')
        network_configs = ota.registry_get('network_configs', [['dhcp', 'http://192.168.60.91:80']])
        local_ips = ota.get_local_ips()
        manifest = get_manifest()

        data = {"type": "DEVICE_CONNECT",
                "uid": uid_hex,
                "name": device_name,
                "app_path": app_path,
                "network_configs": network_configs,
                "version": manifest["version"],
                "local_ips": local_ips}
        await ws.send(json.dumps(data))  # announce as device
        # if not MICROPYTHON:
        #     asyncio.create_task(ws_sender(ws))
        print("Connected!")
        data = {"type": "CURRENT_MODE",
                "uid": uid_hex,
                "mode": mode}
        await ws.send(json.dumps(data))
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
                elif my_dict["type"] == "OFFER":
                    # to_head receives this - act as UDP client
                    from_uid = my_dict.get("from_uid")
                    candidates = my_dict.get("candidates", [])
                    print(f"OFFER received from {from_uid} with {len(candidates)} candidates")
                    
                    try:
                        # Gather candidates (creates socket, gathers host and srflx candidates)
                        sock, answer_candidates = await UDPConnection.gather_candidates(ota.get_local_ips())
                        
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
                        
                        connection = await UDPConnection.create(
                            sock, answer_candidates, candidates, from_uid, uid_hex, ws,
                            onOpen=onOpen,
                            onClose=onClose,
                            on_reliable_message=on_reliable_message,
                            on_unreliable_message=on_unreliable_message,
                        )
                        
                        # Clean up pending connection
                        del pending_udp_connections[from_uid]
                        
                    except Exception as e:
                        print(f"Error handling OFFER: {e}")
                                        
            except Exception as e:
                print("Error processing message:", e)

    except Exception as e:
        await ws.close()
        ws = None
        print("WebSocket error:", e)
        raise  # Re-raise to trigger reconnection
    finally:
        if ws:
            await ws.close()
            print("Connection closed")

async def websocket(server_url):
    """Upgrade the HTTP connection to WebSocket using the provided server_url"""
    print("Upgrading HTTP connection to WebSocket...")
    ws_connection = await upgrade_http_to_websocket(server_url)
    await websocket_client(ws_connection, server_url)

async def as_main(server_url):
    tasks = [joystick(), websocket(server_url)]

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
