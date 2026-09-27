#!/usr/bin/env bash
# Reconstruct the known-good alvr_render companion state on top of the pinned clean revision
# (ecb281249b6900ec6ceb6e0570be5100533c706a) by applying the companion helpers in order.
#
#   bash scripts/apply-alvr-render-companion.sh          # uses $INTEL_XR_ROOT/src/alvr_render
#
# Every helper is idempotent and non-destructive: it never fetches, resets or checks out Git
# refs, and a second run changes nothing. Verified byte-identical against the working tree
# (see TASKS.md "CONSOLIDATION RESULT").
set -Eeuo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

HELPERS=(
  apply-alvr-render-base-compat.py         # 1 ABI rename + Intel linear DMA-BUF (from prepare-companions.sh)
  apply-server-video-instrumentation.py    # 2 INTEL-XR video markers, warning cleanup, NAL probe rate limit
  apply-alvr-render-request-idr.py         # 3 RequestIDR -> IDRScheduler
  apply-alvr-render-encoder-bitrate.py     # 4 VAAPI rate control/refresh/codec from the ALVR session
  apply-alvr-render-intel-map-output.py    # 5 encode the renderer's real output on Intel
  apply-alvr-render-h264-dump.py           # 6 opt-in encoder dump (diagnostic)
  apply-alvr-render-dynamic-bitrate.py     # 7 dynamic bitrate via encoder re-open
  apply-alvr-render-frame-timestamps.py    # 8 tracking frame timestamps (unique)
  apply-alvr-render-idr-dedup.py           # 9 IDR coalescing + fault handler
  apply-alvr-render-stream-extent.py       # 10 two-eye stream canvas
)

for helper in "${HELPERS[@]}"; do
  echo "=== $helper"
  python3 "$HERE/$helper" | grep -E "^\[|ERROR" || true
  # Fail if the helper reported an error (grep above hides nothing but keeps output short).
  python3 "$HERE/$helper" >/dev/null
done
echo "COMPANION OK"
