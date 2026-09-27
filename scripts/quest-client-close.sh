#!/usr/bin/env bash
# Close the ALVR client on every connected Quest that has it installed, which returns the
# headset to Quest Home. Used as the Loft's exit hook (XR_LOFT_ON_EXIT, set by xr-app.sh).
# Needs ADB (USB, or ADB over Wi-Fi); without it this only prints a note.
set -Eeuo pipefail
PKG="${ALVR_CLIENT_PACKAGE:-alvr.client.monado}"
command -v adb >/dev/null || { echo "quest-client-close: adb not found; close the client in the headset"; exit 0; }
closed=0
while read -r serial state; do
  [[ "$state" == device ]] || continue
  if adb -s "$serial" shell pm path "$PKG" 2>/dev/null | grep -q '^package:'; then
    adb -s "$serial" shell am force-stop "$PKG"
    echo "quest-client-close: closed $PKG on $serial"
    closed=$((closed + 1))
  fi
done < <(adb devices | tail -n +2)
[[ $closed -gt 0 ]] || echo "quest-client-close: no ADB headset with $PKG; close the client in the headset"
