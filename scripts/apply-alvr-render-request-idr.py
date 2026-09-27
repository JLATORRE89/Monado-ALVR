#!/usr/bin/env python3
"""Route ALVR RequestIDR events into alvr_render's existing IDRScheduler.

ServerCoreEvent::RequestIDR reaches alvr_render through alvr_poll_event() as
ALVR_EVENT_REQUEST_IDR, but the companion handleEvents() loop dropped it, and
Encoder::present() bypassed IDRScheduler by forcing an IDR on every frame.

This patch:
  * adds a REQUEST_IDR slot to the existing CallbackManager dispatch;
  * dispatches ALVR_EVENT_REQUEST_IDR from handleEvents();
  * registers Encoder's IDRScheduler::InsertIDR() for that event;
  * restores idrScheduler.CheckIDRInsertion() as the PushFrame IDR flag;
  * skips a frame instead of parsing an uninitialized packet if the encoder
    has no output yet;
  * adds rate-limited INTEL-XR markers for the consumed request and encoded IDRs.

Like apply-server-video-instrumentation.py this is non-destructive: it never
fetches, resets or checks out Git refs, and it is idempotent.
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
src = root / "src" / "alvr_render" / "src"
event_manager = src / "EventManager.hpp"
encoder_hpp = src / "Encoder.hpp"
encoder_cpp = src / "Encoder.cpp"

for required in (event_manager, encoder_hpp, encoder_cpp):
    if not required.is_file():
        raise SystemExit(f"ERROR: required source file missing: {required}")

# CallbackManager: storage, registration and dispatch for REQUEST_IDR.
patch_once(
    event_manager,
    """    Fns<void(ViewsInfo)> viewsConfig;
""",
    """    Fns<void(ViewsInfo)> viewsConfig;
    Fns<void()> requestIdr;
""",
    "Fns<void()> requestIdr;",
)

patch_once(
    event_manager,
    """                dispatch<ALVR_EVENT_LOCAL_VIEW_PARAMS>(lastViewsConfig.get());
            }
        } else {""",
    """                dispatch<ALVR_EVENT_LOCAL_VIEW_PARAMS>(lastViewsConfig.get());
            }
        } else if constexpr (eventType == ALVR_EVENT_REQUEST_IDR) {
            requestIdr.push_back(std::move(cb));
        } else {""",
    "requestIdr.push_back(std::move(cb));",
)

patch_once(
    event_manager,
    """                return viewsConfig;
            } else {""",
    """                return viewsConfig;
            } else if constexpr (eventType == ALVR_EVENT_REQUEST_IDR) {
                return requestIdr;
            } else {""",
    "return requestIdr;",
)

# Encoder: remember whether the RequestIDR callback is registered, because
# initEncoding() runs again whenever the compositor target recreates images.
patch_once(
    encoder_hpp,
    """    IDRScheduler idrScheduler;
""",
    """    IDRScheduler idrScheduler;
    bool requestIdrRegistered = false;
""",
    "bool requestIdrRegistered",
)

# handleEvents(): consume ALVR_EVENT_REQUEST_IDR instead of dropping it.
patch_once(
    encoder_cpp,
    """            CallbackManager::get().dispatch<ALVR_EVENT_LOCAL_VIEW_PARAMS>(info);
        } else {""",
    """            CallbackManager::get().dispatch<ALVR_EVENT_LOCAL_VIEW_PARAMS>(info);
        } else if (event.tag == ALVR_EVENT_REQUEST_IDR) {
            static u64 intelXrRequestIdrCount = 0;
            ++intelXrRequestIdrCount;
            if (intelXrRequestIdrCount <= 20 || intelXrRequestIdrCount % 100 == 0) {
                std::cerr << "[INTEL-XR-SERVER] REQUEST_IDR_CONSUMED count=" << intelXrRequestIdrCount
                          << std::endl;
            }
            CallbackManager::get().dispatch<ALVR_EVENT_REQUEST_IDR>();
        } else {""",
    "REQUEST_IDR_CONSUMED",
)

patch_once(
    encoder_cpp,
    """    idrScheduler.OnStreamStart();
}""",
    """    idrScheduler.OnStreamStart();

    // ServerCoreEvent::RequestIDR (video transport ready, client decoder
    // bootstrap, packet loss) feeds the existing IDR scheduler.
    if (!requestIdrRegistered) {
        CallbackManager::get().registerCb<ALVR_EVENT_REQUEST_IDR>([this]() { idrScheduler.InsertIDR(); });
        requestIdrRegistered = true;
    }
}""",
    "registerCb<ALVR_EVENT_REQUEST_IDR>",
)

# present(): honour the scheduler instead of forcing an IDR on every frame.
patch_once(
    encoder_cpp,
    """    encoder->PushFrame(counter++, /* idrScheduler.CheckIDRInsertion() */ true);

    alvr::FramePacket framePacket;
    if (!encoder->GetEncoded(framePacket)) {
        assert(false);
    }
""",
    """    bool const insertIdr = idrScheduler.CheckIDRInsertion();
    encoder->PushFrame(counter++, insertIdr);

    alvr::FramePacket framePacket;
    if (!encoder->GetEncoded(framePacket)) {
        static u64 intelXrNoOutputCount = 0;
        ++intelXrNoOutputCount;
        if (intelXrNoOutputCount <= 20 || intelXrNoOutputCount % 500 == 0) {
            std::cerr << "[INTEL-XR-SERVER] ENCODER_NO_OUTPUT count=" << intelXrNoOutputCount
                      << " requested_idr=" << (insertIdr ? "true" : "false") << std::endl;
        }
        return;
    }

    static u64 intelXrEncodedCount = 0;
    static u64 intelXrEncodedIdrCount = 0;
    ++intelXrEncodedCount;
    if (framePacket.isIDR) {
        ++intelXrEncodedIdrCount;
        if (intelXrEncodedIdrCount <= 50 || intelXrEncodedIdrCount % 50 == 0) {
            std::cerr << "[INTEL-XR-SERVER] ENCODED_IDR frame=" << intelXrEncodedCount
                      << " idr_count=" << intelXrEncodedIdrCount
                      << " requested=" << (insertIdr ? "true" : "false")
                      << " bytes=" << framePacket.size << std::endl;
        }
    } else if (intelXrEncodedCount <= 5 || intelXrEncodedCount % 500 == 0) {
        std::cerr << "[INTEL-XR-SERVER] ENCODED_P_FRAME frame=" << intelXrEncodedCount
                  << " bytes=" << framePacket.size << std::endl;
    }
""",
    "idrScheduler.CheckIDRInsertion();\n    encoder->PushFrame(counter++, insertIdr);",
)

print()
print("alvr_render RequestIDR routing is applied.")
print("Expected markers:")
print("  REQUEST_IDR_CONSUMED count=N  (handleEvents consumed ALVR_EVENT_REQUEST_IDR)")
print("  ENCODED_IDR frame=N ...       (IDRScheduler-requested keyframe was encoded)")
print("  ENCODED_P_FRAME frame=N ...   (non-IDR frames flow between requests)")
print("No Git refs were changed.")
