#!/usr/bin/env python3
"""De-duplicate forced keyframes in alvr_render; log crash backtraces.

1. IDR coalescing. Every ServerCoreEvent::RequestIDR called
   IDRScheduler::InsertIDR(), which forces an IDR on the very next frame with no
   spacing. On a lossy link (client asks per lost packet, server per dropped
   frame) this produced IDRs on consecutive frames. RequestIDR now:
     * coalesces: at most one pending request;
     * spaces forced IDRs by the scheduler's minimum interval (100 ms);
     * treats any encoded IDR (e.g. the first frame after an encoder re-open)
       as satisfying pending requests.
2. Fault handler. The service died once with SIGBUS and systemd/apport kept no
   core. A SIGBUS/SIGSEGV handler now prints the signal, faulting address and a
   backtrace to stderr (journal), then re-raises with the default action.

Apply after apply-alvr-render-request-idr.py. Non-destructive and idempotent.
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
sched_h = src / "alvr_server" / "IDRScheduler.h"
sched_cpp = src / "alvr_server" / "IDRScheduler.cpp"
encoder_cpp = src / "Encoder.cpp"
for required in (sched_h, sched_cpp, encoder_cpp):
    if not required.is_file():
        raise SystemExit(f"ERROR: required source file missing: {required}")

patch_once(
    sched_h,
    """	void InsertIDR();
""",
    """	void InsertIDR();
	// Coalesced, rate-limited IDR request (ServerCoreEvent::RequestIDR).
	void RequestIDR();
	// Any encoded IDR satisfies pending requests.
	void OnIDREncoded();
""",
    "void RequestIDR();",
)

patch_once(
    sched_h,
    """	uint64_t m_minIDRFrameInterval = MIN_IDR_FRAME_INTERVAL;
""",
    """	uint64_t m_minIDRFrameInterval = MIN_IDR_FRAME_INTERVAL;
	uint64_t m_lastIDRTime = 0;
	uint64_t m_coalescedRequests = 0;
""",
    "m_lastIDRTime",
)

patch_once(
    sched_cpp,
    """bool IDRScheduler::CheckIDRInsertion() {""",
    """void IDRScheduler::RequestIDR()
{
	std::unique_lock lock(m_mutex);

	if (m_scheduled) {
		// An IDR is already pending; this request is a duplicate.
		++m_coalescedRequests;
		if (m_coalescedRequests <= 5 || m_coalescedRequests % 100 == 0) {
			std::cerr << "[INTEL-XR-SERVER] IDR_REQUEST_COALESCED count=" << m_coalescedRequests << std::endl;
		}
		return;
	}
	uint64_t const now = GetTimestampUs();
	uint64_t const earliest = m_lastIDRTime + m_minIDRFrameInterval;
	m_insertIDRTime = now >= earliest ? now : earliest;
	m_scheduled = true;
}

void IDRScheduler::OnIDREncoded()
{
	std::unique_lock lock(m_mutex);

	m_lastIDRTime = GetTimestampUs();
	m_scheduled = false;
}

bool IDRScheduler::CheckIDRInsertion() {""",
    "void IDRScheduler::RequestIDR()",
)

patch_once(
    encoder_cpp,
    """[this]() { idrScheduler.InsertIDR(); }""",
    """[this]() { idrScheduler.RequestIDR(); }""",
    "idrScheduler.RequestIDR();",
)

patch_once(
    encoder_cpp,
    """    static u64 intelXrEncodedCount = 0;
    static u64 intelXrEncodedIdrCount = 0;
    ++intelXrEncodedCount;
    if (framePacket.isIDR) {
        ++intelXrEncodedIdrCount;""",
    """    static u64 intelXrEncodedCount = 0;
    static u64 intelXrEncodedIdrCount = 0;
    ++intelXrEncodedCount;
    if (framePacket.isIDR) {
        idrScheduler.OnIDREncoded();
        ++intelXrEncodedIdrCount;""",
    "idrScheduler.OnIDREncoded();",
)

# Fault handler.
patch_once(
    encoder_cpp,
    """#include <atomic>
""",
    """#include <atomic>
#include <csignal>
#include <cstdio>
#include <execinfo.h>
#include <unistd.h>
""",
    "#include <execinfo.h>",
)

patch_once(
    encoder_cpp,
    """vk::Extent2D ensureInit()
{""",
    """// INTEL-XR diagnostic: print signal, faulting address and backtrace, then
// re-raise with the default action (SA_RESETHAND) so the process still dies.
static void intelXrFaultHandler(int sig, siginfo_t* info, void*)
{
    char line[160];
    int len = snprintf(line, sizeof(line), "[INTEL-XR-FAULT] signal=%d code=%d addr=%p\\n", sig,
                       info ? info->si_code : 0, info ? info->si_addr : nullptr);
    if (len > 0) {
        ssize_t written = write(STDERR_FILENO, line, (size_t)len);
        (void)written;
    }
    void* frames[64];
    int count = backtrace(frames, 64);
    backtrace_symbols_fd(frames, count, STDERR_FILENO);
    raise(sig);
}

static void installIntelXrFaultHandler()
{
    struct sigaction action = {};
    action.sa_sigaction = intelXrFaultHandler;
    action.sa_flags = SA_SIGINFO | SA_RESETHAND;
    sigemptyset(&action.sa_mask);
    sigaction(SIGBUS, &action, nullptr);
    sigaction(SIGSEGV, &action, nullptr);
}

vk::Extent2D ensureInit()
{""",
    "installIntelXrFaultHandler()\n{",
)

patch_once(
    encoder_cpp,
    """        InitManager()
        {
""",
    """        InitManager()
        {
            installIntelXrFaultHandler();
""",
    "            installIntelXrFaultHandler();\n",
)

print()
print("alvr_render IDR de-duplication and fault handler are applied.")
print("Expected markers: IDR_REQUEST_COALESCED count=N; [INTEL-XR-FAULT] on a crash.")
print("No Git refs were changed.")
