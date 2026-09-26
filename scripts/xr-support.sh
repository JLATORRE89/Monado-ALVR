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
  echo "Checking host firewall..."
  if command -v ufw >/dev/null 2>&1; then
    # Do not gate the connection on parsing UFW's human-formatted output.
    # UFW syntax/output varies; report status and test the actual transport below.
    sudo -n ufw status 2>/dev/null || {
      echo "NOTE: unable to inspect UFW non-interactively."
      echo "Manual check: sudo ufw status numbered"
    }
    echo "Required ALVR Wi-Fi rules, if UFW is active:"
    echo "  sudo ufw allow from $QUEST_IP to any port 9943 proto udp comment 'ALVR Quest'"
    echo "  sudo ufw allow from $QUEST_IP to any port 9944 proto udp comment 'ALVR Quest'"
    echo "Firewall status is informational; continuing to transport diagnostics."
  else
    echo "ufw not installed."
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
echo "[6/7] ALVR discovery/transport"
if [[ "$TRANSPORT" == wifi ]]; then
  WIFI_DEV="$(ip route get "$QUEST_IP" 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="dev"){print $(i+1); exit}}')"
  echo "Quest route interface: ${WIFI_DEV:-unknown}"
  SOCKETS="$(ss -lntup 2>/dev/null || true)"
  if grep -qE '[:](9943|9944)[[:space:]]' <<<"$SOCKETS"; then
    echo "PASS: ALVR transport socket(s) 9943/9944 are open."
  else
    echo "NOTE: no bound 9943/9944 socket is currently visible; checking packet traffic next."
  fi
  echo "Sampling packets involving Quest $QUEST_IP for 8 seconds..."
  if command -v tcpdump >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
    PACKETS="$(timeout 8 sudo -n tcpdump -ni "${WIFI_DEV:-any}" "host $QUEST_IP and (udp or tcp)" 2>&1 || true)"
    printf '%s\n' "$PACKETS"
    if [[ -z "$PACKETS" || "$PACKETS" == *"0 packets captured"* ]]; then
      echo "ERROR: no Quest network traffic reached the workstation during the discovery sample."
      echo "Keep ALVR foregrounded in the headset and rerun."
      exit 1
    fi
  else
    echo "NOTE: packet capture needs tcpdump and passwordless/current sudo authorization."
    echo "Run once if needed: sudo true"
    echo "Then rerun this workflow."
    exit 1
  fi
fi

echo
echo "Attempting ALVR client discovery/trust (maximum 3 attempts)..."
TRUSTED=0
for i in $(seq 1 3); do
  if QUEST_IP="$QUEST_IP" bash "$S/trust-alvr-client.sh"; then TRUSTED=1; break; fi
  echo "Discovery/trust attempt $i/3 did not identify the Quest."
  sleep 2
done
[[ "$TRUSTED" -eq 1 ]] || {
  echo "ERROR: Quest network traffic exists, but ALVR server_core did not expose a trustable client identity."
  echo "This is now a server discovery/handshake issue, not a generic reachability test."
  exit 1
}

echo
echo "[7/7] Final health\n"bash "$S/monado-service.sh" status

echo "XR support workflow complete."
echo "Monado PID: $MONADO_PID"
echo "Watch the headset for Successful connection / streaming."
