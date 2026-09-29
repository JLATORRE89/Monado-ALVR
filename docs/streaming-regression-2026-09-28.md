# XR regression investigation — 2026-09-28

## Confirmed findings

The project root is a collection of repositories, not itself a Git repository. Baseline:
Monado-ALVR `xr-cleanup` 506ef6ade1dd (31 ahead), alvr-monado `intel-xr-client-diag`
2d4cba1dc472, alvr_render `intel-xr-companion` c36cdf957925, Loft `main` 4d2e604ec348
(9 ahead). All four initially clean; branch/history/submodule/diff evidence retained in
the investigation workspace. No source rollback was found. The running Monado SHA256
478ef0e1af38334d7fa064951e31035c2adeda521f4c958805b0762eb7a5aeb1 matched disk;
server core target/deployed SHA256 both 2a1778777f739b630734626dbeec7a02cc9bc2678b1a11aa2ebc6563f66a2843.
The actual loaded core path was the expected build/alvr_server_core library.

1. Dashboard discovery merged ALVR inventory with ADB but presented the transport's
Streaming state without control health. Failed/absent telemetry was replaced with dashes.
2. ALVR WiredConnection::drop invoked global adb kill-server. Runtime teardown therefore
killed a shared service used by the dashboard and tablet. This is fixed; a live stop/start
smoke test retained ADB PID 166059. A fake-ADB unit test protects the lifecycle boundary.
3. The saved usb-Quest client was streaming at Wi-Fi IP 192.168.86.168, not over USB.
The Quest was USB-enumerated but absent from ADB. Targeted reconnect and one verified
Quest-only USB reset did not immediately recover it. It later returned briefly (battery 95%,
display asleep, client running), then disappeared again. Persistent physical recovery is
NOT verified, and the initial cause of the USB/ADB disappearance remains unresolved.
The old test's proximity override was successfully disabled while ADB was available.
4. Before changes, adaptive bitrate fell from ~22.7 to ~3.3 Mbps and encoder reopens cost
~80 ms. Existing history documents Wi-Fi yaw-edge clipping and ~100–140 ms latency;
there is no confirmed earlier yaw-clipping fix. These are possible contributors, not proof
of this report's rendering root cause.

## Changes

Panel server: independent video report/XR session/control status; fresh/stale/unavailable
telemetry with observation timestamps; retain last successful values for the server session;
known cards survive API outages; isolate failed reads; targeted reconnect with backoff for
missing/offline known Quest devices. Never reconnect unauthorized or authorized-but-slow
devices, never kill shared ADB, never auto-authorize debugging.
Panel UI: degraded/reconnecting health, explicit missing/stale readings, separate indicators,
panel revision and runtime executable hash verification.
Installer/build helpers: record source commit, dirty state and artifact SHA256 metadata.
ALVR ADB: remove shared-server shutdown on wired connection destruction.
Renderer diagnostics: opt-in paired NV12 pre-encode and exact compressed IDR capture with
encoder PTS and eye poses/FOV; more frequent compositor geometry diagnostics. No FOV,
resolution, crop, bitrate, art, seating, or player-height changes.

## Validation

- Six connection-health tests, five discovery tests, four device-access tests, eight pairing
  tests and one installer test passed; one pairing test skipped for unavailable sandbox IPv6.
- Rust alvr_adb lifecycle regression passed.
- Python compilation, JavaScript syntax, Git whitespace checks passed.
- Clean Monado build (491 targets) passed; two upstream Eigen warnings.
- Clean alvr_server_core build + cargo xtask build-server-lib passed; target/deployed hashes
  matched. Existing binding-generator warnings remain.
- Companion reconstruction from ecb281249b6900ec6ceb6e0570be5100533c706a and repeat
  application matched source after normalizing root-dependent diagnostic paths.
- Live boundary capture: PTS 10, 3648x1984 NV12 and matching 185488-byte HEVC IDR, both
  decoded successfully. Stationary/no-headset scene has room content across both eyes.
  This does not reproduce yaw or validate Quest decode/reprojection.
- Live runtime teardown preserved the same shared ADB server PID after the fix.

## Remaining acceptance work

User stopped physical testing. Do not claim yaw clipping fixed. Need an awake/worn Quest,
stable ADB or equivalent client diagnostics, center/left/right synchronized captures,
actual client presentation logs/screenshots and measured transport latency. App eye render
coverage and post-decode presentation still need matching yaw measurements. Current capture
is after compositor/packing, before compression; it is not an app-eye swapchain dump.

For one boundary capture, create both `$XDG_RUNTIME_DIR/intel-xr-boundary-request` and
`intel-xr-view-request` (the latter requests an IDR). Copy the resulting boundary.nv12,
boundary.encoded, boundary.txt and boundary-views.txt immediately into a labeled evidence
folder before the next capture. boundary.txt contains encoder PTS, width, height. Decode
NV12 with ffmpeg rawvideo/nv12 and those dimensions; decode .encoded with format auto-detection.
Captures incur one GPU readback and disk write; keep them out of latency measurements.

## Subsequent live checks

Quest telemetry returned (93%, asleep, client running) and forwarding 9943/9944 was
restored. A three-sample check recorded one timeout with correctly retained/stale values
followed by two fresh healthy samples. This verifies repopulation and stale-value behavior,
not long-term USB stability. Paired captures now use a one-shot process-owned pending
marker so a later runtime's reused frame counter cannot overwrite the saved encoded pair.
