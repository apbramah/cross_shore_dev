#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

THEME_NAME="hydravision"
PLYMOUTH_DIR="/usr/share/plymouth/themes/${THEME_NAME}"
AUTOSTART_DIR="/home/pi/.config/autostart"
SYSTEMD_DIR="/etc/systemd/system"

echo "[1/5] Installing Plymouth theme..."
install -d "$PLYMOUTH_DIR"
cp -a "$SCRIPT_DIR/plymouth/hydravision.plymouth" "$PLYMOUTH_DIR/"
cp -a "$SCRIPT_DIR/plymouth/hydravision.script" "$PLYMOUTH_DIR/"

echo "[2/5] Updating boot flags..."
bash "$SCRIPT_DIR/scripts/pi5_boot_patch.sh"

echo "[3/5] Setting Plymouth default theme..."
if command -v plymouth-set-default-theme >/dev/null 2>&1; then
  plymouth-set-default-theme -R "$THEME_NAME"
else
  echo "plymouth-set-default-theme not found, skipping Plymouth initramfs rebuild."
fi

echo "[4/5] Installing systemd service..."
cp -a "$SCRIPT_DIR/systemd/mvp_bridge.service" "$SYSTEMD_DIR/"
systemctl daemon-reload
systemctl enable --now mvp_bridge.service

echo "[5/5] Installing kiosk autostart..."
install -d "$AUTOSTART_DIR"
cp -a "$SCRIPT_DIR/autostart/hydravision-kiosk.desktop" "$AUTOSTART_DIR/"

echo "Done. Reboot recommended."

