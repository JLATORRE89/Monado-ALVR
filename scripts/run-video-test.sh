#!/usr/bin/env bash
set -Eeuo pipefail
# Resolve the project root without assuming /ai or any fixed mount point.
# Priority: INTEL_XR_ROOT -> enclosing intel-xr-prototype -> repo parent layout.
if [[ -n "${INTEL_XR_ROOT:-}" ]]; then
  ROOT="$INTEL_XR_ROOT"
else
  HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  probe="$PWD"
  ROOT=""
  while [[ "$probe" != "/" ]]; do
    if [[ "$(basename "$probe")" == "intel-xr-prototype" ]]; then ROOT="$probe"; break; fi
    probe="$(dirname "$probe")"
  done
  if [[ -z "$ROOT" ]]; then
    probe="$HERE"
    while [[ "$probe" != "/" ]]; do
      if [[ "$(basename "$probe")" == "intel-xr-prototype" ]]; then ROOT="$probe"; break; fi
      probe="$(dirname "$probe")"
    done
  fi
  [[ -n "$ROOT" ]] || { echo "ERROR: cannot locate enclosing intel-xr-prototype; set INTEL_XR_ROOT"; exit 1; }
fi
SRC="$ROOT/src/Monado-ALVR/demo/checkerboard"
BUILD="$ROOT/build/intel-xr-checkerboard"
SDKBUILD="$ROOT/build/openxr-demo"
# Reuse headers from the already-built desktop OpenXR demo first.
# Android loader headers are a fallback only.
SDK=""
for candidate in "$ROOT/build/openxr-demo" "$ROOT/build/openxr-loader-android"; do
  if [[ -f "$candidate/include/openxr/openxr.h" ]]; then SDK="$candidate"; break; fi
done
if [[ -z "$SDK" ]]; then
  SDK="$(find "$ROOT" -maxdepth 5 -type f -path "*/include/openxr/openxr.h" -print -quit 2>/dev/null | sed "s#/include/openxr/openxr.h$##")"
fi
RUNTIME="$ROOT/build/monado-alvr/openxr_monado-dev.json"
[[ -n "$SDK" && -f "$SDK/include/openxr/openxr.h" ]] || { echo "ERROR: OpenXR SDK headers not found anywhere under $ROOT"; echo "Run: find \"$ROOT\" -type f -path \"*/include/openxr/openxr.h\" | head"; exit 1; }
echo "OpenXR SDK: $SDK"
LOADER="$(find "$SDKBUILD" -type f \( -name "libopenxr_loader.so" -o -name "libopenxr_loader.so.*" \) | head -1)"
[[ -n "$LOADER" ]] || { echo "ERROR: OpenXR loader not found under $SDKBUILD; run scripts/build-openxr-demo.sh"; exit 1; }
LOADER_DIR="$(dirname "$LOADER")"
rm -rf "$BUILD"
cmake -S "$SRC" -B "$BUILD" -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo -DOPENXR_INCLUDE_DIR="$SDK/include" -DOPENXR_LOADER="$LOADER" -DOPENXR_SDK_BUILD="$SDKBUILD"
cmake --build "$BUILD" --parallel "$(nproc)"
[[ -x "$BUILD/intel_xr_checkerboard" ]] || { echo "ERROR: checkerboard binary missing"; exit 1; }
[[ -f "$RUNTIME" ]] || { echo "ERROR: Monado runtime missing"; exit 1; }
export XR_RUNTIME_JSON="$RUNTIME"
export LD_LIBRARY_PATH="$LOADER_DIR:${LD_LIBRARY_PATH:-}"
echo "Runtime: $XR_RUNTIME_JSON"
echo "Demo:    $BUILD/intel_xr_checkerboard"
exec "$BUILD/intel_xr_checkerboard"
