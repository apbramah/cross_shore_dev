import uasyncio as asyncio
from machine import Pin, UART

BAUDRATE = 9600

# VISCA constants
VISCA_END = 0xFF

async def monitor(uart, name="UART"):
    buffer = bytearray()
    while True:
        if uart.any():
            data = uart.read()
            if data:
                buffer.extend(data)

        # Process packets ending with 0xFF
        while True:
            try:
                end_index = buffer.index(bytes([VISCA_END]))
            except ValueError:
                break  # no full packet yet

            # Extract one VISCA packet
            packet = buffer[:end_index+1]
            buffer = buffer[end_index+1:]

            # Parse packet
            if len(packet) > 1:
                source = packet[0]
                body = packet[1:-1]
                print(f"{name} Packet from {hex(source)}: {[hex(b) for b in body]} {hex(VISCA_END)}")

        await asyncio.sleep(0.01)

# Example sender: send VISCA Inquiry (zoom position)
async def generate(uart, interval=2.0):
    inquiry = bytearray([0x81, 0x09, 0x04, 0x47, 0xFF])  # Zoom Position Inquiry
    while True:
        uart.write(inquiry)
        await asyncio.sleep(interval)

def get_tasks(uart_id, direction, test=False):
    if uart_id == 0:
        uart = UART(uart_id, baudrate=BAUDRATE, tx=Pin(0), rx=Pin(1))
    elif uart_id == 1:
        uart = UART(uart_id, baudrate=BAUDRATE, tx=Pin(4), rx=Pin(5))
    else:
        raise ValueError("Invalid UART ID")

    tasks = [monitor(uart, f"VISCA {direction}")]
    print("Listening for VISCA traffic on UART", uart_id)

    if test:
        tasks += [generate(uart)]
        print("Generating VISCA traffic on UART", uart_id)

    return tasks

async def main():
    tasks = get_tasks(0, "-->", test=True)
    tasks += get_tasks(1, "<--", test=True)

    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
