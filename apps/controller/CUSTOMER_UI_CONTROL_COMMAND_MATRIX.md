# Customer UI Control Command Matrix (MVP UI 3)

This document is the working source-of-truth for moving `mvp_ui_3` from MVP to customer-ready while preserving an engineering layer.

Scope:
- UI layout and control inventory for `apps/controller/mvp_ui_3.html`
- Slot definitions from `apps/controller/mvp_ui_3_layout.js`
- Command handling and transport behavior in `apps/controller/mvp_slow_bridge.py` and `apps/controller/mvp_protocol.py`

## 1) Transport classes

- `fast`: continuous motion/control packet path (ADC/axes -> fast UDP).
- `slow`: discrete config command path (`SET_SLOW_CONTROL` -> slow UDP key/value).
- `local`: UI edits local shaping state, then `SET_SHAPING`.
- `system`: device/network utility command (`WIFI_*`, network apply/reset, etc.).

## 2) Fast-path axis mapping (BGC/lens related)

| UI axis key | Input source | Packet field | Notes |
|---|---|---|---|
| `X` | joystick/ADC | `yaw` | pan command |
| `Y` | joystick/ADC | `pitch` | tilt command |
| `Z` | joystick/ADC | `roll` | roll command |
| `Zrotate` | joystick/ADC | `zoom` | signed zoom velocity |
| `Xrotate` | joystick/ADC | `focus` | focus control |
| `Yrotate` | joystick/ADC | `iris` | iris control |

Related controls that affect fast behavior:
- `shape_expo`, `shape_expo_zoom`, `shape_top_speed_*`, `shape_deadband_*`, `shape_zoom_feedback` (via `SET_SHAPING`)
- `control_mode`, `source_zoom`, `source_focus`, `source_iris`, `lens_select` (slow config keys consumed by head runtime)

## 3) Current UI command inventory

## 3.1 Top bar / global controls

| UI control | Current behavior | Command | Class | Customer tier |
|---|---|---|---|---|
| Connect button | Open WS to slow bridge | N/A (client-side action) | local/system | Operator |
| Head selector | Select active head index | `SELECT_HEAD` | system | Operator |
| Tabs (Control/IP/WiFi/Input Tests) | Page switch | N/A | local | Operator/Eng |

## 3.2 Control page (touch buttons)

| UI control | Command payload | Class | Recommended mode |
|---|---|---|---|
| Motors ON | `SET_SLOW_CONTROL key=motors_on value=1` | slow | Operator |
| Motors OFF | `SET_SLOW_CONTROL key=motors_on value=0` | slow | Operator |
| Send Gyro | `SET_SLOW_CONTROL key=gyro_heading_correction value=<selected>` | slow | Operator |
| Save User Defaults | `SAVE_USER_DEFAULTS` | system | Eng |
| Reset User Defaults | `RESET_USER_DEFAULTS` | system | Eng (confirm dialog) |
| Calibrate Inputs | `CALIBRATE_INPUTS duration_s=2.5` | system | Eng |

## 3.3 Dock slot matrix (C1..C5)

All slot commands are mapped through popup editing and `SET_SLOW_CONTROL`, except `local/system` special cases.

| Slot | Label | Command key | Class | Status |
|---|---|---|---|---|
| C1P1 | Motors | `motors_on` | slow | assigned |
| C1P2 | Control Mode | `control_mode` | slow | assigned |
| C1P3 | Lens Select | `lens_select` | slow | assigned |
| C1P4 | Gyro Heading | `gyro_heading_correction` | slow | assigned |
| C1P5..C1P10 | Spare | `null` | N/A | unassigned |
| C2P1 | Zoom Source | `source_zoom` | slow | assigned |
| C2P2 | Focus Source | `source_focus` | slow | assigned |
| C2P3 | Iris Source | `source_iris` | slow | assigned |
| C2P4..C2P10 | Spare | `null` | N/A | unassigned |
| C3P1 | Focus Filter | `filter_enable_focus` | slow | assigned |
| C3P2 | Iris Filter | `filter_enable_iris` | slow | assigned |
| C3P3 | Filter Num | `filter_num` | slow | assigned |
| C3P4 | Filter Den | `filter_den` | slow | assigned |
| C3P5..C3P10 | Spare | `null` | N/A | unassigned |
| C4P1 | Expo PTR | `shape_expo` | local | assigned |
| C4P2 | Expo Zoom | `shape_expo_zoom` | local | assigned |
| C4P3 | Top Speed Pan | `shape_top_speed_yaw` | local | assigned |
| C4P4 | Top Speed Tilt | `shape_top_speed_pitch` | local | assigned |
| C4P5 | Top Speed Roll | `shape_top_speed_roll` | local | assigned |
| C4P6 | Top Speed Zoom | `shape_top_speed_zoom` | local | assigned |
| C4P7 | Deadband Yaw | `shape_deadband_yaw` | local | assigned |
| C4P8 | Deadband Pitch | `shape_deadband_pitch` | local | assigned |
| C4P9 | Deadband Roll | `shape_deadband_roll` | local | assigned |
| C4P10 | Deadband Zoom | `shape_deadband_zoom` | local | assigned |
| C5P1 | Apply Network | `net_apply` -> `APPLY_NETWORK_CONFIG` | system | assigned |
| C5P2 | Factory Net Reset | `net_factory_reset` -> `FACTORY_RESET_NETWORK` | system | assigned |
| C5P3 | WiFi Scan | `wifi_scan` -> `WIFI_SCAN` | system | assigned |
| C5P4 | WiFi Disconnect | `wifi_disconnect` -> `WIFI_DISCONNECT` | system | assigned |
| C5P5 | Zoom Feedback | `shape_zoom_feedback` | local | assigned |
| C5P6..C5P10 | Spare | `null` | N/A | unassigned |

## 3.4 IP Config / WiFi page controls

| UI control | Command payload | Class | Recommended mode |
|---|---|---|---|
| Save Pi LAN | `SET_PI_LAN_CONFIG` | system | Eng |
| Apply Network | `APPLY_NETWORK_CONFIG` | system | Eng |
| Factory Default | `FACTORY_RESET_NETWORK` | system | Eng (confirm dialog) |
| Head row Save | `SET_HEAD_CONFIG index=<i>` | system | Eng |
| WiFi Scan | `WIFI_SCAN` | system | Operator/Eng |
| WiFi Connect | `WIFI_CONNECT ssid,password` | system | Operator/Eng |
| WiFi Disconnect | `WIFI_DISCONNECT` | system | Operator/Eng |

## 3.5 Input Tests page controls

| UI control | Behavior | Class | Recommended mode |
|---|---|---|---|
| Debounce +/- | local variable only | local | Eng |
| Group lockout +/- | local variable only | local | Eng |
| Reset counters | local counters reset | local | Eng |

Note: input test debounce/lockout are not currently persisted back to backend in real time.

## 4) Backend-supported slow command keys

Supported by `mvp_protocol.SLOW_KEY_IDS`:
- `motors_on`
- `control_mode`
- `lens_select`
- `source_zoom`
- `source_focus`
- `source_iris`
- `filter_enable_focus`
- `filter_enable_iris`
- `filter_num`
- `filter_den`
- `gyro_heading_correction`
- `wash_wipe` (`parked` / `wiping`)

If a new control is added with `SET_SLOW_CONTROL`, it must be added to:
1) `mvp_ui_3_layout.js` (command key/value options),
2) `mvp_protocol.py` (`SLOW_KEY_IDS` + encode/decode),
3) head/runtime command handling and telemetry.

## 5) Operator vs engineering split (proposed)

Operator default:
- Connect/head select
- Motors on/off
- Essential fast movement controls
- Lens/source choices that are needed daily
- Minimal status and alarm state

Engineering layer:
- Full shaping/deadband/expo
- Calibration and input test page
- Full network provisioning
- Raw telemetry panes and apply-state diagnostics
- Factory reset / defaults reset actions

## 6) Unassigned inventory (must close for customer solution)

Unassigned dock slots:
- C1P5..C1P10 (6)
- C2P4..C2P10 (7)
- C3P5..C3P10 (6)
- C5P6..C5P10 (5)

Total unassigned slot positions: 24

Recommended next step:
- Define desired customer feature list and map each feature into these 24 slots (or reduce slot count in UI if not needed).

## 7) Change control checklist (for every new control)

- Define UI label and user intent (operator vs engineering).
- Assign transport class (`fast`/`slow`/`local`/`system`).
- Define value domain, clamps, and default.
- Define backend command and expected ack/result.
- Define readback source shown in UI state.
- Add failure behavior (timeout, stale, denied).
- Add persistence behavior (session-only vs saved defaults).
