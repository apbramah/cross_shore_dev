import uasyncio as asyncio
import network
import socket
import time
import struct

# ---- Configuration ----
LISTEN_PORT = 8888
FORWARD_IP = "192.168.1.123"
BUFFER_SIZE = 1024

def decode_udp_packet(data: bytes):
    """Decode a 16-byte control packet into fields."""
    if len(data) < 16:
        print("Packet too short:", len(data))
        return None

    if data[0] != 0xDE or data[1] != 0xFD:
        print("Invalid header:", data[0:2])
        return None

    zoom, focus, iris, pan, pitch, tilt, _ = struct.unpack(">6H2s", data[2:16])
    return {
        "zoom": zoom,
        "focus": focus,
        "iris": iris,
        "pan": pan,
        "pitch": pitch,
        "tilt": tilt,
    }


async def forward(forward_addr):
    # ---- Init Ethernet ----
    nic = network.WIZNET5K()
    nic.active(True)
    print("Bringing up Ethernet...")

    while not nic.isconnected():
        print(".", end="")
        time.sleep(0.5)

    print("\nEthernet connected:", nic.ifconfig())

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)
    sock.bind(("0.0.0.0", LISTEN_PORT))
    print(f"Listening for UDP packets on port {LISTEN_PORT}")

    while True:
        try:
            data, addr = sock.recvfrom(BUFFER_SIZE)  # non-blocking
        except OSError:
            # No data available
            await asyncio.sleep(0)  # yield to scheduler
            continue

        fields = decode_udp_packet(data)
        if fields:
            print("UDP <--", fields)

        # Forward packet
        sock.sendto(data, (forward_addr, LISTEN_PORT))


async def main():
    await asyncio.gather(
        forward(FORWARD_IP)
    )

if __name__ == "__main__":
    asyncio.run(main())
