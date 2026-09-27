#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="${INTEL_XR_ROOT:-/ai/intel-xr-prototype}"
CFG="$ROOT/src/Monado-ALVR/config/xr-build.json"
ACTION="${1:-apply}"
# Workstation override (not committed): config/xr-build.local.json, e.g.
#   {"android": {"usb_stay_awake": true}}
LOCAL_CFG="$ROOT/src/Monado-ALVR/config/xr-build.local.json"
enabled="$(python3 -c '
import json, os, sys
value = json.load(open(sys.argv[1])).get("android", {}).get("usb_stay_awake", False)
if os.path.isfile(sys.argv[2]):
    value = json.load(open(sys.argv[2])).get("android", {}).get("usb_stay_awake", value)
print("1" if value else "0")' "$CFG" "$LOCAL_CFG")"
case "$ACTION" in
 apply)
   command -v adb >/dev/null || { echo "ERROR: adb not found"; exit 1; }
   adb get-state >/dev/null 2>&1 || { echo "ERROR: no authorized ADB device connected"; exit 1; }
   if [[ "$enabled" == 1 ]]; then
     adb shell settings put global stay_on_while_plugged_in 2
     echo "Quest USB stay-awake: ON"
   else
     adb shell settings put global stay_on_while_plugged_in 0
     echo "Quest USB stay-awake: OFF"
   fi
   ;;
 status)
   printf 'Configured: %s\n' "$([[ "$enabled" == 1 ]] && echo ON || echo OFF)"
   printf 'Device value: '; adb shell settings get global stay_on_while_plugged_in
   ;;
 *) echo "Usage: $0 {apply|status}"; exit 2;;
esac
