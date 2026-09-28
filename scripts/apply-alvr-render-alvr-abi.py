#!/usr/bin/env python3
"""Follow ALVR C API changes that alvr_render calls (step 12).

Upstream ALVR master (merged on branch intel-xr-master-merge) added a
`foveation_center_shifts` argument to alvr_send_video_nal(). alvr_render does not foveate, so it
passes nullptr. This helper looks at the ALVR header alvr_render actually compiles against
(src/alvr_binding.h -> the deployed alvr_server_core.h) and patches the call only when that header
has the new signature; with the older header it changes nothing. Non-destructive, idempotent.
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


src = project_root() / "src" / "alvr_render" / "src"
header = src / "alvr_binding.h"
nal = src / "alvr_server" / "NalParsing.cpp"
if not nal.is_file():
    raise SystemExit(f"ERROR: required source file missing: {nal}")

try:
    header_text = header.read_text()
except OSError:
    header_text = ""  # header not generated yet (fresh checkout before the ALVR build)

old = "    alvr_send_video_nal(targetTimestampNs, viewParams, isIdr, buf, len);\n"
new = "    alvr_send_video_nal(targetTimestampNs, viewParams, nullptr /* no foveation */, isIdr, buf, len);\n"
text = nal.read_text()
if "foveation_center_shifts" not in header_text:
    print(f"[not needed] {header}: ALVR header has the older alvr_send_video_nal signature")
elif new in text:
    print(f"[already patched] {nal}: alvr_send_video_nal foveation argument")
elif old in text:
    nal.write_text(text.replace(old, new, 1))
    print(f"[patched] {nal}: alvr_send_video_nal foveation argument")
else:
    raise SystemExit(f"ERROR: alvr_send_video_nal call not found in {nal}")
print("No Git refs were changed.")
