import uasyncio as asyncio
import udp
import bgc
import visca
from machine import Pin, UART

FORWARD_IP = "192.168.1.123"

async def main(mode):
    # Always include the UDP forwarder
    tasks = [udp.forward(FORWARD_IP)]

    # Configure UARTs based on mode
    if mode == "bgc_only":
        uart0 = UART(0, baudrate=115200, tx=Pin(0), rx=Pin(1))
        uart1 = UART(1, baudrate=115200, tx=Pin(4), rx=Pin(5))
        tasks += [
            bgc.monitor(uart0, "BGC -->"),
            bgc.monitor(uart1, "BGC <--"),
            bgc.test(uart0, interval=0.01),
            bgc.test(uart1, interval=0.01)
        ]
    elif mode == "visca_only":
        uart0 = UART(0, baudrate=9600, tx=Pin(0), rx=Pin(1))
        uart1 = UART(1, baudrate=9600, tx=Pin(4), rx=Pin(5))
        tasks += [
            visca.monitor(uart0, "VISCA -->"),
            visca.monitor(uart1, "VISCA <--"),
            visca.test(uart0, interval=0.01),
            visca.test(uart1, interval=0.01)
        ]
    elif mode == "both":
        uart0 = UART(0, baudrate=115200, tx=Pin(0), rx=Pin(1))
        uart1 = UART(1, baudrate=9600, tx=Pin(4), rx=Pin(5))
        tasks += [
            bgc.monitor(uart0, "BGC -->"),
            visca.monitor(uart1, "VISCA -->"),
            bgc.test(uart0, interval=0.01),
            visca.test(uart1, interval=0.01)
        ]
    else:
        print("Invalid mode. Use 'bgc_only', 'visca_only', or 'both'.")
        return

    # Run all tasks concurrently
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main("both"))
