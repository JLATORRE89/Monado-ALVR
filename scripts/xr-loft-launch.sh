#!/usr/bin/env bash
# Launch hook for Loft menu entries (XR_LOFT_LAUNCH_HOOK, set by xr-app.sh). Runs detached.
#   xr-loft-launch.sh apk <android.package>   start a Quest app on each ADB headset that has it
#   xr-loft-launch.sh pc  </abs/path/to/game>  run an OpenXR mini-game on this PC in place of the
#                                             Loft (the Loft exits itself), then restart the Loft
set -Eeuo pipefail
ROOT="${INTEL_XR_ROOT:-/ai/intel-xr-prototype}"
MONADO="$ROOT/src/Monado-ALVR"
kind="${1:-}"
target="${2:-}"
case "$kind" in
  apk)
    [[ "$target" =~ ^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$ ]] || { echo "invalid package: $target"; exit 2; }
    command -v adb >/dev/null || { echo "xr-loft-launch: adb not found"; exit 1; }
    started=0
    while read -r serial state; do
      [[ "$state" == device ]] || continue
      if adb -s "$serial" shell pm path "$target" 2>/dev/null | grep -q '^package:'; then
        adb -s "$serial" shell monkey -p "$target" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 &&
          { echo "xr-loft-launch: started $target on $serial"; started=$((started + 1)); }
      fi
    done < <(adb devices | tail -n +2)
    [[ $started -gt 0 ]] || echo "xr-loft-launch: no ADB headset has $target installed"
    ;;
  pc)
    [[ "$target" == /* && -x "$target" ]] || { echo "not an executable: $target"; exit 2; }
    # Wait for the Loft to leave (it requested exit before calling this hook).
    for _ in $(seq 1 40); do pgrep -x intel_xr_loft >/dev/null || break; sleep 0.25; done
    log="$ROOT/logs/$(date +%Y-%m-%d_%H-%M-%S)_xr-minigame-$(basename "$target").log"
    echo "xr-loft-launch: running $target (log $log)"
    XR_RUNTIME_JSON="$ROOT/build/monado-alvr/openxr_monado-dev.json" \
    LD_LIBRARY_PATH="$ROOT/build/openxr-demo/src/loader:${LD_LIBRARY_PATH:-}" \
      "$target" >"$log" 2>&1 || true
    bash "$MONADO/scripts/xr-app.sh" start loft
    ;;
  *) echo "Usage: $0 {apk <package>|pc <executable>}"; exit 2 ;;
esac
