#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="${INTEL_XR_ROOT:-/ai/intel-xr-prototype}"
S="$ROOT/src/Monado-ALVR/scripts"
QUEST_IP="${QUEST_IP:-192.168.86.168}"
LOGDIR="$ROOT/logs"; mkdir -p "$LOGDIR"
LOG="$LOGDIR/$(date +%Y-%m-%d_%H-%M-%S)_xr-support.log"
exec > >(tee "$LOG") 2>&1

echo "=== Intel XR support workflow ==="
echo "Quest: $QUEST_IP"
echo "Log: $LOG"

echo
echo "[1/5] Runtime/status"
bash "$S/status-intel-xr.sh"

echo
echo "[2/5] Quest reachability"
if ping -c 2 "$QUEST_IP"; then
  echo "Quest reachable over IP."
  TRANSPORT=wifi
else
  echo "Quest not reachable over IP."
  if [[ -t 0 ]]; then
    read -r -p "Configure workstation Wi-Fi now? [Y/n] " a
    case "${a:-Y}" in [Yy]*|"") bash "$S/connect-xr-wifi.sh";; esac
  fi
  if ping -c 2 "$QUEST_IP"; then TRANSPORT=wifi; else TRANSPORT=usb; fi
fi

echo
echo "[3/5] ALVR transport: $TRANSPORT"
if [[ "$TRANSPORT" == usb ]]; then
  bash "$S/setup-usb-alvr.sh"
else
  adb forward --remove tcp:9943 2>/dev/null || true
  adb forward --remove tcp:9944 2>/dev/null || true
fi

echo
echo "[4/5] Client"
adb shell pidof alvr.client.stable >/dev/null 2>&1 ||  adb shell monkey -p alvr.client.stable -c android.intent.category.LAUNCHER 1
sleep 3

echo
echo "[5/5] Trust discovered client"
bash "$S/trust-alvr-client.sh" || {
  echo "Trust could not be completed automatically."
  echo "Run the handshake diagnostic if the headset remains on the Trust screen:"
  echo "  bash $S/usb-handshake-diagnostic.sh"
  exit 1
}

echo
echo "Workflow complete. Watch the Monado terminal and headset for handshake/streaming."
