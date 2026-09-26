#!/usr/bin/env bash
set -u
ROOT="${INTEL_XR_ROOT:-/ai/intel-xr-prototype}"
QUEST_IP="${1:-192.168.86.168}"
LOGDIR="$ROOT/logs"
source "$ROOT/src/Monado-ALVR/scripts/xr-log.sh"
xr_init_log "$(basename "$0" .sh)"

echo "=== Intel XR network diagnostic ==="
echo "Quest IP: $QUEST_IP"
echo
echo "=== WORKSTATION NETWORK ==="
ip -4 addr show | grep -E '^[0-9]+:|inet ' || true
echo
echo "=== ROUTE TO QUEST ==="
ip route get "$QUEST_IP" || true
echo
echo "=== QUEST PING ==="
if ping -c 3 "$QUEST_IP"; then
  echo "PASS: Quest is reachable."
else
  echo
  echo "WARNING: Quest is not reachable at $QUEST_IP."
  WIFI_HELPER="$ROOT/src/Monado-ALVR/scripts/connect-xr-wifi.sh"
  if [[ -f "$WIFI_HELPER" ]]; then
    if [[ -t 0 ]]; then
      read -r -p "Configure workstation Wi-Fi for the Quest network now? [Y/n] " answer
      case "${answer:-Y}" in
        [Yy]*|"") bash "$WIFI_HELPER" ;;
        *) echo "Wi-Fi configuration skipped." ;;
      esac
    else
      echo "Run: bash $WIFI_HELPER"
    fi
  else
    echo "Wi-Fi helper not found: $WIFI_HELPER"
  fi
fi
echo
echo "=== LISTENING ALVR/MONADO PORTS ==="
ss -lntup | grep -E '9943|9944|9945|9946|9947|9948|5353|8082|alvr|monado' || echo "No matching listeners found."
echo
echo "=== ALVR / MONADO PROCESSES ==="
ps aux | grep -Ei '[a]lvr|[m]onado' || true
echo
echo "=== ADB HEADSET ==="
adb devices -l 2>/dev/null || true
adb shell ip route 2>/dev/null || true
adb shell pidof alvr.client.stable 2>/dev/null || true
