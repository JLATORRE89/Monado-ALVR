# Quest controllers through ALVR into Monado (W14 design)

Status 2026-09-27 16:35: steps 1-3 implemented in `src/xrt/drivers/alvr/alvr_controller.cpp`
(poses, buttons, haptics; no alvr_render change: buttons are drained on the tracking callback
instead of a new event handler). The Monado service assigns "ALVR Left/Right Touch Controller" to
the left/right roles; the Loft (loft `input.c`) binds aim/trigger/B-Y/thumbstick/haptic. Awaiting
the in-headset test. Env: `INTEL_XR_ALVR_CONTROLLERS=0` disables the devices,
`INTEL_XR_ALVR_AIM_PITCH_LEFT_DEG` / `_RIGHT_DEG` (defaults -50 / -60, tuned in the headset; the Loft
logs `[LOFT] SELECT ... dx dy`, the hit offset from the tile centre, to calibrate further) tune the aim rays. Known noise: alvr_render prints
"event handler for tag 6 not yet implemend" on stdout for each button batch. Controllers come before Loft
polish, because desktop interaction and joystick locomotion both depend on them.

## What ALVR already exposes (C API, `alvr_binding.h` / `server_core/src/c_api.rs`)

| Need | ALVR call / event | Notes |
|---|---|---|
| Device ids | `alvr_get_ids()` → `{head, hand_left, hand_right}` | hashes of `/user/head`, `/user/hand/left`, `/user/hand/right` |
| Controller pose | `alvr_get_device_motion(hand_id, sample_ts, &motion)` | same call alvr_render already makes for the head on `ALVR_EVENT_TRACKING_UPDATED`; returns pose + linear/angular velocity; false if no sample for that hand at that timestamp (controller off / hand tracking) |
| Hand skeleton | `alvr_get_hand_skeleton(hand, ts, pose[26])` | later; the session has `hand_skeleton` enabled |
| Buttons | `ALVR_EVENT_BUTTONS_UPDATED`, then `alvr_get_buttons(NULL)` for the count and `alvr_get_buttons(entries)` to pop one batch | entries are `{id, value}`; `id = alvr_path_to_id("/user/hand/left/input/trigger/value")` etc.; value is `scalar` (bool) or `floatp` |
| Haptics | `alvr_send_haptics(hand_id, duration_s, frequency, amplitude)` | session haptics enabled (intensity 1.0, min 0.01 s) |
| Battery | `ALVR_EVENT_BATTERY {device_id, gauge, plugged}` | optional |

Session: `headset.controllers.enabled=true`, `tracked=true`,
`emulation_mode=Quest2Touch`, so button ids use the Quest Touch paths
(`common/src/inputs.rs` `QUEST_CONTROLLER_PROFILE`): X/Y (left) or A/B (right) click+touch, menu
click (left), squeeze value, trigger value+touch, thumbstick x/y/click/touch, thumbrest touch.

**Existing risk found:** alvr_render's event loop (`Encoder.cpp`) ignores
`ALVR_EVENT_BUTTONS_UPDATED` and never calls `alvr_get_buttons`, so `BUTTONS_QUEUE` in
server_core grows by one batch per button change for the whole session (slow unbounded memory
growth). Step 2 below fixes it by draining the queue.

## What Monado needs

- One `xrt_device` per hand, `device_type = XRT_DEVICE_TYPE_LEFT_HAND_CONTROLLER` /
  `RIGHT_HAND_CONTROLLER`, `name = XRT_DEVICE_TOUCH_CONTROLLER` (profile
  `/interaction_profiles/oculus/touch_controller`).
- Inputs: `XRT_INPUT_TOUCH_{X,Y|A,B}_{CLICK,TOUCH}`, `MENU_CLICK` (left) / `SYSTEM_CLICK`
  (right), `SQUEEZE_VALUE`, `TRIGGER_VALUE`, `TRIGGER_TOUCH`, `THUMBSTICK` (vec2),
  `THUMBSTICK_CLICK`, `THUMBSTICK_TOUCH`, `THUMBREST_TOUCH`, `GRIP_POSE`, `AIM_POSE`.
- Output: `XRT_OUTPUT_NAME_TOUCH_HAPTIC` → `set_output` → `alvr_send_haptics`.
- Callbacks: `get_tracked_pose` (grip/aim from a per-hand `m_relation_history`),
  `update_inputs` (copy the latest button snapshot under a mutex, stamp timestamps),
  `set_output`, `destroy`.
- Roles: `alvr_prober.c` returns the HMD plus both controllers (`out_xdevs[0..2]`, return 3);
  the legacy builder's `u_device_assign_xdev_roles` picks left/right by `device_type`.
  Reference implementation: `src/xrt/drivers/simulated/simulated_controller.c`.

## Pose mapping

ALVR's hand motion is the client's grip-space pose (client `interaction.rs`: grip action), in
the same stage/local space as the head samples the HMD already accepts. Grip pose = ALVR pose.
Aim pose = grip pose × fixed Quest offset (Touch aim ≈ rotate −~40° about X and translate a few cm
forward; start with the value Monado's Touch drivers use and tune in the headset). Apply the same
quaternion validity check the HMD uses (reject zero/NaN, normalize). Mark position/orientation
valid+tracked only after a sample is accepted; report not-tracked when
`alvr_get_device_motion` returns false for longer than ~0.5 s.

## Data path (no new threads)

The existing alvr_render event loop is the only caller of `alvr_poll_event`. Extend it via
`CallbackManager`, as the HMD does:
1. On `TRACKING_UPDATED`: also query `hand_left` / `hand_right` motion and dispatch a new
   controller callback `(hand, ts, motion)`.
2. On `BUTTONS_UPDATED`: `n = alvr_get_buttons(NULL)`, pop into a vector, dispatch
   `(entries)`; the controller devices map `id → xrt_input` via a table built once with
   `alvr_path_to_id`.
3. Haptics go the other way: `set_output` calls `alvr_send_haptics` directly (thread-safe; takes
   the server-core read lock).

The alvr_render side of 1–2 is a new companion helper
(`apply-alvr-render-controller-events.py`), added to the end of
`apply-alvr-render-companion.sh` and re-verified with the reconstruction audit.

## Minimal viable implementation (incremental; one boundary per step)

1. **Poses only.** Two controller xrt_devices with grip/aim pose; prober returns 3 devices.
   Test: `monado-cli probe` lists 3 devices; Loft/hello_xr draws controller rays.
   Marker: `[INTEL-XR-CTRL] FIRST_POSE hand=L/R`.
2. **Buttons.** Drain `BUTTONS_UPDATED` (fixes the queue growth), map trigger, squeeze,
   thumbstick, A/B/X/Y, menu. Marker: `[INTEL-XR-CTRL] BUTTON id=… value=…` (rate-limited).
   Test: Loft uses trigger to select (replacing 1.5 s gaze dwell as the primary input).
3. **Haptics.** `set_output` → `alvr_send_haptics`. Test: pulse on Loft tile hover.
4. **Loft locomotion.** Left stick move / right stick snap-turn in the Loft (Loft repo only).
5. Later: hand-tracking skeleton (`XRT_DEVICE_HAND_INTERACTION` + hand joints), battery.

Keep the in-app exit (hold left menu 2 s, handled on the client) — Monado will also see the menu
click, so apps must not bind a destructive action to a long menu press.
