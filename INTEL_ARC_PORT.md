# Intel Arc / Ubuntu ALVR integration work

This branch tracks the Linux/Intel Arc work needed to run the Monado ALVR integration without SteamVR.

## Target environment

- Ubuntu 24.04
- Intel Arc GPU (development hardware: Arc A750)
- Mesa Vulkan
- Monado OpenXR runtime
- ALVR transport/client
- SteamVR disabled

## Confirmed fixes carried on this branch

1. **ALVR target-factory lifetime**
   `target_instance.c` previously created the ALVR `comp_target_factory` as a stack local and passed its address to the compositor, which retains the pointer. The factory now has static storage duration.

2. **Ubuntu library paths**
   The experimental build hard-coded Fedora-style `/usr/lib64` paths for x264 and Vulkan. These are changed to Ubuntu/Debian's x86-64 multiarch paths.

3. **Device-extension lifetime**
   The current upstream/fork source already uses a static `device_extensions` array in `alvr_create_target_factory()`. This is important: an earlier revision used a stack-local array and produced invalid extension pointers during Vulkan initialization.

## Hardware validation so far

On the development Arc A750, Monado successfully reaches Vulkan device creation and reports a discrete Intel Arc A750 using Mesa. Renderer resource initialization succeeds and external OPAQUE_FD image memory import/export is reported as supported.

## Current blocker

The older ALVR renderer path used during testing crashes while creating its encoder output image through the DMA-BUF + DRM-format-modifier path in `alvr_render::createOutputImage()`. The crash occurs in Intel's Vulkan driver during `vkCreateImage()`, after Monado's renderer has initialized.

The next compatibility work is to make the ALVR output-image/export path select a supported external-memory strategy instead of unconditionally assuming the historical DMA-BUF/DRM-modifier path. OPAQUE_FD is a candidate because the Arc A750 reports image import/export support for that handle type.

## Repository strategy

Keep `main` close to the forked upstream history. Intel/Ubuntu compatibility work belongs on this branch until it is reproducible and tested end-to-end with an ALVR headset client.
