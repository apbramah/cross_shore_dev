from udp_con import UDPConnection

import json
import threading
import time
import queue

import asyncio
import uuid
import secrets
import os
import base64

try:
    import serial
    import serial.tools.list_ports
    serial_available = True
except ImportError:
    serial_available = False
    print("pyserial not available - COM port forwarding disabled")

# Generate a unique ID based on MAC address + random string (unique per instance)
uid_hex = format(uuid.getnode(), 'x') + secrets.token_hex(8)

import tkinter as tk
from tkinter import ttk

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


map_zoom = lambda value: (value + 0)
map_iris = lambda value: (value + 512) >> 4
map_focus = lambda value: (value + 512) >> 4
map_pitch = lambda value: int(value * 0.2)

async def send_udp_message(values, channel):
    # Pack values into a UDP message
    values = values.copy()  # Don't modify the original
    values[1] = map_pitch(values[1])
    values[3] = map_zoom(values[3])
    values[4] = map_focus(values[4])
    values[5] = map_iris(values[5])
    # Pack values into bytes
    message_bytes = bytes([0xDE, 0xFD, (values[3] >> 8) & 0xFF, values[3] & 0xFF,
                           (values[4] >> 8) & 0xFF, values[4] & 0xFF,
                           (values[5] >> 8) & 0xFF, values[5] & 0xFF,
                           (values[0] >> 8) & 0xFF, values[0] & 0xFF,
                           (values[1] >> 8) & 0xFF, values[1] & 0xFF,
                           (values[2] >> 8) & 0xFF, values[2] & 0xFF,
                           0x00, 0x00])
    if channel:
        await channel.send(message_bytes)

joystick = None

def run_gui():
    """Run the tkinter GUI in a separate thread"""
    global heads_dropdown
    root = tk.Tk()
    root.title("EX Head Controller Relative")
    
    # Handle window close (X button) - exit immediately
    def on_closing():
        os._exit(0)
    
    root.protocol("WM_DELETE_WINDOW", on_closing)
    
    # Heads selection dropdown
    heads_frame = ttk.Frame(root)
    heads_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=10)
    
    ttk.Label(heads_frame, text="Select Head:").pack(side=tk.LEFT, padx=5)
    heads_dropdown = ttk.Combobox(heads_frame, state="readonly", width=30)
    heads_dropdown.pack(side=tk.LEFT, padx=5)
    heads_dropdown.set("No heads available")

    def _extract_uid_from_dropdown_value(value: str):
        """
        Dropdown display values look like: "name (uid)".
        Returns uid string or None if it can't be parsed.
        """
        if not value:
            return None
        l = value.rfind("(")
        r = value.rfind(")")
        if l == -1 or r == -1 or r <= l + 1:
            return None
        uid = value[l + 1:r].strip()
        return uid or None

    def on_connect_pressed():
        # GUI thread only: enqueue an event for asyncio thread to handle.
        selected = heads_dropdown.get()
        to_uid = _extract_uid_from_dropdown_value(selected)
        if not to_uid:
            print(f"Connect pressed but no valid head selected: {selected!r}")
            return
        gui_to_async_queue.put({"type": "CONNECT", "to_uid": to_uid})

    connect_button = ttk.Button(heads_frame, text="Connect", command=on_connect_pressed)
    connect_button.pack(side=tk.LEFT, padx=5)

    def on_disconnect_pressed():
        # GUI thread only: enqueue an event for asyncio thread to handle.
        gui_to_async_queue.put({"type": "DISCONNECT"})

    disconnect_button = ttk.Button(heads_frame, text="Disconnect", command=on_disconnect_pressed)
    disconnect_button.pack(side=tk.LEFT, padx=5)

    def update_selected_head_uid():
        """Update the selected head UID when dropdown changes"""
        selected = heads_dropdown.get()
        uid = _extract_uid_from_dropdown_value(selected)
        global selected_head_uid
        with selected_head_uid_lock:
            selected_head_uid = uid

    def update_dropdown(heads):
        heads = heads or []
        # Build display strings: "name (uid)"
        display_values = [
            f"{head.get('name', 'unknown')} ({head.get('uid', '')})"
            for head in heads
            if isinstance(head, dict)
        ]
        if display_values:
            heads_dropdown["values"] = display_values
            current = heads_dropdown.get()
            if current not in display_values:
                heads_dropdown.set(display_values[0])
            update_selected_head_uid()
        else:
            heads_dropdown["values"] = []
            heads_dropdown.set("No heads available")
            with selected_head_uid_lock:
                global selected_head_uid
                selected_head_uid = None
    
    # Bind dropdown selection change event
    heads_dropdown.bind("<<ComboboxSelected>>", lambda e: update_selected_head_uid())

    # Mode buttons panel (only visible when a UDP connection is active)
    mode_frame = ttk.Frame(root)
    connected = False
    current_mode = None
    previous_mode = None  # Track mode before switching to joystick

    def on_mode_pressed(mode: str):
        # GUI thread only: enqueue an event for asyncio thread to handle.
        nonlocal current_mode, previous_mode
        # If switching away from joystick, save joystick as previous (for toggle back)
        # If switching to joystick, save current mode as previous
        if current_mode == "joystick" and mode != "joystick":
            # Switching away from joystick - don't update previous_mode
            pass
        elif mode == "joystick" and current_mode != "joystick":
            # Switching to joystick - save current mode as previous
            previous_mode = current_mode
        current_mode = mode
        gui_to_async_queue.put({"type": "SET_MODE", "mode": mode})

    auto_cam_button = ttk.Button(mode_frame, text="Auto-cam", command=lambda: on_mode_pressed("auto_cam"))
    joystick_button = ttk.Button(mode_frame, text="Joystick", command=lambda: on_mode_pressed("joystick"))
    fixed_button = ttk.Button(mode_frame, text="Fixed", command=lambda: on_mode_pressed("fixed"))

    auto_cam_button.pack(side=tk.LEFT, padx=5, pady=5)
    joystick_button.pack(side=tk.LEFT, padx=5, pady=5)
    fixed_button.pack(side=tk.LEFT, padx=5, pady=5)

    mode_panel_visible = False

    def set_mode_panel_visible(visible: bool):
        nonlocal mode_panel_visible
        if visible and not mode_panel_visible:
            mode_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=5)
            mode_panel_visible = True
        elif not visible and mode_panel_visible:
            mode_frame.pack_forget()
            mode_panel_visible = False

    def process_async_to_gui_events():
        # GUI thread: apply state changes driven by asyncio thread events.
        try:
            while True:
                event = async_to_gui_queue.get_nowait()
                if isinstance(event, dict) and event.get("type") == "UDP_CONNECTION_STATE":
                    nonlocal connected, current_mode
                    connected = bool(event.get("connected"))
                    set_mode_panel_visible(connected)
                    if not connected:
                        current_mode = None
                elif isinstance(event, dict) and event.get("type") == "HEADS_LIST":
                    update_dropdown(event.get("heads", []))
        except queue.Empty:
            pass
        root.after(100, process_async_to_gui_events)

    # Start processing asyncio->GUI events
    root.after(100, process_async_to_gui_events)
       
    joysticks = []
    try:
        import pygame
        pygame.init()
        pygame.joystick.init()
        for i in range(pygame.joystick.get_count()):
            js = pygame.joystick.Joystick(i)
            js.init()
            print(f"Joystick {i} name: {js.get_name()} axes: {js.get_numaxes()} hats: {js.get_numhats()} buttons: {js.get_numbuttons()}")
            joysticks.append(js)
    except Exception as e:
        print("Joystick init failed:", e)

    # Track previous button states for edge detection
    prev_buttons = None
    prev_hats = None
    
    def change_dropdown_selection(direction):
        """Change dropdown selection up (-1) or down (+1)"""
        values = heads_dropdown["values"]
        if not values or len(values) == 0:
            return
        
        current = heads_dropdown.get()
        try:
            current_index = values.index(current)
        except ValueError:
            # Current value not in list, default to first item
            current_index = 0
        
        new_index = current_index + direction
        # Wrap around: if going up from first, go to last; if going down from last, go to first
        if new_index < 0:
            new_index = len(values) - 1
        elif new_index >= len(values):
            new_index = 0
        
        heads_dropdown.set(values[new_index])
        print(f"Changed head selection to: {values[new_index]}")
    
    def poll_joystick():
        pygame.event.pump()
        global joystick, prev_buttons, prev_hats
        if not joystick:
            for j in joysticks:
                buttons = [j.get_button(i) for i in range(j.get_numbuttons())]

                lb_button = buttons[4]
                rb_button = buttons[5]

                if lb_button and rb_button:
                    joystick = j
                    print(f"Selected joystick name: {joystick.get_name()}")
                    prev_buttons = None  # Reset previous button states when joystick is selected
                    prev_hats = None  # Reset previous hat states when joystick is selected
                    break

        else:
            axes = [joystick.get_axis(i) for i in range(joystick.get_numaxes())]
            buttons = [joystick.get_button(i) for i in range(joystick.get_numbuttons())]
            hats = [joystick.get_hat(i) for i in range(joystick.get_numhats())]
            # print("Axes:", ["{:+.2f}".format(a) for a in axes],
            #       "Buttons:", buttons,
            #       "Hats:", hats)

            # Check for button presses (edge detection)
            if prev_buttons is not None and len(buttons) > 0:
                a_button = buttons[0] if len(buttons) > 0 else False
                b_button = buttons[1] if len(buttons) > 1 else False
                joystick_button = buttons[8] if len(buttons) > 9 else False
                prev_a_button = prev_buttons[0] if len(prev_buttons) > 0 else False
                prev_b_button = prev_buttons[1] if len(prev_buttons) > 1 else False
                prev_joystick_button = prev_buttons[8] if len(prev_buttons) > 9 else False
                
                # B button pressed (Connect) - transition from not pressed to pressed
                if b_button and not prev_b_button:
                    print("B button pressed - triggering Connect")
                    on_connect_pressed()
                
                # A button pressed (Disconnect) - transition from not pressed to pressed
                if a_button and not prev_a_button:
                    print("A button pressed - triggering Disconnect")
                    on_disconnect_pressed()
                
                # Joystick button pressed (toggle Joystick mode)
                if joystick_button and not prev_joystick_button:
                    print("Joystick button pressed - toggling mode")
                    nonlocal current_mode, previous_mode
                    if current_mode == "joystick":
                        # Currently in joystick mode, switch back to previous mode
                        if previous_mode:
                            print(f"Switching back to previous mode: {previous_mode}")
                            on_mode_pressed(previous_mode)
                        else:
                            # No previous mode, default to auto_cam
                            print("No previous mode, defaulting to auto_cam")
                            on_mode_pressed("auto_cam")
                    else:
                        # Not in joystick mode, switch to joystick
                        print("Switching to joystick mode")
                        on_mode_pressed("joystick")
            
            # Check for hat up/down presses (edge detection)
            if prev_hats is not None and len(hats) > 0:
                # Hat values are tuples (x, y) where y: -1 (down), 0 (neutral), 1 (up)
                current_hat = hats[0] if len(hats) > 0 else (0, 0)
                prev_hat = prev_hats[0] if len(prev_hats) > 0 else (0, 0)
                
                current_y = current_hat[1] if len(current_hat) > 1 else 0
                prev_y = prev_hat[1] if len(prev_hat) > 1 else 0
                
                # Hat up pressed (y changed from 0 or -1 to 1)
                if current_y == 1 and prev_y != 1:
                    print("Hat up pressed - moving selection up")
                    change_dropdown_selection(-1)
                
                # Hat down pressed (y changed from 0 or 1 to -1)
                if current_y == -1 and prev_y != -1:
                    print("Hat down pressed - moving selection down")
                    change_dropdown_selection(1)
            
            # Update previous button and hat states
            prev_buttons = buttons.copy() if buttons else None
            prev_hats = hats.copy() if hats else None

            global current_slider_values
            with slider_values_lock:
                current_slider_values = [int(axes[i] * 512) for i in range(6)]

        # Re-schedule for continuous polling inside Tkinter loop
        root.after(50, poll_joystick)

    root.after(50, poll_joystick)

    root.mainloop()

ws = None
current_server_url = None  # Store server URL for UDP discovery
pending_udp_connections = {}  # Store pending UDP connection info: peer_uid -> {socket, is_server, local_candidates}
reliable_channel = None  # Store the reliable channel for sending UDP messages
current_slider_values = [0] * 6  # Store current slider values (thread-safe access needed)
slider_values_lock = threading.Lock()  # Lock for thread-safe access to slider values
heads_list = []  # Store current heads list
heads_list_lock = threading.Lock()  # Lock for thread-safe access to heads list
heads_dropdown = None  # Reference to the dropdown widget
gui_to_async_queue = queue.Queue()  # Queue for passing GUI events to asyncio thread (thread-safe)
async_to_gui_queue = queue.Queue()  # Queue for passing asyncio events to GUI thread (thread-safe)
current_udp_connection = None  # Currently active UDPConnection (if any)
selected_head_uid = None  # Currently selected head UID from dropdown
selected_head_uid_lock = threading.Lock()  # Lock for thread-safe access to selected head UID
com_port_bgc = None     # COM7
com_port_camera = None  # COM11
com_port_lock = threading.Lock()  # Lock for thread-safe access to COM ports

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

async def send_slider_values(channel):
    while True:
        global current_slider_values
        if channel:
            with slider_values_lock:
                values = current_slider_values.copy()
            await send_udp_message(values, channel)
        await asyncio.sleep(0.05)  # 50ms interval, same as original update_values

async def _com_port_forwarding_task(port_name: str, target: str):
    """Read from a local COM port and forward to selected head via websocket as COM_DATA."""
    global selected_head_uid, ws, com_port_bgc, com_port_camera
    
    if not serial_available:
        print("COM port forwarding disabled - pyserial not available")
        return
    
    BAUD_RATE = 115200  # Standard baud rate, but doesn't matter for virtual port
    
    try:
        # Open COM port
        ser = serial.Serial(port_name, BAUD_RATE, timeout=0.1)
        print(f"COM port {port_name} opened for target={target}")
        
        with com_port_lock:
            if target == "camera":
                com_port_camera = ser
            else:
                com_port_bgc = ser
        
        while True:
            try:
                # Read from COM port (blocking, so use to_thread)
                data = await asyncio.to_thread(ser.read, 1024)
                
                if data and len(data) > 0:
                    # Get selected head UID
                    with selected_head_uid_lock:
                        head_uid = selected_head_uid
                    
                    # Only forward if a head is selected and websocket is available
                    if head_uid and ws:
                        # Encode data as base64 for JSON transport
                        data_b64 = base64.b64encode(data).decode('utf-8')
                        
                        # Send to head via websocket
                        msg = {
                            "type": "COM_DATA",
                            "target": target,
                            "to_uid": head_uid,
                            "from_uid": uid_hex,
                            "data": data_b64
                        }
                        print(f"Sending COM data to head {head_uid}: {msg}")
                        try:
                            await ws.send(json.dumps(msg))
                        except Exception as e:
                            print(f"Error sending COM data to head {head_uid}: {e}")
                
                # Small delay to prevent busy loop
                await asyncio.sleep(0.01)
                
            except Exception as e:
                print(f"Error reading from COM port: {e}")
                await asyncio.sleep(0.1)
                
    except serial.SerialException as e:
        print(f"Error opening COM port {port_name}: {e}")
    except Exception as e:
        print(f"Error in COM port forwarding task: {e}")
    finally:
        with com_port_lock:
            port_ref = com_port_camera if target == "camera" else com_port_bgc
            if port_ref:
                try:
                    port_ref.close()
                except:
                    pass
                if target == "camera":
                    com_port_camera = None
                else:
                    com_port_bgc = None
        print(f"COM port {port_name} closed for target={target}")

async def write_to_com_port(target: str, data: bytes):
    """Write data to a local COM port based on target (called from websocket message handler)."""
    global com_port_bgc, com_port_camera
    
    with com_port_lock:
        port = com_port_camera if target == "camera" else com_port_bgc
    
    if port and port.is_open:
        try:
            await asyncio.to_thread(port.write, data)
            await asyncio.to_thread(port.flush)
        except Exception as e:
            print(f"Error writing to COM port: {e}")

async def onOpen(connection):
    print("Connection opened (onOpen callback)")
    global current_udp_connection
    current_udp_connection = connection
    async_to_gui_queue.put({"type": "UDP_CONNECTION_STATE", "connected": True})
    
    # Access channels from connection
    global unreliable_channel
    unreliable_channel = connection.unreliable_channel

async def onClose(connection):
    print("Connection closed (onClose callback)")
    # Kill slider_send task
    if connection and hasattr(connection, '_slider_send_task') and connection._slider_send_task:
        connection._slider_send_task.cancel()
        try:
            await connection._slider_send_task
        except asyncio.CancelledError:
            pass
    global unreliable_channel
    unreliable_channel = None
    global current_udp_connection
    if current_udp_connection is connection:
        current_udp_connection = None
    async_to_gui_queue.put({"type": "UDP_CONNECTION_STATE", "connected": False})

async def _start_slider_send_task_if_needed(connection):
    """Start the continuous slider streaming task (Joystick mode) if it's not already running."""
    if not connection:
        return
    existing = getattr(connection, "_slider_send_task", None)
    if existing and not existing.done():
        return
    task = asyncio.create_task(send_slider_values(connection.unreliable_channel))
    connection._slider_send_task = task

async def _stop_slider_send_task_if_running(connection):
    """Stop the continuous slider streaming task if running."""
    if not connection:
        return
    task = getattr(connection, "_slider_send_task", None)
    if not task:
        return
    if not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def init_udp_connection(to_uid):
    try:
        # Gather candidates (creates socket, gathers host and srflx candidates)
        sock, candidates = await UDPConnection.gather_candidates(ota.get_local_ips())
        
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
        print(f"Error handling init_udp_connection: {e}")

       
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

        data = {"type": "DEVICE_CONNECT",
                "uid": uid_hex,
                "name": device_name,
                "app_path": app_path,
                "device_type": "controller",
                "network_configs": network_configs,
                "version": manifest["version"],
                "local_ips": local_ips}
        await ws.send(json.dumps(data))  # announce as device
        # if not MICROPYTHON:
        #     asyncio.create_task(ws_sender(ws))
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
                elif my_dict["type"] == "HEADS_LIST":
                    # Update heads list and send to GUI thread via async_to_gui_queue
                    new_heads_list = my_dict.get("heads", [])
                    global heads_list
                    with heads_list_lock:
                        heads_list = new_heads_list
                    async_to_gui_queue.put({"type": "HEADS_LIST", "heads": new_heads_list})
                    print(f"Received heads list: {len(new_heads_list)} heads")
                elif my_dict["type"] == "ANSWER":
                    # from_head receives this - establish connection (server side)
                    from_uid = my_dict.get("from_uid")  # This is the to_head's uid (the one who sent ANSWER)
                    candidates = my_dict.get("candidates", [])
                    print(f"ANSWER received from {from_uid} with {len(candidates)} candidates")
                    
                    try:
                        if from_uid not in pending_udp_connections:
                            print(f"No pending connection found for {from_uid}")
                            return
                        
                        conn_info = pending_udp_connections[from_uid]
                        if not conn_info.get("is_server"):
                            print(f"Connection info for {from_uid} is not marked as server, skipping server handler")
                            return
                        
                        sock = conn_info["socket"]
                        local_candidates = conn_info.get("local_candidates", [])
                        
                        connection = await UDPConnection.create(
                            sock, local_candidates, candidates, from_uid, uid_hex, ws,
                            onOpen=onOpen, onClose=onClose
                        )
                                                    # Clean up pending connection
                        del pending_udp_connections[from_uid]
                        
                    except Exception as e:
                        print(f"Error handling ANSWER (server side): {e}")
                elif my_dict["type"] == "COM_DATA":
                    # Data from head - forward to COM port
                    from_uid = my_dict.get("from_uid")
                    data_b64 = my_dict.get("data", "")
                    target = my_dict.get("target", "bgc")
                    
                    try:
                        data = base64.b64decode(data_b64)
                        await write_to_com_port(target, data)
                    except Exception as e:
                        print(f"Error forwarding COM_DATA from {from_uid} to COM port: {e}")
                                        
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

async def run_gui_task():
    """Run the GUI in a separate thread as an asyncio task"""
    
    # Run GUI in a thread (tkinter mainloop is blocking)
    def gui_thread():
        try:
            run_gui()
        except Exception as e:
            print(f"GUI error: {e}")
    
    thread = threading.Thread(target=gui_thread, daemon=True)
    thread.start()
    
    # Wait for the thread to complete (which it won't until the app closes)
    # This keeps the task alive
    while thread.is_alive():
        await asyncio.sleep(1)

async def gui_event_pump_task():
    """Pump GUI events from thread-safe queue into asyncio thread (no asyncio calls in GUI thread)."""
    while True:
        event = await asyncio.to_thread(gui_to_async_queue.get)
        try:
            if isinstance(event, dict) and event.get("type") == "CONNECT":
                if not current_udp_connection:
                    to_uid = event.get("to_uid")
                    if to_uid:
                        await init_udp_connection(to_uid)
            elif isinstance(event, dict) and event.get("type") == "DISCONNECT":
                if current_udp_connection:
                    await _stop_slider_send_task_if_running(current_udp_connection)
                    await current_udp_connection.close()
            elif isinstance(event, dict) and event.get("type") == "SET_MODE":
                mode = event.get("mode")
                if current_udp_connection and mode:
                    if mode == "joystick":
                        await _start_slider_send_task_if_needed(current_udp_connection)
                    else:
                        await _stop_slider_send_task_if_running(current_udp_connection)
                    msg = {"type": "SET_MODE", "mode": mode}
                    channel = getattr(current_udp_connection, "reliable_channel", None)
                    if channel:
                        await channel.send(json.dumps(msg).encode("utf-8"))
        finally:
            try:
                gui_to_async_queue.task_done()
            except Exception:
                pass

async def as_main(server_url):
    tasks = [
        run_gui_task(),
        gui_event_pump_task(),
        websocket(server_url),
        _com_port_forwarding_task("COM7", "bgc"),
        _com_port_forwarding_task("COM11", "camera"),
    ]

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
