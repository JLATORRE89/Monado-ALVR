#!/usr/bin/env python3
"""Per-instance ALVR configuration and logs in alvr_render (step 11).

alvr_render hard-coded ALVR's config directory to ~/.config/alvr/ and its logs to ~/. Several
runtime instances on one PC (one per headset, see scripts/xr-instance.sh) each need their own
session (trusted headset, stream/web ports) and logs:
  * ALVR_CONFIG_DIR  ALVR config directory (default ~/.config/alvr/)
  * ALVR_LOG_DIR     directory for alvr_session.log / alvr_crash.log (default ~/)
Unset means the previous behaviour. Non-destructive and idempotent.
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
    """            auto const homeDir = std::string(std::getenv("HOME"));
            auto confDir = homeDir + "/.config/alvr/";

            alvr_initialize_environment(confDir.c_str(), homeDir.c_str());

            auto sessionLog = homeDir + "/alvr_session.log";
            auto crashLog = homeDir + "/alvr_crash.log";
""",
    """            auto const homeDir = std::string(std::getenv("HOME"));
            // INTEL-XR: one runtime instance per headset -> per-instance ALVR config and logs.
            char const* intelXrConfDir = std::getenv("ALVR_CONFIG_DIR");
            char const* intelXrLogDir = std::getenv("ALVR_LOG_DIR");
            auto confDir = intelXrConfDir && *intelXrConfDir ? std::string(intelXrConfDir) + "/"
                                                             : homeDir + "/.config/alvr/";
            auto const logDir = intelXrLogDir && *intelXrLogDir ? std::string(intelXrLogDir) : homeDir;

            alvr_initialize_environment(confDir.c_str(), logDir.c_str());

            auto sessionLog = logDir + "/alvr_session.log";
            auto crashLog = logDir + "/alvr_crash.log";
""",
    'std::getenv("ALVR_CONFIG_DIR")',
)

print()
print("alvr_render per-instance ALVR config/log directories are applied.")
print("No Git refs were changed.")
