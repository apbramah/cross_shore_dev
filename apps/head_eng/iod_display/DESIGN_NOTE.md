# Design Note - Pico <-> IoD Read-Only Monitor (First Pass)

## Architecture summary

- Pico (`apps/head_eng/main.py`) is source of truth.
- Pico builds a compact binary status frame and publishes it via I2C slave adapter.
- IoD polls as I2C master and keeps a cached runtime status model.
- IoD renders that shared model to:
  - local display renderer
  - hosted web page/API (`/`, `/api/status`)

Transport, model, and presentation are kept separate:

- `status_protocol.*`: wire format and CRC
- `i2c_client.*`: transport polling
- `status_model.*`: freshness/error interpretation
- `display_view.*` and `web_server.*`: presentation

## Module/file layout

- Pico side:
  - `apps/head_eng/main.py`
  - `apps/head_eng/i2c_status_payload.py`
  - `apps/head_eng/i2c_status_slave.py`
- IoD side:
  - `apps/head_eng/iod_display/iod_display.ino`
  - `apps/head_eng/iod_display/status_protocol.h`
  - `apps/head_eng/iod_display/status_protocol.cpp`
  - `apps/head_eng/iod_display/i2c_client.h`
  - `apps/head_eng/iod_display/i2c_client.cpp`
  - `apps/head_eng/iod_display/status_model.h`
  - `apps/head_eng/iod_display/status_model.cpp`
  - `apps/head_eng/iod_display/display_view.h`
  - `apps/head_eng/iod_display/display_view.cpp`
  - `apps/head_eng/iod_display/web_server.h`
  - `apps/head_eng/iod_display/web_server.cpp`

## Assumptions actually used

- Pico firmware target is MicroPython app `apps/head_eng/main.py`.
- I2C wiring/pins are fixed to Pico GPIO4/5 and IoD GPIO0/2.
- Start I2C at 100 kHz.
- Current Pico network mode is treated as manual because `main.py` currently calls `nic.ifconfig(...)` with static values.
- Existing voltage fields in Pico telemetry are placeholders and may be unavailable.

## Missing information in repository

- No existing guaranteed RP2040 MicroPython I2C-slave backend/API is present in-repo.
- No existing IoD-09 app/framework existed in repo before this addition.
- No confirmed production source for head voltage measurements in `apps/head_eng`.
- No confirmed final I2C slave address convention existed in repo.

## Risks / edge cases

- RP2040 MicroPython builds may not include I2C slave support; Pico code now feature-detects and fails soft.
- ESP8266 boot-strap pins GPIO0/GPIO2 must remain high during boot; external circuitry must not pull low.
- If Pico resets or I2C bus stalls, IoD will show stale/offline using timeout policy.
- If optional display library is absent, local display uses Serial fallback only.
