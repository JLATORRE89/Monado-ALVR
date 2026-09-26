#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="${INTEL_XR_ROOT:-/ai/intel-xr-prototype}"
RUNTIME="$ROOT/build/monado-alvr/openxr_monado-dev.json"
HELLO="$(find "$ROOT/build/openxr-demo" -type f -name hello_xr -perm -111 | head -1)"
[[ -n "$HELLO" ]] || { echo "ERROR: hello_xr missing; run scripts/build-openxr-demo.sh"; exit 1; }
[[ -f "$RUNTIME" ]] || { echo "ERROR: Monado runtime missing"; exit 1; }
export XR_RUNTIME_JSON="$RUNTIME"
echo "Launching known-frame OpenXR diagnostic."
echo "This currently uses HelloXR as the frame producer; verify ALVR stays foregrounded."
exec "$HELLO" -g Vulkan -ff Hmd
