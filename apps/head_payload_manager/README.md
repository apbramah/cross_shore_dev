# Head Payload Manager

Second Pico firmware that owns payload I/O:

- Head link UART (`GP0`/`GP1`) via RS232 level shifter
- Canon lens dedicated UART path (`UART1` `GP8`/`GP9`, `19200 8E1`)
- Fuji lens dedicated UART path (PIO software UART on `GP13`/`GP14`, `38400 8N1`)
- RC servo output (windscreen wiper)

## Boot policy

Peripheral scan order is:

1. Canon
2. Fuji
3. Sony VISCA (hook)
4. Proton Camera (hook, includes GPIO direction control)
5. None

## Files

- `main.py` - command loop and routing
- `pm_link_proto.py` - newline-delimited JSON framing
- `pm_link_uart.py` - head link transport
- `canon_port.py` - Canon bus adapter (initial skeleton)
- `fuji_port.py` - Fuji bus adapter (initial skeleton)
- `sony_visca_port.py` - Sony VISCA hook (probe/control API scaffold)
- `proton_camera_port.py` - Proton hook (includes UART/485 direction GPIO hook; current main mapping uses `dir_pin=GP12`)
- `soft_uart_pio.py` - PIO software UART helper
- `servo_wiper.py` - PWM servo driver
