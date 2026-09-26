#!/usr/bin/env bash
set -u
ROOT="${INTEL_XR_ROOT:-/ai/intel-xr-prototype}"
LOGDIR="$ROOT/logs"
source "$ROOT/src/Monado-ALVR/scripts/xr-log.sh"
xr_init_log "$(basename "$0" .sh)"

echo "=== ALVR USB setup ==="
echo
echo "Pinned ALVR wired mode uses ADB FORWARD for control 9943 and stream 9944."
echo "Port 8082 is the dashboard web server and is not part of the wired stream tunnel."
echo

command -v adb >/dev/null || { echo "ERROR: adb not found"; exit 1; }
adb start-server
SERIAL="$(adb devices | awk 'NR>1 && $2=="device" {print $1; exit}')"
[[ -n "$SERIAL" ]] || { echo "ERROR: no authorized ADB headset found"; exit 1; }
echo "Device: $SERIAL"

echo
echo "=== Remove experimental 8082 reverse ==="
adb reverse --remove tcp:8082 2>/dev/null || true

echo
echo "=== Ensure ALVR wired forwards ==="
adb -s "$SERIAL" forward tcp:9943 tcp:9943
adb -s "$SERIAL" forward tcp:9944 tcp:9944
adb forward --list

echo
echo "=== Client package/process ==="
adb -s "$SERIAL" shell dumpsys package alvr.client.stable 2>/dev/null | grep -E 'versionName=|versionCode=' || true
PID="$(adb -s "$SERIAL" shell pidof alvr.client.stable 2>/dev/null | tr -d '\r')"
if [[ -z "$PID" ]]; then
  echo "ALVR client is not running; launching it."
  adb -s "$SERIAL" shell monkey -p alvr.client.stable -c android.intent.category.LAUNCHER 1
  sleep 3
else
  echo "ALVR client PID: $PID"
fi

echo
echo "=== Current listeners ==="
ss -lntup | grep -E '9943|9944|8082|5353|monado|adb' || true
echo
echo "USB setup complete. Keep the headset connected and ALVR foregrounded."
