#!/usr/bin/env bash
set -euo pipefail

echo "Disabling HydraVision cage kiosk mode..."
systemctl disable --now hydravision-cage.service || true
systemctl unmask getty@tty1.service || true
systemctl unmask autovt@tty1.service || true
systemctl enable --now getty@tty1.service || true
systemctl enable --now lightdm.service || true
systemctl enable --now display-manager.service || true
systemctl set-default graphical.target || true
echo "Done. Reboot recommended."
