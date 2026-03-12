# UI Command Display Matrix

Purpose:
- Map internal command keys to operator-facing UI labels.
- Keep technical/protocol naming out of customer-visible controls.
- Provide one place to approve naming language before implementation.

## Naming rules

- UI labels should describe operator intent, not protocol internals.
- Avoid exposing vendor/system internals (for example: BGC-specific wording).
- Prefer plain-language control names:
  - good: `PAN SPEED`
  - avoid: `shape_top_speed_yaw`

## Current baseline mappings

| Internal command key | Current UI display label |
|---|---|
| `shape_top_speed_yaw` | `PAN SPEED` |
| `shape_top_speed_pitch` | `TILT SPEED` |
| `shape_top_speed_roll` | `ROLL SPEED` |
| `shape_top_speed_zoom` | `ZOOM SPEED` |
| `shape_expo` | `PAN/TILT EXPO` |
| `shape_expo_zoom` | `ZOOM EXPO` |
| `shape_deadband_yaw` | `PAN DEAD-BAND` |
| `shape_deadband_pitch` | `TILT DEAD-BAND` |
| `shape_deadband_roll` | `ROLL DEAD-BAND` |
| `shape_deadband_zoom` | `ZOOM DEAD-BAND` |
| `shape_zoom_feedback` | `ZOOM FEEDBACK` |
| `motors_on` | `MOTORS` |
| `control_mode` | `CONTROL MODE` |
| `lens_select` | `LENS SELECT` |
| `source_zoom` | `ZOOM SOURCE` |
| `source_focus` | `FOCUS SOURCE` |
| `source_iris` | `IRIS SOURCE` |
| `filter_enable_focus` | `FOCUS FILTER` |
| `filter_enable_iris` | `IRIS FILTER` |
| `filter_num` | `FILTER NUM` |
| `filter_den` | `FILTER DEN` |
| `gyro_heading_correction` | `PAN TRIM` |
| `wash_wipe` | `WASH/WIPE` |

## Review workflow

1. Update this matrix first.
2. Validate wording with operator/customer stakeholders.
3. Apply approved labels in UI render layer only.
4. Keep protocol keys unchanged in backend/transport code.

