import uasyncio as asyncio
import machine
import network

# ==== CONFIGURATION ====
TCP_PORT   = 8080
UART_ID    = 0           # 0 or 1
UART_BAUD  = 115200
# ========================

# Setup UART
uart = machine.UART(UART_ID, UART_BAUD)

# Setup Ethernet
nic = network.WIZNET5K()
nic.active(True)

print("Waiting for Ethernet link...")
while not nic.isconnected():
    pass
print("Ethernet connected:", nic.ifconfig())

# ==== CONFIGURATION ====
TEST_MODE = False   # True = test mode, False = UART bridge
# ========================

def hexdump(data: bytes) -> str:
    """Return a hex dump string for given bytes."""
    return " ".join(f"{b:02X}" for b in data)

async def handle_client(reader, writer):
    print("Client connected")

    if TEST_MODE:
        # --- TEST MODE: no UART, respond to TCP packets ---
        while True:
            try:
                data = await reader.read(100)
            except Exception as e:
                print("TCP read error:", e)
                break
            if not data:
                print("TCP client disconnected")
                break

            print("TCP received:", hexdump(data))

            if data[0] == 0x24:
                continue

            cmd = data[1]
            if cmd == 0x56:
                response = bytearray([0x3e, 0x56, 0x12, 0x68, 0x24, 0x92, 0xa, 0x2c, 0xbf, 0xfd, 0x0, 0x0, 0x0, 0x0, 0x0, 0x95, 0x2, 0x0, 0x0, 0x0, 0x0, 0x0, 0x3f])
            elif cmd == 20:
                response = bytearray([0x3e, 0x14, 0x1, 0x15, 0x20, 0x20])
            else:
                response = bytearray([0x3e, 0x43, 0x1, 0x44, cmd, cmd])

            print("TCP send:", hexdump(response))

            try:
                writer.write(response)
                await writer.drain()
            except Exception as e:
                print("TCP write error:", e)
                break

    else:
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
                print("TCP -> UART:", hexdump(data))
                uart.write(data)

        task1 = asyncio.create_task(uart_to_tcp_task())
        task2 = asyncio.create_task(tcp_to_uart_task())
        await asyncio.gather(task1, task2)

    writer.close()
    await writer.wait_closed()
    print("Client handler finished")

async def main():
    server = await asyncio.start_server(handle_client, "0.0.0.0", TCP_PORT)
    print("TCP server listening on port", TCP_PORT)

    # Keep running forever
    while True:
        await asyncio.sleep(3600)  # sleep in long chunks


try:
    asyncio.run(main())
finally:
    asyncio.new_event_loop()
