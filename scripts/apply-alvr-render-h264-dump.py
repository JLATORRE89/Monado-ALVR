#!/usr/bin/env python3
"""Opt-in dump of alvr_render encoder output for offline decoding.

When $INTEL_XR_ROOT/logs/INTEL_XR_DUMP_H264 exists at the first encoded
frame, Encoder::present() appends the first 150 encoded frames (Annex-B, as
passed to ParseFrameNals) to $INTEL_XR_ROOT/logs/encoder-dump.h264. Without
the trigger file nothing is written. Decode with e.g.
    ffmpeg -i logs/encoder-dump.h264 -frames:v 1 first.png

Non-destructive and idempotent, like the other apply-*.py companion helpers.
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

# Log directory baked into the patch; INTEL_XR_LOG_DIR overrides <root>/logs.
logs = Path(os.environ.get("INTEL_XR_LOG_DIR", root / "logs"))

patch_once(
    encoder_cpp,
    """    // TODO: This constant conversion sucks
    AlvrViewParams viewParams[2];""",
    f"""    // Opt-in encoder output dump (INTEL-XR diagnostic): create the trigger file
    // {logs}/INTEL_XR_DUMP_H264 before the service starts.
    {{
        static int intelXrDumpState = -1; // -1 unknown, 0 off, 1 on
        static u64 intelXrDumpFrames = 0;
        if (intelXrDumpState < 0) {{
            intelXrDumpState = std::filesystem::exists("{logs}/INTEL_XR_DUMP_H264") ? 1 : 0;
        }}
        if (intelXrDumpState == 1 && intelXrDumpFrames < 150) {{
            std::ofstream dump("{logs}/encoder-dump.h264", std::ios::binary | std::ios::app);
            dump.write(reinterpret_cast<char const*>(framePacket.data), framePacket.size);
            if (++intelXrDumpFrames == 150) {{
                std::cerr << "[INTEL-XR-SERVER] ENCODER_DUMP_DONE frames=150" << std::endl;
            }}
        }}
    }}

    // TODO: This constant conversion sucks
    AlvrViewParams viewParams[2];""",
    "INTEL_XR_DUMP_H264",
)

# Upgrade: dump while the trigger file exists (checked every ~0.5 s, max 30 s at 72 fps),
# starting with a forced IDR so the capture window is decodable; no restart needed.
patch_once(
    encoder_cpp,
    f"""        static int intelXrDumpState = -1; // -1 unknown, 0 off, 1 on
        static u64 intelXrDumpFrames = 0;
        if (intelXrDumpState < 0) {{
            intelXrDumpState = std::filesystem::exists("{logs}/INTEL_XR_DUMP_H264") ? 1 : 0;
        }}
        if (intelXrDumpState == 1 && intelXrDumpFrames < 150) {{
            std::ofstream dump("{logs}/encoder-dump.h264", std::ios::binary | std::ios::app);
            dump.write(reinterpret_cast<char const*>(framePacket.data), framePacket.size);
            if (++intelXrDumpFrames == 150) {{
                std::cerr << "[INTEL-XR-SERVER] ENCODER_DUMP_DONE frames=150" << std::endl;
            }}
        }}""",
    f"""        // INTEL_XR_DUMP_WHILE_TRIGGER: record while the trigger file exists.
        static bool intelXrDumping = false;
        static bool intelXrDumpWaitIdr = false;
        static u64 intelXrDumpCheck = 0;
        static u64 intelXrDumpFrames = 0;
        if (intelXrDumpCheck++ % 36 == 0) {{
            bool const want = std::filesystem::exists("{logs}/INTEL_XR_DUMP_H264");
            if (want && !intelXrDumping) {{
                intelXrDumping = true;
                intelXrDumpWaitIdr = true;
                intelXrDumpFrames = 0;
                idrScheduler.RequestIDR();
                std::cerr << "[INTEL-XR-SERVER] ENCODER_DUMP_START" << std::endl;
            }} else if (!want && intelXrDumping) {{
                intelXrDumping = false;
                std::cerr << "[INTEL-XR-SERVER] ENCODER_DUMP_STOP frames=" << intelXrDumpFrames << std::endl;
            }}
        }}
        if (intelXrDumping && intelXrDumpWaitIdr && framePacket.isIDR) {{
            intelXrDumpWaitIdr = false;
        }}
        if (intelXrDumping && !intelXrDumpWaitIdr && intelXrDumpFrames < 2160) {{
            std::ofstream dump("{logs}/encoder-dump.h264", std::ios::binary | std::ios::app);
            dump.write(reinterpret_cast<char const*>(framePacket.data), framePacket.size);
            ++intelXrDumpFrames;
        }}""",
    "INTEL_XR_DUMP_WHILE_TRIGGER",
)

print()
print("alvr_render opt-in encoder dump is applied.")
print(f"Trigger: touch {logs}/INTEL_XR_DUMP_H264 to start recording, delete it to stop.")
print("No Git refs were changed.")
