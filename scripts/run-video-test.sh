#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="${INTEL_XR_ROOT:-/ai/intel-xr-prototype}"
SRC="$ROOT/src/Monado-ALVR/demo/checkerboard"
BUILD="$ROOT/build/intel-xr-checkerboard"
RUNTIME="$ROOT/build/monado-alvr/openxr_monado-dev.json"
rm -rf "$BUILD"
cmake -S "$SRC" -B "$BUILD" -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo
cmake --build "$BUILD" --parallel "$(nproc)"
[[ -x "$BUILD/intel_xr_checkerboard" ]] || { echo "ERROR: checkerboard binary missing"; exit 1; }
[[ -f "$RUNTIME" ]] || { echo "ERROR: Monado runtime missing"; exit 1; }
export XR_RUNTIME_JSON="$RUNTIME"
echo "Runtime: $XR_RUNTIME_JSON"
echo "Demo:    $BUILD/intel_xr_checkerboard"
exec "$BUILD/intel_xr_checkerboard"
