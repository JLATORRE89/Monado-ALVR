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

Artifacts:
- Monado: `build/monado-alvr`
- Cargo server core: `src/alvr-monado/target/debug/libalvr_server_core.so`
- Deployed server core: `src/alvr-monado/build/alvr_server_core/libalvr_server_core.so`
- Logs: `logs/`

## Immediate objective
Consolidation is done (see `CONSOLIDATION RESULT` in `TASKS.md`). Next: Quest controllers
(`docs/controllers.md`, W14), then the Loft. Preserve the known-good video path; start from the
top of `TASKS.md`.

## Proven state
End-to-end video is confirmed in the headset (red/blue checkerboard) over Wi-Fi at 10 Mbit/s and
over USB at 30 Mbit/s. alvr_render: RequestIDR routed and coalesced in IDRScheduler; VAAPI encodes
the renderer's real output on Intel; rate control follows ALVR (runtime changes via encoder
re-open); frames carry tracking timestamps so ALVR statistics/Adaptive work. ALVR server core:
wired (USB) mode picks the device with the client and falls back to Wi-Fi; send-path congestion
cuts bitrate (AIMD); EINTR is retried; IDR requests are de-duplicated. alvr_render changes live
as idempotent `scripts/apply-*.py` helpers (order in TASKS.md) because alvr_render is a pinned
detached checkout. Live ALVR session settings differ from defaults; see TASKS.md.

Config layers: repo defaults `config/xr-build.json`; workstation overrides
`config/xr-build.local.json` (gitignored); ALVR session `~/.config/alvr/session.json`;
diagnostic env vars on the service. Commit map: `docs/commit-classification.md`.

## Add-ons
`addons/xr-control-panel/` is an optional, separately installed web UI (multi-headset management,
captures, runtime controls). The runtime must never depend on it; see its README.

## Procedure
Read `RULES.md` and `TASKS.md` first. Inspect existing code before patching. Prefer existing ALVR/Monado mechanisms. Make one narrow change per hypothesis. Compile the directly changed component first, verify the actual artifact, then rebuild/restart dependencies. Run one controlled test, record evidence in `TASKS.md`, and commit meaningful changes.

## Branch safety
Do not merge to main. Do not force-push, reset --hard, rewrite history, delete branches, or discard user work. Work only on `xr-cleanup` and `intel-xr-client-diag`.

## Stop conditions
Stop and document before destructive Git, headset firmware/OS changes, factory reset, credential/account changes, unrelated firewall/network changes, evidence deletion, or broad speculative changes. Leave repositories buildable.
