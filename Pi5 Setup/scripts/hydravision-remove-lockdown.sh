#!/usr/bin/env bash
set -euo pipefail

echo "Removing HydraVision kiosk lockdown controls..."

rm -f /etc/systemd/logind.conf.d/99-hydravision-kiosk.conf
rm -f /etc/ssh/sshd_config.d/99-hydravision-kiosk.conf
rm -f /etc/firefox/policies/policies.json

for tty in 2 3 4 5 6; do
  systemctl unmask "getty@tty${tty}.service" >/dev/null 2>&1 || true
  systemctl unmask "autovt@tty${tty}.service" >/dev/null 2>&1 || true
done

if systemctl list-unit-files | grep -q '^ssh\.service'; then
  systemctl restart ssh || true
elif systemctl list-unit-files | grep -q '^sshd\.service'; then
  systemctl restart sshd || true
fi

systemctl restart systemd-logind || true
echo "Lockdown controls removed. Reboot recommended."
