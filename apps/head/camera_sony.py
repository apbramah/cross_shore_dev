from machine import UART

UART_ID = 1           # 0 or 1
UART_BAUD = 9600

class CameraSony:
    def __init__(self):
        self.uart = UART(UART_ID, UART_BAUD)
