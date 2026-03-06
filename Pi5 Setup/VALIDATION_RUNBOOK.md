# Pi5 Kiosk Validation Runbook

Acceptance tests and rollback/recovery procedure for the HydraVision Pi 5 kiosk.

## Pre-deployment checklist (before applying kiosk scripts)

- [ ] Raspberry Pi Imager used: Pi 5, Pi OS (64-bit) Bookworm desktop.
- [ ] Hostname, user `admin`, strong password, SSH with public-key only set in Imager.
- [ ] First boot: `sudo apt update && sudo apt full-upgrade -y`, then reboot.
- [ ] `echo $XDG_SESSION_TYPE` returns `wayland`.
- [ ] Touch and controller present: `ls /dev/input/by-id` shows expected devices.
- [ ] Baseline image backup created (recommended).

## Automated validation

Run after install:

```sh
sudo /usr/local/bin/hydravision-validate.sh
```

This checks: both bridge services enabled/active, ports 8765 and 8766 listening (when respective services are active), launcher scripts and env file present, unlock password not left as `CHANGE_ME`, SSH/logind/Firefox drop-ins when lockdown enabled, getty mask for tty2–6 when lockdown enabled, cage service when KIOSK_MODE=cage.

## Acceptance tests (manual)

### Boot and visibility

- [ ] **Cold boot timing:** Power on to interactive UI. Measure time; document for baseline.
- [ ] **Splash only:** No unintended boot text or logos beyond Plymouth HydraVision splash (and optional brief transition to browser).
- [ ] **Display:** Rotation correct if `HYDRAVISION_DISPLAY_ROTATE` was set; no black/blank hang.

### Functionality

- [ ] **Fast bridge:** UI receives joystick/ADC data (WS :8765). Operator can pan/tilt/focus/iris/zoom.
- [ ] **Slow bridge:** UI receives slow-path state (WS :8766). Any slow-state features work.
- [ ] **Touch:** Touchscreen input works in the controller UI.
- [ ] **Gamepad:** Physical game controller is recognized and axes/buttons map correctly in the UI.

### Security and lockdown

- [ ] **No terminal/files from kiosk:** Run dialog (Super+r), Ctrl+Alt+t, Alt+Tab, Alt+F4 do not open terminal or file manager (blocked or no-op).
- [ ] **VT switch blocked:** Ctrl+Alt+F1–F6 do not switch VTs (when lockdown enabled).
- [ ] **SSH key-only:** Password login disabled; key-based SSH as `admin` works.
- [ ] **Hidden unlock:** Ctrl+Alt+Shift+U opens password prompt; correct password closes kiosk browser and exposes desktop (or console in cage mode). Wrong password shows error; attempts visible in journal: `journalctl -t hydravision-admin-unlock`.

### Recovery

- [ ] **Disable kiosk autostart:** Remove `~/.config/autostart/hydravision-kiosk.desktop` (desktop mode); next login does not auto-start browser.
- [ ] **Rollback cage:** `sudo /usr/local/bin/hydravision-disable-cage.sh` and reboot restores display-manager and desktop session.
- [ ] **Remove lockdown:** `sudo /usr/local/bin/hydravision-remove-lockdown.sh` and reboot restores getty/VTs and eases Firefox policy.
- [ ] **Restore boot patch:** From rescue/single-user, copy `backup_hydravision_*` cmdline.txt and config.txt back to `/boot/firmware/` and reboot.

## Rollback and recovery procedure

### Quick rollback (from SSH or local shell)

1. Stop kiosk from auto-starting:
   ```sh
   rm -f ~/.config/autostart/hydravision-kiosk.desktop
   ```
2. If using cage mode, restore desktop session:
   ```sh
   sudo /usr/local/bin/hydravision-disable-cage.sh
   sudo reboot
   ```
3. If you need to re-enable TTYs and relax Firefox:
   ```sh
   sudo /usr/local/bin/hydravision-remove-lockdown.sh
   sudo reboot
   ```

### Re-enable legacy bridge

If you need the old single bridge instead of ADC + slow:

```sh
sudo systemctl disable --now mvp_bridge_adc.service mvp_slow_bridge.service
sudo systemctl enable --now mvp_bridge.service
```

### Single-user / rescue boot (when GUI and SSH are unusable)

1. Power off; remove SD card or mount boot partition from another system.
2. Edit `/boot/firmware/cmdline.txt`: append `systemd.unit=rescue.target` (or `single`).
3. Boot; at rescue shell, fix config (re-enable display-manager, remove kiosk autostart, etc.).
4. Restore cmdline: copy from `/boot/firmware/backup_hydravision_*/cmdline.txt` to `/boot/firmware/cmdline.txt` (remove the rescue.target append).
5. Reboot.

### Restore original boot flags

To undo only the boot patch (quiet/splash/display_rotate):

```sh
# From rescue or single-user, or after booting with backup cmdline once
sudo cp /boot/firmware/backup_hydravision_YYYYMMDD_HHMMSS/cmdline.txt /boot/firmware/cmdline.txt
sudo cp /boot/firmware/backup_hydravision_YYYYMMDD_HHMMSS/config.txt /boot/firmware/config.txt
sudo reboot
```

## Logs and diagnostics

- Bridge logs: `journalctl -u mvp_bridge_adc.service -u mvp_slow_bridge.service -f`
- Kiosk launcher log: `tail -f ~/.cache/hydravision-kiosk.log`
- Unlock attempts: `journalctl -t hydravision-admin-unlock`
- Cage service: `journalctl -u hydravision-cage.service -f`
