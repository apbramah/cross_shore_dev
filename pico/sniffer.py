import uasyncio as asyncio
import udp
import bgc
import visca

FORWARD_IP = "192.168.1.123"

async def main(mode):
    # Always include the UDP forwarder
    tasks = udp.get_tasks(FORWARD_IP)

    # Configure UARTs based on mode
    if mode == "bgc_only":
        tasks += bgc.get_tasks(0, "-->", test=True)
        tasks += bgc.get_tasks(1, "<--", test=True)
    elif mode == "visca_only":
        tasks += visca.get_tasks(0, "-->", test=True)
        tasks += visca.get_tasks(1, "<--", test=True)
    elif mode == "both":
        tasks += bgc.get_tasks(0, "-->", test=True)
        tasks += visca.get_tasks(1, "-->", test=True)
    else:
        print("Invalid mode. Use 'bgc_only', 'visca_only', or 'both'.")
        return

    # Run all tasks concurrently
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main("both"))
