#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

THEME_NAME="hydravision"
PLYMOUTH_DIR="/usr/share/plymouth/themes/${THEME_NAME}"
AUTOSTART_DIR="/home/admin/.config/autostart"
LABWC_DIR="/home/admin/.config/labwc"
SYSTEMD_DIR="/etc/systemd/system"
BIN_DIR="/usr/local/bin"
SSHD_DROPIN_DIR="/etc/ssh/sshd_config.d"
ENABLE_SSH_HARDENING="${ENABLE_SSH_HARDENING:-1}"
ENABLE_KIOSK_LOCKDOWN="${ENABLE_KIOSK_LOCKDOWN:-1}"
KIOSK_MODE="${KIOSK_MODE:-desktop}"
KIOSK_ENV_FILE="/etc/default/hydravision-kiosk"
LOGIND_DROPIN_DIR="/etc/systemd/logind.conf.d"
FIREFOX_POLICY_DIR="/etc/firefox/policies"

echo "[1/6] Ensuring Plymouth script plugin..."
if command -v apt-get >/dev/null 2>&1; then
  apt-get update -y
  if apt-cache show plymouth-plugin-script >/dev/null 2>&1; then
    apt-get install -y plymouth plymouth-themes plymouth-plugin-script
  else
    echo "plymouth-plugin-script not available on this OS; continuing with base plymouth."
    apt-get install -y plymouth plymouth-themes
  fi
  apt-get install -y firefox-esr zenity openssh-server python3-websockets python3-serial imv librsvg2-bin wlr-randr
  if [ "$KIOSK_MODE" = "cage" ]; then
    apt-get install -y cage
  fi
fi

echo "[2/6] Installing Plymouth theme..."
install -d "$PLYMOUTH_DIR"
cp -a "$SCRIPT_DIR/plymouth/hydravision.plymouth" "$PLYMOUTH_DIR/"
cp -a "$SCRIPT_DIR/plymouth/hydravision.script" "$PLYMOUTH_DIR/"
cp -a "$SCRIPT_DIR/plymouth/hydravision_boot.svg" "$PLYMOUTH_DIR/"
install -d "/usr/share/hydravision"
if command -v rsvg-convert >/dev/null 2>&1; then
  rsvg-convert -w 1920 -h 1080 "$PLYMOUTH_DIR/hydravision_boot.svg" -o "/usr/share/hydravision/hydravision_boot.png" || true
fi

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

echo "[5/6] Installing systemd services..."
cp -a "$SCRIPT_DIR/systemd/mvp_bridge.service" "$SYSTEMD_DIR/"
cp -a "$SCRIPT_DIR/systemd/mvp_bridge_adc.service" "$SYSTEMD_DIR/"
cp -a "$SCRIPT_DIR/systemd/mvp_slow_bridge.service" "$SYSTEMD_DIR/"
systemctl daemon-reload
systemctl disable --now mvp_bridge.service || true
systemctl enable --now mvp_bridge_adc.service
systemctl enable --now mvp_slow_bridge.service

# Optional udev rule for serial/Teensy (ttyACM/ttyUSB) so bridge can access device reliably
if [ -f "$SCRIPT_DIR/udev/99-hydravision-serial.rules" ]; then
  install -m 644 "$SCRIPT_DIR/udev/99-hydravision-serial.rules" /etc/udev/rules.d/99-hydravision-serial.rules
  udevadm control --reload-rules || true
fi
# Ensure admin user is in dialout for serial access (idempotent)
if getent group dialout >/dev/null 2>&1; then
  usermod -aG dialout admin || true
fi

echo "[6/6] Installing kiosk autostart..."
install -d "$AUTOSTART_DIR"
cp -a "$SCRIPT_DIR/autostart/hydravision-kiosk.desktop" "$AUTOSTART_DIR/"
install -d "$LABWC_DIR"
cp -a "$SCRIPT_DIR/labwc/autostart" "$LABWC_DIR/autostart"
chmod +x "$LABWC_DIR/autostart"
install -d "$BIN_DIR"
install -m 755 "$SCRIPT_DIR/scripts/hydravision-kiosk-launch.sh" "$BIN_DIR/hydravision-kiosk-launch.sh"
install -m 755 "$SCRIPT_DIR/scripts/hydravision-admin-unlock.sh" "$BIN_DIR/hydravision-admin-unlock.sh"
install -m 755 "$SCRIPT_DIR/scripts/hydravision-remove-lockdown.sh" "$BIN_DIR/hydravision-remove-lockdown.sh"
install -m 755 "$SCRIPT_DIR/scripts/hydravision-validate.sh" "$BIN_DIR/hydravision-validate.sh"
install -m 755 "$SCRIPT_DIR/scripts/hydravision-cage-launch.sh" "$BIN_DIR/hydravision-cage-launch.sh"
install -m 755 "$SCRIPT_DIR/scripts/hydravision-splash-then-browser.sh" "$BIN_DIR/hydravision-splash-then-browser.sh"
install -m 755 "$SCRIPT_DIR/scripts/hydravision-disable-cage.sh" "$BIN_DIR/hydravision-disable-cage.sh"
if [ ! -f "$KIOSK_ENV_FILE" ]; then
  install -m 640 "$SCRIPT_DIR/config/hydravision-kiosk.env" "$KIOSK_ENV_FILE"
fi

if grep -q '^HYDRAVISION_KIOSK_MODE=' "$KIOSK_ENV_FILE"; then
  sed -i "s/^HYDRAVISION_KIOSK_MODE=.*/HYDRAVISION_KIOSK_MODE=${KIOSK_MODE}/" "$KIOSK_ENV_FILE"
else
  printf '\nHYDRAVISION_KIOSK_MODE=%s\n' "$KIOSK_MODE" >>"$KIOSK_ENV_FILE"
fi

chown root:admin "$KIOSK_ENV_FILE"
chmod 640 "$KIOSK_ENV_FILE"
python3 "$SCRIPT_DIR/scripts/labwc_configure_keybinds.py"
chown -R admin:admin "$LABWC_DIR" "$AUTOSTART_DIR"

if [ "$ENABLE_SSH_HARDENING" = "1" ]; then
  echo "[extra] Applying SSH hardening drop-in..."
  install -d "$SSHD_DROPIN_DIR"
  install -m 644 "$SCRIPT_DIR/ssh/99-hydravision-kiosk.conf" "$SSHD_DROPIN_DIR/99-hydravision-kiosk.conf"
  if systemctl list-unit-files | grep -q '^ssh\.service'; then
    systemctl restart ssh
  elif systemctl list-unit-files | grep -q '^sshd\.service'; then
    systemctl restart sshd
  fi
fi

if [ "$ENABLE_KIOSK_LOCKDOWN" = "1" ]; then
  echo "[extra] Applying kiosk lockdown profile..."
  install -d "$LOGIND_DROPIN_DIR"
  install -m 644 "$SCRIPT_DIR/logind/99-hydravision-kiosk.conf" "$LOGIND_DROPIN_DIR/99-hydravision-kiosk.conf"
  install -d "$FIREFOX_POLICY_DIR"
  install -m 644 "$SCRIPT_DIR/firefox/policies.json" "$FIREFOX_POLICY_DIR/policies.json"

  for tty in 2 3 4 5 6; do
    systemctl mask "getty@tty${tty}.service" >/dev/null 2>&1 || true
    systemctl mask "autovt@tty${tty}.service" >/dev/null 2>&1 || true
  done
  systemctl restart systemd-logind || true
fi

if [ "$KIOSK_MODE" = "cage" ]; then
  echo "[extra] Configuring single-app cage kiosk session..."
  cp -a "$SCRIPT_DIR/systemd/hydravision-cage.service" "$SYSTEMD_DIR/"
  systemctl daemon-reload
  systemctl disable --now getty@tty1.service || true
  systemctl mask getty@tty1.service || true
  systemctl mask autovt@tty1.service || true
  systemctl disable --now lightdm.service || true
  systemctl disable --now display-manager.service || true
  rm -f /home/admin/.config/autostart/hydravision-kiosk.desktop
  systemctl set-default multi-user.target
  systemctl enable --now hydravision-cage.service
else
  systemctl disable --now hydravision-cage.service || true
  systemctl unmask getty@tty1.service || true
  systemctl unmask autovt@tty1.service || true
fi

echo "Done. Reboot recommended."

