# Command Matrix Reference: Slow, Fast, Naming & Hardware Mapping

Single reference for UI/bridge/head command names, value encoding, and which hardware (BGC, Canon, Fuji, Sony VISCA) each command targets.

**Code sources of truth:**
- **Slow keys:** `apps/controller/mvp_protocol.py` → `SLOW_KEY_IDS`
- **Slow apply:** `apps/head_eng/main.py` → `apply_slow_command()` + `SLOW_KEY_*` / `SLOW_KEY_NAMES`
- **Fast packet:** `apps/controller/mvp_protocol.py` → `build_udp_packet()` / fast struct (yaw, pitch, roll, zoom, focus, iris)
- **Shaping (fast “commands”):** `apps/controller/mvp_slow_bridge.py` → `_default_shaping_profile()`; UI lists in `mvp_ui_3.html` → `FAST_SLIDER_COMMANDS`, `FAST_QUICK_COMMANDS`, `SLOW_SLIDER_COMMANDS`, `SLOW_QUICK_COMMANDS`

---

## 1) Naming statements

| Scope | Rule | Example |
|-------|------|--------|
| **Slow command keys** | `snake_case`; must match `mvp_protocol.SLOW_KEY_IDS` and head `SLOW_KEY_NAMES`. | `motors_on`, `gyro_heading_correction`, `wash_wipe` |
| **Fast (shaping) keys in UI** | Prefix `shape_` + axis or parameter name. | `shape_expo`, `shape_top_speed_yaw`, `shape_deadband_zoom` |
| **Assignment slot value** | `mode:key` with mode `fast` or `slow`; key is the command key above. | `fast:shape_top_speed_yaw`, `slow:gyro_heading_correction` |
| **Unassigned** | Use literal `none:none` in assignment arrays. | Quick/slider default |
| **lens_select enum** | Lowercase: `fuji`, `canon`. Encoded on wire as 0 = Fuji, 1 = Canon. | `lens_select` → 0 (Fuji) or 1 (Canon) |
| **source_* enum** | Lowercase: `pc`, `camera`, `off`. Encoded 0 / 1 / 2. | `source_zoom` → 0 (pc), 1 (camera), 2 (off) |
| **wash_wipe enum** | `parked` / `wipe` (or 0/1). Encoded 0 = parked, 1 = wiping. | `wash_wipe` → 0 or 1 |
| **control_mode** | `speed` or `angle`. Encoded 0 = speed, 1 = angle. | `control_mode` → 0 or 1 |

---

## 2) Slow command matrix

Each row: **key** (and key_id), **value encoding**, **hardware** (BGC / Fuji / Canon), **notes**.

| Key | key_id | Value encoding | BGC | Fuji | Canon | Notes |
|-----|--------|----------------|-----|------|--------|------|
| `motors_on` | 1 | 0 = off, 1 = on | ✓ | — | — | BGC CMD motors enable |
| `control_mode` | 2 | 0 = speed, 1 = angle | ✓ | — | — | BGC speed vs angle mode |
| `lens_select` | 3 | 0 = fuji, 1 = canon | — | ✓ | ✓ | Selects lens type; Fuji/Canon lens controller |
| `source_zoom` | 4 | 0 = pc, 1 = camera, 2 = off | — | ✓ | ✓ | Zoom source (PC/camera/off) |
| `source_focus` | 5 | 0 = pc, 1 = camera, 2 = off | — | ✓ | ✓ | Focus source |
| `source_iris` | 6 | 0 = pc, 1 = camera, 2 = off | — | ✓ | ✓ | Iris source |
| `filter_enable_focus` | 7 | 0 = off, 1 = on | — | ✓ | ✓ | Focus input filter enable |
| `filter_enable_iris` | 8 | 0 = off, 1 = on | — | ✓ | ✓ | Iris input filter enable |
| `filter_num` | 9 | integer (filter numerator) | — | ✓ | ✓ | Input filter ratio num |
| `filter_den` | 10 | integer (filter denominator) | — | ✓ | ✓ | Input filter ratio den |
| `gyro_heading_correction` | 11 | integer (e.g. 0–16383) | ✓ | — | — | BGC gyro heading set |
| `wash_wipe` | 12 | 0 = parked, 1 = wiping | ✓ | — | — | BGC Servo PWM1 (wash/wipe) |
| `pan_accel` | 13 | 0–255 | ✓ | — | — | BGC pan (yaw) accel |
| `tilt_accel` | 14 | 0–255 | ✓ | — | — | BGC tilt (pitch) accel |
| `roll_accel` | 15 | 0–255 | ✓ | — | — | BGC roll accel |
| `pan_gain` | 16 | 0–255 | ✓ | — | — | BGC pan (yaw) gain |
| `tilt_gain` | 17 | 0–255 | ✓ | — | — | BGC tilt (pitch) gain |
| `roll_gain` | 18 | 0–255 | ✓ | — | — | BGC roll gain |

**Dead-ahead (DA) slow keys** (if present in UI/state): `da_enabled`, `da_yaw_range`, `da_pitch_range`, `da_roll_range`, `da_deadband`, `da_speed` — typically drive BGC/behavior config; exact key_ids and encoding are defined where they are added to the protocol.

**Wire format:** UDP `PKT_SLOW_CMD` (magic, ver, type, seq, apply_id, key_id, value). Encoder in controller: `mvp_protocol.encode_slow_value(key, value)`; decoder on head: `main.py` `apply_slow_command()` by `key_id`.

---

## 3) Fast (shaping) “command” matrix

These are not separate wire commands; they configure how the **controller** shapes joystick/ADC into the fast UDP stream. The head receives already-shaped yaw/pitch/roll/zoom (and focus/iris). BGC receives the fast packet; lens (Fuji/Canon) receives zoom/focus/iris from the same packet or derived state.

| UI key | Backend shaping field | UI scale (0–10) | BGC / lens | Notes |
|--------|------------------------|-----------------|------------|--------|
| `shape_expo` | `expo` | 1–10 (linear sensitivity) | Affects stick→axis curve on controller | Pan/tilt/roll expo |
| `shape_expo_zoom` | `expo_zoom` | 1–10 | Same for zoom axis | Zoom expo |
| `shape_top_speed_yaw` | `top_speed.yaw` | 0–10 | Max pan speed from stick | |
| `shape_top_speed_pitch` | `top_speed.pitch` | 0–10 | Max tilt speed | |
| `shape_top_speed_roll` | `top_speed.roll` | 0–10 | Max roll speed | |
| `shape_top_speed_zoom` | `top_speed.zoom` | 0–10 | Max zoom speed | |
| `shape_deadband_yaw` | `deadband.yaw` | 0–10 | Deadband pan | |
| `shape_deadband_pitch` | `deadband.pitch` | 0–10 | Deadband tilt | |
| `shape_deadband_roll` | `deadband.roll` | 0–10 | Deadband roll | |
| `shape_deadband_zoom` | `deadband.zoom` | 0–10 | Deadband zoom | |
| `shape_zoom_feedback` | `zoom_feedback` | 1–10 | Zoom feedback gain | |
| `shape_invert_yaw` | `invert.yaw` | 0/1 (OFF/ON) | Pan invert | Quick only |
| `shape_invert_pitch` | `invert.pitch` | 0/1 | Tilt invert | Quick only |
| `shape_invert_roll` | `invert.roll` | 0/1 | Roll invert | Quick only |

**Backend:** `mvp_slow_bridge.py` holds `shaping_state`; applied to ADC bridge via `_apply_shaping_to_adc_profile()`. **UI list:** `mvp_ui_3.html` `FAST_SLIDER_COMMANDS`, `FAST_QUICK_COMMANDS`, `FAST_ROW_COMMANDS`.

---

## 4) BGC, Canon, Fuji, Sony VISCA mapping summary

| Hardware | Role | Slow commands that target it | Fast / shaping |
|----------|------|------------------------------|----------------|
| **BGC** | Gimbal (pan/tilt/roll); motors; gyro; wash/wipe; accel/gain | `motors_on`, `control_mode`, `gyro_heading_correction`, `wash_wipe`, `pan_accel`, `tilt_accel`, `roll_accel`, `pan_gain`, `tilt_gain`, `roll_gain` | Receives continuous yaw/pitch/roll (and zoom) from fast UDP; shaping is applied on controller before send. |
| **Fuji** | ENG lens (zoom/focus/iris) | `lens_select` (when fuji), `source_zoom`, `source_focus`, `source_iris`, `filter_enable_focus`, `filter_enable_iris`, `filter_num`, `filter_den` | Zoom/focus/iris from fast packet; Fuji protocol (e.g. serial). |
| **Canon** | ENG lens (zoom/focus/iris) | `lens_select` (when canon), `source_*`, `filter_*` same as Fuji | Zoom/focus/iris from fast packet; Canon protocol (Type-B, etc.). |
| **Sony VISCA** | Camera/lens (e.g. head_zoom / head apps) | Not in current slow key set; different head variant | Sony camera/lens control in `head_zoom` / `camera_sony` path; not the same as ENG lens slow keys above. |

**Canon / Fuji:** Value encoding for `lens_select`, `source_*`, and filter keys is in `mvp_protocol.encode_slow_value()`. Head applies them in `apps/head_eng/main.py` → `apply_slow_command()`; lens-specific code in `canon_lens.py`, `fuji_lens*.py`, `lens_controller.py`.

**Sony VISCA:** Documented in head_zoom/head camera flow; add a row here when a slow key or fast axis is explicitly mapped to Sony VISCA in the controller/head.

---

## 5) Where to add or change commands

| Change | File(s) to update |
|--------|-------------------|
| New slow command | `mvp_protocol.py`: add constant + entry in `SLOW_KEY_IDS`; `encode_slow_value()` if new encoding. `head_eng/main.py`: add `SLOW_KEY_*`, `SLOW_KEY_NAMES`, and branch in `apply_slow_command()`. Optionally `mvp_slow_bridge.py` `_default_slow_state()` and `mvp_factory_defaults.json`. UI: add to `SLOW_SLIDER_COMMANDS` and/or `SLOW_QUICK_COMMANDS` in `mvp_ui_3.html`. |
| New fast (shaping) key | Bridge: `_default_shaping_profile()` and `_normalized_shaping_profile()` in `mvp_slow_bridge.py`. UI: `FAST_SLIDER_COMMANDS` or `FAST_QUICK_COMMANDS` in `mvp_ui_3.html`. Factory defaults: `mvp_factory_defaults.json` `shaping` if needed. |
| New lens type (e.g. Sony VISCA as slow) | Protocol: extend `lens_select` encoding and `SLOW_KEY_IDS` if needed. Head: lens_controller + apply branch; add VISCA mapping in this doc. |

Keep this file in sync when adding or renaming slow keys, fast (shaping) keys, or hardware (BGC, Canon, Fuji, Sony VISCA).
