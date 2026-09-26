# Intel Arc Linux Port

## Goal

Run PC-powered OpenXR applications on Ubuntu 24.04 through Monado and ALVR without SteamVR, targeting Intel Arc GPUs and a Quest-class ALVR client.

## Reproducible source set

The `intel-arc-linux` branch is the project source of truth.

Companion repositories are prepared by `scripts/prepare-companions.sh`:

- ALVR `monado`: `5d45a6dcd9a5ae3df7c60c6a1282fb52140346da`
- alvr_render: `ecb281249b6900ec6ceb6e0570be5100533c706a`

These are pinned because the Monado/ALVR bridge is a historical experimental integration and its companion branches have not advanced in lockstep with current ALVR mainline.

## Compatibility changes

The preparation script applies two deterministic compatibility changes to the companion checkout:

1. Renames the historical `VIEWS_PARAMS` C API use in alvr_render to the generated `LOCAL_VIEW_PARAMS` ABI used by the pinned ALVR server core.
2. On Intel Vulkan devices, disables the historical DRM-format-modifier image creation path while retaining DMA-BUF export through the linear fallback. This targets the observed Arc A750/Mesa crash in `vkCreateImage()` while preserving the DMA-BUF metadata path consumed by the FFmpeg/VAAPI bridge.

The Monado fork also keeps the ALVR compositor target factory alive for the compositor lifetime and uses Ubuntu/Debian multiarch paths for x264 and Vulkan.

## Workflow

Fresh Ubuntu 24.04 machine:

```bash
bash scripts/bootstrap-intel-xr.sh
```

Existing workstation:

```bash
git pull
bash scripts/build-intel-xr.sh
```

Inspect:

```bash
bash scripts/status-intel-xr.sh
```

Runtime test:

```bash
bash scripts/test-intel-xr.sh
```

Logs are intentionally overwritten on each run:

- `/ai/intel-xr-prototype/logs/bootstrap-intel-xr.log`
- `/ai/intel-xr-prototype/logs/build-intel-xr.log`
- `/ai/intel-xr-prototype/logs/test-intel-xr.log`

## Validated hardware state

The development workstation has detected an Intel Arc A750 through Mesa Vulkan. During previous runtime testing Monado successfully created the Intel Vulkan device, graphics queue, external-memory/semaphore capabilities, renderer resources, and images before reaching the historical alvr_render DRM-modifier output-image crash.

The Intel linear DMA-BUF compatibility change is intended to move beyond that specific crash. It still requires workstation validation.

## SteamVR

SteamVR integration is intentionally disabled. This project uses Monado as the OpenXR runtime and ALVR as the headset transport.
