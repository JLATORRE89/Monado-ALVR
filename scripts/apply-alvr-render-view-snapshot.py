#!/usr/bin/env python3
"""On-demand snapshot of the view a headset is being streamed (step 13).

Lets the control panel capture what a headset sees without ADB (so also over Wi-Fi, and per
runtime instance): when $XDG_RUNTIME_DIR/intel-xr-view-request appears, alvr_render removes it,
forces a keyframe and writes that single encoded frame (Annex-B with parameter sets, decodable on
its own) to $XDG_RUNTIME_DIR/intel-xr-view.h264 (written to .tmp, then renamed). Each runtime
instance has its own XDG_RUNTIME_DIR, so each headset's request reaches its own encoder.
The image is the streamed frame (both eyes side by side): Loft/app content, not passthrough or the
Quest's own overlays. Non-destructive and idempotent.
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


encoder_cpp = project_root() / "src" / "alvr_render" / "src" / "Encoder.cpp"
if not encoder_cpp.is_file():
    raise SystemExit(f"ERROR: required source file missing: {encoder_cpp}")

patch_once(
    encoder_cpp,
    """    // TODO: This constant conversion sucks
    AlvrViewParams viewParams[2];""",
    """    // INTEL-XR view snapshot on request (control panel, no ADB needed): see
    // scripts/apply-alvr-render-view-snapshot.py.
    {
        static bool intelXrViewWanted = false;
        static u64 intelXrViewCheck = 0;
        static std::string const intelXrRuntimeDir =
            std::getenv("XDG_RUNTIME_DIR") ? std::string(std::getenv("XDG_RUNTIME_DIR")) : std::string("/tmp");
        if (!intelXrViewWanted && intelXrViewCheck++ % 9 == 0) {
            std::error_code ec;
            if (std::filesystem::remove(intelXrRuntimeDir + "/intel-xr-view-request", ec)) {
                intelXrViewWanted = true;
                idrScheduler.RequestIDR();
            }
        }
        if (intelXrViewWanted && framePacket.isIDR) {
            intelXrViewWanted = false;
            std::string const out = intelXrRuntimeDir + "/intel-xr-view.h264";
            {
                std::ofstream view(out + ".tmp", std::ios::binary | std::ios::trunc);
                view.write(reinterpret_cast<char const*>(framePacket.data), framePacket.size);
            }
            std::error_code ec;
            std::filesystem::rename(out + ".tmp", out, ec);
            std::cerr << "[INTEL-XR-SERVER] VIEW_SNAPSHOT bytes=" << framePacket.size << std::endl;
        }
    }

    // TODO: This constant conversion sucks
    AlvrViewParams viewParams[2];""",
    "intel-xr-view-request",
)

print()
print("alvr_render on-demand view snapshots are applied.")
print("No Git refs were changed.")
