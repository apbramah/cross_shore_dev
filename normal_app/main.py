import uasyncio as asyncio
import network
import time
import socket
import struct
import uwebsockets.client
from machine import Pin, UART

ota_present = False
try:
    import ota
    ota_present = True
except Exception as e:
    print("Couldn't import ota:", e)

import json
import machine
import ubinascii
from uwebsockets.protocol import ConnectionClosed

REGISTRY_PATH = "/registry.json"

def get_device_name():
    try:
        with open(REGISTRY_PATH) as f:
            data = json.load(f)
        name = data.get("name")
        if name:
            return name
    except Exception as e:
        print("Error reading registry:", e)
    data = {"name": "unknown"}
    try:
        with open(REGISTRY_PATH, "w") as f:
            json.dump(data, f)
    except Exception as e:
        print("Error writing default registry:", e)
    return "unknown"

def set_device_name(name):
    try:
        data = {"name": name}
        with open(REGISTRY_PATH, "w") as f:
            json.dump(data, f)
    except Exception as e:
        print("Error updating registry:", e)

def ota_trust():
    if ota_present:
        ota.trust()

# ==== CONFIGURATION ====
TCP_PORT   = 8080
TCP_PORT2   = 8081
UART_ID    = 0           # 0 or 1
UART_ID1    = 1           # 0 or 1
UART_BAUD  = 115200
UART_BAUD1  = 9600
LISTEN_PORT_JOYSTICK = 8888
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

async def handle_client(reader, writer):
    print("Client connected")

    # --- NORMAL UART BRIDGE MODE ---
    async def uart_to_tcp_task():
        while True:
            if uart.any():
                data = uart.read()
                if data:
                    try:
                        writer.write(data)
                        await writer.drain()
                    except Exception as e:
                        print("TCP write error:", e)
                        break
            await asyncio.sleep_ms(5)

    async def tcp_to_uart_task():
        while True:
            try:
                data = await reader.read(100)
            except Exception as e:
                print("TCP read error:", e)
                break
            if not data:
                print("TCP client disconnected")
                break
            uart.write(data)

    task1 = asyncio.create_task(uart_to_tcp_task())
    task2 = asyncio.create_task(tcp_to_uart_task())
    await asyncio.gather(task1, task2)

    writer.close()
    await writer.wait_closed()
    print("Client handler finished")

async def handle_client2(reader, writer):
    print("Client connected")

    # --- NORMAL UART BRIDGE MODE ---
    async def uart_to_tcp_task():
        while True:
            if uart1.any():
                data = uart1.read()
                if data:
                    try:
                        writer.write(data)
                        await writer.drain()
                    except Exception as e:
                        print("TCP write error:", e)
                        break
            await asyncio.sleep_ms(5)

    async def tcp_to_uart_task():
        while True:
            try:
                data = await reader.read(100)
            except Exception as e:
                print("TCP read error:", e)
                break
            if not data:
                print("TCP client disconnected")
                break
            uart1.write(data)

    task1 = asyncio.create_task(uart_to_tcp_task())
    task2 = asyncio.create_task(tcp_to_uart_task())
    await asyncio.gather(task1, task2)

    writer.close()
    await writer.wait_closed()
    print("Client handler finished")

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

async def auto_cam():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)
    sock.bind(("0.0.0.0", LISTEN_PORT_AUTOCAM))
    print("Listening for auto_cam UDP packets on port", LISTEN_PORT_AUTOCAM)

    while True:
        try:
            data, addr = sock.recvfrom(BUFFER_SIZE)  # non-blocking
        except OSError:
            # No data available
            await asyncio.sleep(0)  # yield to scheduler
            continue

        if mode != "auto_cam":
            continue

        fields = decode_udp_packet(data)
        if fields:
            yaw = struct.pack(">H", fields['yaw'])
            pitch = struct.pack(">H", fields['pitch'])
            roll = struct.pack(">H", fields['roll'])

            payload = bytearray([0x42, 0x08, 0x02, 0x00]) + pitch + bytearray([0x02, 0x00]) + roll + bytearray([0x02, 0x00]) + yaw
            packet = create_packet(CMD_CONTROL_EXT, payload)
            print("UART autocam -->", hexdump(packet))
            uart.write(packet)

async def server_task():
    await asyncio.start_server(handle_client, "0.0.0.0", TCP_PORT)
    print("TCP server listening on port", TCP_PORT)

async def server_task2():
    await asyncio.start_server(handle_client2, "0.0.0.0", TCP_PORT2)
    print("TCP server listening on port", TCP_PORT2)

ws = None

import builtins

# Get the unique ID as bytes
uid_bytes = machine.unique_id()

# Convert to hex string
uid_hex = ubinascii.hexlify(uid_bytes).decode()

# print function that also sends to websocket if available
def ws_print(*args, **kwargs):
    original_print(*args, **kwargs)

    global ws
    if ws and ws.open:
        sep = kwargs.get("sep", " ")
        end = kwargs.get("end", "\n")
        message = sep.join(str(arg) for arg in args) + end

        data = {"type": "PRINTF",
                "uid": uid_hex,
                "message": message.strip()}
        ws.send(json.dumps(data))

# Override the built-in print function
original_print = builtins.print
builtins.print = ws_print

async def websocket_client():
    global mode, ws
    try:
        print("Connecting to WebSocket server...")
        ws = uwebsockets.client.connect(WS_URL)
        ws.sock.setblocking(False)

        device_name = get_device_name()

        data = {"type": "HEAD_CONNECTED",
                "uid": uid_hex,
                "name": device_name}
        ws.send(json.dumps(data))  # announce as device
        print("Connected!")
        data = {"type": "CURRENT_MODE",
                "uid": uid_hex,
                "mode": mode}
        ws.send(json.dumps(data))

        while True:

            # Check for incoming messages
            try:
                msg = ws.recv()
            except ConnectionClosed:
                print("WebSocket ConnectionClosed")
                break

            # None means a close frame; empty string means "no data yet" on non-blocking socket
            if msg is None:
                print("WebSocket server closed")
                break
            if msg == "":
                await asyncio.sleep(0)
                continue

            print("Received:", msg)
            try:
                my_dict = json.loads(msg)
                if my_dict["type"] == "SET_MODE":
                    if my_dict['mode'] == "auto_cam":
                        led.value(1)
                        mode = "auto_cam"
                        data = {"type": "CURRENT_MODE",
                                "uid": uid_hex,
                                "mode": mode}
                        ws.send(json.dumps(data))
                    elif my_dict['mode'] == "joystick":
                        led.value(0)
                        mode = "joystick"

                        payload = bytearray([0x01, 0x26, 0x00, 0x15, 0x00, 0x00])
                        packet = create_packet(CMD_SET_ADJ_VARS_VAL, payload)
                        uart.write(packet)

                        # When switching to joystick mode, ensure that the angle mode is disabled
                        payload = bytearray([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
                        packet = create_packet(CMD_CONTROL, payload)
                        uart.write(packet)

                        data = {"type": "CURRENT_MODE",
                                "uid": uid_hex,
                                "mode": mode}
                        ws.send(json.dumps(data))
                    elif my_dict['mode'] == "fixed":
                        led.value(0)
                        mode = "fixed"

                        data = {"type": "CURRENT_MODE",
                                "uid": uid_hex,
                                "mode": mode}
                        ws.send(json.dumps(data))
                elif my_dict["type"] == "REBOOT":
                    print("Rebooting as requested...")
                    time.sleep(1)
                    machine.reset()
                elif my_dict["type"] == "SET_NAME":
                    new_name = my_dict.get("name")
                    if new_name:
                        set_device_name(new_name)
            except Exception as e:
                print("Error processing message:", e)

            ota_trust()
            await asyncio.sleep(0)

    except Exception as e:
        print("WebSocket error:", e)
    finally:
        if ws:
            ws.close()
            print("Connection closed")

async def websocket():
    while True:
        await websocket_client()
        print("Reconnecting in 1 seconds...")
        await asyncio.sleep(1)

async def as_main():
    tasks = [server_task(), server_task2(), joystick(), auto_cam(), websocket()]

    # Run all tasks concurrently
    await asyncio.gather(*tasks)

def main():
    try:
        asyncio.run(as_main())
    finally:
        asyncio.new_event_loop()

if __name__ == "__main__":
    # Need network setup here
    main()
