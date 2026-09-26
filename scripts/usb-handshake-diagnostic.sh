#!/usr/bin/env bash
set -u
ROOT="${INTEL_XR_ROOT:-/ai/intel-xr-prototype}"
LOGDIR="$ROOT/logs"
source "$ROOT/src/Monado-ALVR/scripts/xr-log.sh"
xr_init_log "$(basename "$0" .sh)"

echo "=== ALVR USB handshake diagnostic ==="
echo "Run for ~20 seconds with ALVR foregrounded in the headset."
echo
adb start-server
SERIAL="$(adb devices | awk 'NR>1 && $2=="device"{print $1;exit}')"
[[ -n "$SERIAL" ]] || { echo "ERROR: no authorized ADB headset"; exit 1; }

echo "=== State ==="
echo "Device: $SERIAL"
adb forward --list
adb shell pidof alvr.client.stable || true
echo
echo "=== Clear Quest logcat ==="
adb logcat -c
echo
echo "=== Capture ==="
echo "Quest ALVR/log networking and workstation sockets will be sampled for 20 seconds."
for i in $(seq 1 10); do
  echo "--- sample $i $(date +%T) ---"
  ss -ntup | grep -E '9943|9944|8082|monado|adb' || true
  sleep 2
done
echo
echo "=== Quest logcat since capture start ==="
adb logcat -d -v time | grep -Ei 'alvr|9943|9944|handshake|protocol|connection|socket|stream|client_core|server' | tail -300 || true
echo
echo "=== Final workstation socket state ==="
ss -ntup | grep -E '9943|9944|8082|monado|adb' || true
echo
echo "Diagnostic complete."
