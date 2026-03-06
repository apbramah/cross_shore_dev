#!/usr/bin/env bash
set -euo pipefail

if [ -r /etc/default/hydravision-kiosk ]; then
  # shellcheck disable=SC1091
  . /etc/default/hydravision-kiosk
fi

LOG="${HOME}/.cache/hydravision-kiosk.log"
UI_URL="${HYDRAVISION_UI_URL:-file:///home/admin/Dev/cross_shore_dev/apps/controller/mvp_ui_3.html}"
SPLASH_IMG="${HYDRAVISION_SPLASH_IMAGE:-/usr/share/hydravision/hydravision_boot.png}"
SPLASH_HANDOFF_TIMEOUT_SECONDS="${HYDRAVISION_SPLASH_HANDOFF_TIMEOUT_SECONDS:-20}"
SPLASH_HANDOFF_POLL_SECONDS="${HYDRAVISION_SPLASH_HANDOFF_POLL_SECONDS:-0.2}"
SPLASH_HANDOFF_MIN_SECONDS="${HYDRAVISION_SPLASH_HANDOFF_MIN_SECONDS:-0.8}"
PROFILE_DIR="${HOME}/.hydravision-firefox-profile"
OUTPUT_NAME="${HYDRAVISION_OUTPUT_NAME:-DSI-2}"
OUTPUT_TRANSFORM="${HYDRAVISION_OUTPUT_TRANSFORM:-90}"

mkdir -p "$(dirname "$LOG")" "$PROFILE_DIR"

{
  echo "==== $(date -Iseconds) HydraVision splash-then-browser ===="
  echo "UI: ${UI_URL}"
  echo "Splash image: ${SPLASH_IMG}"
  echo "Splash handoff timeout: ${SPLASH_HANDOFF_TIMEOUT_SECONDS}s"
  echo "Splash handoff poll: ${SPLASH_HANDOFF_POLL_SECONDS}s"
  echo "Output transform policy: ${OUTPUT_NAME} -> ${OUTPUT_TRANSFORM}"
} >>"$LOG"

IMV_BIN="$(command -v imv-wayland || command -v imv || true)"
SPLASH_PID=""
if [ -n "$IMV_BIN" ] && [ -r "$SPLASH_IMG" ]; then
  "$IMV_BIN" -f "$SPLASH_IMG" >>"$LOG" 2>&1 &
  SPLASH_PID="$!"
else
  echo "Splash holder unavailable (imv or image missing); continuing without holder." >>"$LOG"
fi

if command -v wlr-randr >/dev/null 2>&1 && [ -n "$OUTPUT_NAME" ] && [ -n "$OUTPUT_TRANSFORM" ]; then
  if wlr-randr --output "$OUTPUT_NAME" --transform "$OUTPUT_TRANSFORM" >>"$LOG" 2>&1; then
    echo "Applied output transform: ${OUTPUT_NAME} -> ${OUTPUT_TRANSFORM}" >>"$LOG"
  else
    echo "Failed to apply output transform; continuing." >>"$LOG"
  fi
else
  echo "wlr-randr unavailable or transform disabled; skipping output transform." >>"$LOG"
fi

BROWSER="$(command -v firefox-esr || command -v firefox || true)"
if [ -z "$BROWSER" ]; then
  echo "Firefox was not found in PATH." >>"$LOG"
  exit 1
fi

env MOZ_ENABLE_WAYLAND=1 "$BROWSER" \
  --kiosk \
  --private-window \
  --new-instance \
  --no-remote \
  --profile "$PROFILE_DIR" \
  "$UI_URL" >>"$LOG" 2>&1 &
BROWSER_PID="$!"

wayland_connected() {
  local pid="$1"
  local fdpath=""
  for fdpath in /proc/"$pid"/fd/*; do
    [ -e "$fdpath" ] || continue
    if readlink "$fdpath" 2>/dev/null | grep -q "wayland-"; then
      return 0
    fi
  done
  return 1
}

handoff_start="$(date +%s.%N)"
handoff_deadline="$(python3 - "$handoff_start" "$SPLASH_HANDOFF_TIMEOUT_SECONDS" <<'PY'
import sys
print(float(sys.argv[1]) + float(sys.argv[2]))
PY
)"

sleep "$SPLASH_HANDOFF_MIN_SECONDS"
while true; do
  if ! kill -0 "$BROWSER_PID" 2>/dev/null; then
    echo "Browser exited before splash handoff." >>"$LOG"
    break
  fi
  if wayland_connected "$BROWSER_PID"; then
    echo "Browser connected to Wayland; performing splash handoff." >>"$LOG"
    break
  fi

  now="$(date +%s.%N)"
  if python3 - "$now" "$handoff_deadline" <<'PY'
import sys
sys.exit(0 if float(sys.argv[1]) < float(sys.argv[2]) else 1)
PY
  then
    sleep "$SPLASH_HANDOFF_POLL_SECONDS"
  else
    echo "Splash handoff timeout reached; continuing anyway." >>"$LOG"
    break
  fi
done

if [ -n "$SPLASH_PID" ]; then
  kill "$SPLASH_PID" >/dev/null 2>&1 || true
  wait "$SPLASH_PID" 2>/dev/null || true
fi

wait "$BROWSER_PID"
