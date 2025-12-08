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
    import ustruct as struct
    
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
    import struct
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
udp_connections = {}  # Track UDP connections: peer_uid -> UDPConnection

# Packet format (binary):
# [flags:1 byte][channel_id:2 bytes][seq_num:4 bytes][data:variable]
# Flags: bit 0 = ACK, bits 1-7 reserved
FLAG_ACK = 0x01

class UDPConnection:
    """
    Manages a UDP connection with multiple datachannels.
    Handles packet demultiplexing and channel management.
    """
    def __init__(self, sock, peer_addr, peer_uid):
        self.sock = sock
        self.peer_addr = peer_addr  # (ip, port)
        self.peer_uid = peer_uid
        self.channels = {}  # channel_id -> DataChannel
        self.next_channel_id = 1
        self.running = False
        self._receiver_task = None
        
    def create_channel(self, channel_type='unreliable'):
        """
        Create a new datachannel.
        channel_type: 'reliable' or 'unreliable'
        Returns: DataChannel instance
        """
        channel_id = self.next_channel_id
        self.next_channel_id += 1
        
        if channel_type == 'reliable':
            channel = ReliableDataChannel(self, channel_id)
        else:
            print(self, channel_id)
            channel = UnreliableDataChannel(self, channel_id)
        
        self.channels[channel_id] = channel
        return channel
    
    def _encode_packet(self, channel_id, seq_num, data, flags=0):
        """Encode a packet for transmission"""
        # Pack: flags (1 byte), channel_id (2 bytes), seq_num (4 bytes), data
        header = struct.pack('!BHI', flags, channel_id, seq_num)
        return header + data
    
    def _decode_packet(self, packet):
        """Decode a received packet"""
        if len(packet) < 7:  # Minimum header size
            return None
        
        flags, channel_id, seq_num = struct.unpack('!BHI', packet[:7])
        data = packet[7:]
        return flags, channel_id, seq_num, data
    
    def _send_raw(self, packet):
        """Send a raw packet over the UDP socket"""
        try:
            self.sock.sendto(packet, self.peer_addr)
            return True
        except Exception as e:
            print(f"Error sending UDP packet: {e}")
            return False
    
    async def _receiver_loop(self):
        """Main receiver loop - demultiplexes packets to channels"""
        if not MICROPYTHON:
            loop = asyncio.get_running_loop()

        while self.running:
            try:
                if MICROPYTHON:
                    # MicroPython: use timeout-based approach
                    self.sock.setblocking(False)
                    try:
                        data, addr = self.sock.recvfrom(2048)
                    except OSError:
                        await asyncio.sleep(0.01)  # Small delay if no data
                        continue
                    finally:
                        self.sock.setblocking(True)
                else:
                    self.sock.settimeout(0.25)
                    try:
                        data, addr = await loop.sock_recvfrom(self.sock, 2048)
                    except socket.timeout:
                        print('timeout')
                        continue
                
                # Verify packet is from expected peer
                if addr != self.peer_addr:
                    continue
                
                # Decode packet
                result = self._decode_packet(data)
                if result is None:
                    continue
                
                flags, channel_id, seq_num, payload = result
                
                # Route to appropriate channel
                if channel_id in self.channels:
                    channel = self.channels[channel_id]
                    await channel._handle_packet(flags, seq_num, payload)
                    
            except Exception as e:
                print(f"Error in receiver loop: {e}")
                await asyncio.sleep(0.1)
    
    async def start(self):
        """Start the connection and receiver loop"""
        if self.running:
            return
        
        self.running = True
        self._receiver_task = asyncio.create_task(self._receiver_loop())
    
    async def close(self):
        """Close the connection and all channels"""
        self.running = False
        if self._receiver_task:
            self._receiver_task.cancel()
            try:
                await self._receiver_task
            except asyncio.CancelledError:
                pass
        
        for channel in self.channels.values():
            await channel.close()
        
        try:
            self.sock.close()
        except:
            pass


class DataChannel:
    """Base class for datachannels"""
    def __init__(self, connection, channel_id):
        self.connection = connection
        self.channel_id = channel_id
        self.next_seq_out = 0
        self.next_seq_in = 0
        self.closed = False
        
    async def send(self, data):
        print('cannot be here')
        """Send data over the channel. Must be implemented by subclass."""
        raise NotImplementedError
    
    async def _handle_packet(self, flags, seq_num, payload):
        """Handle incoming packet. Must be implemented by subclass."""
        raise NotImplementedError
    
    async def close(self):
        """Close the channel"""
        self.closed = True


class UnreliableDataChannel(DataChannel):
    """
    Unreliable datachannel - no retransmission, out-of-order packets ignored.
    Uses sequence numbers to filter duplicates and out-of-order packets.
    """
    def __init__(self, connection, channel_id):
        super().__init__(connection, channel_id)
        print('hey this is me creating an object')
        
    async def send(self, data):
        """Send data unreliably"""
        if self.closed:
            return False
        
        seq_num = self.next_seq_out
        self.next_seq_out = (self.next_seq_out + 1) & 0xFFFFFFFF
        
        try:
            packet = self.connection._encode_packet(self.channel_id, seq_num, data)
        except Exception as e:
            print("encode didn't go well", e)
        return self.connection._send_raw(packet)
    
    async def _handle_packet(self, flags, seq_num, payload):
        """Handle incoming unreliable packet"""
        if self.closed:
            return
        
        # Check if packet is in order or duplicate
        if seq_num < self.next_seq_in:
            # Out of order or duplicate - ignore
            return
        
        # In-order packet - advance sequence window
        self.next_seq_in = seq_num + 1
        
        # Notify application (if callback registered)
        if hasattr(self, 'on_message'):
            try:
                await self.on_message(payload)
            except Exception as e:
                print(f"Error in on_message callback: {e}")

class ReliableDataChannel(DataChannel):
    """
    Reliable datachannel - retransmits unacknowledged packets.
    Uses sequence numbers and ACKs for reliability.
    """
    def __init__(self, connection, channel_id):
        super().__init__(connection, channel_id)
        self.pending_packets = {}  # seq_num -> (data, timestamp, retransmit_count)
        self.received_packets = {}  # seq_num -> data (for out-of-order)
        self.ack_timeout = 0.5  # Seconds before retransmit
        self.max_retransmits = 5
        self._retransmit_task = None
        
    async def send(self, data):
        """Send data reliably with retransmission"""
        if self.closed:
            return False
        
        seq_num = self.next_seq_out
        self.next_seq_out = (self.next_seq_out + 1) & 0xFFFFFFFF
        
        # Store packet for retransmission
        self.pending_packets[seq_num] = (data, time.time(), 0)
        
        # Send initial packet
        packet = self.connection._encode_packet(self.channel_id, seq_num, data)
        self.connection._send_raw(packet)
        
        return True
    
    async def _handle_packet(self, flags, seq_num, payload):
        """Handle incoming reliable packet"""
        if self.closed:
            return
        
        # Check if this is an ACK
        if flags & FLAG_ACK:
            # Remove acknowledged packet from pending
            if seq_num in self.pending_packets:
                del self.pending_packets[seq_num]
            return
        
        # Send ACK for received packet
        ack_packet = self.connection._encode_packet(
            self.channel_id, seq_num, b'', FLAG_ACK
        )
        self.connection._send_raw(ack_packet)
        
        # Handle data packet
        if seq_num < self.next_seq_in:
            # Old/duplicate packet - already processed
            return
        
        # Store packet (may be out of order)
        self.received_packets[seq_num] = payload
        
        # Deliver in-order packets
        while self.next_seq_in in self.received_packets:
            data = self.received_packets.pop(self.next_seq_in)
            self.next_seq_in = (self.next_seq_in + 1) & 0xFFFFFFFF
            
            # Notify application
            if hasattr(self, 'on_message'):
                try:
                    await self.on_message(data)
                except Exception as e:
                    print(f"Error in on_message callback: {e}")
    
    async def _retransmit_loop(self):
        """Periodically retransmit unacknowledged packets"""
        while not self.closed:
            try:
                current_time = time.time()
                to_retransmit = []
                
                for seq_num, (data, timestamp, retransmit_count) in self.pending_packets.items():
                    if current_time - timestamp > self.ack_timeout:
                        if retransmit_count < self.max_retransmits:
                            to_retransmit.append((seq_num, data, retransmit_count))
                        else:
                            # Max retransmits reached - give up
                            print(f"Max retransmits reached for seq {seq_num}, dropping")
                            del self.pending_packets[seq_num]
                
                # Retransmit packets
                for seq_num, data, retransmit_count in to_retransmit:
                    packet = self.connection._encode_packet(self.channel_id, seq_num, data)
                    self.connection._send_raw(packet)
                    self.pending_packets[seq_num] = (data, current_time, retransmit_count + 1)
                
                await asyncio.sleep(0.1)  # Check every 100ms
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error in retransmit loop: {e}")
                await asyncio.sleep(0.1)
    
    async def start(self):
        """Start retransmission loop"""
        if self._retransmit_task is None:
            self._retransmit_task = asyncio.create_task(self._retransmit_loop())
    
    async def close(self):
        """Close the channel"""
        await super().close()
        if self._retransmit_task:
            self._retransmit_task.cancel()
            try:
                await self._retransmit_task
            except asyncio.CancelledError:
                pass

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

async def perform_udp_hole_punch(peer_ip, peer_port, peer_uid, local_port=8889):
    """
    Perform UDP hole-punching to establish a connection with a peer.
    Returns: (UDPConnection or None, success: bool, message: str)
    """
    try:
        peer_port = int(peer_port)
        local_port = int(local_port)
        
        # Create UDP socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        # Bind to a local port
        try:
            sock.bind(('0.0.0.0', local_port))
        except OSError:
            sock.bind(('0.0.0.0', 0))
        
        peer_addr = (peer_ip, peer_port)
        
        # Set socket timeout
        sock.settimeout(0.1)
        
        print(f"Starting UDP hole-punching to {peer_ip}:{peer_port} from port {local_port}")
        
        # Send multiple packets to punch through NAT
        success = False
        for i in range(10):
            test_data = f"HOLE_PUNCH_{i}".encode('utf-8')
            sock.sendto(test_data, peer_addr)
            print(f"Sent hole-punch packet {i} to {peer_ip}:{peer_port}")
            
            await asyncio.sleep(0.1)
            
            # Try to receive a response
            try:
                data, addr = sock.recvfrom(1024)
                if addr == peer_addr:
                    print(f"Received response from {addr}: {data.decode('utf-8')}")
                    success = True
                    break
            except Exception as e:
                pass
        
        if success:
            # Create UDPConnection object
            connection = UDPConnection(sock, peer_addr, peer_uid)
            udp_connections[peer_uid] = connection
            await connection.start()
            
            return (connection, True, f"UDP connection established with {peer_uid}")
        else:
            sock.close()
            return (None, False, f"Hole-punching did not receive confirmation from {peer_ip}:{peer_port}")
        
    except Exception as e:
        error_msg = f"UDP hole-punching failed: {str(e)}"
        print(error_msg)
        try:
            sock.close()
        except:
            pass
        return (None, False, error_msg)

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
                        connection, success, message = await perform_udp_hole_punch(
                            peer_ip, peer_port, peer_uid
                        )
                        
                        if success and connection:
                            # Example: Create a reliable and unreliable channel
                            reliable_channel = connection.create_channel('reliable')
                            await reliable_channel.start()
                            
                            unreliable_channel = connection.create_channel('unreliable')
                            
                            # Set up message handlers (optional)
                            async def on_reliable_message(data):
                                print(f"Reliable channel received: {data}")
                            async def on_unreliable_message(data):
                                print(f"Unreliable channel received: {data}")
                            
                            reliable_channel.on_message = on_reliable_message
                            unreliable_channel.on_message = on_unreliable_message
                            
                            print(f"Created UDP connection with channels for {peer_uid}")

                            async def occasional_send(channel, my_string):
                                while True:
                                    print('sending', my_string)
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
