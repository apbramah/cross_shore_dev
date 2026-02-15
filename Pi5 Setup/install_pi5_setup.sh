#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

THEME_NAME="hydravision"
PLYMOUTH_DIR="/usr/share/plymouth/themes/${THEME_NAME}"
AUTOSTART_DIR="/home/admin/.config/autostart"
LABWC_DIR="/home/admin/.config/labwc"
SYSTEMD_DIR="/etc/systemd/system"

echo "[1/6] Ensuring Plymouth script plugin..."
if command -v apt-get >/dev/null 2>&1; then
  apt-get update -y
  apt-get install -y plymouth plymouth-themes plymouth-plugin-script
  apt-get install -y firefox-esr
fi

echo "[2/6] Installing Plymouth theme..."
install -d "$PLYMOUTH_DIR"
cp -a "$SCRIPT_DIR/plymouth/hydravision.plymouth" "$PLYMOUTH_DIR/"
cp -a "$SCRIPT_DIR/plymouth/hydravision.script" "$PLYMOUTH_DIR/"

echo "[3/6] Updating boot flags..."
bash "$SCRIPT_DIR/scripts/pi5_boot_patch.sh"

echo "[4/6] Setting Plymouth default theme..."
if command -v plymouth-set-default-theme >/dev/null 2>&1; then
  plymouth-set-default-theme -R "$THEME_NAME"
else
  echo "plymouth-set-default-theme not found, skipping Plymouth initramfs rebuild."
fi

if [ -f /etc/plymouth/plymouthd.conf ]; then
  cat >/etc/plymouth/plymouthd.conf <<EOF
[Daemon]
Theme=$THEME_NAME
EOF
fi

if command -v update-initramfs >/dev/null 2>&1; then
  update-initramfs -u
fi

echo "[5/6] Installing systemd service..."
cp -a "$SCRIPT_DIR/systemd/mvp_bridge.service" "$SYSTEMD_DIR/"
systemctl daemon-reload
systemctl enable --now mvp_bridge.service

echo "[6/6] Installing kiosk autostart..."
install -d "$AUTOSTART_DIR"
cp -a "$SCRIPT_DIR/autostart/hydravision-kiosk.desktop" "$AUTOSTART_DIR/"
install -d "$LABWC_DIR"
cp -a "$SCRIPT_DIR/labwc/autostart" "$LABWC_DIR/autostart"
chmod +x "$LABWC_DIR/autostart"

echo "Done. Reboot recommended."

