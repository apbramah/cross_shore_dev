# Control Pipeline API Source of Truth

Related document: `apps/head_eng/CONTROL_RESOLUTION_BUDGET.md` (endpoint-first UART range and resolution budget tables).

```text
Browser UI (gamepad)
  -> WebSocket JSON (`apps/controller/mvp_ui.html`)
    -> Bridge state/update handlers (`apps/controller/mvp_bridge.py::handler`)
      -> Fast packet build (`apps/controller/mvp_bridge.py::_get_fast_packet`)
        -> v2 active path: `apps/controller/mvp_protocol.py::build_fast_packet_v2`
      -> UDP send (`apps/controller/mvp_protocol.py::send_udp_to`)
        -> Pico fast recv/decode (`apps/head_eng/main.py::recv_latest_fast_packet`, `decode_fast_packet_v2`)
          -> BGC apply (`apps/head_eng/bgc.py::BGC.send_joystick_control`)
          -> Lens apply (`apps/head_eng/lens_controller.py` -> active lens runtime)
      -> Slow table sender (`apps/controller/mvp_bridge.py::slow_sender_task`)
        -> slow encode (`apps/controller/mvp_protocol.py::build_slow_cmd_packet`)
        -> Pico slow recv/decode/apply (`apps/head_eng/main.py::poll_slow_command_once`, `decode_slow_cmd_packet`, `apply_slow_command`)
```

## Fast API

### Wire + semantics

| Mode | Active runtime | Packet bytes | Format | Endianness | Evidence |
|---|---|---:|---|---|---|
| `v2_19` | Active (`ENABLE_DUAL_CHANNEL=True`) | 19 | `<BBBHhHHHHHH` = `magic,ver,type,seq,zoom,focus,iris,yaw,pitch,roll,reserved` | Little-endian | `apps/controller/mvp_protocol.py::build_fast_packet_v2`, `apps/head_eng/main.py::decode_fast_packet_v2` |

`v2_19` field details:

| Field | Type | Meaning |
|---|---|---|
| `magic` | `u8` | `0xDE` (`PKT_MAGIC`) |
| `ver` | `u8` | `0x01` (`PKT_VER`) |
| `type` | `u8` | `0x10` (`PKT_FAST_CTRL`) |
| `seq` | `u16` | bridge fast sequence; increments each packet and wraps |
| `zoom` | `i16` | signed zoom command |
| `focus`,`iris`,`yaw`,`pitch`,`roll` | `u16` | unsigned 16-bit command fields |
| `reserved` | `u16` | currently `0` |

Evidence: `apps/controller/mvp_protocol.py::build_fast_packet_v2`, `apps/head_eng/main.py::decode_fast_packet_v2`.

Legacy dependency note (current implementation, not target API): `build_fast_packet_v2` currently derives payload fields by round-tripping through `build_udp_packet` and `decode_legacy_fast_fields` before packing v2. Evidence: `apps/controller/mvp_protocol.py::build_fast_packet_v2`.

### Encode/decode helper functions by stage

| Stage | Encode/transform helpers | Decode/apply helpers |
|---|---|---|
| UI | `apps/controller/mvp_ui.html::readNamedAxes`, `normDeadzone`, axis mapper state in `axisMap` | N/A |
| Bridge | `apps/controller/mvp_bridge.py::_get_fast_packet`, `_clamp_fast_hz`, `fast_sender_task` | N/A |
| Protocol module | `apps/controller/mvp_protocol.py::build_fast_packet_v2` (currently depends on `build_udp_packet` + `decode_legacy_fast_fields`) | `decode_fast_packet_v2` helper exists in protocol and Pico (`apps/head_eng/main.py::decode_fast_packet_v2`) |
| Pico runtime | N/A | `apps/head_eng/main.py::recv_latest_fast_packet`, `decode_fast_packet_v2`, then `bgc.send_joystick_control` and lens functions |

### Update rates / throttles / heartbeat

| Location | Behavior | Value | Evidence |
|---|---|---:|---|
| UI -> bridge send throttle | Sends `GAMEPAD` only if last send >20 ms | ~50 Hz | `apps/controller/mvp_ui.html::tick` |
| Bridge fast loop default | `FAST_SEND_HZ` | 50 Hz | `apps/controller/mvp_bridge.py::FAST_SEND_HZ` |
| Bridge fast clamp | `_clamp_fast_hz` | 25..100 Hz | `apps/controller/mvp_bridge.py::_clamp_fast_hz` |
| Bridge heartbeat | send even unchanged packet when due | 0.5 s | `apps/controller/mvp_bridge.py::FAST_HEARTBEAT_S`, `fast_sender_task` |

### Axis mappings and transforms

| Layer | Transform |
|---|---|
| UI | Raw gamepad axis index -> named axis (`X,Y,Z,Xrotate,Yrotate,Zrotate`) via `axisMap`; deadzone `0.03` via `normDeadzone` |
| Protocol fast encode | Deadzone `0.06`; invert flags (`yaw/pitch/roll`); speed scaling for pan/tilt/roll; clamp to `[-1,1]`; float -> integer (`*512` for pan/tilt/roll/focus/iris, `*zoom_gain` for zoom); map functions (`map_focus`,`map_iris`,`map_pitch`,`map_zoom`) |
| v2 path | `build_fast_packet_v2` derives values by building then decoding legacy packet (`decode_legacy_fast_fields`) before packing v2 |

Evidence: `apps/controller/mvp_ui.html::readNamedAxes`, `normDeadzone`; `apps/controller/mvp_protocol.py::build_udp_packet`, `build_fast_packet_v2`.

### Lens control sideband usage

Current target API (`v2_19`) has no active lens sideband fields in fast packet decode.

Historical/legacy dependency context (for removal planning): legacy packet bytes `14..15` carry sideband if marker present:

| Byte | Name | Meaning |
|---|---|---|
| `14` | `ctrl0` | `b1..b0 lens` (`0=fuji,1=canon`), `b3..b2 zoom source`, `b5..b4 focus source`, `b7..b6 iris source` (`0=pc,1=camera,2=off`) |
| `15` | `ctrl1` | marker `0xA5` means sideband valid |

Encode/decode: `apps/controller/mvp_protocol.py::_encode_lens_control`, `apps/head_eng/bgc.py::_decode_lens_control`.

Current runtime note: in `v2_19` mode, Pico fast decode (`apps/head_eng/main.py::decode_fast_packet_v2`) does not include `lens_control`, so this sideband path is inactive.

## Slow API

### Slow packet structure and versioning

| Packet | Struct | Bytes | Versioning/checks |
|---|---|---:|---|
| Slow command | `<BBBHHBi>` | 12 | validated against `PKT_MAGIC=0xDE`, `PKT_VER=0x01`, `PKT_SLOW_CMD=0x20` |
| Slow ACK helper | `<BBBHHBB>` | 9 | helper-only in controller module |
| Slow telemetry type | constant only | unknown | `PKT_SLOW_TELEM=0x30` defined, no active send/recv in scoped files |

Evidence: `apps/controller/mvp_protocol.py::{build_slow_cmd_packet,build_slow_ack_packet,decode_slow_ack_packet}`, `apps/head_eng/main.py::decode_slow_cmd_packet`.

### Full key table

| Key name | Key ID | Value encoding | Expected behavior on Pico |
|---|---:|---|---|
| `motors_on` | 1 | bool -> `0/1` | set `slow_motors_on`; gate BGC send path |
| `control_mode` | 2 | `"speed"->0`, `"angle"->1` | track mode; `speed` disables angle mode; `angle` accepted with pending apply message |
| `lens_select` | 3 | `"fuji"->0`, `"canon"->1` | compatibility key; runtime override ignored (head selects lens at boot) |
| `source_zoom` | 4 | `pc=0`, `camera=1`, `off=2` | set zoom source ownership |
| `source_focus` | 5 | `pc=0`, `camera=1`, `off=2` | set focus source ownership |
| `source_iris` | 6 | `pc=0`, `camera=1`, `off=2` | set iris source ownership |
| `filter_enable_focus` | 7 | bool -> `0/1` | delegate to lens filter-enable hook for focus |
| `filter_enable_iris` | 8 | bool -> `0/1` | delegate to lens filter-enable hook for iris |
| `filter_num` | 9 | integer | delegate to lens filter numerator hook |
| `filter_den` | 10 | integer | delegate to lens filter denominator hook |
| `lens_check` | 19 | bool/integer (`0/1`) | one-shot reboot request to force lens re-detect |

Evidence: `apps/controller/mvp_protocol.py::SLOW_KEY_IDS`, `encode_slow_value`; `apps/head_eng/main.py::apply_slow_command`.

### Apply semantics (`seq`, `apply_id`, dedupe, ordering)

| Item | Current behavior | Evidence |
|---|---|---|
| Sender cadence | every `0.5s` | `apps/controller/mvp_bridge.py::SLOW_SEND_INTERVAL_S`, `slow_sender_task` |
| `apply_id` | incremented once per sender cycle (before full key table send) | `slow_sender_task` |
| `seq` | incremented per slow packet | `slow_sender_task` |
| Retry | unknown/no explicit retry logic in sender | no retry loop or ACK wait in `slow_sender_task` |
| Receiver dedupe | drop only immediate duplicate `(apply_id, seq)` pair | `apps/head_eng/main.py::apply_slow_command` |
| Ordering assumptions | UDP arrival order only; one slow packet polled per loop iteration | `poll_slow_command_once`, main loop |

### Receiver/apply path on Pico

Entry path: `apps/head_eng/main.py::poll_slow_command_once` -> `decode_slow_cmd_packet` -> `apply_slow_command`.

Key handlers inside `apply_slow_command`:
- Lens select/source keys -> `apps/head_eng/lens_controller.py::{set_lens_type,set_axis_source}`.
- Filter keys -> `apps/head_eng/lens_controller.py::{set_input_filter_enabled,set_input_filter_num,set_input_filter_den}` (dynamic `getattr` dispatch on active lens implementation).
- Motor/mode keys -> `slow_motors_on` and `slow_control_mode`; `speed` mode calls `apps/head_eng/bgc.py::BGC.disable_angle_mode`.

Lens boot lifecycle:
- Boot probes Fuji then Canon (`apps/head_eng/lens_detect.py::detect_lens`).
- If neither responds with a valid payload, runtime enters no-lens mode (`lens = None`) and continues full BGC/network boot.

## Numbering Registry

| Category | Symbol | Value | Source |
|---|---|---:|---|
| Packet | `PKT_MAGIC` | `0xDE` | `apps/controller/mvp_protocol.py`, `apps/head_eng/main.py` |
| Packet | `PKT_VER` | `0x01` | same |
| Packet | `PKT_FAST_CTRL` | `0x10` | same |
| Packet | `PKT_SLOW_CMD` | `0x20` | same |
| Packet | `PKT_SLOW_ACK` | `0x21` | `apps/controller/mvp_protocol.py` |
| Packet | `PKT_SLOW_TELEM` | `0x30` | `apps/controller/mvp_protocol.py` |
| Legacy subtype (deprecation context) | fast `data_type` | `0xFD` and `0xF3` | `apps/head_eng/bgc.py::BGC.decode_udp_packet` |
| Slow key | `SLOW_KEY_MOTORS_ON` | 1 | `apps/controller/mvp_protocol.py`, `apps/head_eng/main.py` |
| Slow key | `SLOW_KEY_CONTROL_MODE` | 2 | same |
| Slow key | `SLOW_KEY_LENS_SELECT` | 3 | same |
| Slow key | `SLOW_KEY_SOURCE_ZOOM` | 4 | same |
| Slow key | `SLOW_KEY_SOURCE_FOCUS` | 5 | same |
| Slow key | `SLOW_KEY_SOURCE_IRIS` | 6 | same |
| Slow key | `SLOW_KEY_FILTER_ENABLE_FOCUS` | 7 | same |
| Slow key | `SLOW_KEY_FILTER_ENABLE_IRIS` | 8 | same |
| Slow key | `SLOW_KEY_FILTER_NUM` | 9 | same |
| Slow key | `SLOW_KEY_FILTER_DEN` | 10 | same |
| Slow key | `SLOW_KEY_LENS_CHECK` | 19 | same |
| Lens enum | `LENS_FUJI` / `LENS_CANON` | `"fuji"` / `"canon"` | `apps/head_eng/lens_controller.py` |
| Source enum | `SOURCE_PC` / `SOURCE_CAMERA` / `SOURCE_OFF` | `"pc"` / `"camera"` / `"off"` | `apps/head_eng/fuji_lens_from_calibration.py`, `apps/head_eng/canon_lens.py` |
| Mode encoding | `control_mode` wire | `speed=0`, `angle=1` | `apps/controller/mvp_protocol.py::encode_slow_value` |
| Port | WebSocket `WS_PORT` | 8765 | `apps/controller/mvp_bridge.py` |
| Port | Fast UDP `FAST_PORT`/`FAST_UDP_PORT` | 8888 | `apps/controller/mvp_protocol.py`, `apps/head_eng/main.py` |
| Port | Slow CMD UDP `SLOW_CMD_PORT`/`SLOW_UDP_PORT` | 8890 | same |
| Port | Slow telemetry UDP `SLOW_TELEM_PORT` | 8891 | `apps/controller/mvp_protocol.py` |
| Timing | Fast default | 50 Hz | `apps/controller/mvp_bridge.py::FAST_SEND_HZ` |
| Timing | Fast clamp | 25..100 Hz | `apps/controller/mvp_bridge.py::_clamp_fast_hz` |
| Timing | Fast heartbeat | 0.5 s | `apps/controller/mvp_bridge.py::FAST_HEARTBEAT_S` |
| Timing | Slow interval | 0.5 s | `apps/controller/mvp_bridge.py::SLOW_SEND_INTERVAL_S` |
| Timing | UI send throttle | 20 ms | `apps/controller/mvp_ui.html::tick` |
| Timing | Fuji runtime tx period | 20 ms | `apps/head_eng/fuji_lens_from_calibration.py::CONTROL_TX_PERIOD_MS` |
| Timing | Fuji SW4 poll | 300 ms | `apps/head_eng/fuji_control_calibration.py::SW4_POLL_MS` (imported by `fuji_control_calibration_copy`) |
| Timing | Fuji connect keepalive | 1000 ms | `apps/head_eng/fuji_control_calibration.py::CONNECT_KEEPALIVE_MS` |

## Ownership Map

| API element | Encode owner | Transport/send owner | Decode owner | Apply owner |
|---|---|---|---|---|
| Fast `v2_19` | `apps/controller/mvp_protocol.py::build_fast_packet_v2` | `apps/controller/mvp_bridge.py::fast_sender_task` via `mvp_protocol.send_udp_to` | `apps/head_eng/main.py::decode_fast_packet_v2` | `apps/head_eng/main.py` main loop -> `bgc.send_joystick_control`, `lens.move_zoom`, `lens.set_focus_input`, `lens.set_iris_input` |
| Fast legacy dependency (to remove) | `apps/controller/mvp_protocol.py::{build_udp_packet,decode_legacy_fast_fields}` (currently called by `build_fast_packet_v2`) | not required as a transport mode when `FAST_CHANNEL_MODE="v2"` | `apps/head_eng/bgc.py::BGC.decode_udp_packet` (legacy decode helper) | legacy-only path |
| Slow command | `apps/controller/mvp_protocol.py::{encode_slow_value,build_slow_cmd_packet}` | `apps/controller/mvp_bridge.py::slow_sender_task` | `apps/head_eng/main.py::decode_slow_cmd_packet` | `apps/head_eng/main.py::apply_slow_command` |
| Slow ACK helper | `apps/controller/mvp_protocol.py::build_slow_ack_packet` | unknown | `apps/controller/mvp_protocol.py::decode_slow_ack_packet` | unknown |

Short call-chain snippets:
- Fast: `mvp_ui.html::tick` -> WebSocket `GAMEPAD` -> `mvp_bridge.py::handler` updates `latest_axes` -> `fast_sender_task` -> `_get_fast_packet` -> UDP -> `head_eng/main.py::recv_latest_fast_packet` -> `decode_fast_packet_v2` -> apply.
- Slow: UI `SET_SLOW_CONTROL` or lens settings -> `mvp_bridge.py::handler` updates `dual_slow_state` -> `slow_sender_task` sends full key table -> `head_eng/main.py::poll_slow_command_once` -> `apply_slow_command`.

## Current-State Truth Table

| Slow key | Status | Evidence |
|---|---|---|
| `motors_on` | implemented and active | `apply_slow_command` updates `slow_motors_on`; main loop gates `bgc.send_joystick_control` |
| `control_mode` | partially implemented | `speed` branch calls `bgc.disable_angle_mode`; `angle` branch logs `"accepted; apply pending"` |
| `lens_select` | implemented but ignored at runtime | `apply_slow_command` explicitly ignores runtime override; head lens type is chosen only during boot detection |
| `source_zoom` | implemented and active | `apply_slow_command` calls `lens.set_axis_source("zoom", ...)`; runtime lens methods gate by source |
| `source_focus` | implemented and active | same pattern for focus |
| `source_iris` | implemented and active | same pattern for iris |
| `filter_enable_focus` | accepted but no-op (active Fuji runtime) | delegated by `lens_controller.py::set_input_filter_enabled` via `getattr`; active class `fuji_lens_from_calibration.py::FujiLens` has no `set_input_filter_enabled` |
| `filter_enable_iris` | accepted but no-op (active Fuji runtime) | same evidence pattern |
| `filter_num` | accepted but no-op (active Fuji runtime) | delegated by `lens_controller.py::set_input_filter_num`; no method in active `FujiLens` |
| `filter_den` | accepted but no-op (active Fuji runtime) | delegated by `lens_controller.py::set_input_filter_den`; no method in active `FujiLens` |
| `lens_check` | implemented and active (one-shot) | `apply_slow_command` ACKs then calls reboot path (`machine.reset`) when value is non-zero |

Active Fuji runtime evidence: `apps/head_eng/lens_controller.py` imports `FujiLens` from `apps/head_eng/fuji_lens_from_calibration.py`.

## Drift / Inconsistency Report

1. `apps/controller/mvp_protocol.py::send_udp` docstring claims a "16-byte packet", but active fast mode is 19-byte v2 and slow is 12-byte.
2. Legacy lens sideband exists (`_encode_lens_control`/`_decode_lens_control`) but is effectively bypassed in active v2 path because `decode_fast_packet_v2` does not expose `lens_control`.
3. Slow ACK and slow telemetry constants/helpers are defined in `apps/controller/mvp_protocol.py` but not wired in bridge/head runtime modules in scope.
4. Input shaping is duplicated across layers: UI deadzone (`0.03`) and protocol deadzone (`0.06`) both apply.
5. Slow filter keys are periodically transmitted (`mvp_bridge.py::slow_sender_task`) but active Fuji runtime path lacks filter methods, producing no-op behavior.
6. `control_mode="angle"` is accepted but not fully applied (`apps/head_eng/main.py::apply_slow_command` prints apply pending).
7. Legacy decoder supports `data_type 0xF3` in `apps/head_eng/bgc.py::BGC.decode_udp_packet`, but scoped sender path builds `0xFD` (`apps/controller/mvp_protocol.py::build_udp_packet`). Producer of `0xF3` is unknown in scoped modules.
8. Active `v2_19` builder is not independent yet; it derives values by encode/decode through legacy helpers (`apps/controller/mvp_protocol.py::build_fast_packet_v2` + `decode_legacy_fast_fields` + `build_udp_packet`).

## Cleanup Plan (no code changes)

### Stage 1: Documentation alignment
- Declare `v2_19` as the only maintained fast API.
- Move all legacy references under a clearly labeled "deprecation dependency" section only.
- Explicitly mark lens sideband as inactive in current `v2_19` runtime.
- Publish slow-key support matrix with current truth-table statuses.
- Record unknowns: `0xF3` producer, ACK/telemetry runtime usage.

Acceptance checks:
- Every field in maintained packets (`v2_19` fast, slow cmd) has byte order/type/range and owning symbol.
- Every slow key has a status and apply owner.
- Unknowns are explicitly listed with missing evidence.

### Stage 2: Helper ownership consolidation
- Port all transform dependencies currently implicit in `build_udp_packet` into explicit v2-native helpers (deadzone, invert, speed scaling, clamps, map transforms) with identical numeric outputs.
- Update `build_fast_packet_v2` to call only v2-native helpers (no `build_udp_packet` / `decode_legacy_fast_fields` dependency).
- Define one shared constants source for packet IDs, key IDs, enums, and ports.
- Define explicit lens capability contract for filter support and tie slow apply semantics to capability.

Acceptance checks:
- One encode/decode owner per active API element.
- `build_fast_packet_v2` has no call dependency on legacy helpers.
- One constants registry imported on both sender and receiver.
- No silent no-op keys without capability annotation.

### Stage 3: Test harness updates
- Add byte-exact golden vector tests for: v2 fast and slow command encode/decode.
- During migration, run parity tests proving legacy helper output == new v2-native transform output for representative axis/control-state fixtures.
- After parity passes, remove legacy fast helpers and legacy fast decode paths from maintained modules (`build_udp_packet`, `decode_legacy_fast_fields`, and legacy decode branches where no longer used).
- Add integration tests for sender cadence/heartbeat behavior (`fast` changed-or-heartbeat and `slow` interval send loop).
- Add per-key apply tests on Pico-side logic (or host mirror) to assert implemented/partial/no-op states.

Acceptance checks:
- Golden vectors pass for all packet structures.
- Parity suite passes before legacy helper removal; removal PR contains no remaining runtime references to removed helpers.
- Per-key apply outcomes match this truth table.
- Drift report either reduced or explicitly accepted as technical debt.

