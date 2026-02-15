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

