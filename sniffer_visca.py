import uasyncio as asyncio
from machine import Pin, UART

# VISCA constants
VISCA_END = 0xFF

# UART configuration
uart0 = UART(0, baudrate=9600, tx=Pin(0), rx=Pin(1))  # VISCA default = 9600
uart1 = UART(1, baudrate=9600, tx=Pin(4), rx=Pin(5))

async def visca_monitor(uart, name="UART"):
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
async def send_visca_inquiry(uart, interval=2.0):
    inquiry = bytearray([0x81, 0x09, 0x04, 0x47, 0xFF])  # Zoom Position Inquiry
    while True:
        uart.write(inquiry)
        #print("Sent VISCA Zoom Inquiry:", [hex(x) for x in inquiry])
        await asyncio.sleep(interval)

async def main():
    await asyncio.gather(
        visca_monitor(uart0, "UART0"),
        visca_monitor(uart1, "UART1"),
        send_visca_inquiry(uart0, interval=5.0)
    )

asyncio.run(main())
