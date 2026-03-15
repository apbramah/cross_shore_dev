#!/bin/bash
# Run this ON THE PI after 'git pull'. Copies repo files into runtime (/opt/ui/, /opt/wsbridge/)
# so the kiosk and wsbridge actually use the new version. Git pull alone is NOT enough.

set -e
REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"
cd "$REPO_ROOT"

echo "Deploying from repo: $REPO_ROOT"

# UI: kiosk loads from /opt/ui/
sudo install -m 644 apps/controller/mvp_ui_3.html /opt/ui/
[ -f apps/controller/mvp_ui_3_layout.js ] && sudo install -m 644 apps/controller/mvp_ui_3_layout.js /opt/ui/ || true
[ -f apps/controller/position_map_standalone.html ] && sudo install -m 644 apps/controller/position_map_standalone.html /opt/ui/ || true

# Bridge: wsbridge runs from /opt/wsbridge/
sudo install -m 644 apps/controller/mvp_slow_bridge.py /opt/wsbridge/

# Restart so running processes use new files
sudo systemctl restart wsbridge.service
sudo systemctl restart kiosk.service
# If ADC bridge runs as a service (controller or mvp_bridge_adc), restart so it uses new code from repo
for svc in controller.service mvp_bridge_adc.service; do
  if systemctl is-enabled "$svc" &>/dev/null || systemctl list-unit-files --full "$svc" &>/dev/null; then
    sudo systemctl restart "$svc" 2>/dev/null && echo "Restarted $svc" || true
  fi
done

echo "Done. Verify hashes match:"
sha256sum apps/controller/mvp_ui_3.html /opt/ui/mvp_ui_3.html
[ -f /opt/ui/position_map_standalone.html ] && sha256sum apps/controller/position_map_standalone.html /opt/ui/position_map_standalone.html || true
