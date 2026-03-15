# Pi5 Setup - Troubleshooting Notes

This file documents what was attempted and where it failed on the Pi 5.

## Context
- Pi OS Desktop (Wayland labwc)
- Repo path: `/home/admin/Dev/cross_shore_dev`

## What was attempted
1) Plymouth script-based text splash
- Theme installed at `/usr/share/plymouth/themes/hydravision`
- Default theme set to `hydravision`
- Boot cmdline includes `quiet splash loglevel=3 vt.global_cursor_default=0 plymouth.ignore-serial-consoles`
- Result: boot shows a blank white splash with no text
- Status: likely Plymouth script text rendering fails on this firmware/driver. Needs PNG-based splash as fallback.

2) Chromium kiosk autostart (labwc)
- Autostart configured in `~/.config/labwc/autostart`
- Chromium launched with kiosk flags and keyring suppression flags
- Result: keyring password prompt still appears
- Status: Chromium keyring prompt could not be suppressed reliably in this environment.

3) Cog (WPE WebKit) kiosk
- Switched autostart to `cog` for Wayland to avoid keyring
- Result: `cog` not available on this Pi OS repo (`apt-cache search cog` returned no browser package)
- Status: cannot install Cog from default repositories.

4) Firefox ESR kiosk
- Switched autostart to `firefox-esr --kiosk --private-window`
- Pending validation in this environment at time of handoff

## Evidence (from Pi)
- Splash: still blank white screen
- `cog` binary missing:
  - `/usr/bin/cog` not found
  - `apt-cache search cog` returned unrelated packages

## Next recommended steps (not executed)
- Replace Plymouth script text with a PNG splash for reliable rendering.
- Use Firefox ESR for kiosk under labwc, or configure a different compositor/startup where Chromium keyring can be disabled.

## Additional runtime notes (2026-03-15)

5) Position Display panel opens but map is blank
- Symptom: Position Display shell loads, but map area is empty on Pi Chromium.
- Root cause seen in this cycle: `position_map_standalone.html` not copied into `/opt/ui/` during deploy.
- Fix: include explicit install of `apps/controller/position_map_standalone.html` to `/opt/ui/` in deploy steps/script, then restart kiosk/wsbridge and verify file hash.

6) Position Display map shows no tiles
- Symptom: standalone map loads but no tile imagery appears.
- Mitigations added:
  - multi-provider tile fallback chain in standalone map
  - on-screen tile status diagnostics
- Operational interpretation: if runtime file hashes match and diagnostics still report no tiles, likely outbound network/CDN access constraints on Pi environment.

7) Pi browser cache can hide new standalone map updates
- Symptom: recent map fixes appear to have no effect despite redeploy.
- Mitigation added: cache-busting version query parameter on Position Display iframe URL.

## Resolved in current build (2026-03-15)

8) Head IP programming from controller
- Result: working with transaction-mode network push (`ENTER`/`APPLY`/`EXIT`) and strict IP/prefix/gateway validation.
- Bridge now guards against duplicate late APPLY ACKs and can infer success on timeout when target IP becomes reachable.
- Operational note: when using Pico via Thonny, updated `apps/head_eng/main.py` must be saved to device as `main.py` and rebooted.

9) Position map runtime behavior
- Result: working in deployed runtime when `position_map_standalone.html` is present in `/opt/ui/` and hashes match source.

