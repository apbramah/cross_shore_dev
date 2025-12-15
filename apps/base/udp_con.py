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
            # Set socket to non-blocking for asyncio
            self.sock.setblocking(False)

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
                    # CPython: use asyncio sock_recvfrom with non-blocking socket
                    try:
                        # sock_recvfrom will yield control to event loop
                        data, addr = await asyncio.wait_for(
                            loop.sock_recvfrom(self.sock, 2048),
                            timeout=0.25
                        )
                    except asyncio.TimeoutError:
                        # Timeout - continue loop to allow other tasks to run
                        continue
                
                # Verify packet is from expected peer
                if addr != self.peer_addr:
                    continue
                
                # Decode packet
                result = self._decode_packet(data)

                print('result', result)
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
        # Use fixed-size arrays for MicroPython compatibility
        self.window_size = 8  # Power of 2 for efficient modulo
        self.pending_packets = [None] * self.window_size  # Array of (data, timestamp, retransmit_count) or None
        self.pending_window_start = None  # First seq_num in pending window
        self.received_packets = [None] * self.window_size  # Array of payload or None
        self.received_window_start = None  # First seq_num in received window
        self.ack_timeout = 0.5  # Seconds before retransmit
        self.max_retransmits = 5
        self._retransmit_task = None
    
    def _pending_seq_to_index(self, seq_num):
        """Convert sequence number to pending_packets array index"""
        if self.pending_window_start is None:
            return 0  # First packet, will initialize window
        return (seq_num - self.pending_window_start) & (self.window_size - 1)
    
    def _received_seq_to_index(self, seq_num):
        """Convert sequence number to received_packets array index"""
        if self.received_window_start is None:
            return 0  # First packet, will initialize window
        return (seq_num - self.received_window_start) & (self.window_size - 1)
    
    def _slide_pending_window(self, new_start):
        """Slide the pending window forward, clearing old entries"""
        old_start = self.pending_window_start
        if old_start is None:
            self.pending_window_start = new_start
            return
        
        # Clear entries that are now outside the window
        for i in range(self.window_size):
            seq_num = old_start + i
            if seq_num < new_start:
                # This entry is now outside the window
                index = (seq_num - old_start) & (self.window_size - 1)
                self.pending_packets[index] = None
        
        self.pending_window_start = new_start
    
    def _slide_received_window(self, new_start):
        """Slide the received window forward, clearing old entries"""
        old_start = self.received_window_start
        if old_start is None:
            self.received_window_start = new_start
            return
        
        # Clear entries that are now outside the window
        for i in range(self.window_size):
            seq_num = old_start + i
            if seq_num < new_start:
                # This entry is now outside the window
                index = (seq_num - old_start) & (self.window_size - 1)
                self.received_packets[index] = None
        
        self.received_window_start = new_start
        
    async def send(self, data):
        """Send data reliably with retransmission"""
        if self.closed:
            return False
        
        seq_num = self.next_seq_out
        self.next_seq_out = (self.next_seq_out + 1) & 0xFFFFFFFF
        
        # Initialize window if this is the first packet
        if self.pending_window_start is None:
            self.pending_window_start = seq_num
        
        # Check if we need to slide the window forward
        if seq_num - self.pending_window_start >= self.window_size:
            # Slide window forward to make room
            new_start = seq_num - self.window_size + 1
            self._slide_pending_window(new_start)
        
        # Store packet for retransmission
        index = self._pending_seq_to_index(seq_num)
        self.pending_packets[index] = (data, time.time(), 0)
        
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
            if self.pending_window_start is not None:
                # Check if seq_num is within the current window
                if self.pending_window_start <= seq_num < self.pending_window_start + self.window_size:
                    index = self._pending_seq_to_index(seq_num)
                    if self.pending_packets[index] is not None:
                        self.pending_packets[index] = None
            return
        
        # Send ACK for received packet
        ack_packet = self.connection._encode_packet(
            self.channel_id, seq_num, b'', FLAG_ACK
        )
        self.connection._send_raw(ack_packet)
        
        # Initialize window if this is the first packet
        if self.received_window_start is None:
            self.received_window_start = seq_num
        elif seq_num < self.received_window_start:
            # Packet is too old (before window start), ignore
            return
        
        # Check if we need to slide the window forward to include this packet
        if seq_num - self.received_window_start >= self.window_size:
            # Slide window forward to make room for this packet
            new_start = seq_num - self.window_size + 1
            self._slide_received_window(new_start)
        
        # Store packet (may be out of order)
        index = self._received_seq_to_index(seq_num)
        self.received_packets[index] = payload
        
        # Deliver in-order packets
        while True:
            if self.received_window_start is None:
                break
            
            # Check if we have the next expected packet
            expected_index = self._received_seq_to_index(self.next_seq_in)
            data = self.received_packets[expected_index]
            
            if data is None:
                # Missing packet, can't deliver more
                break
            
            # Deliver this packet
            self.received_packets[expected_index] = None
            self.next_seq_in = (self.next_seq_in + 1) & 0xFFFFFFFF
            
            # Slide window forward if we've consumed the first entry
            if self.next_seq_in >= self.received_window_start + self.window_size:
                new_start = self.received_window_start + 1
                self._slide_received_window(new_start)
            
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
                
                if self.pending_window_start is not None:
                    # Iterate through the window
                    for i in range(self.window_size):
                        seq_num = self.pending_window_start + i
                        index = i
                        entry = self.pending_packets[index]
                        
                        if entry is None:
                            continue
                        
                        data, timestamp, retransmit_count = entry
                        
                        if current_time - timestamp > self.ack_timeout:
                            if retransmit_count < self.max_retransmits:
                                to_retransmit.append((seq_num, data, retransmit_count, index))
                            else:
                                # Max retransmits reached - give up
                                print(f"Max retransmits reached for seq {seq_num}, dropping")
                                self.pending_packets[index] = None
                
                # Retransmit packets
                for seq_num, data, retransmit_count, index in to_retransmit:
                    packet = self.connection._encode_packet(self.channel_id, seq_num, data)
                    self.connection._send_raw(packet)
                    self.pending_packets[index] = (data, current_time, retransmit_count + 1)
                
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
