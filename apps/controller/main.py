from udp_con import UDPConnection

import json
import threading
import time

import asyncio
uid_hex = 'andyunique'

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

def run_gui():
    """Run the tkinter GUI in a separate thread"""
    root = tk.Tk()
    root.title("EX Head Controller Relative")
    
    sliders = []
    
    # Labels for sliders
    slider_names = ["Yaw", "Pitch", "Roll", "Zoom", "Focus", "Iris"]
    
    # Create and place sliders
    for name in slider_names:
        frame = ttk.Frame(root)
        frame.pack(fill=tk.BOTH, expand=True)
        
        label = ttk.Label(frame, text=name)
        label.pack(side=tk.TOP, pady=5)
        
        slider = ttk.Scale(frame, from_=-512, to=512, orient=tk.HORIZONTAL, length=200)
        slider.set(0)
        value_var = tk.IntVar(value=0)  # Variable to hold the current value
    
        # Live value label
        value_label = ttk.Label(frame, textvariable=value_var)
        value_label.pack(side=tk.RIGHT, padx=5)
    
        # Entry box to type value
        entry = ttk.Entry(frame, width=5)
        entry.pack(side=tk.RIGHT, padx=5)
        entry.insert(0, "0")
    
        def on_slider_move(value, var=value_var, e=entry):
            val = int(float(value))
            var.set(val)
            e.delete(0, tk.END)
            e.insert(0, str(val))

            # Update shared slider values whenever any slider changes
            global current_slider_values
            with slider_values_lock:
                current_slider_values = [int(s.get()) for s in sliders]
    
        def on_entry_change(event, s=slider, var=value_var):
            try:
                val = int(event.widget.get())
                s.set(val)
                var.set(val)
            except ValueError:
                pass  # ignore non-integer input
    
        slider.config(command=lambda val, var=value_var, e=entry: on_slider_move(val, var, e))
        entry.bind("<Return>", on_entry_change)
        slider.pack(side=tk.TOP)
        sliders.append(slider)
    
    buttons = []
    
    def set_slider_values(values):
        for slider, value in zip(sliders, values):
            slider.set(value)
    
    class ButtonWithLongPress(ttk.Button):
        def __init__(self, master=None, **kwargs):
            super().__init__(master, **kwargs)
            self.bind("<ButtonPress>", self.on_press)
            self.bind("<ButtonRelease>", self.on_release)
            self.long_press_duration = 1000  # Duration for long press in milliseconds
            self.press_time = None
            self.stored_values = [0] * 6  # Initialize with default slider values
    
        def on_press(self, event):
            self.press_time = time.time()
            self.after(self.long_press_duration, self.check_long_press)
    
        def on_release(self, event):
            if self.press_time:
                elapsed = time.time() - self.press_time
                if elapsed < self.long_press_duration / 1000:
                    # Short press detected
                    set_slider_values(self.stored_values)
                self.press_time = None
    
        def check_long_press(self):
            if self.press_time and (time.time() - self.press_time) >= self.long_press_duration / 1000:
                # Long press detected
                self.stored_values = [int(slider.get()) for slider in sliders]
                print(f"Stored values for button {self['text']}: {self.stored_values}")
                self.press_time = None
    
    # Create and place buttons
    for i in range(4):
        button = ButtonWithLongPress(root, text=f"Position {i + 1}")
        button.pack(side=tk.LEFT, padx=5, pady=5)
        buttons.append(button)
    
    # Sequencer function to press buttons with a 2s delay
    sequencer_enabled = False
    
    def press_buttons_sequentially(index=0):
        if sequencer_enabled:
            buttons[index].event_generate("<ButtonPress>")
            buttons[index].event_generate("<ButtonRelease>")
            next_index = (index + 1) % len(buttons)
            root.after(2000, press_buttons_sequentially, next_index)
    
    def toggle_sequencer():
        nonlocal sequencer_enabled
        sequencer_enabled = not sequencer_enabled
        if sequencer_enabled:
            sequencer_button.config(text="Disable Sequencer")
            press_buttons_sequentially()
        else:
            sequencer_button.config(text="Enable Sequencer")
    
    # Create the sequencer toggle button
    sequencer_button = ttk.Button(root, text="Enable Sequencer", command=toggle_sequencer)
    sequencer_button.pack(side=tk.BOTTOM, pady=10)
    
    root.mainloop()

ws = None
current_server_url = None  # Store server URL for UDP discovery
pending_udp_connections = {}  # Store pending UDP connection info: peer_uid -> {socket, is_server, local_candidates}
reliable_channel = None  # Store the reliable channel for sending UDP messages
current_slider_values = [0] * 6  # Store current slider values (thread-safe access needed)
slider_values_lock = threading.Lock()  # Lock for thread-safe access to slider values

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

async def onOpen(connection):
    print("Connection opened (onOpen callback)")
    
    # Access channels from connection
    global unreliable_channel
    unreliable_channel = connection.unreliable_channel
    
    # Start slider values sending task
    slider_send_task = asyncio.create_task(send_slider_values(unreliable_channel))
    connection._slider_send_task = slider_send_task

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
                elif my_dict["type"] == "INITIATE_UDP_CONNECTION":
                    # from_head receives this - act as UDP server
                    to_uid = my_dict.get("to_uid")
                    
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
                        print(f"Error handling INITIATE_UDP_CONNECTION: {e}")
                    
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
                            onOpen=onOpen, onClose=onClose
                        )
                        
                        # Clean up pending connection
                        del pending_udp_connections[from_uid]
                        
                    except Exception as e:
                        print(f"Error handling OFFER: {e}")
                    
                elif my_dict["type"] == "ANSWER":
                    # from_head receives this - establish connection (server side)
                    from_uid = my_dict.get("from_uid")  # This is the to_head's uid (the one who sent ANSWER)
                    candidates = my_dict.get("candidates", [])
                    print(f"ANSWER received from {from_uid} with {len(candidates)} candidates")
                    
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
                        
                        connection = await UDPConnection.create(
                            sock, local_candidates, candidates, from_uid, uid_hex, ws,
                            onOpen=onOpen, onClose=onClose
                        )
                                                    # Clean up pending connection
                        del pending_udp_connections[from_uid]
                        
                    except Exception as e:
                        print(f"Error handling ANSWER (server side): {e}")
                                        
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

async def as_main(server_url):
    tasks = [run_gui_task(), websocket(server_url)]

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
