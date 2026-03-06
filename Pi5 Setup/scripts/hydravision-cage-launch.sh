#!/usr/bin/env bash
set -euo pipefail

if [ -r /etc/default/hydravision-kiosk ]; then
  # shellcheck disable=SC1091
  . /etc/default/hydravision-kiosk
fi

UI_URL="${HYDRAVISION_UI_URL:-file:///home/admin/Dev/cross_shore_dev/apps/controller/mvp_ui_3.html}"
WS_HOST="${HYDRAVISION_WS_HOST:-127.0.0.1}"
WS_SLOW_PORT="${HYDRAVISION_WS_SLOW_PORT:-8766}"
WS_WAIT_SECONDS="${HYDRAVISION_WS_WAIT_SECONDS:-25}"
LOG="${HOME}/.cache/hydravision-kiosk.log"

mkdir -p "$(dirname "$LOG")"

wait_for_port() {
  local host="$1" port="$2" timeout="$3"
  python3 - "$host" "$port" "$timeout" <<'PY' || return 1
import socket
import sys
import time
host, port, timeout = sys.argv[1], int(sys.argv[2]), float(sys.argv[3])
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
  echo "==== $(date -Iseconds) HydraVision cage launch ===="
  echo "UI: ${UI_URL}"
  echo "Waiting for slow WS ${WS_HOST}:${WS_SLOW_PORT} (max ${WS_WAIT_SECONDS}s)"
} >>"$LOG"

if ! wait_for_port "$WS_HOST" "$WS_SLOW_PORT" "$WS_WAIT_SECONDS"; then
  echo "Slow bridge (${WS_SLOW_PORT}) was not ready within ${WS_WAIT_SECONDS}s." >>"$LOG"
fi

# Display awake (optional; cage may not have X)
xset s off >/dev/null 2>&1 || true
xset -dpms >/dev/null 2>&1 || true
xset s noblank >/dev/null 2>&1 || true

INNER_LAUNCHER="/usr/local/bin/hydravision-splash-then-browser.sh"
if [ ! -x "$INNER_LAUNCHER" ]; then
  echo "Inner launcher missing: $INNER_LAUNCHER" >>"$LOG"
  exit 1
fi

exec cage -- "$INNER_LAUNCHER" >>"$LOG" 2>&1