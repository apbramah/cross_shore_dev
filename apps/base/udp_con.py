import time
try:
    import uasyncio as asyncio
    import usocket as socket
    import ustruct as struct
    MICROPYTHON = True
except ImportError:
    import asyncio
    import socket
    import struct
    MICROPYTHON = False
    
# Packet format (binary):
# [flags:1 byte][channel_id:2 bytes][seq_num:4 bytes][data:variable]
# Flags: bit 0 = ACK, bits 1-7 reserved
FLAG_ACK = 0x01

udp_connections = {}  # Track UDP connections: peer_uid -> UDPConnection

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

async def perform_udp_hole_punch(peer_ip, peer_port, peer_uid, existing_socket=None):
    """
    Perform UDP hole-punching to establish a connection with a peer.
    existing_socket: Optional pre-existing socket to reuse (must already be bound).
    Returns: (UDPConnection or None, success: bool, message: str)
    """
    sock = existing_socket  # Use provided socket if available
    try:
        peer_port = int(peer_port)
        
        
        peer_addr = (peer_ip, peer_port)
        
        # Set socket timeout (works for both new and existing sockets)
        try:
            sock.settimeout(0.1)
        except AttributeError:
            # Some socket implementations might not support settimeout
            pass
        
        print(f"Starting UDP hole-punching to {peer_ip}:{peer_port}")
        
        # Send multiple packets to punch through NAT
        success = False
        for i in range(100):
            test_data = f"HOLE_PUNCH_{i}".encode('utf-8')
            sock.sendto(test_data, peer_addr)
            print(f"Sent hole-punch packet {i} to {peer_ip}:{peer_port}")
            
            await asyncio.sleep(0.001)
            
            # Try to receive a response
            try:
                data, addr = sock.recvfrom(1024)
                if addr == peer_addr:
                    print(f"Received response from {addr}: {data.decode('utf-8')}")
                    success = True
                    break
                else:
                    print(f"Received response from {addr} but it's not the peer : {data.decode('utf-8')}")
                    test_data = f"HOLE_PUNCH_RESPONSE{i}".encode('utf-8')
                    sock.sendto(test_data, addr)
                    print(f"Sent hole-punch packet {i} to:", addr)
            except Exception as e:
                pass
        
        if success:
            # Create UDPConnection object
            connection = UDPConnection(sock, peer_addr, peer_uid)
            udp_connections[peer_uid] = connection
            await connection.start()
            
            return (connection, True, f"UDP connection established with {peer_uid}")
        else:
            # Only close socket if we created it (not if it was passed in)
            if existing_socket is None:
                sock.close()
            return (None, False, f"Hole-punching did not receive confirmation from {peer_ip}:{peer_port}")
        
    except Exception as e:
        error_msg = f"UDP hole-punching failed: {str(e)}"
        print(error_msg)
        # Only close socket if we created it (not if it was passed in)
        if existing_socket is None:
            try:
                sock.close()
            except:
                pass
        return (None, False, error_msg)
