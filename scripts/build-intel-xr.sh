#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${INTEL_XR_ROOT:-/ai/intel-xr-prototype}"
MONADO="$ROOT/src/Monado-ALVR"
ALVR_RENDER="$ROOT/src/alvr_render"
ALVR="$ROOT/src/alvr-monado"
BUILD="$ROOT/build/monado-alvr"
PREFIX="$ROOT/local"
LOGDIR="$ROOT/logs"

mkdir -p "$LOGDIR"
LOG="$LOGDIR/build-intel-xr.log"
exec > >(tee "$LOG") 2>&1

echo "=== Intel XR build ==="
echo "Root: $ROOT"
echo "Log:  $LOG"

for d in "$MONADO" "$ALVR_RENDER" "$ALVR"; do
    if [[ ! -d "$d/.git" ]]; then
        echo "ERROR: required repository missing: $d"
        exit 1
    fi
done

echo
echo "=== Source revisions ==="
git -C "$MONADO" log -1 --oneline
git -C "$ALVR_RENDER" log -1 --oneline
git -C "$ALVR" log -1 --oneline

echo
echo "=== Required tools ==="
for tool in cmake ninja cargo cbindgen pkg-config; do
    command -v "$tool" >/dev/null || { echo "ERROR: missing tool: $tool"; exit 1; }
done

source "$HOME/.cargo/env" 2>/dev/null || true

echo
echo "=== Build ALVR server core ==="
git -C "$ALVR" submodule sync --recursive
git -C "$ALVR" submodule update --init --recursive
(
    cd "$ALVR"
    cargo xtask build-server-lib
)

test -f "$ALVR/build/alvr_server_core/libalvr_server_core.so" || {
    echo "ERROR: ALVR server core library was not produced."
    exit 1
}
test -f "$ALVR/build/alvr_server_core/alvr_server_core.h" || {
    echo "ERROR: ALVR server core header was not produced."
    exit 1
}

echo
echo "=== ALVR generated ABI ==="
grep -nE 'ALVR_EVENT_(VIEWS_PARAMS|LOCAL_VIEW_PARAMS)|views_params|local_view_params'     "$ALVR/build/alvr_server_core/alvr_server_core.h" || true

echo
echo "=== Configure Monado-ALVR ==="
rm -rf "$BUILD"

cmake     -S "$MONADO"     -B "$BUILD"     -G Ninja     -DCMAKE_BUILD_TYPE=RelWithDebInfo     -DCMAKE_INSTALL_PREFIX="$PREFIX"     -DXRT_BUILD_DRIVER_ALVR=ON     -DXRT_FEATURE_OPENXR=ON     -DXRT_MODULE_COMPOSITOR=ON     -DXRT_MODULE_COMPOSITOR_MAIN=ON     -DXRT_MODULE_MONADO_CLI=ON     -DXRT_FEATURE_SERVICE=ON     -DXRT_OPENXR_INSTALL_ACTIVE_RUNTIME=OFF     -DXRT_FEATURE_STEAMVR_PLUGIN=OFF     -DXRT_BUILD_DRIVER_STEAMVR_LIGHTHOUSE=OFF

echo
echo "=== Build Monado-ALVR ==="
cmake --build "$BUILD" --parallel "$(nproc)"

echo
echo "=== Artifacts ==="
test -x "$BUILD/src/xrt/targets/service/monado-service"
test -f "$BUILD/src/xrt/targets/openxr/libopenxr_monado.so"
test -f "$BUILD/openxr_monado-dev.json"

echo "monado-service:       $BUILD/src/xrt/targets/service/monado-service"
echo "OpenXR runtime:       $BUILD/src/xrt/targets/openxr/libopenxr_monado.so"
echo "OpenXR manifest:      $BUILD/openxr_monado-dev.json"
echo
echo "BUILD SUCCESS"
echo "SteamVR integration remains disabled."
echo "Runtime is NOT started automatically."
