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



def cleanup_companion_warnings() -> None:
    """Fix warning-producing companion code without changing ABI-sensitive bindings."""
    renderer = root / "src" / "alvr_render" / "src" / "Renderer.hpp"
    utils = root / "src" / "alvr_render" / "src" / "utils.hpp"

    if renderer.is_file():
        text = renderer.read_text()
        old = """        return AlvrVkExport {
            .sem = timelineSem,
        };"""
        new = """        AlvrVkExport out {};
        out.sem = timelineSem;
        return out;"""
        if old in text:
            renderer.write_text(text.replace(old, new, 1))
            print(f"[cleanup] {renderer}: initialize AlvrVkExport")
        elif "AlvrVkExport out {};" in text:
            print(f"[already cleaned] {renderer}: AlvrVkExport")

    if utils.is_file():
        text = utils.read_text()
        # Optional::get() currently falls off the end after assert(false), which
        # triggers -Wreturn-type and is undefined behavior in release builds.
        old = """        assert(false);
    }"""
        new = """        assert(false);
        std::abort();
    }"""
        if old in text and "std::abort();" not in text:
            if "#include <cstdlib>" not in text:
                text = text.replace("#include ", "#include <cstdlib>\n#include ", 1)
            utils.write_text(text.replace(old, new, 1))
            print(f"[cleanup] {utils}: make Optional::get() non-returning")
        elif "std::abort();" in text:
            print(f"[already cleaned] {utils}: Optional::get()")

cleanup_companion_warnings()
alvr_render = root / "src" / "alvr_render" / "src" / "Encoder.cpp"

if not alvr_render.is_file():
    raise SystemExit(f"ERROR: required source file missing: {alvr_render}")

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

print()
print("Server video instrumentation is applied.")
print("Expected markers:")
print("  FRAME_RECEIVED_FROM_MONADO   (Monado-ALVR repository source)")
print("  ENCODER_INPUT                (alvr_render companion)")
print("  ENCODED_FRAME ... idr=...    (alvr_render companion)")
print("  VIDEO_PACKET_SENT ...        (JLATORRE89/ALVR branch)")
print("  DECODER_CONFIG_SENT ...      (JLATORRE89/ALVR branch)")
print()
print("No Git refs were changed.")
