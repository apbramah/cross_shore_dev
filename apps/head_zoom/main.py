from udp_con import UDPConnection

import json
import uasyncio as asyncio
import machine
import ubinascii
import binascii
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

ota_present = False
try:
    import ota
    ota_present = True
except Exception as e:
    print("Couldn't import ota:", e)

def ota_trust():
    if ota_present:
        ota.trust()

from machine import Pin
from bgc import BGC
from camera_sony import CameraSony

# BGC controller instance
bgc = BGC()
camera = CameraSony()

bgc_power_en = Pin(25, Pin.OUT)
bgc_power_en.value(1) # Force power enable through to BGC
camera_power_en = Pin(15, Pin.OUT)
camera_power_en.value(1) # Force power enable through to camera

mode = "joystick"  # "joystick" or "auto_cam"

ws = None
current_server_url = None  # Store server URL for UDP discovery
pending_udp_connections = {}  # Store pending UDP connection info: peer_uid -> {socket, is_server, local_candidates}
com_peer_uid = None  # controller uid to send COM_DATA back to (learned from inbound COM_DATA)

async def _bgc_com_tx_task():
    """Read raw bytes from BGC UART and send to controller via COM_DATA websocket messages."""
    global ws, com_peer_uid
    while True:
        try:
            data = bgc.read_raw()
            if data:
                peer = com_peer_uid
                if peer and ws:
                    msg = {
                        "type": "COM_DATA",
                        "target": "bgc",
                        "to_uid": peer,
                        "from_uid": uid_hex,
                        "data": binascii.b2a_base64(data).decode().strip(),
                    }
                    await ws.send(json.dumps(msg))
            await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            break
        except Exception as e:
            print("Error in _bgc_com_tx_task:", e)
            await asyncio.sleep(0.1)

async def _camera_com_tx_task():
    """Read raw bytes from camera UART and send to controller via COM_DATA websocket messages."""
    global ws, com_peer_uid
    while True:
        try:
            data = camera.read_raw()
            if data != None:
                peer = com_peer_uid
                if peer and ws:
                    msg = {
                        "type": "COM_DATA",
                        "target": "camera",
                        "to_uid": peer,
                        "from_uid": uid_hex,
                        "data": binascii.b2a_base64(data).decode().strip(),
                    }
                    await ws.send(json.dumps(msg))
            await asyncio.sleep(0.0)
        except asyncio.CancelledError:
            break
        except Exception as e:
            print("Error in _camera_com_tx_task:", e)
            await asyncio.sleep(0.1)

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
def ws_print(*args, **kwargs):
    original_print(*args, **kwargs)

    # Our overridden print cannot raise an exception, so we need to catch it here
    try:
        if ws and getattr(ws, 'open', True):
            sep = kwargs.get("sep", " ")
            end = kwargs.get("end", "\n")
            message = sep.join(str(arg) for arg in args) + end

            data = {"type": "PRINTF",
                    "uid": uid_hex,
                    "message": message.strip()}
            ws.send_sync(json.dumps(data))
    except Exception as e:
        original_print(f"Error sending PRINTF via websocket: {e}")

# Override the built-in print function
original_print = builtins.print
builtins.print = ws_print

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
            mode = "auto_cam"
        elif requested_mode == "joystick":
            mode = "joystick"

            bgc.set_gyro_heading_adjustment()
            bgc.disable_angle_mode()
        elif requested_mode == "fixed":
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
    fields = BGC.decode_udp_packet(data)
    if fields:
        bgc.send_joystick_control(fields["yaw"], fields["pitch"], fields["roll"])
        camera.move_zoom(fields["zoom"])
                        
async def websocket_client(ws_connection, server_url=None):
    """Handle WebSocket client logic with an upgraded connection"""
    global mode, ws, current_server_url, com_peer_uid
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
                "device_type": "head",
                "network_configs": network_configs,
                "version": manifest["version"],
                "local_ips": local_ips}
        await ws.send(json.dumps(data))  # announce as device
        print("Connected!")
        data = {"type": "CURRENT_MODE",
                "uid": uid_hex,
                "mode": mode}
        await ws.send(json.dumps(data))
        ota_trust()

        # Start BGC -> WS COM_DATA bridge (TX direction)
        bgc_tx_task = asyncio.create_task(_bgc_com_tx_task())
        camera_tx_task = asyncio.create_task(_camera_com_tx_task())

        while True:
            msg = await ws.recv()

            #print("Received:", msg)
            my_dict = json.loads(msg)
            if my_dict["type"] == "REBOOT":
                raise Exception("Reboot requested")
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
            elif my_dict["type"] == "IDENTIFY":
                bgc.beep()
            elif my_dict["type"] == "COM_DATA":
                # Raw bytes destined for BGC UART (from controller COM tunnel)
                try:
                    from_uid = my_dict.get("from_uid")
                    target = my_dict.get("target", "bgc")
                    data_b64 = my_dict.get("data", "")
                    if from_uid:
                        com_peer_uid = from_uid
                    if data_b64:
                        raw = binascii.a2b_base64(data_b64)
                        if target == "camera":
                            camera.write_raw(raw)
                        else:
                            bgc.write_raw(raw)
                except Exception as e:
                    print("Error handling COM_DATA:", e)
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
                                        
    finally:
        try:
            bgc_tx_task.cancel()
            await bgc_tx_task
        except Exception:
            pass
        try:
            camera_tx_task.cancel()
            await camera_tx_task
        except Exception:
            pass
        ws = None

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
