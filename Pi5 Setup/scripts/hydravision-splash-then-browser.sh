#!/usr/bin/env bash
set -euo pipefail

if [ -r /etc/default/hydravision-kiosk ]; then
  # shellcheck disable=SC1091
  . /etc/default/hydravision-kiosk
fi

LOG="${HOME}/.cache/hydravision-kiosk.log"
UI_URL="${HYDRAVISION_UI_URL:-file:///home/admin/Dev/cross_shore_dev/apps/controller/mvp_ui.html}"
SPLASH_IMG="${HYDRAVISION_SPLASH_IMAGE:-/usr/share/hydravision/hydravision_boot.png}"
SPLASH_HOLD_SECONDS="${HYDRAVISION_SPLASH_HOLD_SECONDS:-2}"
PROFILE_DIR="${HOME}/.hydravision-firefox-profile"

mkdir -p "$(dirname "$LOG")" "$PROFILE_DIR"

{
  echo "==== $(date -Iseconds) HydraVision splash-then-browser ===="
  echo "UI: ${UI_URL}"
  echo "Splash image: ${SPLASH_IMG}"
  echo "Splash hold seconds: ${SPLASH_HOLD_SECONDS}"
} >>"$LOG"

IMV_BIN="$(command -v imv-wayland || command -v imv || true)"
SPLASH_PID=""
if [ -n "$IMV_BIN" ] && [ -r "$SPLASH_IMG" ]; then
  "$IMV_BIN" -f "$SPLASH_IMG" >>"$LOG" 2>&1 &
  SPLASH_PID="$!"
else
  echo "Splash holder unavailable (imv or image missing); continuing without holder." >>"$LOG"
fi

sleep "$SPLASH_HOLD_SECONDS"

if [ -n "$SPLASH_PID" ]; then
  kill "$SPLASH_PID" >/dev/null 2>&1 || true
  wait "$SPLASH_PID" 2>/dev/null || true
fi

BROWSER="$(command -v firefox-esr || command -v firefox || true)"
if [ -z "$BROWSER" ]; then
  echo "Firefox was not found in PATH." >>"$LOG"
  exit 1
fi

exec env MOZ_ENABLE_WAYLAND=1 "$BROWSER" \
  --kiosk \
  --private-window \
  --new-instance \
  --no-remote \
  --profile "$PROFILE_DIR" \
  "$UI_URL" >>"$LOG" 2>&1
