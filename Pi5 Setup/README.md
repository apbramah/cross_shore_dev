# Pi5 Setup - HydraVision Boot and Kiosk

This folder contains deployment assets for a locked-down Pi 5 kiosk: quiet boot with HydraVision splash, dual bridges (ADC + slow), fullscreen operator UI in Firefox, SSH hardening, optional lockdown, and optional cage-based single-app session.

## Assumptions

- Raspberry Pi OS Desktop (64-bit), Bookworm, on Pi 5.
- Repo path: `/home/admin/Dev/cross_shore_dev`.
- UI file: `/home/admin/Dev/cross_shore_dev/apps/controller/mvp_ui_3.html`.
- Runtime user is `admin`.

If your paths differ, edit:

- `Pi5 Setup/systemd/*.service`
- `Pi5 Setup/scripts/hydravision-kiosk-launch.sh`

---

## Boot sequence (order of events)

1. **Power-on** — Firmware/bootloader runs.
2. **Kernel** — `cmdline.txt` applied (quiet, splash, loglevel=3, Plymouth flags).
3. **Initramfs** — Plymouth runs with the HydraVision theme and splash asset.
4. **Root FS** — Systemd brings up userspace.
5. **Bridges** — `mvp_bridge_adc.service` and `mvp_slow_bridge.service` start (WebSocket :8765 and :8766).
6. **Display** — Either `display-manager.service` (labwc desktop) or `hydravision-cage.service` (cage mode).
7. **Session** — labwc or cage starts; autostart runs.
8. **Kiosk launcher** — `hydravision-kiosk-launch.sh` runs (from labwc autostart or cage).
9. **Browser** — Firefox (or cage+Firefox) opens the controller UI URL.
10. **Ready** — Operator UI is loaded and usable.

---

## Assets required

### Plymouth (boot splash)

| Asset | Installed path |
|-------|----------------|
| Theme dir | `/usr/share/plymouth/themes/hydravision` |
| Theme descriptor | `/usr/share/plymouth/themes/hydravision/hydravision.plymouth` |
| Watermark image | `/usr/share/plymouth/themes/hydravision/watermark.png` |
| Splash image | `/usr/share/plymouth/themes/hydravision/hydravision_boot.svg` |

Source paths under this repo: `Pi5 Setup/plymouth/` (`.plymouth`, `hydravision_boot.svg`).

HydraVision uses a non-script Plymouth theme path on Bookworm-class targets, so it does not depend on `plymouth-plugin-script`.
If HydraVision activation fails, installer falls back to a non-branded Plymouth theme (`text` by default, configurable via `HYDRAVISION_PLYMOUTH_FALLBACK_THEME`).

### Boot configuration

| Asset | Path | Notes |
|-------|------|--------|
| Kernel cmdline | `/boot/firmware/cmdline.txt` | Patched by `pi5_boot_patch.sh` (quiet, splash, loglevel, Plymouth flags). |
| Firmware config | `/boot/firmware/config.txt` | Patched by `pi5_boot_patch.sh` (`disable_splash`, optional `display_rotate` override). |
| Backup dir | `/boot/firmware/backup_hydravision_*` | Timestamped backup of cmdline/config before patch. |

Patch script: `Pi5 Setup/scripts/pi5_boot_patch.sh`.

### Systemd services

| Service | Purpose |
|---------|--------|
| `mvp_bridge_adc.service` | Fast path bridge, WS :8765. |
| `mvp_slow_bridge.service` | Slow path bridge, WS :8766. |
| `mvp_bridge.service` | Legacy bridge; installed but disabled. |
| `hydravision-cage.service` | Optional; cage + Firefox instead of desktop session. |

Source: `Pi5 Setup/systemd/*.service`.

### Udev (serial/controller)

| Asset | Path | Notes |
|-------|------|--------|
| Serial rules | `Pi5 Setup/udev/99-hydravision-serial.rules` | Installed to `/etc/udev/rules.d/`; ensures ttyACM/ttyUSB are group `dialout`. Admin is added to group `dialout` so `mvp_bridge_adc.service` can open the Teensy port. |

### Launchers and helpers (installed to `/usr/local/bin`)

| Script | Purpose |
|--------|---------|
| `hydravision-kiosk-launch.sh` | Starts Firefox (or cage+Firefox) to controller UI. |
| `hydravision-configure-ethernet.sh` | Applies static Ethernet config via NetworkManager. |
| `hydravision-admin-unlock.sh` | Unlock kiosk with password (Ctrl+Alt+Shift+U). |
| `hydravision-remove-lockdown.sh` | Remove lockdown profile. |
| `hydravision-validate.sh` | Kiosk readiness check. |
| `hydravision-cage-launch.sh` | Cage session launcher. |
| `hydravision-disable-cage.sh` | Disable cage and return to desktop session. |

Source: `Pi5 Setup/scripts/`.

### Session / Wayland

| Asset | Path |
|-------|------|
| Kiosk autostart desktop | `~/.config/autostart/hydravision-kiosk.desktop` |
| labwc autostart script | `~/.config/labwc/autostart` |
| labwc keybind config | `~/.config/labwc/rc.xml` (keybind patch for unlock) |

Source: `Pi5 Setup/autostart/`, `Pi5 Setup/labwc/`.

### Config drop-ins (when lockdown/hardening enabled)

| Asset | Path |
|-------|------|
| SSH | `/etc/ssh/sshd_config.d/99-hydravision-kiosk.conf` |
| Logind | `/etc/systemd/logind.conf.d/99-hydravision-kiosk.conf` |
| Firefox policy | `/etc/firefox/policies/policies.json` |

Source: `Pi5 Setup/ssh/`, `Pi5 Setup/logind/`, `Pi5 Setup/firefox/`.

### Kiosk environment

| Asset | Path |
|-------|------|
| Env file | `/etc/default/hydravision-kiosk` (optional; created by install if missing) |

---

## Screen rotation (definitive)

By default, rotation is applied at compositor level with `wlr-randr` in the kiosk launch path. This is the required behavior for the known Pi 5 DSI panel path.

| Variable | Values | Effect |
|----------|--------|--------|
| `HYDRAVISION_OUTPUT_NAME` | e.g. `DSI-2` | Output name to transform. |
| `HYDRAVISION_OUTPUT_TRANSFORM` | `normal`, `90`, `180`, `270`, ... | Transform value passed to `wlr-randr`. |

Set these in `/etc/default/hydravision-kiosk`:

```sh
HYDRAVISION_OUTPUT_NAME=DSI-2
HYDRAVISION_OUTPUT_TRANSFORM=90
```

Boot-level rotation is optional compatibility mode only:

| Variable | Values | Effect |
|----------|--------|--------|
| `HYDRAVISION_BOOT_DISPLAY_ROTATE` | `0..3` | Writes `display_rotate` in `/boot/firmware/config.txt` when explicitly set. |

Example:

```sh
sudo HYDRAVISION_BOOT_DISPLAY_ROTATE=1 bash "Pi5 Setup/scripts/pi5_boot_patch.sh"
sudo reboot
```

---

## Raspberry Pi Imager baseline (recommended)

Use this baseline before running install scripts:

1. Device: **Raspberry Pi 5**
2. OS: **Raspberry Pi OS (64-bit)** (Bookworm desktop)
3. Advanced options: hostname per unit, user `admin` with strong password, enable SSH with public-key auth, locale/timezone/keyboard set correctly.

After first boot:

```sh
sudo apt update && sudo apt full-upgrade -y
sudo reboot
```

---

## Quick install

On the Pi, from repo root:

```sh
sudo bash "Pi5 Setup/install_pi5_setup.sh"
sudo reboot
```

Example with compositor transform set to 90°:

```sh
sudo HYDRAVISION_OUTPUT_NAME=DSI-2 HYDRAVISION_OUTPUT_TRANSFORM=90 \
  bash "Pi5 Setup/install_pi5_setup.sh"
sudo reboot
```

### Single-app session install (cage + browser)

To run without desktop-session autostart and minimize desktop flash:

```sh
sudo KIOSK_MODE=cage bash "Pi5 Setup/install_pi5_setup.sh"
sudo reboot
```

### Static Ethernet policy (fleet)

Installer applies static Ethernet by default (`HYDRAVISION_ETH_ENABLE=1`) using NetworkManager:

- Hostname pattern `HydraVision-00xx` maps to `192.168.60.1xx`
- Example: `HydraVision-0002` -> `192.168.60.102`
- Defaults:
  - subnet base: `192.168.60`
  - prefix: `/24`
  - gateway: `192.168.60.1`
  - DNS: `192.168.60.1`

Override options in `/etc/default/hydravision-kiosk`:

```sh
HYDRAVISION_ETH_ENABLE=1
HYDRAVISION_ETH_SUBNET_BASE=192.168.60
HYDRAVISION_ETH_PREFIX=24
HYDRAVISION_ETH_GATEWAY=192.168.60.1
HYDRAVISION_ETH_DNS=192.168.60.1
# optional fixed override:
HYDRAVISION_ETH_STATIC_IP=192.168.60.102
```

To apply manually after install:

```sh
sudo /usr/local/bin/hydravision-configure-ethernet.sh
```

Rollback to desktop-session mode:

```sh
sudo /usr/local/bin/hydravision-disable-cage.sh
sudo reboot
```

---

## Secret local unlock flow

1. Set unlock password in environment before starting session:
   ```sh
   export HYDRAVISION_ADMIN_UNLOCK_PASSWORD='your-secret-password'
   ```
2. In kiosk session press **Ctrl+Alt+Shift+U**.
3. Enter password in prompt.
4. Kiosk browser exits and desktop becomes accessible.

For persistent unlock password on a device, add the variable via a secure systemd environment source. Do not store it in the repo.

**Secret backdoor design (support access):** The unlock hotkey is the only visible escape; it opens an on-screen password prompt (zenity). On correct password, the kiosk browser is closed so the operator sees the labwc desktop (desktop mode) or a console (cage mode on tty1). Unlock attempts and outcomes are logged to the system journal (`logger -t hydravision-admin-unlock`). Remote support uses SSH with key-only authentication (password auth disabled); no separate “backdoor” service.

---

## SSH hardening behavior

Default installer behavior applies key-only SSH hardening (`ENABLE_SSH_HARDENING=1`): password login disabled, root login disabled, forwarding/agent forwarding disabled.

To skip SSH hardening during install:

```sh
sudo ENABLE_SSH_HARDENING=0 bash "Pi5 Setup/install_pi5_setup.sh"
```

---

## Kiosk lockdown profile

## Kiosk lockdown profile

Default installer behavior applies lockdown (`ENABLE_KIOSK_LOCKDOWN=1`): masks TTY services tty2–tty6, reduces alternate VTs via logind, applies Firefox enterprise policy (blocks dev tools/about:config/add-ons), binds common escape keys in labwc to no-op commands (including run dialog `Super+r`, new terminal `Ctrl+Alt+t`, Alt+Tab, Alt+F4, and Ctrl+Alt+F1–F6 VT switch). Customer cannot open terminal or file manager from the kiosk session. Touch and gamepad input are available at kiosk launch; ensure touchscreen and controller are present under `/dev/input/` before applying lockdown.

To skip lockdown during install:

```sh
sudo ENABLE_KIOSK_LOCKDOWN=0 bash "Pi5 Setup/install_pi5_setup.sh"
```

---

## Operations and checks

- Run full kiosk readiness check:
  ```sh
  sudo /usr/local/bin/hydravision-validate.sh
  ```
- Acceptance tests and rollback procedure: see **Pi5 Setup/VALIDATION_RUNBOOK.md**.
- Check cage mode service (if enabled):
  ```sh
  systemctl status hydravision-cage.service
  ```
- Service status:
  ```sh
  systemctl status mvp_bridge_adc.service mvp_slow_bridge.service
  ```
- Follow logs:
  ```sh
  journalctl -u mvp_bridge_adc.service -f
  journalctl -u mvp_slow_bridge.service -f
  tail -f ~/.cache/hydravision-kiosk.log
  ```
- Enabled state:
  ```sh
  systemctl is-enabled mvp_bridge.service mvp_bridge_adc.service mvp_slow_bridge.service
  ```

---

## Recovery and disable

### Normal recovery (from running system)

- Stop kiosk/browser autostart:
  ```sh
  rm -f ~/.config/autostart/hydravision-kiosk.desktop
  ```
- Re-enable legacy bridge if needed:
  ```sh
  sudo systemctl disable --now mvp_bridge_adc.service mvp_slow_bridge.service
  sudo systemctl enable --now mvp_bridge.service
  ```
- Remove lockdown controls (if needed for service/debug):
  ```sh
  sudo /usr/local/bin/hydravision-remove-lockdown.sh
  sudo reboot
  ```

### Recovery: single-user and TTY fallback

If the kiosk or display is unusable and you need console access:

1. **TTY1 (cage mode)**  
   When `hydravision-cage.service` is enabled, the session runs on tty1. You can plug a USB keyboard and switch to a different VT only if you have not locked down VTs (e.g. if `ENABLE_KIOSK_LOCKDOWN=0` was used). If VTs are masked, use single-user or SSH.

2. **SSH (preferred)**  
   With SSH hardening enabled, use key-based SSH as `admin`. Then:
   ```sh
   sudo systemctl stop hydravision-cage.service   # if cage mode
   sudo systemctl start display-manager.service   # restore desktop
   # or disable kiosk autostart, remove lockdown, etc.
   ```

3. **Single-user / recovery kernel cmdline**  
   To get a root shell at boot (e.g. from another machine via serial, or by editing cmdline on the SD card):
   - Mount the boot partition and edit `cmdline.txt`.
   - Append `systemd.unit=rescue.target` (or `single`) to the kernel command line.
   - Reboot; you get a rescue/single-user root shell. Fix config, then reboot normally.
   - Restore cmdline from backup under `/boot/firmware/backup_hydravision_*` if needed.

4. **Revert boot patch from rescue**  
   From rescue or single-user:
   ```sh
  cp /boot/firmware/backup_hydravision_YYYYMMDD_HHMMSS/cmdline.txt /boot/firmware/cmdline.txt
  cp /boot/firmware/backup_hydravision_YYYYMMDD_HHMMSS/config.txt /boot/firmware/config.txt
   ```
   Then reboot. This restores pre-patch cmdline/config (removes quiet/splash and any optional display_rotate override).
