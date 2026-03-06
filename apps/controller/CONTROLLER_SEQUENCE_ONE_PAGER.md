# Controller End - One-Page Sequence Diagram

## Runtime Sequence (Slow + Fast Split)

```mermaid
sequenceDiagram
    autonumber
    participant GP as USB Gamepad (Encoders)
    participant UI as mvp_ui_2.html
    participant SWS as Slow WS Bridge (:8766)
    participant FBridge as ADC Bridge (mvp_bridge_adc.py)
    participant CDC as USB CDC ADC Stream
    participant HeadFile as mvp_selected_head.json
    participant Head as Head Controller

    Note over UI,SWS: Slow control plane (encoder/menu events)
    UI->>SWS: WS connect
    SWS-->>UI: STATE {heads, selected, slow_controls}
    GP->>UI: Button edges (CW/CCW/SW)
    UI->>SWS: SELECT_HEAD {index}
    SWS->>HeadFile: Persist selected_index
    SWS-->>UI: SELECTED {selected}
    UI->>SWS: SET_SLOW_CONTROL {key, value}
    SWS-->>UI: SLOW_APPLIED {key, value}
    loop every 0.5s
      SWS->>Head: UDP SLOW_CMD (8890): motors_on, gyro_heading_correction
    end
    Note over SWS,Head: gyro_heading_correction also sent immediately on apply

    Note over CDC,FBridge: Fast motion plane (USB ADC -> UDP fast)
    CDC->>FBridge: ADCv1,seq,teensy_us,x,y,z,rx,ry,rz
    FBridge->>FBridge: Parse + clamp raw ADC [0..4095]
    FBridge->>FBridge: Shape -> normalized axes [-1..1]
    FBridge->>HeadFile: Read selected_index (poll)
    FBridge->>Head: UDP FAST v2 (8888): seq,zoom,focus,iris,yaw,pitch,roll
```

## Message/API Snapshot

- Slow WS API (`:8766`)
  - Client -> server: `SELECT_HEAD`, `SET_SLOW_CONTROL`
  - Server -> client: `STATE`, `SELECTED`, `SLOW_APPLIED`
- Slow UDP API (`8890`)
  - Packet type: `PKT_SLOW_CMD (0x20)`
  - Active keys in current slow bridge loop: `motors_on`, `gyro_heading_correction`
- Fast UDP API (`8888`)
  - Packet format: v2 fast packet `<BBBHhHHHHHH>`
  - Carries axis/motion controls continuously at configured rate (default ~50 Hz)

## Key Integration Point

- `mvp_selected_head.json` is the shared contract between planes:
  - Slow bridge writes selected head index.
  - ADC fast bridge follows that index for retargeting fast UDP output.
