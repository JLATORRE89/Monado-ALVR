#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${INTEL_XR_ROOT:-/ai/intel-xr-prototype}"
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
