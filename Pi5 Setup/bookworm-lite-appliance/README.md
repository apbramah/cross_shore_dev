# HydraVision Bookworm Lite Appliance Profile

This profile provides a reproducible Raspberry Pi 5 appliance boot path on Raspberry Pi OS Bookworm Lite:

EEPROM splash -> silent kernel boot -> systemd -> controller -> wsbridge -> kiosk (cage + browser) -> local UI

It is intentionally independent from Plymouth.

## Files

- Installer: `Pi5 Setup/bookworm-lite-appliance/install.sh`
- Units:
  - `Pi5 Setup/bookworm-lite-appliance/systemd/controller.service`
  - `Pi5 Setup/bookworm-lite-appliance/systemd/wsbridge.service`
  - `Pi5 Setup/bookworm-lite-appliance/systemd/kiosk.service`
  - `Pi5 Setup/bookworm-lite-appliance/systemd/boot-splash-lock.service`

## Required package list

- `cage`
- `firefox-esr`
- `network-manager`
- `openssh-server`
- `python3`
- `python3-serial`
- `python3-websockets`
- `wlr-randr`

## Directory layout

- `/opt/ui/boot.html`
- `/opt/ui/mvp_ui_3.html`
- `/opt/ui/mvp_ui_3_layout.js`
- `/opt/wsbridge/`
- `/usr/local/bin/controller_daemon`
- `/usr/local/bin/wsbridge_daemon`
- `/usr/local/bin/kiosk-browser`

## Browser launch command (example)

`cage -- /usr/local/bin/kiosk-browser`

The launcher opens:
`file:///opt/ui/boot.html` (black trampoline), then redirects to:
`file:///opt/ui/mvp_ui_3.html`

## Install and enable

From repo root on Pi:

```bash
sudo bash "Pi5 Setup/bookworm-lite-appliance/install.sh"
sudo reboot
```

## Expected systemd dependency graph

Minimal deterministic ordering:

- `controller.service`
- `wsbridge.service` (After=controller.service)
- `kiosk.service` (After=systemd-user-sessions.service, Wants=wsbridge.service)

No dependency on `network-online.target`.

## Boot analysis command

```bash
systemd-analyze critical-chain
```

Target critical chain shape:

- `multi-user.target`
  - `kiosk.service`

`controller.service` may still run in parallel with non-critical units depending on system load and ordering.
