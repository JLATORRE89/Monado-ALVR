#!/usr/bin/env bash
set -u
ROOT="${INTEL_XR_ROOT:-/ai/intel-xr-prototype}"
QUEST_IP="${1:-192.168.86.168}"
LOGDIR="$ROOT/logs"
mkdir -p "$LOGDIR"
LOG="$LOGDIR/$(date +%Y-%m-%d_%H-%M-%S)_network-diagnostic.log"
exec > >(tee "$LOG") 2>&1

echo "=== Intel XR network diagnostic ==="
echo "Quest IP: $QUEST_IP"
echo "Log: $LOG"
echo
echo "=== WORKSTATION NETWORK ==="
ip -4 addr show | grep -E '^[0-9]+:|inet ' || true
echo
echo "=== ROUTE TO QUEST ==="
ip route get "$QUEST_IP" || true
echo
echo "=== QUEST PING ==="
ping -c 3 "$QUEST_IP" || true
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
