# ADC Bridge Interface Contract (MVP)

This document defines the contract for the parallel ADC bridge runtime described by the ADC Bridge Pivot Plan.

## Scope

- New ADC path only: `mvp_bridge_adc*.py`
- Legacy fallback remains untouched: `mvp_bridge.py`
- Single USB cable assumption:
  - CDC serial stream carries axis samples.
  - HID gamepad carries encoder buttons to the webpage.

## Axis Mapping (Source of Truth)

Teensy ADC pin to logical axis mapping:

- `A5 -> X`
- `A7 -> Y`
- `A6 -> Z`
- `A17 -> Rx` (bridge key: `Xrotate`)
- `A16 -> Ry` (bridge key: `Yrotate`)
- `A0 -> Rz` (bridge key: `Zrotate`)

## CDC Frame Contract

Framing:

- Transport: UTF-8 text lines over CDC serial.
- Delimiter: newline (`\n`).
- One sample per line.

Required frame format:

```text
ADCv1,<seq>,<teensy_us>,<x>,<y>,<z>,<rx>,<ry>,<rz>
```

Field rules:

- `ADCv1`: literal protocol version token.
- `seq`: unsigned monotonic sequence number (wrap allowed).
- `teensy_us`: monotonic microsecond timestamp from Teensy.
- `<x>..<rz>`: raw ADC integers expected in the 12-bit range `[0, 4095]`.

Example:

```text
ADCv1,12054,40330022,2048,2046,2052,2010,2101,1987
```

Invalid frame handling:

- Parse failure, wrong field count, wrong token, or non-integer values: drop frame and increment parse error counter.
- Out-of-range axis values: clamp to `[0, 4095]` and increment range warning counter.

## Health and Watchdog Semantics

Health state fields:

- `last_seq`: last accepted sequence.
- `seq_gaps`: cumulative detected dropped-frame count.
- `last_rx_monotonic_s`: host monotonic timestamp of last valid frame.
- `frame_age_ms`: current age of last valid frame.
- `parse_errors`: cumulative parse failures.
- `reconnect_count`: cumulative serial reconnect attempts.
- `ingest_ok`: true when fresh frames are available.

Freshness/timeout:

- `stale_timeout_ms` default: `150`.
- If `frame_age_ms > stale_timeout_ms`, axis output enters neutral-safe state.

Neutral-safe output:

- Emit centered axis values (post-shaping zero command) until ingest recovers.
- Keep slow telemetry/status output active.

## Runtime Tuning Schema (Per Axis)

Required keys:

- `deadband`: float, `[0.0, 1.0]`
- `center_offset`: float, `[-1.0, 1.0]`
- `lpf_alpha`: float, `(0.0, 1.0]`
- `expo`: float, `[-1.0, 1.0]`
- `slew_rate`: float, `(0.0, +inf)` units/sec
- `invert`: bool
- `gain`: float, `(0.0, +inf)`
- `clamp_min`: float, `[-1.0, 0.0]`
- `clamp_max`: float, `[0.0, 1.0]`, must satisfy `clamp_min < clamp_max`

Persistence:

- File: `apps/controller/adc_bridge_profile.json`
- Includes top-level `schema_version` and per-axis tuning blocks.
- Apply semantics: stage -> validate -> atomic swap -> ACK.
- Validation failure: reject update and preserve last-known-good profile.

## Bridge Output Contract

Shaping output keys (protocol-ready):

- `X`, `Y`, `Z`, `Xrotate`, `Yrotate`, `Zrotate`

Output behavior:

- Fast path attempts reuse of `mvp_protocol` fast packet builders/senders.
- Slow path attempts reuse of `mvp_protocol` slow packet builders/senders.
- If `mvp_protocol` is unavailable, bridge still emits a deterministic JSON payload over UDP for integration testing.

## Phase Gates and Minimal Operator Tests

Phase 0 (instrumentation):

- Verify legacy browser-axis path unchanged.
- Capture baseline fast/slow rates and packet heartbeat/change behavior.

Phase 1 (parallel bring-up):

- CDC disconnect/reconnect while running.
- Force stale frame timeout and assert neutral-safe output.
- Validate USB re-enumeration device selection.

Phase 2 (tuning acceptance):

- Sweep center/deadband at idle and low motion.
- Sweep LPF/expo/slew and record response.
- Verify profile save/load consistency.

Phase 3 (controlled switchover):

- Complete end-to-end operator run.
- Execute forced fallback drill to legacy path.
- Review telemetry for dropped/stale/late frames.
