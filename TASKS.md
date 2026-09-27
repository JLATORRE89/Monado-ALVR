# Intel XR Prototype — Task Progress

## Active blocker
`ServerCoreEvent::RequestIDR` is successfully queued after `VIDEO_CHANNEL_INSTALL`, but no fresh encoded IDR has yet been observed. Trace the event receiver/consumer into Monado/alvr_render and wire it to the existing force-keyframe mechanism.

## Proven
- [x] Quest client builds/installs and reaches OpenXR FOCUSED.
- [x] Monado service/API stable.
- [x] Valid initial HMD and eye poses; `xrLocateViews` succeeds.
- [x] Real Quest tracking accepted.
- [x] Checkerboard reaches render and projection submission.
- [x] Monado compositor present path reached.
- [x] Encoder receives frame and produces ~95 KB H.264 IDR.
- [x] Annex-B `00 00 00 01` / prefix 4 verified.
- [x] NAL parser -> Rust C ABI -> ServerCore send path verified.
- [x] Initial IDR observed while `video_channel_sender=None`.
- [x] StreamReady/socket setup later installs video channel and marks Streaming.
- [x] `70b0097d`: request fresh IDR after video transport ready.
- [x] Runtime: `REQUEST_IDR_AFTER_VIDEO_READY ok=true`.
- [x] Rust build freshness issue understood: explicitly build server_core, verify marker/mtime, deploy, compare hashes.
- [x] Target/deployed server-core hashes matched after correct build.
- [x] Build warning cleanup moved to scoped CMake configuration.

## Next tasks
- [ ] Locate every consumer/match arm for `ServerCoreEvent::RequestIDR`.
- [ ] Identify existing alvr_render/encoder force-IDR API.
- [ ] Wire RequestIDR to force-keyframe behavior with minimal architecture change.
- [ ] Compile server_core directly and verify artifacts.
- [ ] Verify a new `ENCODED_FRAME ... idr=true` occurs after `VIDEO_CHANNEL_INSTALL`.
- [ ] Verify `VIDEO_CHANNEL_LOCK_OK present=true`.
- [ ] Verify `VIDEO_CHANNEL_TRY_SEND_RESULT ok=true`.
- [ ] Verify `VIDEO_CHANNEL_DEQUEUE` and `VIDEO_PACKET_SENT`.
- [ ] Verify Quest packet receive, decoder config/IDR, decoder output, and displayed checkerboard.
- [ ] If teardown occurs, capture `SHUTDOWN_TRIGGER client_streaming=... lifecycle=...` and fix the proven cause only.

## After pixels
- [ ] Save concise end-to-end evidence.
- [ ] Separate production fixes from diagnostics.
- [ ] Prepare clean tracking fixes for main.
- [ ] Prepare video startup/RequestIDR fix for main after end-to-end verification.
- [ ] Remove/rate-limit obsolete probes.
- [ ] Leave a reproducible regression test.

## Overnight completion
Ideal: `VIDEO_CHANNEL_INSTALL -> RequestIDR -> fresh IDR -> enqueue -> dequeue -> packet sent -> Quest receive -> decoder output -> displayed checkerboard`.

Minimum useful result: identify the exact RequestIDR consumer path, implement/compile a narrow fix or document the blocker, update this file with commits/tests, and leave both repos buildable.
