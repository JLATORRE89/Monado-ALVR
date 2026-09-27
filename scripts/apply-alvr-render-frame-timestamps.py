#!/usr/bin/env python3
"""Tag encoded frames with ALVR tracking timestamps and report present/composed.

ALVR's statistics (network latency, the input to Adaptive bitrate) and the
client's per-frame pose lookup are keyed by the tracking sample timestamp
(`poll_timestamp`) the frame was rendered for. alvr_render passed the encoder's
frame counter (0, 1, 2, ...) to alvr_send_video_nal(), so no frame ever matched a
tracking sample: network latency was never measured and Adaptive bitrate had
no data.

This patch remembers the latest ALVR_EVENT_TRACKING_UPDATED sample timestamp
in handleEvents(), reports it via alvr_report_present()/alvr_report_composed()
before encoding, and passes it to ParseFrameNals() as the frame timestamp. The
encoder's own pts remains the monotonic counter. Before the first tracking
sample, the counter is used as before.

Apply after apply-server-video-instrumentation.py (it shares the
ParseFrameNals line). Non-destructive and idempotent.
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


root = project_root()
encoder_cpp = root / "src" / "alvr_render" / "src" / "Encoder.cpp"
if not encoder_cpp.is_file():
    raise SystemExit(f"ERROR: required source file missing: {encoder_cpp}")

patch_once(
    encoder_cpp,
    """#include <chrono>
""",
    """#include <atomic>
#include <chrono>
""",
    "#include <atomic>",
)

patch_once(
    encoder_cpp,
    """void handleEvents()
{""",
    """// Latest ALVR tracking sample timestamp (poll_timestamp). Frames are tagged with it
// so ALVR statistics and the client's pose lookup can match them.
static std::atomic<u64> g_latestTrackingTimestampNs { 0 };

void handleEvents()
{""",
    "g_latestTrackingTimestampNs",
)

patch_once(
    encoder_cpp,
    """            auto ts = event.TRACKING_UPDATED.sample_timestamp_ns;
""",
    """            auto ts = event.TRACKING_UPDATED.sample_timestamp_ns;
            g_latestTrackingTimestampNs.store(ts);
""",
    "g_latestTrackingTimestampNs.store(ts);",
)

patch_once(
    encoder_cpp,
    """    // Apply ALVR's dynamic encoder params (ConstantMbps changes / Adaptive mode),""",
    """    // Frame timestamp = latest tracking sample; report present/composed for ALVR stats.
    u64 const trackingTimestampNs = g_latestTrackingTimestampNs.load();
    if (trackingTimestampNs != 0) {
        alvr_report_present(trackingTimestampNs, 0);
        alvr_report_composed(trackingTimestampNs, 0);
        static bool intelXrFrameTimestampLogged = false;
        if (!intelXrFrameTimestampLogged) {
            std::cerr << "[INTEL-XR-SERVER] FRAME_TIMESTAMP source=tracking ts_ns=" << trackingTimestampNs
                      << std::endl;
            intelXrFrameTimestampLogged = true;
        }
    }

    // Apply ALVR's dynamic encoder params (ConstantMbps changes / Adaptive mode),""",
    "FRAME_TIMESTAMP source=tracking",
)

patch_once(
    encoder_cpp,
    """    ParseFrameNals(encoder->GetCodec(), viewParams, framePacket.data, framePacket.size, framePacket.pts, framePacket.isIDR);""",
    """    u64 const frameTimestampNs = trackingTimestampNs != 0 ? trackingTimestampNs : framePacket.pts;
    ParseFrameNals(encoder->GetCodec(), viewParams, framePacket.data, framePacket.size, frameTimestampNs, framePacket.isIDR);""",
    "u64 const frameTimestampNs",
)

# Frames outpace tracking samples (Monado ~90 Hz vs Quest tracking 72 Hz), so several frames
# got the same timestamp. The client looks up each frame's view params by timestamp and takes
# the first match, i.e. a stale head/eye pose for repeated timestamps (double vision/judder
# during head motion). Keep timestamps unique and increasing.
patch_once(
    encoder_cpp,
    """    u64 const frameTimestampNs = trackingTimestampNs != 0 ? trackingTimestampNs : framePacket.pts;""",
    """    static u64 lastFrameTimestampNs = 0;
    u64 frameTimestampNs = trackingTimestampNs != 0 ? trackingTimestampNs : framePacket.pts;
    // The client matches view params by timestamp: never reuse one (frames outpace tracking).
    if (frameTimestampNs <= lastFrameTimestampNs) {
        frameTimestampNs = lastFrameTimestampNs + 1;
    }
    lastFrameTimestampNs = frameTimestampNs;""",
    "lastFrameTimestampNs",
)

print()
print("alvr_render frame timestamps are applied.")
print("Expected marker: FRAME_TIMESTAMP source=tracking ts_ns=...")
print("No Git refs were changed.")
