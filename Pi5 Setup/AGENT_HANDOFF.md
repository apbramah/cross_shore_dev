# HydraVision Pi5 Handoff (1-Page)

Use this as the quick start for a new agent. Full detail is in:
- `Pi5 Setup/SPLASH_HOLDER_DESIGN.md`

## Mission (non-negotiable)

- Deliver a fast, clean kiosk boot to operator UI.
- Keep HydraVision splash as a system-level splash path.
- No browser-only fake splash as final solution.
- Keep dual bridges auto-running.
- Keep kiosk locked down with hidden admin access path.

## Current known state

- Prior attempts had instability from:
  - OS mismatch behavior (trixie vs expected Bookworm behavior),
  - CRLF shell scripts on Pi,
  - `tty1` getty contention with cage,
  - mixed ad-hoc Pi edits not represented in repo.
- Rotation for active panel `DSI-2` is known good via:
  - `wlr-randr --output DSI-2 --transform 90`
- Kernel/firmware rotation flags may be ignored on this DSI path.

## OS decision

- Preferred baseline: **Raspberry Pi OS (64-bit) Bookworm Desktop**.
- If staying on trixie, treat as compatibility mode with visual limitations and test every assumption.

## Do-this-first process

1. Classify Pi state: clean baseline vs contaminated.
2. Ensure remote control path (SSH) and known desktop recovery path work.
3. Enforce repo-first deployment (no ad-hoc unmanaged edits).
4. Apply kiosk stack in controlled phases with one verification gate per phase.
5. Persist compositor-level rotation for `DSI-2`.
6. Run acceptance checklist (visual, function, security, stability).

## Required behavior gates

1. Visual:
   - No desktop exposure to customer.
   - HydraVision splash path present.
   - Minimize/avoid black cursor gaps.
2. Function:
   - `mvp_bridge_adc.service` and `mvp_slow_bridge.service` healthy.
   - Touch + controller active in UI.
3. Security:
   - Operator cannot open repo/files/terminal.
   - Hidden unlock + key-only SSH path works.
4. Stability:
   - Repeatable cold-boot success (10 cycles target).

## Agent rules

- One command at a time; wait for output.
- Label facts vs assumptions.
- Provide rollback command before risky changes.
- Do not claim "final fix" until acceptance gates pass.
- Do not deviate from requirement without explicit user sign-off.
