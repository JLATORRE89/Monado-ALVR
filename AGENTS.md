# Intel XR Prototype — Agent Guide

## Mission
Build and verify the Monado + ALVR standalone XR prototype incrementally. Preserve proven results and advance one evidence boundary at a time.

## Working tree
Project root: `/ai/intel-xr-prototype`

Repositories:
- `src/Monado-ALVR` — `JLATORRE89/Monado-ALVR`, branch `xr-cleanup`
- `src/alvr-monado` — `JLATORRE89/ALVR`, branch `intel-xr-client-diag` (remote `jason`)
- `src/alvr_render` — companion renderer/encoder consumed by Monado; pinned at `ecb2812`,
  reconstructed by `scripts/apply-alvr-render-companion.sh` (local snapshot branch
  `intel-xr-companion`, not pushable)
- `src/loft` — `JLATORRE89/loft`, branch `main` (demo app; optional)
- `src/alvr-merge` — worktree of the ALVR fork on `intel-xr-master-merge` (untested upstream
  merge; tracks the fork's `master`: never push it there)

Two agents (Claude, Codex) share this tree: read and update
`/ai/intel-xr-prototype/LOFT-CODEX-HANDOFF.md` (newest first) and claim a repo before writing.

Artifacts:
- Monado: `build/monado-alvr`
- Cargo server core: `src/alvr-monado/target/debug/libalvr_server_core.so`
- Deployed server core: `src/alvr-monado/build/alvr_server_core/libalvr_server_core.so`
- Logs: `logs/`

## Immediate objective
Consolidation re-verified 2026-09-29 (see `CONSOLIDATION RESULT` at the top of `TASKS.md`):
the companion reconstructs byte-identically and everything builds from committed files. Keep it
that way: every alvr_render change is a new idempotent helper added to
`scripts/apply-alvr-render-companion.sh`, then re-run the audit. Next: live re-open check while
streaming and a headset check of the yaw-edge fix (step 17), then the Loft (modular; never couple the
runtime/transport to it).

## Proven state
End-to-end video in the headset over USB and Wi-Fi: Monado compositor (paced at ALVR's refresh
rate, 72 Hz) → alvr_render → Intel VAAPI HEVC 8-bit → ALVR → Quest MediaCodec. alvr_render:
RequestIDR routed and coalesced in IDRScheduler; VAAPI encodes the renderer's real output on
Intel; rate control follows ALVR, runtime changes re-open the encoder after draining and freeing
the old one (no Resizable BAR on this Arc: two encoders at once exhausted CPU-visible VRAM);
frames carry tracking timestamps. ALVR server core: wired mode with Wi-Fi fallback, AIMD
congestion response, UDP pacing, bounded queues, EINTR retry, IDR de-dup. Quest Touch
controllers (poses, buttons, haptics). Several headsets per PC (one runtime instance each).
alvr_render changes live as 17 idempotent `scripts/apply-*.py` helpers because alvr_render is a
pinned checkout (order in TASKS.md).

Config layers: repo defaults `config/xr-build.json`; workstation overrides
`config/xr-build.local.json` (gitignored; the panel saves `android.usb_stay_awake` there); ALVR
session `~/.config/alvr/session.json`; diagnostics are env vars / request files on the service.
Commit map: `docs/commit-classification.md`.

## Add-ons
`addons/xr-control-panel/` is an optional, separately installed web UI (multi-headset management,
captures, runtime controls). The runtime must never depend on it; see its README.

## Procedure
Read `RULES.md` and `TASKS.md` first. Inspect existing code before patching. Prefer existing ALVR/Monado mechanisms. Make one narrow change per hypothesis. Compile the directly changed component first, verify the actual artifact, then rebuild/restart dependencies. Run one controlled test, record evidence in `TASKS.md`, and commit meaningful changes.

## Branch safety
Do not merge to main. Do not force-push, reset --hard, rewrite history, delete branches, or discard user work. Work only on `xr-cleanup` and `intel-xr-client-diag`.

## Stop conditions
Stop and document before destructive Git, headset firmware/OS changes, factory reset, credential/account changes, unrelated firewall/network changes, evidence deletion, or broad speculative changes. Leave repositories buildable.
