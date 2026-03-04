# Controller End - Executive Summary

## Current Runtime Shape (What is live now)

- The controller side is currently split into two independent paths:
  - **Slow control path (UI-driven):** USB gamepad encoder buttons -> browser (`mvp_ui_2.html`) -> WebSocket slow bridge (`mvp_slow_bridge.py`, port `8766`) -> UDP slow commands to head (`port_slow_cmd`, default `8890`).
  - **Fast motion path (USB ingest):** USB CDC axis stream (`ADCv1` frames) -> ADC bridge (`mvp_bridge_adc.py`) -> fast UDP control packets to head (`port_fast`, default `8888`).
- Head targeting is coordinated via `mvp_selected_head.json`; slow bridge writes selected head index, ADC bridge follows it when `--host` is not overridden.
- `mvp_ui_2.html` is a **slow-control console**, not a fast-axis sender.

## End-to-End Data Flow

1. **Operator input (USB gamepad encoders)**  
   Browser reads `navigator.getGamepads()[0].buttons` and maps 15 buttons as five encoder lanes (`CW/CCW/SW` per lane).
2. **UI state and commands**  
   Encoder lane logic drives UI focus/edit/apply for:
   - `SELECT_HEAD`
   - `SET_SLOW_CONTROL` for `motors_on` and `gyro_heading_correction`
3. **Slow message server (`mvp_slow_bridge.py`)**  
   Receives WebSocket commands, persists state (`mvp_slow_state.json`), and emits UDP slow command packets every `0.5s` (plus immediate send for gyro updates).
4. **Fast axis ingest (`mvp_bridge_adc_ingest.py`)**  
   Reads Teensy CDC lines in format:  
   `ADCv1,<seq>,<teensy_us>,<x>,<y>,<z>,<rx>,<ry>,<rz>`
5. **Number shaping (`mvp_bridge_adc_shape.py`)**  
   Converts raw `0..4095` to `[-1.0..1.0]`, then applies per-axis: center offset, deadband, expo, LPF, slew, invert, gain, clamp.
6. **Fast output (`mvp_bridge_adc_output.py`)**  
   Sends v2 fast UDP packets at configured rate (default `50 Hz`) to selected head fast port (`8888`).

## Number Handling (Important)

- **Encoder/buttons path:** edge-triggered digital events only; no analog math.
- **Slow values encoding:**
  - `motors_on`: bool -> `0/1`
  - `gyro_heading_correction`: int passthrough (defaults to `0x1500` if invalid)
  - slow packet value field is a signed 32-bit int (`build_slow_cmd_packet`).
- **Fast values encoding:**
  - USB raw ADC `0..4095` -> normalized float `[-1..1]`
  - shaped float axes -> packet fields:
    - `yaw/pitch/roll/focus/iris`: mapped to unsigned `u16` via center `32768`
    - `zoom`: signed `s16` (scaled by `zoom_gain`)

## Slow Server API (`mvp_slow_bridge.py`, WS `:8766`)

### Client -> Server

- `{"type":"SELECT_HEAD","index":<int>}`
- `{"type":"SET_SLOW_CONTROL","key":"motors_on","value":0|1}`
- `{"type":"SET_SLOW_CONTROL","key":"gyro_heading_correction","value":<int>}`

### Server -> Client

- `STATE` (on connect): heads list, selected index, slow_controls snapshot
- `SELECTED`: confirms selected head index
- `SLOW_APPLIED`: confirms applied slow key/value

### Server -> Head (UDP)

- Port: `port_slow_cmd` in `heads.json` (fallback `8890`)
- Packet type: `PKT_SLOW_CMD (0x20)`
- Keys currently transmitted by this bridge loop:
  - `motors_on`
  - `gyro_heading_correction`

## Fast Server / Fast Path API

### Runtime producer now (ADC bridge)

- Producer: `mvp_bridge_adc.py` + `mvp_bridge_adc_output.py`
- Transport: UDP fast channel to `port_fast` (fallback `8888`)
- Packet: v2 fast packet (`build_fast_packet_v2`)
  - Struct: `<BBBHhHHHHHH>`
  - Fields: `magic, ver, type, seq, zoom, focus, iris, yaw, pitch, roll, reserved`

### Alternate WebSocket bridge (available, not used by `mvp_ui_2.html`)

- `mvp_bridge.py` on WS `:8765` accepts `GAMEPAD` + control messages and emits fast UDP + slow UDP.
- This is the path used by `mvp_ui.html`/`ui_dev`, not by `mvp_ui_2.html`.

## Practical Conclusion

- You currently have a **clean split**:
  - **Slow:** encoder-button UX in HTML -> slow bridge (`8766`) -> UDP `8890`
  - **Fast:** USB ADC/jpysticks-style axis ingest in Python -> fast UDP `8888`
- The integration pivot is already in place: `mvp_selected_head.json` links both paths to the same selected head target.
