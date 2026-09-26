#!/usr/bin/env bash
set -u
ROOT="${INTEL_XR_ROOT:-/ai/intel-xr-prototype}"
echo "=== Intel XR status ==="
echo "Root: $ROOT"
echo
echo "=== GPU ==="
lspci -nn | grep -Ei 'VGA|3D|Display' || true
echo
echo "=== Vulkan ==="
vulkaninfo --summary 2>&1 | grep -E 'deviceName|deviceType|driverName|driverInfo' || true
echo
echo "=== Sources ==="
for repo in "$ROOT/src/Monado-ALVR" "$ROOT/src/alvr-monado" "$ROOT/src/alvr_render"; do
  echo "-- $repo"
  if [[ -d "$repo/.git" ]]; then git -C "$repo" log -1 --oneline; else echo "MISSING"; fi
done
echo
echo "=== Build artifacts ==="
for f in  "$ROOT/build/monado-alvr/src/xrt/targets/service/monado-service"  "$ROOT/build/monado-alvr/src/xrt/targets/openxr/libopenxr_monado.so"  "$ROOT/build/monado-alvr/openxr_monado-dev.json"; do
  [[ -e "$f" ]] && echo "OK  $f" || echo "MISS $f"
done
