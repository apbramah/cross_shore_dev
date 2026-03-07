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
KIOSK_SELECT_BIN="/usr/local/bin/hydravision-kiosk-browser-select"
APPLIANCE_ENV="/etc/default/hydravision-appliance"
SYSTEMD_DIR="/etc/systemd/system"

UI_SRC_HTML="${APP_ROOT}/apps/controller/mvp_ui_3.html"
UI_SRC_LAYOUT="${APP_ROOT}/apps/controller/mvp_ui_3_layout.js"
WS_SRC_BRIDGE="${APP_ROOT}/apps/controller/mvp_slow_bridge.py"
WS_SRC_PROTOCOL="${APP_ROOT}/apps/controller/mvp_protocol.py"
HEADS_SRC="${APP_ROOT}/apps/controller/heads.json"
SEL_HEAD_SRC="${APP_ROOT}/apps/controller/mvp_selected_head.json"
SLOW_STATE_SRC="${APP_ROOT}/apps/controller/mvp_slow_state.json"
CTRL_SRC="${APP_ROOT}/apps/controller/mvp_bridge_adc.py"

cleanup_stale_unit_override() {
  local unit_name="$1"
  local unit_path="/etc/systemd/system/${unit_name}"
  if [ -L "$unit_path" ]; then
    local target
    target="$(readlink "$unit_path" || true)"
    if [ "$target" = "/dev/null" ]; then
      echo "Removing masked unit override: ${unit_path} -> /dev/null"
      rm -f "$unit_path"
    fi
  elif [ -f "$unit_path" ] && [ ! -s "$unit_path" ]; then
    echo "Removing empty unit override: ${unit_path}"
    rm -f "$unit_path"
  fi
}

echo "[1/8] Installing required packages..."
apt-get update -y
apt-get install -y \
  cage \
  chromium-browser \
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
    "systemd.show_status=false",
    "rd.systemd.show_status=false",
}
parts = [p for p in parts if p not in drop_exact]
drop_prefixes = (
    "loglevel=",
    "systemd.show_status=",
    "rd.systemd.show_status=",
    "systemd.log_level=",
    "udev.log_priority=",
    "console=tty1",
    "console=tty0",
)
parts = [p for p in parts if not any(p.startswith(prefix) for prefix in drop_prefixes)]

parts += [
    "quiet",
    "splash",
    "loglevel=0",
    "vt.global_cursor_default=0",
    "logo.nologo",
    "systemd.show_status=false",
    "rd.systemd.show_status=false",
    "systemd.log_level=emerg",
    "udev.log_priority=3",
]
if not any(p.startswith("console=tty3") for p in parts):
    parts.append("console=tty3")
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
cat >"$UI_DIR/boot.html" <<'EOF'
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    html, body {
      margin: 0;
      width: 100%;
      height: 100%;
      background: #000;
      overflow: hidden;
    }
  </style>
</head>
<body>
  <script>
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        location.replace("file:///opt/ui/mvp_ui_3.html");
      });
    });
  </script>
</body>
</html>
EOF

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

if [ ! -f "$APPLIANCE_ENV" ]; then
  cat >"$APPLIANCE_ENV" <<'EOF'
HYDRAVISION_KIOSK_BROWSER=chromium
HYDRAVISION_ROTATION_OUTPUT=DSI-2
HYDRAVISION_ROTATION_TRANSFORM=90
HYDRAVISION_BROWSER_START_DELAY=0.25
HYDRAVISION_ETH_ENABLE=1
HYDRAVISION_ETH_SUBNET_BASE=192.168.60
HYDRAVISION_ETH_PREFIX=24
HYDRAVISION_ETH_GATEWAY=192.168.60.1
HYDRAVISION_ETH_DNS=192.168.60.1
# Optional override:
# HYDRAVISION_ETH_STATIC_IP=192.168.60.103
EOF
fi
if grep -q '^HYDRAVISION_KIOSK_BROWSER=' "$APPLIANCE_ENV"; then
  sed -i 's/^HYDRAVISION_KIOSK_BROWSER=.*/HYDRAVISION_KIOSK_BROWSER=chromium/' "$APPLIANCE_ENV"
else
  printf '\nHYDRAVISION_KIOSK_BROWSER=chromium\n' >>"$APPLIANCE_ENV"
fi
chown root:root "$APPLIANCE_ENV"
chmod 644 "$APPLIANCE_ENV"

cat >"$KIOSK_BROWSER_BIN" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

if [ -r /etc/default/hydravision-appliance ]; then
  # shellcheck disable=SC1091
  . /etc/default/hydravision-appliance
fi

ROT_OUTPUT="${HYDRAVISION_ROTATION_OUTPUT:-DSI-2}"
ROT_TRANSFORM="${HYDRAVISION_ROTATION_TRANSFORM:-90}"
START_DELAY="${HYDRAVISION_BROWSER_START_DELAY:-0.25}"
BROWSER_CHOICE="${HYDRAVISION_KIOSK_BROWSER:-chromium}"

if command -v wlr-randr >/dev/null 2>&1; then
  wlr-randr --output "$ROT_OUTPUT" --transform "$ROT_TRANSFORM" >/dev/null 2>&1 || true
fi
sleep "$START_DELAY"

PROFILE="/var/lib/kiosk/firefox"
mkdir -p "$PROFILE"

cat >"$PROFILE/user.js" <<'JS'
user_pref("browser.startup.homepage_override.mstone", "ignore");
user_pref("browser.startup.blankWindow", false);
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("browser.tabs.warnOnClose", false);
user_pref("browser.sessionstore.resume_from_crash", false);
user_pref("browser.aboutConfig.showWarning", false);
user_pref("toolkit.telemetry.reportingpolicy.firstRun", false);
user_pref("ui.systemUsesDarkTheme", 1);
user_pref("browser.display.background_color", "#000000");
user_pref("app.update.auto", false);
user_pref("datareporting.healthreport.uploadEnabled", false);
user_pref("browser.startup.page", 0);
user_pref("browser.tabs.drawInTitlebar", false);
JS

case "$BROWSER_CHOICE" in
  chromium)
    exec /usr/bin/chromium-browser \
      --kiosk \
      --no-first-run \
      --noerrdialogs \
      --disable-infobars \
      --disable-session-crashed-bubble \
      --incognito \
      --ozone-platform=wayland \
      "file:///opt/ui/boot.html"
    ;;
  firefox|*)
    exec env MOZ_ENABLE_WAYLAND=1 /usr/bin/firefox-esr \
      --kiosk \
      --new-instance \
      --no-remote \
      --private-window \
      --profile "$PROFILE" \
      "file:///opt/ui/boot.html"
    ;;
esac
EOF
chmod 755 "$KIOSK_BROWSER_BIN"

cat >"$KIOSK_SELECT_BIN" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Usage: $0 <firefox|chromium>"
  exit 1
fi

choice="$1"
case "$choice" in
  firefox|chromium) ;;
  *)
    echo "Invalid browser choice: $choice"
    exit 1
    ;;
esac

env_file="/etc/default/hydravision-appliance"
if [ ! -f "$env_file" ]; then
  cat >"$env_file" <<'BASE'
HYDRAVISION_KIOSK_BROWSER=chromium
HYDRAVISION_ROTATION_OUTPUT=DSI-2
HYDRAVISION_ROTATION_TRANSFORM=90
HYDRAVISION_BROWSER_START_DELAY=0.25
BASE
fi

if grep -q '^HYDRAVISION_KIOSK_BROWSER=' "$env_file"; then
  sed -i "s/^HYDRAVISION_KIOSK_BROWSER=.*/HYDRAVISION_KIOSK_BROWSER=${choice}/" "$env_file"
else
  printf '\nHYDRAVISION_KIOSK_BROWSER=%s\n' "$choice" >>"$env_file"
fi

echo "Browser set to: $choice"
echo "Restarting kiosk.service..."
systemctl restart kiosk.service
EOF
chmod 755 "$KIOSK_SELECT_BIN"

chown -R "$KIOSK_USER:$KIOSK_USER" "$WS_DIR"

install -d /etc/firefox/policies
cat >/etc/firefox/policies/policies.json <<'EOF'
{
  "policies": {
    "DisableTelemetry": true,
    "DisableFirefoxStudies": true,
    "DisableAppUpdate": true,
    "DontCheckDefaultBrowser": true,
    "DisplayMenuBar": "never"
  }
}
EOF

echo "[6/8] Installing systemd unit files..."
cleanup_stale_unit_override controller.service
cleanup_stale_unit_override wsbridge.service
cleanup_stale_unit_override kiosk.service
install -m 644 "$SCRIPT_DIR/systemd/controller.service" "$SYSTEMD_DIR/controller.service"
install -m 644 "$SCRIPT_DIR/systemd/wsbridge.service" "$SYSTEMD_DIR/wsbridge.service"
install -m 644 "$SCRIPT_DIR/systemd/kiosk.service" "$SYSTEMD_DIR/kiosk.service"
install -m 644 "$SCRIPT_DIR/systemd/boot-splash-lock.service" "$SYSTEMD_DIR/boot-splash-lock.service"

systemctl daemon-reload
for unit in controller.service wsbridge.service kiosk.service boot-splash-lock.service; do
  fragment_path="$(systemctl show -p FragmentPath --value "$unit" 2>/dev/null || true)"
  if [ -z "$fragment_path" ] || [ ! -f "$fragment_path" ]; then
    echo "ERROR: Unit ${unit} is not loadable after install (FragmentPath='${fragment_path}')."
    exit 1
  fi
done

echo "[7/8] Applying appliance boot target and service policy..."
systemctl set-default multi-user.target

for svc in bluetooth cups ModemManager avahi-daemon triggerhappy; do
  systemctl disable --now "$svc" 2>/dev/null || true
done

systemctl disable --now NetworkManager-wait-online.service 2>/dev/null || true

systemctl disable --now getty@tty1.service 2>/dev/null || true
systemctl mask getty@tty1.service autovt@tty1.service || true
systemctl unmask controller.service wsbridge.service kiosk.service || true

echo "[8/8] Enabling required services..."
systemctl enable --now NetworkManager.service
systemctl enable --now ssh.service
systemctl enable --now boot-splash-lock.service
systemctl enable --now controller.service
systemctl enable --now wsbridge.service
systemctl enable --now kiosk.service

echo "[extra] Applying static ethernet profile (non-blocking)..."
bash -c '
set -euo pipefail
if [ ! -r /etc/default/hydravision-appliance ]; then
  exit 0
fi
. /etc/default/hydravision-appliance
if [ "${HYDRAVISION_ETH_ENABLE:-1}" != "1" ]; then
  echo "Ethernet automation disabled."
  exit 0
fi

SUBNET="${HYDRAVISION_ETH_SUBNET_BASE:-192.168.60}"
PREFIX="${HYDRAVISION_ETH_PREFIX:-24}"
GATEWAY="${HYDRAVISION_ETH_GATEWAY:-192.168.60.1}"
DNS="${HYDRAVISION_ETH_DNS:-192.168.60.1}"
STATIC_IP="${HYDRAVISION_ETH_STATIC_IP:-}"

if [ -z "$STATIC_IP" ]; then
  host_name="$(hostnamectl --static 2>/dev/null || hostname)"
  if [[ "$host_name" =~ ([0-9]+)$ ]]; then
    suffix_all="${BASH_REMATCH[1]}"
    suffix_two=$((10#${suffix_all} % 100))
    if [ "$suffix_two" -eq 0 ]; then
      suffix_two=1
    fi
    last_octet=$((100 + suffix_two))
    STATIC_IP="${SUBNET}.${last_octet}"
  else
    STATIC_IP="${SUBNET}.101"
  fi
fi

CONN_NAME="$(
  nmcli -t -f NAME,TYPE connection show \
    | awk -F: '"'"'$2=="802-3-ethernet"{print $1; exit}'"'"'
)"
if [ -z "$CONN_NAME" ]; then
  IFACE="$(
    nmcli -t -f DEVICE,TYPE device status \
      | awk -F: '"'"'$2=="ethernet"{print $1; exit}'"'"'
  )"
  if [ -n "$IFACE" ]; then
    CONN_NAME="Wired connection 1"
    nmcli connection add type ethernet ifname "$IFACE" con-name "$CONN_NAME" || true
  fi
fi

if [ -z "$CONN_NAME" ]; then
  echo "No ethernet connection profile found; skipping static ethernet setup."
  exit 0
fi

echo "Configuring $CONN_NAME => ${STATIC_IP}/${PREFIX} gw ${GATEWAY}"
nmcli connection modify "$CONN_NAME" \
  ipv4.method manual \
  ipv4.addresses "${STATIC_IP}/${PREFIX}" \
  ipv4.gateway "$GATEWAY" \
  ipv4.dns "$DNS" \
  ipv6.method ignore \
  connection.autoconnect yes
nmcli connection up "$CONN_NAME" || true
' || echo "Static ethernet setup failed; continuing."

echo "Install complete. Reboot recommended."
