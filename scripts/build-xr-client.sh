#!/usr/bin/env bash
set -Eeuo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/xr-env.sh"
ALVR="$INTEL_XR_ROOT/src/alvr-monado"
echo "XR client build"
printf '[%-22s] %s\n' Config "$XR_CONFIG"
printf '[%-22s] %s\n' Java "$JAVA_HOME"
printf '[%-22s] %s\n' Android "$ANDROID_HOME"
printf '[%-22s] %s\n' NDK "$ANDROID_NDK_ROOT"
printf '[%-22s] %s\n' Target "$XR_ANDROID_RUST_TARGET"
[[ -d "$ANDROID_NDK_ROOT" ]] || { echo "ERROR: configured NDK is missing"; exit 1; }
rustup target list --installed | grep -qx "$XR_ANDROID_RUST_TARGET" || { echo "ERROR: Rust target $XR_ANDROID_RUST_TARGET missing"; exit 1; }
cd "$ALVR"
cargo xtask build-client --release
