# IoD-09TH Pico Monitor (Read-Only, First Pass)

This app polls the Pico over I2C and renders the same status on:

- IoD local display
- IoD hosted web page (`/` with `/api/status`)

## Wiring (first pass)

- Pico GPIO4 -> IoD GPIO0 (SDA)
- Pico GPIO5 -> IoD GPIO2 (SCL)
- Pico GND -> IoD GND

## Boot-strap pin caution (ESP8266 IoD)

IoD GPIO0 and GPIO2 are boot-strap pins. Keep them high during boot/reset.
This app only initializes I2C in `setup()` after boot.

Reference: [IoD-09 datasheet](https://resources.4dsystems.com.au/datasheets/iod/IoD-09/#arduino-ide)

## Protocol (Pico -> IoD)

Fixed 28-byte frame:

- magic `H`,`V` (2 bytes)
- version (u8)
- payload length (u8)
- flags (u16)
- IPv4 address (4 bytes)
- subnet mask (4 bytes)
- gateway (4 bytes)
- main voltage mV (u16, `0xFFFF` = unavailable)
- aux voltage mV (u16, `0xFFFF` = unavailable)
- source age ms (u32)
- CRC16 (u16, IBM poly `0x8005`)

## Displayed fields

- IP address
- subnet mask
- gateway
- network mode (`dhcp`/`manual` when known)
- Ethernet link state
- voltage values (`N/A` if unavailable)
- comms freshness / stale state / last error

## Build dependencies

- ESP8266 Arduino core (for `Wire`, `ESP8266WiFi`, `ESP8266WebServer`)
- Optional: `GFX4dIoD9` for on-device TFT rendering
  - if absent, app still runs and outputs local view to Serial as fallback
