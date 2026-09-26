#!/usr/bin/env bash
set -u

ROOT="${INTEL_XR_ROOT:-/ai/intel-xr-prototype}"
LOGDIR="$ROOT/logs"
QUEST_IP="${QUEST_IP:-192.168.86.168}"
SSID="${1:-}"
mkdir -p "$LOGDIR"
LOG="$LOGDIR/$(date +%Y-%m-%d_%H-%M-%S)_connect-xr-wifi.log"
exec > >(tee "$LOG") 2>&1

echo "=== Intel XR Wi-Fi setup ==="
echo "Log: $LOG"
echo "Quest IP: $QUEST_IP"

command -v nmcli >/dev/null || { echo "ERROR: nmcli is not installed."; exit 1; }

WIFI_DEV="$(nmcli -t -f DEVICE,TYPE device status | awk -F: '$2=="wifi"{print $1; exit}')"
[[ -n "$WIFI_DEV" ]] || { echo "ERROR: no Wi-Fi interface found."; exit 1; }
echo "Wi-Fi interface: $WIFI_DEV"

sudo nmcli radio wifi on
sudo nmcli device wifi rescan ifname "$WIFI_DEV" || true

if [[ -z "$SSID" ]]; then
    echo
    echo "Available networks:"
    nmcli --colors no -f IN-USE,SSID,SIGNAL,SECURITY device wifi list ifname "$WIFI_DEV"
    echo
    read -r -p "Wi-Fi SSID to connect to: " SSID
fi
[[ -n "$SSID" ]] || { echo "ERROR: no SSID supplied."; exit 1; }

echo
echo "Connecting to: $SSID"
# --ask keeps the Wi-Fi password out of this script, Git, logs and shell history.
sudo nmcli --ask device wifi connect "$SSID" ifname "$WIFI_DEV"

echo
echo "=== Connection state ==="
nmcli device status
echo
echo "=== Wi-Fi IPv4 ==="
ip -4 addr show dev "$WIFI_DEV"
echo
echo "=== Route to Quest ==="
ip route get "$QUEST_IP" || true
echo
echo "=== Quest reachability ==="
ping -c 3 "$QUEST_IP" || true

WIFI_IP="$(ip -4 -o addr show dev "$WIFI_DEV" | awk '{print $4}' | cut -d/ -f1 | head -1)"
echo
echo "Workstation Wi-Fi IP: ${WIFI_IP:-none}"
echo "Quest IP: $QUEST_IP"
if [[ "$WIFI_IP" == 192.168.86.* ]]; then
    echo "PASS: workstation and known Quest address are on the 192.168.86.x LAN."
else
    echo "NOTE: workstation Wi-Fi is not on 192.168.86.x; inspect the route/ping results above."
fi
