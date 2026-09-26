#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="${INTEL_XR_ROOT:-/ai/intel-xr-prototype}"
CFG="$ROOT/src/Monado-ALVR/config/xr-build.json"
SDK="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["demo"]["openxr_sdk_source"])' "$CFG")"
BUILD="$ROOT/build/openxr-demo"
[[ -f "$SDK/CMakeLists.txt" ]] || { echo "ERROR: OpenXR-SDK-Source missing at $SDK"; exit 1; }
cmake -S "$SDK" -B "$BUILD" -G Ninja \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo \
  -DBUILD_LOADER=ON -DBUILD_API_LAYERS=OFF -DBUILD_TESTS=OFF -DBUILD_CONFORMANCE_TESTS=OFF \
  -DBUILD_SDK_TESTS=ON
if ! cmake --build "$BUILD" --target help | grep -qE "(^|[[:space:]])hello_xr([[:space:]]|$)"; then
  echo "ERROR: hello_xr target was not generated. BUILD_TESTS must be ON with BUILD_SDK_TESTS=ON for this SDK revision."
  exit 1
fi
cmake --build "$BUILD" --target hello_xr --parallel "$(nproc)"
HELLO="$(find "$BUILD" -type f -name hello_xr -perm -111 | head -1)"
[[ -n "$HELLO" ]] || { echo "ERROR: hello_xr was not produced"; exit 1; }
echo "OpenXR demo: $HELLO"
