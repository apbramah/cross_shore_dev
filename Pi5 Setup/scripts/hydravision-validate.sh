#!/usr/bin/env bash
set -euo pipefail

PASS_COUNT=0
FAIL_COUNT=0
WARN_COUNT=0

pass() {
  echo "[PASS] $1"
  PASS_COUNT=$((PASS_COUNT + 1))
}

fail() {
  echo "[FAIL] $1"
  FAIL_COUNT=$((FAIL_COUNT + 1))
}

warn() {
  echo "[WARN] $1"
  WARN_COUNT=$((WARN_COUNT + 1))
}

check_service_state() {
  local service="$1"
  if systemctl is-enabled "$service" >/dev/null 2>&1; then
    pass "Service enabled: $service"
  else
    fail "Service not enabled: $service"
  fi

  if systemctl is-active "$service" >/dev/null 2>&1; then
    pass "Service active: $service"
  else
    fail "Service not active: $service"
  fi
}

check_port_listening() {
  local port="$1"
  if ss -ltn "( sport = :$port )" | grep -q LISTEN; then
    pass "TCP port listening: $port"
  else
    fail "TCP port not listening: $port"
  fi
}

check_exists() {
  local path="$1"
  if [ -e "$path" ]; then
    pass "Path exists: $path"
  else
    fail "Path missing: $path"
  fi
}

check_masked() {
  local unit="$1"
  if systemctl is-enabled "$unit" 2>/dev/null | grep -q masked; then
    pass "Unit masked: $unit"
  else
    fail "Unit not masked: $unit"
  fi
}

echo "HydraVision kiosk validation started."
echo "Date: $(date -Iseconds)"
echo

if [ -r /etc/default/hydravision-kiosk ]; then
  # shellcheck disable=SC1091
  . /etc/default/hydravision-kiosk
fi

KIOSK_MODE="${HYDRAVISION_KIOSK_MODE:-desktop}"

check_service_state "mvp_bridge_adc.service"
check_service_state "mvp_slow_bridge.service"

# mvp_bridge_adc is a Teensy CDC -> UDP path, not a TCP/WebSocket listener.
if systemctl is-active mvp_bridge_adc.service >/dev/null 2>&1; then
  pass "mvp_bridge_adc.service active (fast path uses UDP, no TCP listener expected)"
else
  warn "mvp_bridge_adc.service not active; fast-path validation incomplete."
fi
if systemctl is-active mvp_slow_bridge.service >/dev/null 2>&1; then
  check_port_listening "8766"
else
  warn "mvp_slow_bridge.service not active; skipping port 8766 check."
fi

check_exists "/usr/local/bin/hydravision-kiosk-launch.sh"
check_exists "/usr/local/bin/hydravision-cage-launch.sh"
check_exists "/usr/local/bin/hydravision-splash-then-browser.sh"
check_exists "/usr/local/bin/hydravision-configure-ethernet.sh"
check_exists "/usr/local/bin/hydravision-admin-unlock.sh"
check_exists "/usr/local/bin/hydravision-remove-lockdown.sh"
check_exists "/etc/default/hydravision-kiosk"
if [ -e "/etc/ssh/sshd_config.d/99-hydravision-kiosk.conf" ]; then
  pass "Path exists: /etc/ssh/sshd_config.d/99-hydravision-kiosk.conf"
else
  warn "SSH hardening drop-in missing (ENABLE_SSH_HARDENING may be disabled)."
fi
if [ -e "/etc/systemd/logind.conf.d/99-hydravision-kiosk.conf" ]; then
  pass "Path exists: /etc/systemd/logind.conf.d/99-hydravision-kiosk.conf"
else
  warn "Logind lockdown drop-in missing (ENABLE_KIOSK_LOCKDOWN may be disabled)."
fi
if [ -e "/etc/firefox/policies/policies.json" ]; then
  pass "Path exists: /etc/firefox/policies/policies.json"
else
  warn "Firefox kiosk policy missing (ENABLE_KIOSK_LOCKDOWN may be disabled)."
fi

if [ "$KIOSK_MODE" = "cage" ]; then
  check_service_state "hydravision-cage.service"
  if systemctl is-enabled getty@tty1.service 2>/dev/null | grep -q masked; then
    pass "Unit masked: getty@tty1.service"
  else
    warn "Unit not masked: getty@tty1.service (possible tty contention in cage mode)"
  fi
else
  check_exists "/home/admin/.config/labwc/autostart"
fi

if [ -f /etc/default/hydravision-kiosk ]; then
  if grep -q "^HYDRAVISION_ADMIN_UNLOCK_PASSWORD=CHANGE_ME$" /etc/default/hydravision-kiosk; then
    fail "Unlock password is still CHANGE_ME in /etc/default/hydravision-kiosk"
  elif grep -q "^HYDRAVISION_ADMIN_UNLOCK_PASSWORD=" /etc/default/hydravision-kiosk; then
    pass "Unlock password appears configured in /etc/default/hydravision-kiosk"
  else
    fail "Unlock password variable missing in /etc/default/hydravision-kiosk"
  fi
fi

if [ "${HYDRAVISION_ETH_ENABLE:-1}" = "1" ]; then
  if ip -4 addr show | grep -q "192.168.60."; then
    pass "Static ethernet appears configured in 192.168.60.0/24"
  else
    warn "No 192.168.60.x IPv4 address detected; static ethernet may not be applied yet."
  fi
fi

for tty in 2 3 4 5 6; do
  if systemctl is-enabled "getty@tty${tty}.service" 2>/dev/null | grep -q masked; then
    pass "Unit masked: getty@tty${tty}.service"
  else
    warn "Unit not masked: getty@tty${tty}.service"
  fi
done

echo
echo "Validation summary: ${PASS_COUNT} passed, ${FAIL_COUNT} failed, ${WARN_COUNT} warnings."
if [ "$FAIL_COUNT" -gt 0 ]; then
  exit 1
fi
