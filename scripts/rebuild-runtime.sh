#!/usr/bin/env bash
# Safe, incremental runtime rebuild: re-apply the idempotent alvr_render companion patches,
# rebuild/deploy the ALVR server core and rebuild Monado. Never fetches, resets or checks
# out Git refs (unlike build-intel-xr.sh / prepare-companions.sh). Restart the runtime
# afterwards: bash scripts/monado-service.sh restart
set -Eeuo pipefail
ROOT="${INTEL_XR_ROOT:-/ai/intel-xr-prototype}"
MONADO="$ROOT/src/Monado-ALVR"
ALVR="$ROOT/src/alvr-monado"

echo "=== Apply alvr_render companion patches ==="
bash "$MONADO/scripts/apply-alvr-render-companion.sh"

echo "=== Build and deploy ALVR server core ==="
(cd "$ALVR" && cargo build -p alvr_server_core)
(cd "$ALVR/alvr" && cargo xtask build-server-lib)
target="$(sha256sum "$ALVR/target/debug/libalvr_server_core.so" | cut -d' ' -f1)"
deployed="$(sha256sum "$ALVR/build/alvr_server_core/libalvr_server_core.so" | cut -d' ' -f1)"
[[ "$target" == "$deployed" ]] || { echo "ERROR: deployed server core does not match build" >&2; exit 1; }
echo "server core sha256 $target"

echo "=== Build Monado ==="
cmake --build "$ROOT/build/monado-alvr" --parallel "$(nproc)"

echo "REBUILD OK. Restart: bash $MONADO/scripts/monado-service.sh restart"
