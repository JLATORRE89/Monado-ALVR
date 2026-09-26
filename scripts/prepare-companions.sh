#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${INTEL_XR_ROOT:-/ai/intel-xr-prototype}"
LOGDIR="$ROOT/logs"
mkdir -p "$LOGDIR"
LOG="$LOGDIR/$(date +%Y-%m-%d_%H-%M-%S)_prepare-companions.log"
exec > >(tee "$LOG") 2>&1
ALVR="$ROOT/src/alvr-monado"
ALVR_RENDER="$ROOT/src/alvr_render"

# These are the current tips of the historical companion integration branches
# used by Monado-ALVR. Pinning makes workstation builds reproducible.
ALVR_REV="5d45a6dcd9a5ae3df7c60c6a1282fb52140346da"
ALVR_RENDER_REV="ecb281249b6900ec6ceb6e0570be5100533c706a"

for d in "$ALVR" "$ALVR_RENDER"; do
    [[ -d "$d/.git" ]] || { echo "ERROR: missing repository: $d"; exit 1; }
done

echo "=== Prepare companion sources ==="
git -C "$ALVR" fetch origin
git -C "$ALVR" checkout --detach "$ALVR_REV"
git -C "$ALVR" submodule sync --recursive
git -C "$ALVR" submodule update --init --recursive

echo "=== Apply XR multi-mode client compatibility ==="
python3 - "$ALVR/alvr/session/src/settings.rs" "$ALVR/alvr/server_core/src/web_server.rs" <<'PY'
from pathlib import Path
import sys
settings=Path(sys.argv[1]); s=settings.read_text()
s=s.replace('auto_trust_clients: cfg!(debug_assertions),','auto_trust_clients: true,')
settings.write_text(s)

web=Path(sys.argv[2]); w=web.read_text()
# Add a compact persistent-state endpoint for the local XR client manager.
needle='.route("/ping", routing::get(async || ())),'
repl='''.route("/ping", routing::get(async || ()))
                .route("/xr/clients", routing::get(get_xr_clients)),'''
if needle in w and 'get_xr_clients' not in w:
    w=w.replace(needle,repl,1)
    w += '''
async fn get_xr_clients() -> Json<serde_json::Value> {
    let session = SESSION_MANAGER.read();
    Json(serde_json::json!({
        "auto_accept": session.settings().connection.client_discovery
            .as_option().map(|c| c.auto_trust_clients).unwrap_or(false),
        "clients": session.client_list(),
    }))
}
'''
web.write_text(w)
PY

git -C "$ALVR_RENDER" fetch origin
git -C "$ALVR_RENDER" checkout --detach "$ALVR_RENDER_REV"
git -C "$ALVR_RENDER" reset --hard "$ALVR_RENDER_REV"

echo "=== Apply Monado/ALVR ABI compatibility ==="
for f in "$ALVR_RENDER/src/Encoder.cpp" "$ALVR_RENDER/src/EventManager.hpp"; do
    sed -i       -e 's/ALVR_EVENT_VIEWS_PARAMS/ALVR_EVENT_LOCAL_VIEW_PARAMS/g'       -e 's/event\.views_params/event.local_view_params/g'       "$f"
done

echo "=== Apply Intel Arc DMA-BUF compatibility ==="
python3 - "$ALVR_RENDER/src/Renderer.cpp" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
s = p.read_text()
old = "bool haveDrmModifiers = true;"
new = """// Intel ANV can export DMA-BUF, but the historical DRM-modifier image
    // creation path crashes during vkCreateImage on the tested Arc A750/Mesa
    // stack. Keep DMA-BUF for FFmpeg/VAAPI, but use the linear fallback.
    const bool isIntel = ctx.physDev.getProperties().vendorID == 0x8086;
    bool haveDrmModifiers = !isIntel;"""
if old not in s and new not in s:
    raise SystemExit("ERROR: expected DRM modifier switch not found")
if old in s:
    s = s.replace(old, new, 1)
p.write_text(s)
PY

echo "=== Companion state ==="
git -C "$ALVR" log -1 --oneline
git -C "$ALVR_RENDER" log -1 --oneline
git -C "$ALVR_RENDER" diff -- src/Encoder.cpp src/EventManager.hpp src/Renderer.cpp
