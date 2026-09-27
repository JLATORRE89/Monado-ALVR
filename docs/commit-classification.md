# Commit classification (consolidation, 2026-09-27)

History is left intact (no squash/rebase/force-push). This file is the map for a later,
deliberate port to `main`. Categories: **P** production fix, **F** feature, **D** diagnostic,
**Doc** documentation, **T** temporary / experiment / workstation-specific, **S** superseded
(fix-of-a-fix or replaced by a later commit — do not port individually).

## Monado-ALVR `xr-cleanup` (101 commits since `main` @ 1ab7cb7df)

### Production fixes (port to main, in this order)
| Area | Commits | Notes |
|---|---|---|
| Tracking/OpenXR validity | bc9db02d8, 887bf1475, e5a90a083, ab36ceb85 | valid identity head/eye poses, reject invalid samples |
| Build hygiene | 9cdfa311f, 9a4402bf2, c3a376b0f, bb91d8352, 170e5a1b8, 506281b21, 0748b1b0b, 8928218d3 | scoped `-Wno-pedantic`; companion warning cleanup |
| Companion video path (alvr_render via `scripts/apply-*.py`) | 603c25467 → ac98803f1 → d4ab226d7 → 8d9a9f91c → 3ce2701f5 (+ unique timestamps in cc2aeacc6) → add2b7689 (coalescing part) → 00a835f88 → 8bee6bf01 | **order matters**; reconstruction entry point `scripts/apply-alvr-render-companion.sh` |
| Wired mode service env | 22c489f41 | SDK `adb` on the unit PATH |
| Safe rebuild | rebuild script in 8a5004fb4 (`scripts/rebuild-runtime.sh`) + 8bee6bf01 | never resets repos |
| Decouple runtime from UI | 8a5004fb4 (monado-service.sh / xr-support.sh parts) | runtime must not depend on the add-on |

### Features
| Feature | Commits |
|---|---|
| XR Control Panel add-on (`addons/xr-control-panel`) | 8a5004fb4 (supersedes 8792bbb72, af0fea496, 926afa854, 1c41081c6, a4e75e58a), 724430fd8 (tests part) |
| App launcher (`scripts/xr-app.sh`, checkerboard/Loft) | 8792bbb72, cc2aeacc6 |
| Session-driven codec / 10-bit (opt-in) | b7ab80911 |
| Checkerboard / color OpenXR test apps | 69f649cea, d5ac50212, 334c55943, d00c90e87, 072f1f126, 7256b26ea, 6da90b4a0, 75d4ca62b, 51f8c6d26 |
| Stats reader | 6ca9fefd8 (`scripts/alvr-stats.py`) |

### Diagnostics (keep on the diag branch; remove or gate before main)
07ca07317, ceb9be457, a4587c130, 41fef94ce, 4be5bdee0, 3dd734445, 52b7a742e, 133f22aec,
72e3f5928 + eb63f2caf (encoder dump), 0d08cfd00 (`INTEL_XR_NO_REOPEN`), cc2aeacc6 (views
diagnostics part), add2b7689 (fault handler part), d707ca6c3, 76abaa782, a35029363, 7fdebc9a9,
a489e5959, 3e18a014e, 3c6860d84, 914303644. The `INTEL-XR-*` markers in the companion patch
(`apply-server-video-instrumentation.py`) are diagnostics; the video fixes do not depend on them.

### Superseded / fix-of-fix (do not port individually)
125eb10a2, 0e6e40d53, c22ca7637, 1d2a73028, 3f0fa6987, 0ddfbf103, 8645f8cf4, fbabccf80,
579817703, 2c1ffe02a, dc12dad21, 696bb65f8, e7f975125, 5d90bb53f + c7d6b81fa (replaced by
2d63b7349 / CMake scoping), a835ad533 + dc5105d76 (duplicate).

### Documentation
cdfb3a2ac, 64594e11a, 6d251401d, 144b1e638, 61e826cb2, all `docs:` commits since 25316f274, TERMS.md.

### Must NOT go to main as-is (workstation / test)
- `systemd/intel-xr-monado.service`: `ALVR_LEGACY_PROTOCOL_TEST=1` (test-only protocol bypass),
  `ALVR_DIRECT_CLIENT_IP=192.168.86.168` (this workstation's Quest), hard-coded `/ai/...` paths.
- `config/xr-build.json` `android.usb_stay_awake=true` (workstation choice; repo default is false).
- Unattended-diagnostic scripts and one-shot test captures (T/D above).
- `cleanup: remove temporary video instrumentation patches` (9e5e19587) predates the current
  companion model; re-evaluate against the helpers.

## ALVR `intel-xr-client-diag` (34 commits since `origin/monado` @ 5d45a6dc)

| Class | Commits |
|---|---|
| P: base Monado integration checkpoint | c3b0bc1f (legacy discovery, mDNS, direct-IP fallback, **test-only** legacy protocol) |
| P: client log-mirror deadlock | bc08f7e6, 85b79dfd (85b79dfd bypasses mirroring; revisit) |
| P: fresh IDR when transport ready | 70b0097d |
| P: wired device selection / Wi-Fi fallthrough | 2f53241c, cfb2e4cf |
| P: EINTR retry | 1d955f09 |
| P: IDR de-dup (server/client) | a6d57db2 — pairs with companion coalescing (add2b7689) |
| P/F: congestion AIMD, bitrate-sized buffer, UDP pacing, wired queue | f1f3e0f6 → 616a740d → 830a55bb |
| F: in-headset exit | 0bf9b502 → b13c4e5d (process exit fix) |
| D | 87cc2219, 533cf64c, 47ee1eca, 32305922, fc6941fa, 9cca7e4c, 55167184, 45357b7a, e7272a20, c048203a, f05f11f0, ef016d22, b92115f1, 847dc82f, 484d6802, 52c99161, d4edb167, 074f9764, 5401e13c, b40375a1 |
| Cleanup | cd285266 |

Dependencies: congestion control (f1f3e0f6) needs the companion dynamic-bitrate re-open to have
any effect; pacing/buffer sizing (616a740d) and wired queue (830a55bb) assume the session
anti-bufferbloat settings; IDR de-dup is split between a6d57db2 (server) and the companion
`IDRScheduler::RequestIDR` coalescing.

Must NOT go to upstream/main: the test-only legacy protocol bypass in c3b0bc1f, raw `eprintln!`
probes, per-frame client `INTEL-XR-VIDEO` logging (floods logcat).

## alvr_render (local branch `intel-xr-companion`, not pushable)
153db90, 4814e5f: snapshots of the companion tree; the source of truth is the Monado-ALVR
helpers (byte-identical reconstruction verified, tree 030ce494).
