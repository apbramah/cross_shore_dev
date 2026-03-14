# Controller End - Executive Summary

## Current Runtime Shape (What is live now)

- Runtime is split into two coordinated planes:
  - **Slow/control plane:** `mvp_ui_3.html` -> WebSocket `mvp_slow_bridge.py` (`:8766`) -> UDP slow commands (`8890`).
  - **Fast/motion plane:** USB CDC ADC stream -> `mvp_bridge_adc.py` -> UDP fast packets (`8888`).
- Head selection is shared across both planes through `heads.json` + `mvp_selected_head.json`.
- Slow bridge now publishes a richer canonical `STATE` model (slow controls, apply status, shaping, defaults, telemetry, connection/network, Wi-Fi, calibration, UI defaults).

## End-to-End Data Flow

1. **Operator input**
   - Browser reads 15 encoder buttons (`CW/CCW/SW` for 5 encoder lanes) and touch controls.
2. **UI actions**
   - Sends `SELECT_HEAD`, `SET_SLOW_CONTROL`, `SET_SHAPING`, `SAVE/RESET_USER_DEFAULTS`, network and Wi-Fi actions, and `CALIBRATE_INPUTS`.
3. **Slow bridge (`mvp_slow_bridge.py`)**
   - Persists state, sends immediate/periodic slow commands, ingests ACK + telemetry, and publishes merged runtime state to UI.
4. **ADC bridge (`mvp_bridge_adc.py`)**
   - Ingests CDC `ADCv1` frames, applies shaping profile, and sends fast control packets to selected head.
5. **Calibration loop**
   - UI request file -> ADC sample median per axis -> center offset update in `adc_bridge_profile.json` -> status reflected back in UI.

## Key Runtime Behaviors Added

- Full slow-command coverage baseline with per-key apply status (`pending/sent/confirmed/rejected/send_error`).
- Shaping persistence with user defaults and factory reset behavior.
- Deadband controls exposed for `yaw/pitch/roll/zoom`.
- Input Tests diagnostics:
  - raw/accepted/debounce-suppressed/group-suppressed counters
  - per-encoder non-wrapping test values `0..10`
  - backend-configurable default debounce/lockout values.
- Wi-Fi provisioning and IP config workflows from UI.
- Connection status layering:
  - physical link
  - selected-head connectivity state
  - bridge/UI health
  - live Pi LAN snapshot separated from saved LAN config.

## Number Handling (Current Rule Set)

- **UI scale rule:**
  - default numeric controls target `0..10`
  - high-res slots use `0.0..10.0`
  - numeric fields are non-wrapping
  - text-backed values may wrap.
- **Shaping normalization:**
  - UI stores shaping on `0..10`
  - bridge maps to engineering ranges when writing ADC profile:
    - expo: `0..10 -> -1.0..1.0`
    - top speed: `0..10 -> 0.0..2.0`
    - deadband: `0..10 -> 0.0..0.25`
  - legacy shaping values are migrated forward during load.

## Telemetry Summary

- Lens telemetry includes canonical `positions` (`zoom/focus/iris`) + `lens_full_name`.
- Zoom telemetry now uses lens feedback with safe Fuji polling at ~3 Hz.
- Slow telemetry + ACK are filtered against selected head IP to avoid cross-head contamination.

## Practical Conclusion

- Controller runtime is now feature-complete for the expansion baseline with focus on deterministic behavior, persistence, and measurable diagnostics.
- Known risky path (full UI normalized stepping variant) was reverted after kiosk regression and replaced with safer incremental normalization.
