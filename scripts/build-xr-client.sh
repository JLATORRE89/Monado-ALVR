#!/usr/bin/env bash
set -Eeuo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/xr-env.sh"
ALVR="$INTEL_XR_ROOT/src/alvr-monado"
OPENXR_SRC="$INTEL_XR_ROOT/src/OpenXR-SDK-Source"
OPENXR_BUILD="$INTEL_XR_ROOT/build/openxr-loader-android"
OPENXR_DST="$ALVR/deps/android_openxr/arm64-v8a"
echo "XR client build"
printf '[%-22s] %s\n' Config "$XR_CONFIG"
printf '[%-22s] %s\n' Java "$JAVA_HOME"
printf '[%-22s] %s\n' Android "$ANDROID_HOME"
printf '[%-22s] %s\n' NDK "$ANDROID_NDK_ROOT"
printf '[%-22s] %s\n' Target "$XR_ANDROID_RUST_TARGET"
[[ -d "$ANDROID_NDK_ROOT" ]] || { echo "ERROR: configured NDK is missing"; exit 1; }
rustup target list --installed | grep -qx "$XR_ANDROID_RUST_TARGET" || { echo "ERROR: Rust target $XR_ANDROID_RUST_TARGET missing"; exit 1; }
# Quest needs the Khronos Android OpenXR loader bundled with this custom APK.
# Build it from the pinned source configured in xr-build.json if missing.
OPENXR_REPO="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["android"]["openxr_sdk_repo"])' "$XR_CONFIG")"
OPENXR_REF="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["android"]["openxr_sdk_ref"])' "$XR_CONFIG")"
mkdir -p "$OPENXR_DST"
if [[ ! -f "$OPENXR_DST/libopenxr_loader.so" ]]; then
  printf '[%-22s] %s\n' "OpenXR loader" "BUILD"
  if [[ ! -d "$OPENXR_SRC/.git" ]]; then git clone --depth 1 --branch "$OPENXR_REF" "$OPENXR_REPO" "$OPENXR_SRC"; fi
  cmake -S "$OPENXR_SRC" -B "$OPENXR_BUILD" \
    -DCMAKE_TOOLCHAIN_FILE="$ANDROID_NDK_ROOT/build/cmake/android.toolchain.cmake" \
    -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-$XR_ANDROID_PLATFORM_API \
    -DCMAKE_BUILD_TYPE=Release -DBUILD_LOADER=ON -DBUILD_API_LAYERS=OFF \
    -DBUILD_CONFORMANCE_TESTS=OFF -DBUILD_TESTS=OFF
  cmake --build "$OPENXR_BUILD" --target openxr_loader -j"$(nproc)"
  LOADER="$(find "$OPENXR_BUILD" -type f -name libopenxr_loader.so | head -1)"
  [[ -n "$LOADER" ]] || { echo "ERROR: OpenXR loader build produced no libopenxr_loader.so"; exit 1; }
  cp "$LOADER" "$OPENXR_DST/libopenxr_loader.so"
fi
printf '[%-22s] %s\n' "OpenXR loader" "OK"

cd "$ALVR"
cargo xtask build-client --release
