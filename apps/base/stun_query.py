"""
STUN query functionality for discovering server-reflexive (srflx) candidates.
"""
import struct
import random
try:
    import uasyncio as asyncio
    import usocket as socket
    import utime as time_module
    MICROPYTHON = True
except ImportError:
    import asyncio
    import socket
    import time as time_module
    MICROPYTHON = False

# STUN message types
STUN_BINDING_REQUEST = 0x0001
STUN_BINDING_RESPONSE = 0x0101

# STUN attributes
STUN_ATTR_XOR_MAPPED_ADDRESS = 0x0020

# STUN server
STUN_SERVER_HOST = "stun.l.google.com"
STUN_SERVER_PORT = 19302

# STUN Magic Cookie (RFC 5389)
STUN_MAGIC_COOKIE = 0x2112A442

stun_addr = None

def get_stun_addr():
    global stun_addr

    # Apparently, DNS resolution is expensive on Pico, so we cache the address.
    if not stun_addr:
        try:
            stun_addr = socket.getaddrinfo(STUN_SERVER_HOST, STUN_SERVER_PORT)[0][-1]
        except Exception as e:
            print(f"Error resolving STUN address: {e}")

    return stun_addr

def create_stun_binding_request():
    """Create a STUN Binding Request message"""
    # Message Type: Binding Request (0x0001)
    msg_type = STUN_BINDING_REQUEST
    # Message Length: 0 (no attributes)
    msg_length = 0
    # Magic Cookie (RFC 5389)
    magic_cookie = STUN_MAGIC_COOKIE
    # Transaction ID (12 random bytes)
    transaction_id = struct.pack('!12B', *[random.randint(0, 255) for _ in range(12)])
    
    # Build message header
    message = struct.pack('!HHI', msg_type, msg_length, magic_cookie) + transaction_id
    return message, transaction_id

def parse_stun_response(data, expected_transaction_id):
    """Parse STUN Binding Response and extract XOR-MAPPED-ADDRESS"""
    if len(data) < 20:  # Minimum STUN header size
        return None
    
    # Parse header
    msg_type, msg_length, magic_cookie = struct.unpack('!HHI', data[0:8])
    transaction_id = data[8:20]
    
    # Verify it's a Binding Success Response
    if msg_type != STUN_BINDING_RESPONSE:
        return None
    
    # Verify magic cookie
    if magic_cookie != STUN_MAGIC_COOKIE:
        return None
    
    # Verify transaction ID matches
    if transaction_id != expected_transaction_id:
        return None
    
    # Parse attributes
    offset = 20
    while offset < len(data):
        if offset + 4 > len(data):
            break
        
        attr_type, attr_length = struct.unpack('!HH', data[offset:offset+4])
        offset += 4
        
        if attr_type == STUN_ATTR_XOR_MAPPED_ADDRESS:
            if offset + attr_length > len(data):
                break
            
            # Parse XOR-MAPPED-ADDRESS
            # Format: reserved (1 byte) + family (1 byte) + port (2 bytes) + address (4 or 16 bytes)
            attr_data = data[offset:offset+attr_length]
            if len(attr_data) < 8:
                break
            
            reserved, family = struct.unpack('!BB', attr_data[0:2])
            if family == 0x01:  # IPv4
                if len(attr_data) < 8:
                    break
                xor_port, xor_address = struct.unpack('!HI', attr_data[2:8])
                # XOR decode with magic cookie (port uses high 16 bits, address uses full 32 bits)
                port = xor_port ^ (STUN_MAGIC_COOKIE >> 16)
                address_int = xor_address ^ STUN_MAGIC_COOKIE
                # Convert to IP string (equivalent to socket.inet_ntoa)
                address = ".".join(str((address_int >> shift) & 0xFF) for shift in (24, 16, 8, 0))
                return (address, port)
        
        # Move to next attribute (pad to 4-byte boundary)
        offset += attr_length
        offset = (offset + 3) & ~3  # Round up to 4-byte boundary
    
    return None

async def query_stun_server(sock, timeout=0.25):
    """
    Query STUN server to discover server-reflexive candidate.
    
    Args:
        sock: The UDP socket to use (already bound)
        timeout: Timeout in seconds (default 0.25)
    
    Returns:
        List of srflx candidates [{"type": "srflx", "address": str, "port": int}]
        or empty list if query fails or times out
    """
    srflx_candidates = []
    
    try:
        # Create STUN Binding Request
        request, transaction_id = create_stun_binding_request()
        
        # Get original socket blocking state
        original_blocking = None
        if hasattr(sock, 'getblocking'):
            try:
                original_blocking = sock.getblocking()
            except:
                pass
        
        # Send request to STUN server
        try:
            if MICROPYTHON:
                sock.setblocking(True)
            sock.sendto(request, get_stun_addr())
        except Exception as e:
            print(f"Error sending STUN request: {e}")
            # Restore socket state
            if original_blocking is not None and MICROPYTHON:
                try:
                    sock.setblocking(original_blocking)
                except:
                    pass
            return srflx_candidates
        
        # Receive response with timeout
        start_time = time_module.time()
        
        try:
            if MICROPYTHON:
                # MicroPython: use timeout-based approach
                sock.settimeout(timeout)
                try:
                    data, addr = sock.recvfrom(2048)
                    elapsed = time_module.time() - start_time
                    if elapsed <= timeout:
                        # Parse response
                        result = parse_stun_response(data, transaction_id)
                        if result:
                            srflx_address, srflx_port = result
                            srflx_candidates.append({
                                "type": "srflx",
                                "address": srflx_address,
                                "port": srflx_port
                            })
                            print(f"STUN query successful: srflx candidate {srflx_address}:{srflx_port}")
                        else:
                            print("STUN response parsing failed")
                except OSError as e:
                    # Check if it's a timeout error (errno 110 = ETIMEDOUT)
                    errno = getattr(e, 'errno', None)
                    error_str = str(e).lower()
                    if errno == 110 or 'timed out' in error_str or 'timeout' in error_str:
                        print(f"STUN query timed out after {timeout}s")
                    else:
                        print(f"Error receiving STUN response: {e}")
                except Exception as e:
                    # Catch any other exceptions (including socket.timeout if it exists)
                    error_str = str(e).lower()
                    if 'timeout' in error_str:
                        print(f"STUN query timed out after {timeout}s")
                    else:
                        print(f"Error receiving STUN response: {e}")
                except Exception as e:
                    print(f"Error receiving STUN response: {e}")
            else:
                # CPython: use asyncio
                loop = asyncio.get_event_loop()
                # Ensure socket is non-blocking for asyncio
                sock.setblocking(False)
                try:
                    data, addr = await asyncio.wait_for(
                        loop.sock_recvfrom(sock, 2048),
                        timeout=timeout
                    )
                    # Parse response
                    result = parse_stun_response(data, transaction_id)
                    if result:
                        srflx_address, srflx_port = result
                        srflx_candidates.append({
                            "type": "srflx",
                            "address": srflx_address,
                            "port": srflx_port
                        })
                        print(f"STUN query successful: srflx candidate {srflx_address}:{srflx_port}")
                    else:
                        print("STUN response parsing failed")
                except asyncio.TimeoutError:
                    print(f"STUN query timed out after {timeout}s")
                except Exception as e:
                    print(f"Error receiving STUN response: {e}")
        finally:
            # Restore original blocking state
            if original_blocking is not None:
                try:
                    sock.setblocking(original_blocking)
                except:
                    pass
            elif not MICROPYTHON:
                # CPython: restore to non-blocking (default for asyncio)
                try:
                    sock.setblocking(False)
                except:
                    pass
    
    except Exception as e:
        print(f"Error in STUN query: {e}")
    
    return srflx_candidates

