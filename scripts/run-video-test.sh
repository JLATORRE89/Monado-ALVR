#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="${INTEL_XR_ROOT:-/ai/intel-xr-prototype}"
SRC="$ROOT/src/Monado-ALVR/demo/checkerboard"
BUILD="$ROOT/build/intel-xr-checkerboard"
SDK="$ROOT/src/OpenXR-SDK-Source"
SDKBUILD="$ROOT/build/openxr-demo"
RUNTIME="$ROOT/build/monado-alvr/openxr_monado-dev.json"
[[ -f "$SDK/include/openxr/openxr.h" ]] || { echo "ERROR: missing $SDK/include/openxr/openxr.h"; exit 1; }
LOADER="$(find "$SDKBUILD" -type f \( -name "libopenxr_loader.so" -o -name "libopenxr_loader.so.*" \) | head -1)"
[[ -n "$LOADER" ]] || { echo "ERROR: OpenXR loader not found under $SDKBUILD; run scripts/build-openxr-demo.sh"; exit 1; }
LOADER_DIR="$(dirname "$LOADER")"
rm -rf "$BUILD"
cmake -S "$SRC" -B "$BUILD" -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo \\
  -DOPENXR_INCLUDE_DIR="$SDK/include" -DOPENXR_LOADER="$LOADER" -DOPENXR_SDK_BUILD="$SDKBUILD"
cmake --build "$BUILD" --parallel "$(nproc)"
[[ -x "$BUILD/intel_xr_checkerboard" ]] || { echo "ERROR: checkerboard binary missing"; exit 1; }
[[ -f "$RUNTIME" ]] || { echo "ERROR: Monado runtime missing"; exit 1; }
export XR_RUNTIME_JSON="$RUNTIME"
export LD_LIBRARY_PATH="$LOADER_DIR:${LD_LIBRARY_PATH:-}"
echo "Runtime: $XR_RUNTIME_JSON"
echo "Demo:    $BUILD/intel_xr_checkerboard"
exec "$BUILD/intel_xr_checkerboard"
