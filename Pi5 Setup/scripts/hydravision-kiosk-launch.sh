#!/usr/bin/env bash
set -euo pipefail

if [ -f /etc/default/hydravision-kiosk ]; then
  # shellcheck disable=SC1091
  . /etc/default/hydravision-kiosk
fi

LOG="${HOME}/.cache/hydravision-kiosk.log"
UI_URL="${HYDRAVISION_UI_URL:-file:///home/admin/Dev/cross_shore_dev/apps/controller/mvp_ui.html}"
WS_FAST_HOST="${HYDRAVISION_WS_HOST:-127.0.0.1}"
WS_FAST_PORT="${HYDRAVISION_WS_FAST_PORT:-8765}"
WS_SLOW_PORT="${HYDRAVISION_WS_SLOW_PORT:-8766}"
WS_WAIT_SECONDS="${HYDRAVISION_WS_WAIT_SECONDS:-25}"

mkdir -p "$(dirname "$LOG")"

wait_for_port() {
  local host="$1"
  local port="$2"
  local timeout="$3"

  python3 - "$host" "$port" "$timeout" <<'PY'
import socket
import sys
import time

host = sys.argv[1]
port = int(sys.argv[2])
timeout = float(sys.argv[3])
deadline = time.time() + timeout

while time.time() < deadline:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            sys.exit(0)
    except OSError:
        time.sleep(0.2)

sys.exit(1)
PY
}

{
  echo "==== $(date -Iseconds) HydraVision kiosk launch ===="
  echo "UI: ${UI_URL}"
  echo "Waiting for WS ${WS_FAST_HOST}:${WS_FAST_PORT} and ${WS_FAST_HOST}:${WS_SLOW_PORT}"
} >>"$LOG"

xset s off >/dev/null 2>&1 || true
xset -dpms >/dev/null 2>&1 || true
xset s noblank >/dev/null 2>&1 || true

if ! wait_for_port "$WS_FAST_HOST" "$WS_FAST_PORT" "$WS_WAIT_SECONDS"; then
  echo "Fast bridge socket was not ready within ${WS_WAIT_SECONDS}s." >>"$LOG"
fi
if ! wait_for_port "$WS_FAST_HOST" "$WS_SLOW_PORT" "$WS_WAIT_SECONDS"; then
  echo "Slow bridge socket was not ready within ${WS_WAIT_SECONDS}s." >>"$LOG"
fi

FIREFOX_BIN="$(command -v firefox-esr || command -v firefox || true)"
if [ -z "$FIREFOX_BIN" ]; then
  echo "Firefox was not found in PATH." >>"$LOG"
  exit 1
fi

while true; do
  MOZ_ENABLE_WAYLAND=1 "$FIREFOX_BIN" \
    --kiosk \
    --private-window \
    --new-instance \
    "${UI_URL}" >>"$LOG" 2>&1
  echo "Firefox exited; restarting in 2s." >>"$LOG"
  sleep 2
done
