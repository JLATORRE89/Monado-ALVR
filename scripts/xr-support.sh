#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="${INTEL_XR_ROOT:-/ai/intel-xr-prototype}"
S="$ROOT/src/Monado-ALVR/scripts"
QUEST_IP="${QUEST_IP:-192.168.86.168}"
SERVICE="$ROOT/build/monado-alvr/src/xrt/targets/service/monado-service"
LOGDIR="$ROOT/logs"; mkdir -p "$LOGDIR"
source "$S/xr-log.sh"
xr_init_log "xr-session"

echo "=== Intel XR support workflow ==="
echo "Quest: $QUEST_IP"
echo "Session log: $XR_SESSION_LOG"

echo
echo "[1/6] Runtime/artifacts"
[[ -x "$SERVICE" ]] || { echo "ERROR: monado-service missing. Run build-intel-xr.sh."; exit 1; }

echo
echo "[2/6] Monado user service/API"
bash "$S/monado-service.sh" ensure
MONADO_PID="$(systemctl --user show -p MainPID --value intel-xr-monado.service)"
echo "Monado systemd PID: $MONADO_PID"
echo
echo "[3/6] Quest reachability"
if ping -c 2 "$QUEST_IP"; then
  TRANSPORT=wifi
else
  echo "Quest not reachable over IP."
  if [[ -t 0 ]]; then
    read -r -p "Configure workstation Wi-Fi now? [Y/n] " a
    case "${a:-Y}" in [Yy]*|"") bash "$S/connect-xr-wifi.sh";; esac
  fi
  if ping -c 2 "$QUEST_IP"; then TRANSPORT=wifi; else TRANSPORT=usb; fi
fi
echo "Transport: $TRANSPORT"

echo
echo "[4/7] Firewall + transport"
if [[ "$TRANSPORT" == wifi ]]; then
  echo "Checking host firewall requirements..."
  if command -v ufw >/dev/null 2>&1; then
    UFW_STATUS="$(sudo -n ufw status 2>/dev/null || true)"
    if [[ -z "$UFW_STATUS" ]]; then
      echo "NOTE: firewall inspection needs sudo. Run:"
      echo "  sudo ufw status numbered"
      echo "Then rerun this support script."
      exit 1
    elif grep -q '^Status: active' <<<"$UFW_STATUS"; then
      FIREWALL_OK=1
      QUEST_NET="${QUEST_IP%.*}.0/24"
      for port in 9943 9944; do
        if grep -E "[[:space:]]${port}/udp[[:space:]]+ALLOW IN[[:space:]]+(${QUEST_IP}|${QUEST_NET})([[:space:]]|$)" <<<"$UFW_STATUS" >/dev/null; then
          echo "PASS: UDP $port allowed from Quest ($QUEST_IP or $QUEST_NET)"
        else
          FIREWALL_OK=0
          echo "MISSING: UDP $port allow rule covering Quest $QUEST_IP"
          echo "Fix with:"
          echo "  sudo ufw allow from $QUEST_IP to any port $port proto udp comment 'ALVR Quest'"
        fi
      done
      if [[ "$FIREWALL_OK" -ne 1 ]]; then
        echo "Firewall prerequisites are incomplete; not attempting ALVR connection."
        exit 1
      fi
    else
      echo "UFW is inactive; no UFW rule required."
    fi
  else
    echo "ufw not installed; skipping UFW-specific check."
  fi
fi

if [[ "$TRANSPORT" == usb ]]; then
  bash "$S/setup-usb-alvr.sh"
else
  adb forward --remove tcp:9943 2>/dev/null || true
  adb forward --remove tcp:9944 2>/dev/null || true
fi

echo
echo "[5/7] ALVR client"
adb start-server
adb shell pidof alvr.client.stable >/dev/null 2>&1 || adb shell monkey -p alvr.client.stable -c android.intent.category.LAUNCHER 1
sleep 3

echo
echo "[6/7] Discover/trust client"
TRUSTED=0
for i in $(seq 1 3); do
  if QUEST_IP="$QUEST_IP" bash "$S/trust-alvr-client.sh"; then TRUSTED=1; break; fi
  echo "Client not discoverable yet; retry $i/3..."
  sleep 2
done
[[ "$TRUSTED" -eq 1 ]] || {
  echo "ERROR: client was not discovered/trusted."
  echo "For Wi-Fi inspect: bash $S/network-diagnostic.sh $QUEST_IP"
  echo "For USB inspect:   bash $S/usb-handshake-diagnostic.sh"
  exit 1
}

echo
echo "[7/7] Final health\n"bash "$S/monado-service.sh" status

echo "XR support workflow complete."
echo "Monado PID: $MONADO_PID"
echo "Watch the headset for Successful connection / streaming."
