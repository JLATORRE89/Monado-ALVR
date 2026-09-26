#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="${INTEL_XR_ROOT:-/ai/intel-xr-prototype}"
BUILD="$ROOT/build/openxr-demo"
RUNTIME="$ROOT/build/monado-alvr/openxr_monado-dev.json"
HELLO="$(find "$BUILD" -type f -name hello_xr -perm -111 | head -1)"
[[ -n "$HELLO" ]] || { echo "ERROR: demo missing; run scripts/build-openxr-demo.sh"; exit 1; }
[[ -f "$RUNTIME" ]] || { echo "ERROR: Monado OpenXR manifest missing"; exit 1; }
export XR_RUNTIME_JSON="$RUNTIME"
echo "Runtime: $XR_RUNTIME_JSON"
echo "Demo:    $HELLO"
exec "$HELLO" -g Vulkan -ff Hmd
