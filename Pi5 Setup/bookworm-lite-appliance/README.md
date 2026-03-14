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
  - `Pi5 Setup/bookworm-lite-appliance/systemd/hydravision-boot-selfheal.service`

## Required package list

- `cage`
- `chromium-browser`
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
- `/usr/local/bin/hydravision-kiosk-browser-select`
- `/usr/local/bin/hydravision-boot-guard`
- `/usr/local/bin/hydravision-boot-selfheal`
- `/etc/default/hydravision-appliance`

## Browser launch command (example)

`cage -- /usr/local/bin/kiosk-browser`

The launcher opens:
`file:///opt/ui/boot.html` (black trampoline), then redirects to:
`file:///opt/ui/mvp_ui_3.html`

Installer enforces Chromium as default on each install run. To switch browser and roll back quickly:

```bash
sudo /usr/local/bin/hydravision-kiosk-browser-select chromium
sudo /usr/local/bin/hydravision-kiosk-browser-select firefox
```

## Boot resilience hardening

- Installer writes `/boot/firmware/cmdline.txt` atomically and normalizes permissions to `0644`.
- Last-known-good cmdline is stored at `/boot/firmware/hydravision_lkg/cmdline.txt`.
- `hydravision-boot-selfheal.service` runs at boot and restores cmdline from LKG if current cmdline is invalid, then reboots to apply.
- `hydravision-boot-guard` is also run during install as a fail-fast verifier.

## Ethernet automation

Installer configures static ethernet by default while leaving Wi-Fi available for SSH fallback.

- Policy: hostname suffix `00xx` -> `192.168.60.1xx`
- Example: `HydraVision-0003` -> `192.168.60.103`

Config in `/etc/default/hydravision-appliance`:

```bash
HYDRAVISION_ETH_ENABLE=1
HYDRAVISION_ETH_SUBNET_BASE=192.168.60
HYDRAVISION_ETH_PREFIX=24
HYDRAVISION_ETH_GATEWAY=192.168.60.1
HYDRAVISION_ETH_DNS=192.168.60.1
# optional fixed override:
# HYDRAVISION_ETH_STATIC_IP=192.168.60.103
```

Rotation:

- `HYDRAVISION_ROTATION_OUTPUT` and `HYDRAVISION_ROTATION_TRANSFORM` control display rotation.
- Installer auto-migrates historical typo key `HYDRAVISION_ROTATION_TRANSFOR` to `HYDRAVISION_ROTATION_TRANSFORM`.
- Touch rotation is now applied automatically during install using the same transform value (`HYDRAVISION_ROTATION_TRANSFORM`).
- Touch udev matching uses `ID_INPUT_TOUCHSCREEN=1` (capability-based), not panel-name matching. This avoids misses on devices that do not expose `TouchScreen` in `ATTRS{name}`.
- Manual helper remains available for override/testing:
  - `sudo hydravision-touch-rotate 90`
  - `sudo hydravision-touch-rotate 270`
  - `sudo hydravision-touch-rotate 180`
  - `sudo hydravision-touch-rotate 0`
  - `sudo hydravision-touch-rotate off`

If touch appears mirrored or unrotated while display rotation is correct, verify that the active rule is capability-based and includes your expected matrix:

```bash
cat /etc/udev/rules.d/99-hydravision-touch-rotation.rules
for d in /dev/input/event*; do
  echo "=== $d ==="
  udevadm info --query=property --name="$d" | sed -n '/^NAME=/p;/^ID_INPUT_TOUCHSCREEN=/p;/^LIBINPUT_CALIBRATION_MATRIX=/p'
done
```

If needed, reapply touch transform and restart kiosk:

```bash
sudo hydravision-touch-rotate 180   # example
sudo udevadm control --reload-rules
sudo udevadm trigger
sudo systemctl restart kiosk.service
```

## Install and enable

From repo root on Pi:

```bash
git fsck --full
sudo bash "Pi5 Setup/bookworm-lite-appliance/install.sh"
sudo reboot
```

If `git fsck` reports corrupt objects, reclone before running installer.

## Recovery notes

- If `kiosk.service`, `controller.service`, or `wsbridge.service` appears masked, run:
  - `sudo systemctl unmask controller.service wsbridge.service kiosk.service`
- If `/etc/systemd/system/kiosk.service` (or controller/wsbridge) is an empty file or symlink to `/dev/null`, remove it and rerun installer:
  - `sudo rm -f /etc/systemd/system/kiosk.service /etc/systemd/system/controller.service /etc/systemd/system/wsbridge.service`
- Installer now cleans stale unit overrides and fails fast if canonical unit files are not loadable.

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
