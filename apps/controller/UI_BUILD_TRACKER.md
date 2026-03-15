# UI Build Tracker (MVP UI 3)

Working tracker for customer-facing UI progression and engineering-layer features.

## Current Status

- Frontend has been updated for 800x480 readability and gloved operation.
- Top bar and Control tab have been reworked around operator flow.
- Backend work is intentionally deferred for new Dead Ahead messages.

## Completed (Frontend)

- Font/size pass for 800x480.
- Top bar restructured:
  - Head selection via custom large-button picker.
  - Disconnect button near head selector.
  - Removed manual WS URL entry and connect button.
  - Head ID readout with status border/glow:
    - grey = no physical layer
    - yellow = physical layer
    - green = connected
- Theme system in Engineering tab:
  - Starship
  - Black and White
  - Neon (electric turquoise glow)
  - Dayglow
- Control tab simplified to sliders-only.
- Slider bank refactor:
  - 2x3 layout (6 sliders)
  - larger touch targets for gloves
  - reduced padding / better vertical fill
  - compact labels (`S1:top_speed_yaw` style)
- Slider assignment controls in Engineering tab.
- Slow slider UX state:
  - pending hold
  - applied highlight after confirmation/readback
- Lockoff button added in top bar.
- Lockoff and Motors ON top-bar buttons size-matched for consistent touch targets.
- Control slider labels no longer show `S1`/slot prefixes; now use operator-facing names.
- Removed value text under control-page sliders (operator view now label + slider only).
- Control-page sliders now explicitly fill card height (track and slider expand to remaining box space).
- Renamed operator-facing `gyro_heading_correction` label from `GYRO HEADING` to `PAN TRIM`.
- Added top-bar `Home` button behavior:
  - tap: sends Home/Goto command
  - 3s hold: sends Set Home command
- Standardized top-bar button widths to equal size for gloved operation.
- Remapped page navigation to C-buttons:
  - `C1` -> Control page
  - `C2` -> Slow page
  - `C3` -> Fast page
  - `C4` -> Network page (IP + WiFi)
  - `C5` -> Engineering page
- Removed top tab strip and in-page section `<h3>` headers; primary navigation is now bottom-button only.
- Bottom navigation button labels now show page names (`Control`, `Slow`, `Fast`, `Network`, `Engineering`) instead of `C1..C5`.
- Added Control-page quick action row:
  - 5 equal-width buttons above sliders
  - assignment controls added to Engineering page
  - quick actions currently support enum/toggle-style fast/slow commands and cycle values on tap
  - **note:** final customer quick-button command list still needs to be formally defined
- Added new slow command key `wash_wipe`:
  - available in slider assignment and quick-button assignment lists
  - UI label: `WASH/WIPE`
  - values: `parked` / `wiping`
  - bridge/protocol/head key-id plumbing added; Servo PWM1 command mapping in BGC remains a TODO for final hardware-specific implementation
- Control slider live-axis overlay for speed assignments:
  - when assigned to `PAN SPEED`, `TILT SPEED`, or `ROLL SPEED`, a centered realtime bar is shown inside the slider track
  - bar expands left/right around center from shaped joystick demand telemetry (with local gamepad fallback)
- Added `UI_COMMAND_DISPLAY_MATRIX.md` to track internal-key to UI-label mapping and keep protocol/vendor naming out of customer UI text.
- Dead Ahead config controls added in Engineering tab:
  - yaw range
  - pitch range
  - roll range
  - dead-band
  - speed

## Pending (Backend)

Implement handlers in `mvp_slow_bridge.py` for:

- `SET_DEAD_AHEAD_CONFIG`
- `SET_DEAD_AHEAD_MODE`

Suggested handling pattern:

1. Validate payload ranges.
2. Persist selected values (state/profile file as agreed).
3. Forward/translate to BGC command path.
4. Return explicit result event (ok/fail/message).
5. Include resulting state in periodic `STATE` payload for UI readback.

## Pending (UI Follow-ups)

- Bind Lockoff visual state to authoritative backend readback (instead of local-only).
- Add explicit readback display for Dead Ahead config values in Engineering page.
- Optional: show concise operator-safe state strip (instead of raw JSON blocks) for final customer mode.
- Optional: per-theme fine tuning after hardware validation on Pi screen.

## Test Checklist (Quick)

- Head selection:
  - large picker opens, scrolls, and is glove-usable
  - selecting head auto-connects and sets active head
- Disconnect:
  - one-touch disconnect works
  - button style changes by connection state
- Head ID box:
  - shows `No Head` when disconnected
  - shows selected/connected head label when connected
  - border state color matches link/head state
- Control sliders:
  - 2x3 fills control page
  - labels readable and compact
  - assigned sliders send expected command class (fast vs slow)
  - pan/tilt/roll speed assignments show centered realtime axis bar
- Themes:
  - switch immediately
  - persist across refresh/restart

## Completed (Last 24h)

- Position Display panel restored and expanded:
  - top-bar `Pos Display` action opens panel
  - left telemetry block includes Pan/Tilt/Roll/Zoom/Iris/Focus
  - heading offset slider integrated and persisted
  - sim mode toggle from main UI into embedded map mode
- Position map standalone behavior updates:
  - heading indicator changed to circle + ray + moving triangle marker
  - triangle position now driven by lens-reported zoom (`zoom_norm`) and measured from center
  - bottom-left tilt/roll overlay instrument added (vertical rail + rotating indicator)
  - map scale bar added and map-control visual darkening
  - tile-provider failover chain + on-screen tile diagnostics added for Pi validation
- Engineering page updates:
  - Position map coordinate entry now supports what3words lookup (+ API key)
  - Theme Lab (8-color) added to main UI with:
    - live preview
    - custom-theme enable/disable
    - preset CRUD
    - JSON export/import for cross-device sharing
- Deployment/runtime hardening:
  - `deploy-to-pi.sh` now copies `position_map_standalone.html` into `/opt/ui/`
  - deploy script hash check includes standalone map file
  - map iframe URL cache-busting version key added to force updated asset load on kiosk

## Completed (Head IP programming + map validation)

- Head ID Configuration now supports explicit per-row **Push To Head** for network config.
- Validation gates added for legal IP inputs (IPv4 format, prefix bounds, subnet and gateway checks).
- Slow-channel network push is now transaction-based:
  - enter config mode
  - send network fields
  - apply
  - exit config mode
- Push status handling hardened:
  - route transition handling
  - duplicate late APPLY ACK guard
  - inferred success when target IP becomes reachable after transition
- Current runtime status: head IP programming working, map working.

