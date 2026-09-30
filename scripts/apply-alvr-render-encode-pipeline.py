#!/usr/bin/env python3
"""Pipeline the VAAPI encode so the compositor keeps 72 fps (step 18).

With async_depth=1 avcodec_send_frame() returns only after the frame is fully encoded, and it runs
inside the compositor's present: the compositor waited for its own render, the colour conversion
and the HEVC encode of every frame (measured with bpftrace on 2026-09-29: Encoder::present 16.6 ms,
of which avcodec_send_frame 16.4 ms; GPU engines 34 % 3D / 23 % video at 36 fps). Longer than the
13.9 ms of a 72 Hz frame, so the compositor missed every other vsync and streamed 36 fps: older
frames for the Quest to reproject, which showed the frame edges during fast head turns.
With async_depth=2 the encoder works on frame N while the compositor renders frame N+1; the packet
for frame N comes out during frame N+1's present. Each packet is therefore sent with the views and
tracking timestamp of the frame it encodes (kept by encoder pts), not those of the frame being
presented. INTEL_XR_ENCODE_ASYNC_DEPTH (1..4, default 2) selects the depth; 1 is the previous
behaviour. Non-destructive and idempotent.
"""
from __future__ import annotations

import os
from pathlib import Path


def project_root() -> Path:
    if os.getenv("INTEL_XR_ROOT"):
        return Path(os.environ["INTEL_XR_ROOT"]).resolve()
    here = Path(__file__).resolve()
    for candidate in (Path.cwd(), here.parent):
        for parent in (candidate, *candidate.parents):
            if parent.name == "intel-xr-prototype":
                return parent
    inferred = here.parents[3]
    if (inferred / "src" / "Monado-ALVR").is_dir():
        return inferred
    raise SystemExit("ERROR: cannot locate intel-xr-prototype; set INTEL_XR_ROOT")


def patch_once(path: Path, old: str, new: str, marker: str) -> bool:
    text = path.read_text()
    if marker in text:
        print(f"[already patched] {path}: {marker}")
        return False
    if old not in text:
        raise SystemExit(f"ERROR: insertion point missing in {path}: {marker}")
    path.write_text(text.replace(old, new, 1))
    print(f"[patched] {path}: {marker}")
    return True


src = project_root() / "src" / "alvr_render" / "src"
pipeline_cpp = src / "EncodePipelineVAAPI.cpp"
encoder_cpp = src / "Encoder.cpp"
for f in (pipeline_cpp, encoder_cpp):
    if not f.is_file():
        raise SystemExit(f"ERROR: required source file missing: {f}")

# 1. Encoder depth (the re-open of step 15 copies it with the other private options).
patch_once(
    pipeline_cpp,
    """  av_opt_set_int(encoder_ctx->priv_data, "async_depth", 1, 0);
""",
    """  // INTEL_XR_ENCODE_PIPELINE: encode frame N while the compositor renders frame N+1 (see
  // scripts/apply-alvr-render-encode-pipeline.py); INTEL_XR_ENCODE_ASYNC_DEPTH=1 restores the
  // fully synchronous encode.
  {
    char const *v = getenv("INTEL_XR_ENCODE_ASYNC_DEPTH");
    int depth = v ? atoi(v) : 2;
    if (depth < 1 || depth > 4)
      depth = 2;
    std::cerr << "[INTEL-XR-SERVER] ENCODE_ASYNC_DEPTH " << depth << std::endl;
    av_opt_set_int(encoder_ctx->priv_data, "async_depth", depth, 0);
  }
""",
    "INTEL_XR_ENCODE_PIPELINE",
)

# 2. Remember each frame's views and tracking timestamp by encoder pts.
patch_once(
    encoder_cpp,
    """    bool const insertIdr = idrScheduler.CheckIDRInsertion();
    encoder->PushFrame(counter++, insertIdr);
""",
    """    bool const insertIdr = idrScheduler.CheckIDRInsertion();
    // INTEL_XR_FRAME_META: with a pipelined encode (step 18) the packet received below can belong
    // to an earlier frame; keep what each frame was rendered with, keyed by its encoder pts.
    struct IntelXrFrameMeta {
        u64 pts = ~0ull;
        ViewsInfo views {};
        u64 trackingNs = 0;
    };
    static IntelXrFrameMeta intelXrFrameMeta[8];
    intelXrFrameMeta[counter % 8] = IntelXrFrameMeta { counter, views, trackingTimestampNs };
    encoder->PushFrame(counter++, insertIdr);
""",
    "INTEL_XR_FRAME_META",
)

# 3. Use the packet's own frame metadata from here on.
patch_once(
    encoder_cpp,
    """    // Pair the optional raw readback with the exact compressed frame and eye poses.
""",
    """    // INTEL_XR_PACKET_META: views and tracking timestamp of the frame this packet encodes.
    ViewsInfo const *packetViews = &views;
    u64 packetTrackingNs = trackingTimestampNs;
    {
        IntelXrFrameMeta const &meta = intelXrFrameMeta[framePacket.pts % 8];
        if (meta.pts == framePacket.pts) {
            packetViews = &meta.views;
            packetTrackingNs = meta.trackingNs;
        }
    }

    // Pair the optional raw readback with the exact compressed frame and eye poses.
""",
    "INTEL_XR_PACKET_META",
)
patch_once(
    encoder_cpp,
    """            for (auto const &v : {views.left, views.right}) {""",
    """            for (auto const &v : {packetViews->left, packetViews->right}) {""",
    "{packetViews->left, packetViews->right}",
)
patch_once(
    encoder_cpp,
    """    viewParams[0] = views.left;
    viewParams[1] = views.right;
""",
    """    viewParams[0] = packetViews->left;
    viewParams[1] = packetViews->right;
""",
    "viewParams[0] = packetViews->left;",
)
patch_once(
    encoder_cpp,
    """    u64 frameTimestampNs = trackingTimestampNs != 0 ? trackingTimestampNs : framePacket.pts;""",
    """    u64 frameTimestampNs = packetTrackingNs != 0 ? packetTrackingNs : framePacket.pts;""",
    "u64 frameTimestampNs = packetTrackingNs",
)
