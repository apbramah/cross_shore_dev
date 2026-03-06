# Main Runtime Flow

This diagram shows the programs and helpers involved when `main.py` runs, including the Canon path when slow command `lens_select` switches to Canon.

Static image artifact: `main_runtime_flow.png`  
Mermaid source artifact: `main_runtime_flow.mmd`

```mermaid
flowchart TD
    A[Boot main py] --> B[Init hardware and ethernet]
    B --> C[Create BGC from bgc py]
    B --> D[Create LensController default fuji]

    D --> E[LensSerial UART transport]
    D --> F[CanonLens helper loaded]
    D --> G[FujiLens helper active at startup]

    G --> H[FujiCalibration runtime logic]
    G --> I[Fuji protocol frame builders]

    A --> J[Apply fuji ownership once]
    A --> K[Bind UDP sockets fast 8888 slow 8890]

    K --> L{Main loop}
    L --> M[poll_slow_command_once]
    M --> N[apply_slow_command]
    N --> D
    N --> C
    N --> O{lens select key}
    O -->|canon| P[set lens type canon]
    P --> F
    F --> Q[Canon protocol frames]
    Q --> X[Lens UART writes]
    O -->|fuji| R[set lens type fuji]
    R --> G

    L --> S[recv_latest_fast_packet]
    S --> T{fast channel mode}
    T -->|v2| U[decode_fast_packet_v2 in main py]
    T -->|legacy| V[BGC decode_udp_packet]

    U --> W[control fields]
    V --> W

    W --> Y{slow motors on}
    Y -->|yes| Z[map YPR to speed]
    Z --> AA[BGC send joystick control]

    W --> AB[apply zoom focus iris inputs]
    AB --> D
    D -->|active fuji| G
    D -->|active canon| F

    F --> Q
    G --> H
    H --> I
    I --> X

    L --> AC[lens periodic keepalive watchdog control tx]
    AC --> D
```
