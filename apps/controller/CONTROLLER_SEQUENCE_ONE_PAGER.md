# Controller End - One-Page Sequence Diagram

## Runtime Sequence (Current `mvp_ui_3` stack)

```mermaid
sequenceDiagram
    autonumber
    participant GP as USB Gamepad (Encoders)
    participant UI as mvp_ui_3.html
    participant SWS as Slow WS Bridge (:8766)
    participant FBridge as ADC Bridge (mvp_bridge_adc.py)
    participant CDC as USB CDC ADC Stream
    participant Files as Runtime JSON Files
    participant Head as Head Controller

    Note over UI,SWS: Slow/control plane
    UI->>SWS: WS connect
    SWS-->>UI: STATE {slow_controls, shaping, network, telemetry, calibration...}
    GP->>UI: Button edges (CW/CCW/SW)
    UI->>SWS: SELECT_HEAD / SET_SLOW_CONTROL / SET_SHAPING
    UI->>SWS: WIFI_* / SET_*_CONFIG / CALIBRATE_INPUTS
    SWS->>Files: Persist selected/state/defaults/network
    loop every 0.5s
      SWS->>Head: UDP SLOW_CMD (8890) for full key set
    end
    Head-->>SWS: UDP SLOW_ACK + SLOW_TELEM
    SWS-->>UI: STATE updates (apply status + telemetry + connection)

    Note over CDC,FBridge: Fast motion plane
    CDC->>FBridge: ADCv1,seq,teensy_us,x,y,z,rx,ry,rz
    FBridge->>Files: Read selected_head + shaping profile
    FBridge->>FBridge: Normalize + shape + deadband/expo/gain/invert
    FBridge->>Head: UDP FAST v2 (8888): zoom/focus/iris/yaw/pitch/roll

    Note over UI,FBridge: Calibration side channel
    UI->>SWS: CALIBRATE_INPUTS
    SWS->>Files: Write calibration request JSON
    FBridge->>Files: Read request, sample median centers, write result JSON
    SWS-->>UI: Calibration status/result in STATE
```

## Message/API Snapshot

- Slow WS API (`:8766`)
  - Client -> server:
    - `REQUEST_STATE`, `SELECT_HEAD`, `SET_SLOW_CONTROL`
    - `SET_SHAPING`, `SAVE_USER_DEFAULTS`, `RESET_USER_DEFAULTS`
    - `SET_PI_LAN_CONFIG`, `SET_HEAD_CONFIG`, `APPLY_NETWORK_CONFIG`, `FACTORY_RESET_NETWORK`
    - `WIFI_SCAN`, `WIFI_CONNECT`, `WIFI_DISCONNECT`, `WIFI_STATUS`
    - `CALIBRATE_INPUTS`
  - Server -> client:
    - `STATE`
    - result envelopes (`*_RESULT`, `*_SAVED`, `SHAPING_APPLIED`, `CALIBRATE_INPUTS_ACCEPTED`)
- Slow UDP API (`8890`)
  - Packet type: `PKT_SLOW_CMD (0x20)` + ACK/telemetry ingest path.
- Fast UDP API (`8888`)
  - Packet format: v2 fast packet `<BBBHhHHHHHH>` at configured stream rate.

## Key Integration Point

- `heads.json` + `mvp_selected_head.json` remain the shared targeting contract:
  - slow bridge owns selection persistence,
  - ADC fast bridge follows same selection for fast-path routing.
