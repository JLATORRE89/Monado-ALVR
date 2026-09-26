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
CFG="$ROOT/src/Monado-ALVR/config/xr-build.json"
SDK="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["demo"]["openxr_sdk_source"])' "$CFG")"
BUILD="$ROOT/build/openxr-demo"
# Always reconfigure cleanly: this is a disposable diagnostic build.
rm -rf "$BUILD"
[[ -f "$SDK/CMakeLists.txt" ]] || { echo "ERROR: OpenXR-SDK-Source missing at $SDK"; exit 1; }
cmake -S "$SDK" -B "$BUILD" -G Ninja \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo \
  -DBUILD_LOADER=ON -DBUILD_API_LAYERS=OFF -DBUILD_TESTS=ON -DBUILD_CONFORMANCE_TESTS=OFF \
  -DBUILD_SDK_TESTS=ON
# hello_xr is created by src/tests when both BUILD_TESTS and BUILD_SDK_TESTS are enabled.
cmake --build "$BUILD" --target hello_xr --parallel "$(nproc)"
HELLO="$(find "$BUILD" -type f -name hello_xr -perm -111 | head -1)"
[[ -n "$HELLO" ]] || { echo "ERROR: hello_xr was not produced"; exit 1; }
echo "OpenXR demo: $HELLO"
