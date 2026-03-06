#!/usr/bin/env bash
set -euo pipefail

if [ -r /etc/default/hydravision-kiosk ]; then
  # shellcheck disable=SC1091
  . /etc/default/hydravision-kiosk
fi

ETH_ENABLE="${HYDRAVISION_ETH_ENABLE:-1}"
if [ "$ETH_ENABLE" != "1" ]; then
  echo "HydraVision Ethernet config disabled (HYDRAVISION_ETH_ENABLE=$ETH_ENABLE)."
  exit 0
fi

ETH_SUBNET_BASE="${HYDRAVISION_ETH_SUBNET_BASE:-192.168.60}"
ETH_PREFIX="${HYDRAVISION_ETH_PREFIX:-24}"
ETH_GATEWAY="${HYDRAVISION_ETH_GATEWAY:-192.168.60.1}"
ETH_DNS="${HYDRAVISION_ETH_DNS:-192.168.60.1}"
ETH_CONN_NAME="${HYDRAVISION_ETH_CONNECTION_NAME:-}"
ETH_STATIC_IP="${HYDRAVISION_ETH_STATIC_IP:-}"

if ! command -v nmcli >/dev/null 2>&1; then
  echo "nmcli not found; cannot configure static ethernet."
  exit 1
fi

if [ -z "$ETH_STATIC_IP" ]; then
  host_name="$(hostnamectl --static 2>/dev/null || hostname)"
  if [[ "$host_name" =~ ([0-9]+)$ ]]; then
    # Fleet rule: hostname suffix 00xx -> last octet 1xx.
    suffix_all="${BASH_REMATCH[1]}"
    suffix_two=$((10#${suffix_all} % 100))
    if [ "$suffix_two" -eq 0 ]; then
      suffix_two=1
    fi
    last_octet=$((100 + suffix_two))
    ETH_STATIC_IP="${ETH_SUBNET_BASE}.${last_octet}"
  else
    ETH_STATIC_IP="${ETH_SUBNET_BASE}.101"
  fi
fi

if [ -z "$ETH_CONN_NAME" ]; then
  ETH_CONN_NAME="$(
    nmcli -t -f NAME,TYPE connection show \
      | awk -F: '$2=="802-3-ethernet"{print $1; exit}'
  )"
fi

ETH_IFACE=""
if [ -z "$ETH_CONN_NAME" ]; then
  ETH_IFACE="$(
    nmcli -t -f DEVICE,TYPE device status \
      | awk -F: '$2=="ethernet"{print $1; exit}'
  )"
  if [ -z "$ETH_IFACE" ]; then
    echo "No ethernet interface detected by NetworkManager."
    exit 1
  fi
  ETH_CONN_NAME="HydraVision Ethernet"
  nmcli connection add type ethernet ifname "$ETH_IFACE" con-name "$ETH_CONN_NAME"
fi

echo "Configuring ethernet connection '$ETH_CONN_NAME' to ${ETH_STATIC_IP}/${ETH_PREFIX} gw ${ETH_GATEWAY}"
nmcli connection modify "$ETH_CONN_NAME" \
  ipv4.method manual \
  ipv4.addresses "${ETH_STATIC_IP}/${ETH_PREFIX}" \
  ipv4.gateway "$ETH_GATEWAY" \
  ipv4.dns "$ETH_DNS" \
  ipv6.method ignore \
  connection.autoconnect yes

nmcli connection up "$ETH_CONN_NAME" || true
echo "Ethernet static config applied."
