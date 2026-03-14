#!/usr/bin/env bash
set -euo pipefail

if [ -f /etc/default/hydravision-kiosk ]; then
  # shellcheck disable=SC1091
  . /etc/default/hydravision-kiosk
fi

EXPECTED_PASSWORD="${HYDRAVISION_ADMIN_UNLOCK_PASSWORD:-}"
LOG_TAG="hydravision-admin-unlock"

if [ -z "$EXPECTED_PASSWORD" ]; then
  logger -t "$LOG_TAG" "Unlock denied: HYDRAVISION_ADMIN_UNLOCK_PASSWORD is not set."
  exit 1
fi

if ! command -v zenity >/dev/null 2>&1; then
  logger -t "$LOG_TAG" "Unlock denied: zenity is not installed."
  exit 1
fi

entered_password="$(
  zenity --password \
    --title="HydraVision Admin Access" \
    --text="Enter admin unlock password" || true
)"

if [ -z "$entered_password" ]; then
  logger -t "$LOG_TAG" "Unlock cancelled."
  exit 1
fi

if [ "$entered_password" != "$EXPECTED_PASSWORD" ]; then
  logger -t "$LOG_TAG" "Unlock denied: invalid password."
  zenity --error --title="Access denied" --text="Invalid password." || true
  exit 1
fi

logger -t "$LOG_TAG" "Unlock accepted; switching to desktop session."
pkill -f "firefox-esr --kiosk" >/dev/null 2>&1 || true
pkill -f "firefox --kiosk" >/dev/null 2>&1 || true

zenity --info --title="HydraVision" --text="Kiosk unlocked. Desktop access granted." || true
exit 0
