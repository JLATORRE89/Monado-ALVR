#!/usr/bin/env python3
"""Apply low-noise Intel XR server video-path markers to companion checkouts.

This script is intentionally non-destructive: it does not fetch, reset, checkout, or
otherwise change Git refs. It only patches the two companion source files that are
outside the Monado-ALVR repository.
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

    # Expected checkout layout: <root>/src/Monado-ALVR/scripts/this_file.py
    inferred = here.parents[3]
    if (inferred / "src" / "Monado-ALVR").is_dir():
        return inferred

    raise SystemExit("ERROR: cannot locate intel-xr-prototype; set INTEL_XR_ROOT")


def patch_once(path: Path, old: str, new: str, marker: str) -> bool:
    text = path.read_text()
    if marker in text:
        print(f"[already instrumented] {path}: {marker}")
        return False
    if old not in text:
        raise SystemExit(f"ERROR: insertion point missing in {path}: {marker}")
    path.write_text(text.replace(old, new, 1))
    print(f"[patched] {path}: {marker}")
    return True


root = project_root()
alvr_render = root / "src" / "alvr_render" / "src" / "Encoder.cpp"
connection = root / "src" / "alvr-monado" / "alvr" / "server_core" / "src" / "connection.rs"

for path in (alvr_render, connection):
    if not path.is_file():
        raise SystemExit(f"ERROR: required source file missing: {path}")

encoder_old = """    renderer.get().render(vkCtx, idx, timelineVal);

    // TODO: not sure, but might actually work
    static u64 counter = 0;

    encoder->PushFrame(counter++, /* idrScheduler.CheckIDRInsertion() */ true);

    alvr::FramePacket framePacket;
    if (!encoder->GetEncoded(framePacket)) {
        assert(false);
    }

    // TODO: This constant conversion sucks
"""

encoder_new = """    renderer.get().render(vkCtx, idx, timelineVal);

    // Low-noise server-side diagnostic: prove that a Monado compositor image made
    // it all the way to the encode submission boundary.
    static bool intelXrEncoderInputLogged = false;
    if (!intelXrEncoderInputLogged) {
        std::cerr << "[INTEL-XR-SERVER] ENCODER_INPUT image=" << idx
                  << " timeline=" << timelineVal << std::endl;
        intelXrEncoderInputLogged = true;
    }

    // TODO: not sure, but might actually work
    static u64 counter = 0;

    encoder->PushFrame(counter++, /* idrScheduler.CheckIDRInsertion() */ true);

    alvr::FramePacket framePacket;
    if (!encoder->GetEncoded(framePacket)) {
        assert(false);
    }

    static bool intelXrEncodedFrameLogged = false;
    if (!intelXrEncodedFrameLogged) {
        std::cerr << "[INTEL-XR-SERVER] ENCODED_FRAME bytes=" << framePacket.size
                  << " idr=" << (framePacket.isIDR ? "true" : "false")
                  << " codec=" << encoder->GetCodec() << std::endl;
        intelXrEncodedFrameLogged = true;
    }

    // TODO: This constant conversion sucks
"""

patch_once(
    alvr_render,
    encoder_old,
    encoder_new,
    "[INTEL-XR-SERVER] ENCODER_INPUT",
)

connection_old = """        move || {
            while is_streaming(&client_hostname) {
"""

connection_new = """        move || {
            let mut intel_xr_video_packet_sent_logged = false;
            while is_streaming(&client_hostname) {
"""

patch_once(
    connection,
    connection_old,
    connection_new,
    "intel_xr_video_packet_sent_logged",
)

send_old = """                video_sender.send(buffer).ok();
"""

send_new = """                let payload_len = payload.len();
                let is_idr = header.is_idr;
                if video_sender.send(buffer).is_ok() && !intel_xr_video_packet_sent_logged {
                    info!(
                        "[INTEL-XR-SERVER] VIDEO_PACKET_SENT bytes={} idr={}",
                        payload_len, is_idr
                    );
                    intel_xr_video_packet_sent_logged = true;
                }
"""

patch_once(
    connection,
    send_old,
    send_new,
    "[INTEL-XR-SERVER] VIDEO_PACKET_SENT",
)

print()
print("Server video instrumentation is applied.")
print("Expected markers:")
print("  FRAME_RECEIVED_FROM_MONADO   (Monado-ALVR repository source)")
print("  ENCODER_INPUT                (alvr_render companion)")
print("  ENCODED_FRAME ... idr=...    (alvr_render companion)")
print("  VIDEO_PACKET_SENT ...        (ALVR server_core companion)")
print()
print("No Git refs were changed.")
