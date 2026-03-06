#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_ROOT="${APP_ROOT:-/home/admin/Dev/cross_shore_dev}"
KIOSK_USER="${KIOSK_USER:-admin}"

UI_DIR="/opt/ui"
WS_DIR="/opt/wsbridge"
CTRL_BIN="/usr/local/bin/controller_daemon"
WS_BIN="/usr/local/bin/wsbridge_daemon"
KIOSK_BROWSER_BIN="/usr/local/bin/kiosk-browser"
SYSTEMD_DIR="/etc/systemd/system"

UI_SRC_HTML="${APP_ROOT}/apps/controller/mvp_ui_3.html"
UI_SRC_LAYOUT="${APP_ROOT}/apps/controller/mvp_ui_3_layout.js"
WS_SRC_BRIDGE="${APP_ROOT}/apps/controller/mvp_slow_bridge.py"
WS_SRC_PROTOCOL="${APP_ROOT}/apps/controller/mvp_protocol.py"
HEADS_SRC="${APP_ROOT}/apps/controller/heads.json"
SEL_HEAD_SRC="${APP_ROOT}/apps/controller/mvp_selected_head.json"
SLOW_STATE_SRC="${APP_ROOT}/apps/controller/mvp_slow_state.json"
CTRL_SRC="${APP_ROOT}/apps/controller/mvp_bridge_adc.py"

echo "[1/8] Installing required packages..."
apt-get update -y
apt-get install -y \
  cage \
  firefox-esr \
  network-manager \
  openssh-server \
  python3 \
  python3-serial \
  python3-websockets \
  wlr-randr

echo "[2/8] Removing graphical layers not needed..."
apt-get purge -y plymouth plymouth-themes || true
apt-get autoremove -y || true

for dm in lightdm gdm gdm3 sddm display-manager; do
  systemctl disable --now "$dm" 2>/dev/null || true
done

echo "[3/8] Configuring boot cmdline..."
python3 - <<'PY'
from pathlib import Path

cmdline = Path("/boot/firmware/cmdline.txt")
line = cmdline.read_text().strip().splitlines()[0]
parts = [p for p in line.split(" ") if p]

drop_exact = {
    "quiet",
    "splash",
    "logo.nologo",
    "vt.global_cursor_default=0",
}
parts = [p for p in parts if p not in drop_exact]
parts = [p for p in parts if not p.startswith("loglevel=")]

parts += [
    "quiet",
    "splash",
    "loglevel=0",
    "vt.global_cursor_default=0",
    "logo.nologo",
]
cmdline.write_text(" ".join(parts) + "\n")
PY

echo "[4/8] Preparing appliance directories..."
install -d -m 755 "$UI_DIR" "$WS_DIR" /var/lib/kiosk/firefox /var/log/hydravision
chown -R "$KIOSK_USER:$KIOSK_USER" /var/lib/kiosk/firefox /var/log/hydravision

if [ ! -f "$UI_SRC_HTML" ] || [ ! -f "$UI_SRC_LAYOUT" ]; then
  echo "UI source files missing under $APP_ROOT/apps/controller"
  exit 1
fi

install -m 644 "$UI_SRC_HTML" "$UI_DIR/mvp_ui_3.html"
install -m 644 "$UI_SRC_LAYOUT" "$UI_DIR/mvp_ui_3_layout.js"

install -m 644 "$WS_SRC_BRIDGE" "$WS_DIR/mvp_slow_bridge.py"
install -m 644 "$WS_SRC_PROTOCOL" "$WS_DIR/mvp_protocol.py"
install -m 644 "$HEADS_SRC" "$WS_DIR/heads.json"
install -m 644 "$SEL_HEAD_SRC" "$WS_DIR/mvp_selected_head.json"
install -m 644 "$SLOW_STATE_SRC" "$WS_DIR/mvp_slow_state.json"

echo "[5/8] Installing daemon launchers..."
cat >"$CTRL_BIN" <<EOF
#!/usr/bin/env bash
set -euo pipefail
exec /usr/bin/python3 "$CTRL_SRC" -p /dev/ttyACM0 --host 127.0.0.1
EOF
chmod 755 "$CTRL_BIN"

cat >"$WS_BIN" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
cd /opt/wsbridge
exec /usr/bin/python3 /opt/wsbridge/mvp_slow_bridge.py
EOF
chmod 755 "$WS_BIN"

cat >"$KIOSK_BROWSER_BIN" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

PROFILE="/var/lib/kiosk/firefox"
mkdir -p "$PROFILE"

cat >"$PROFILE/user.js" <<'JS'
user_pref("browser.startup.homepage_override.mstone", "ignore");
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("browser.tabs.warnOnClose", false);
user_pref("browser.sessionstore.resume_from_crash", false);
user_pref("browser.aboutConfig.showWarning", false);
user_pref("toolkit.telemetry.reportingpolicy.firstRun", false);
user_pref("browser.display.background_color", "#000000");
JS

exec env MOZ_ENABLE_WAYLAND=1 /usr/bin/firefox-esr \
  --kiosk \
  --new-instance \
  --no-remote \
  --profile "$PROFILE" \
  "file:///opt/ui/mvp_ui_3.html"
EOF
chmod 755 "$KIOSK_BROWSER_BIN"
chown -R "$KIOSK_USER:$KIOSK_USER" "$WS_DIR"

echo "[6/8] Installing systemd unit files..."
install -m 644 "$SCRIPT_DIR/systemd/controller.service" "$SYSTEMD_DIR/controller.service"
install -m 644 "$SCRIPT_DIR/systemd/wsbridge.service" "$SYSTEMD_DIR/wsbridge.service"
install -m 644 "$SCRIPT_DIR/systemd/kiosk.service" "$SYSTEMD_DIR/kiosk.service"
install -m 644 "$SCRIPT_DIR/systemd/boot-splash-lock.service" "$SYSTEMD_DIR/boot-splash-lock.service"

systemctl daemon-reload

echo "[7/8] Applying appliance boot target and service policy..."
systemctl set-default multi-user.target

for svc in bluetooth cups ModemManager avahi-daemon triggerhappy; do
  systemctl disable --now "$svc" 2>/dev/null || true
done

systemctl disable --now NetworkManager-wait-online.service 2>/dev/null || true

systemctl disable --now getty@tty1.service 2>/dev/null || true
systemctl mask getty@tty1.service autovt@tty1.service || true

echo "[8/8] Enabling required services..."
systemctl enable --now NetworkManager.service
systemctl enable --now ssh.service
systemctl enable --now boot-splash-lock.service
systemctl enable --now controller.service
systemctl enable --now wsbridge.service
systemctl enable --now kiosk.service

echo "Install complete. Reboot recommended."
