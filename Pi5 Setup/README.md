# Pi5 Setup - HydraVision Boot and Kiosk

This folder contains the scripts and configs to:
- Hide Raspberry Pi OS boot branding/text
- Show a custom fade-in HydraVision splash on a dark background
- Auto-run the Python bridge and open the UI fullscreen in Firefox ESR

## Assumptions
- Raspberry Pi OS Desktop (64-bit) on Pi 5
- Project checked out at `/home/admin/Dev/cross_shore_dev`
- UI file is `/home/admin/Dev/cross_shore_dev/apps/controller/mvp_ui.html`
- Bridge file is `/home/admin/Dev/cross_shore_dev/apps/controller/mvp_bridge.py`

If your paths differ, edit:
- `Pi5 Setup/systemd/mvp_bridge.service` (ExecStart and WorkingDirectory)
- `Pi5 Setup/autostart/hydravision-kiosk.desktop` (file URL)

## Quick install
On the Pi, from the repo root:
```sh
sudo bash "Pi5 Setup/install_pi5_setup.sh"
sudo reboot
```

## What gets installed
- Plymouth theme: `/usr/share/plymouth/themes/hydravision`
- Plymouth default theme: `hydravision`
- Boot cmdline/config tweaks to reduce text/logos
- systemd service: `mvp_bridge.service`
- Autostart: `~/.config/autostart/hydravision-kiosk.desktop`
- Labwc autostart (Wayland): `~/.config/labwc/autostart`

## Notes
- The splash text is rendered by Plymouth itself (no external image file needed).
- On Wayland (labwc), the kiosk is launched from `~/.config/labwc/autostart`.
- Firefox ESR is used to avoid keyring prompts.
- Labwc kiosk log: `~/.cache/hydravision-kiosk.log`
- The installer backs up `/boot/firmware/cmdline.txt` and `/boot/firmware/config.txt`
  to `/boot/firmware/backup_hydravision_YYYYMMDD_HHMMSS/`.
- To disable kiosk/autostart, remove the desktop file or disable the service:
  - `sudo systemctl disable --now mvp_bridge.service`
  - `rm ~/.config/autostart/hydravision-kiosk.desktop`

