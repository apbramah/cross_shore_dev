import time
import json
try:
    import uasyncio as asyncio
    import usocket as socket
    import ustruct as struct
    import utime as time_module
    MICROPYTHON = True
except ImportError:
    import asyncio
    import socket
    import struct
    import time as time_module
    MICROPYTHON = False
    
# Packet format (binary):
# [DATA_MAGIC:4 bytes][flags:1 byte][channel_id:2 bytes][seq_num:4 bytes][data:variable]
# Flags: bit 0 = ACK, bits 1-7 reserved
DATA_MAGIC = b'UDPD'  # Magic header to identify valid packets
STUN_CHECK_MAGIC = b"STUN_CHECK"
STUN_RESPONSE_MAGIC = b"STUN_RESPONSE"
FLAG_ACK = 0x01

udp_connections = {}  # Track UDP connections: peer_uid -> UDPConnection

class UDPConnection:
    """
    Manages a UDP connection with multiple datachannels.
    Handles packet demultiplexing and channel management.
    Also handles candidate pair evaluation for connection establishment.
    """
    def __init__(self, sock, local_candidates, remote_candidates, peer_uid, onOpen=None, onClose=None):
        self.sock = sock
        self.local_candidates = local_candidates
        self.all_remote_candidates = remote_candidates.copy()
        self.peer_uid = peer_uid
        self.peer_addr = None  # Will be set when we receive a DATA_MAGIC packet or successful STUN response
        self.channels = {}  # channel_id -> DataChannel
        self.next_channel_id = 1
        self.running = False
        self._receiver_task = None
        self._evaluation_task = None
        self.response_addresses = set()  # Track addresses we've responded to during evaluation
        self.checks_sent = {}  # Track connectivity checks sent during evaluation
        self.last_response_send_time = {}  # Track when we last sent a response to each address
        self.candidate_no_response_count = {}  # Track rounds without response for each candidate: (address, port) -> count
        self.candidates_that_responded = set()  # Track candidates that have responded (address, port) tuples
        self.onOpen = onOpen  # Callback called when peer_addr is set
        self.onClose = onClose  # Callback called when connection closes
        
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
        return DATA_MAGIC + header + data
    
    def _decode_packet(self, packet):
        """Decode a received packet"""
        # Check for DATA_MAGIC header
        if len(packet) < len(DATA_MAGIC) + 7:  # Minimum size: magic + header
            return None
        
        # Verify magic header
        if packet[:len(DATA_MAGIC)] != DATA_MAGIC:
            return None
        
        # Strip magic header and decode
        payload = packet[len(DATA_MAGIC):]
        flags, channel_id, seq_num = struct.unpack('!BHI', payload[:7])
        data = payload[7:]
        return flags, channel_id, seq_num, data
    
    def _send_raw(self, packet, addr=None):
        """Send a raw packet over the UDP socket"""
        try:
            if addr == None:
                addr = self.peer_addr

            if addr == None:
                print("Error: Cannot send packet, addr not set")
                return

            self.sock.sendto(packet, addr)
        except Exception as e:
            print(f"Error sending UDP packet: {e}")
    
    async def _receiver_loop(self):
        """
        Unified receiver loop - handles both STUN packets (for continuous evaluation)
        and DATA packets (for data channels) simultaneously
        """
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
                
                if data.startswith(DATA_MAGIC):
                    await self._handle_data_packet(data, addr)
                elif data.startswith(STUN_RESPONSE_MAGIC) or data.startswith(STUN_CHECK_MAGIC):
                    await self._handle_stun_packet(data, addr)
                    
            except Exception as e:
                print(f"Error in receiver loop: {e}")
                await asyncio.sleep(0.1)
    

    async def _open(self, addr):
        self.peer_addr = addr
        if self.onOpen:
            try:
                await self.onOpen()
            except Exception as e:
                print(f"Error in onOpen callback: {e}")

    async def _handle_data_packet(self, data, addr):
        # Set peer_addr if not already set
        if self.peer_addr is None:
            await self._open(addr)
        
        # Only process if from the known peer (or first time)
        if addr == self.peer_addr:
            result = self._decode_packet(data)
            if result is not None:
                flags, channel_id, seq_num, payload = result
                # Route to appropriate channel
                if channel_id in self.channels:
                    channel = self.channels[channel_id]
                    await channel._handle_packet(flags, seq_num, payload)

    async def _handle_stun_packet(self, data, addr):
        """Handle STUN packets for continuous candidate evaluation"""
        # Check if response is from an expected address (within our sent checks)
        expected_addr = None
        for check_addr in self.checks_sent.keys():
            if addr == check_addr:
                expected_addr = check_addr
                break
        
        if expected_addr:
            # Response from expected address - pair is successful!
            # Mark this candidate as having responded
            self.candidates_that_responded.add(addr)
            # Reset no-response count for this candidate
            if addr in self.candidate_no_response_count:
                del self.candidate_no_response_count[addr]
            # Set peer_addr if not already set
            if self.peer_addr is None:
                await self._open(addr)
        else:
            # Response from unexpected address - discover prflx candidate
            print(f"Received STUN response from unexpected address {addr}, creating prflx candidate")
            prflx_candidate = {
                "type": "prflx",
                "address": addr[0],
                "port": addr[1]
            }
            
            # Check if we already know about this candidate
            already_known = False
            for known_cand in self.all_remote_candidates:
                if (known_cand["address"] == prflx_candidate["address"] and
                    known_cand["port"] == prflx_candidate["port"]):
                    already_known = True
                    break
            
            if not already_known:
                self.all_remote_candidates.append(prflx_candidate)
                # Mark this prflx candidate as having responded
                self.candidates_that_responded.add(addr)
                # Reset no-response count for this candidate
                if addr in self.candidate_no_response_count:
                    del self.candidate_no_response_count[addr]
                print(f"Added new prflx candidate: {prflx_candidate}")
                # Will form new pairs in next round
        
        # If it's a check from peer, respond (and mark this address for continued responses)
        if data.startswith(STUN_CHECK_MAGIC):
            response_packet = STUN_RESPONSE_MAGIC + data[len(STUN_CHECK_MAGIC):]
            try:
                self._send_raw(response_packet, addr)
                self.response_addresses.add(addr)  # Mark for continued responses
                print(f"Sent connectivity check response to {addr}")
            except Exception as e:
                print(f"Error sending response to {addr}: {e}")
    
    async def _evaluation_loop(self):
        """Continuously perform candidate pair evaluation using ICE-like connectivity checks"""
        # Socket should already be non-blocking (set by receiver loop)
        round_num = 0
        round_interval = 0.5  # Send checks every 500ms
        previous_checks_sent = {}  # Track checks sent in previous round
        
        while self.running:
            round_num += 1
            print(f"Candidate pair evaluation round {round_num}")
            
            # Update no-response counts for candidates checked in previous round
            # (skip this on first round when previous_checks_sent is empty)
            if previous_checks_sent:
                # Increment count for candidates that were checked but didn't respond
                for remote_addr in previous_checks_sent.keys():
                    if remote_addr not in self.candidates_that_responded:
                        # This candidate was checked but didn't respond
                        self.candidate_no_response_count[remote_addr] = self.candidate_no_response_count.get(remote_addr, 0) + 1
                        count = self.candidate_no_response_count[remote_addr]
                        print(f"Candidate {remote_addr} has {count} rounds without response")
                        
                        # Remove candidate if it has exceeded 10 rounds without response
                        if count >= 10:
                            print(f"Removing candidate {remote_addr} after {count} rounds without response")
                            # Remove from all_remote_candidates
                            self.all_remote_candidates = [
                                cand for cand in self.all_remote_candidates
                                if (cand["address"], cand["port"]) != remote_addr
                            ]
                            # Clean up tracking
                            if remote_addr in self.candidate_no_response_count:
                                del self.candidate_no_response_count[remote_addr]
            
            # Reset response tracking for this round
            self.candidates_that_responded.clear()
            
            # Form candidate pairs from local socket and all remote candidates
            all_pairs = []
            for local_cand in self.local_candidates:
                for remote_cand in self.all_remote_candidates:
                    all_pairs.append((local_cand, remote_cand))
            
            if not all_pairs:
                print("No candidate pairs to evaluate - closing connection")
                await self.close()
                return
            
            # Evaluate pairs by sending connectivity checks
            self.checks_sent = {}
            for local_cand, remote_cand in all_pairs:
                remote_addr = (remote_cand["address"], remote_cand["port"])
                try:
                    # Send connectivity check
                    check_packet = STUN_CHECK_MAGIC + json.dumps({
                        "local": local_cand,
                        "remote": remote_cand
                    }).encode('utf-8')
                    self._send_raw(check_packet, remote_addr)
                    self.checks_sent[remote_addr] = (local_cand, remote_cand)
                    print(f"Sent connectivity check to {remote_addr}")
                except Exception as e:
                    print(f"Error sending connectivity check to {remote_addr}: {e}")
            
            # Continue sending keepalive responses to known addresses
            current_time = time_module.time()
            for resp_addr in list(self.response_addresses):
                last_send = self.last_response_send_time.get(resp_addr, 0)
                if current_time - last_send >= 0.1:  # Send every 100ms
                    try:
                        response_packet = STUN_RESPONSE_MAGIC + b"KEEPALIVE"
                        self._send_raw(response_packet, resp_addr)
                        self.last_response_send_time[resp_addr] = current_time
                    except Exception as e:
                        print(f"Error sending keepalive response to {resp_addr}: {e}")
            
            # Save current round's checks for next iteration
            previous_checks_sent = self.checks_sent.copy()
            
            # Wait before next round
            await asyncio.sleep(round_interval)
    
    async def start(self):
        """Start the connection: start receiver loop and continuous evaluation"""
        if self.running:
            return
        
        self.running = True
        self._receiver_task = asyncio.create_task(self._receiver_loop())
        self._evaluation_task = asyncio.create_task(self._evaluation_loop())
        
        # Create reliable channel
        reliable_channel = self.create_channel('reliable')
        await reliable_channel.start()
        
        # Create unreliable channel
        unreliable_channel = self.create_channel('unreliable')
        
        # Store channel references as attributes for easy access
        self.reliable_channel = reliable_channel
        self.unreliable_channel = unreliable_channel
        
        # Set up default message handlers
        async def on_reliable_message(data):
            print(f"Reliable channel received: {data}")
        async def on_unreliable_message(data):
            print(f"Unreliable channel received: {data}")
        
        reliable_channel.on_message = on_reliable_message
        unreliable_channel.on_message = on_unreliable_message
    
    async def close(self):
        """Close the connection and all channels"""
        self.running = False
        if self._receiver_task:
            self._receiver_task.cancel()
            try:
                await self._receiver_task
            except asyncio.CancelledError:
                pass
        if self._evaluation_task:
            self._evaluation_task.cancel()
            try:
                await self._evaluation_task
            except asyncio.CancelledError:
                pass
        
        for channel in self.channels.values():
            await channel.close()
        
        # Call onClose callback
        if self.onClose:
            try:
                await self.onClose()
            except Exception as e:
                print(f"Error in onClose callback: {e}")
        
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
        
        packet = self.connection._encode_packet(self.channel_id, seq_num, data)
        self.connection._send_raw(packet)
    
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
