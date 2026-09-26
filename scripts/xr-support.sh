#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="${INTEL_XR_ROOT:-/ai/intel-xr-prototype}"
S="$ROOT/src/Monado-ALVR/scripts"
QUEST_IP="${QUEST_IP:-192.168.86.168}"
SERVICE="$ROOT/build/monado-alvr/src/xrt/targets/service/monado-service"
LOGDIR="$ROOT/logs"; mkdir -p "$LOGDIR"
STAMP="$(date +%Y-%m-%d_%H-%M-%S)"
LOG="$LOGDIR/${STAMP}_xr-support.log"
SERVICE_LOG="$LOGDIR/${STAMP}_monado-service.log"
exec > >(tee "$LOG") 2>&1

echo "=== Intel XR support workflow ==="
echo "Quest: $QUEST_IP"
echo "Log: $LOG"

echo
echo "[1/6] Runtime/artifacts"
[[ -x "$SERVICE" ]] || { echo "ERROR: monado-service missing. Run build-intel-xr.sh."; exit 1; }

if pgrep -f "$SERVICE" >/dev/null; then
  MONADO_PID="$(pgrep -f "$SERVICE" | head -1)"
  echo "Monado already running (PID $MONADO_PID)."
else
  echo "Starting Monado service."
  nohup env XRT_LOG="${XRT_LOG:-debug}" "$SERVICE" >"$SERVICE_LOG" 2>&1 &
  MONADO_PID=$!
  echo "Monado PID: $MONADO_PID"
  echo "Monado log: $SERVICE_LOG"
fi

echo
echo "[2/6] Wait for ALVR API"
API_READY=0
for i in $(seq 1 20); do
  if curl -fsS -H 'X-ALVR: 1' http://127.0.0.1:8082/api/ping >/dev/null 2>&1; then
    API_READY=1; break
  fi
  if ! kill -0 "$MONADO_PID" 2>/dev/null; then
    echo "ERROR: Monado exited while starting."
    [[ -f "$SERVICE_LOG" ]] && tail -100 "$SERVICE_LOG"
    exit 1
  fi
  sleep 1
done
[[ "$API_READY" -eq 1 ]] || { echo "ERROR: ALVR API did not become ready on :8082."; [[ -f "$SERVICE_LOG" ]] && tail -100 "$SERVICE_LOG"; exit 1; }
echo "ALVR API ready."

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
echo "[4/6] Configure transport"
if [[ "$TRANSPORT" == usb ]]; then
  bash "$S/setup-usb-alvr.sh"
else
  adb forward --remove tcp:9943 2>/dev/null || true
  adb forward --remove tcp:9944 2>/dev/null || true
fi

echo
echo "[5/6] ALVR client"
adb start-server
adb shell pidof alvr.client.stable >/dev/null 2>&1 || adb shell monkey -p alvr.client.stable -c android.intent.category.LAUNCHER 1
sleep 3

echo
echo "[6/6] Discover/trust client"
TRUSTED=0
for i in $(seq 1 15); do
  if QUEST_IP="$QUEST_IP" bash "$S/trust-alvr-client.sh"; then TRUSTED=1; break; fi
  echo "Client not discoverable yet; retry $i/15..."
  sleep 2
done
[[ "$TRUSTED" -eq 1 ]] || {
  echo "ERROR: client was not discovered/trusted."
  echo "For Wi-Fi inspect: bash $S/network-diagnostic.sh $QUEST_IP"
  echo "For USB inspect:   bash $S/usb-handshake-diagnostic.sh"
  exit 1
}

echo
echo "XR support workflow complete."
echo "Monado PID: $MONADO_PID"
[[ -f "$SERVICE_LOG" ]] && echo "Monado log: $SERVICE_LOG"
echo "Watch the headset for Successful connection / streaming."
