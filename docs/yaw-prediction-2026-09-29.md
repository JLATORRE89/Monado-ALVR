# Display-time head prediction correction — 2026-09-29

## Code defect and correction

The Monado companion called `alvr_get_device_motion(head, poll_timestamp)`, returning
an unpredicted pose. The HMD driver stamped this remote pose at local receipt time;
Monado extrapolated only to its local display deadline. This omitted the measured
end-to-end prediction used by ALVR's existing OpenVR HMD path (`server_openvr/src/lib.rs`).
The Quest must reproject a frame covering the older head direction to its later display
pose; uncovered edges are one consequence of this lag during yaw. The code omission
is confirmed. Its contribution to the user's exact visible clipping still requires a
worn-headset before/after test; do not claim the visual symptom conclusively resolved.

Added `alvr_get_head_motion_for_display`: fetch the raw head sample, reuse ALVR's
`DeviceMotion::predict` with `get_motion_to_photon_latency()` (already bounded by the
configured `max_prediction_ms`), return the predicted pose with zero velocities.
This matches OpenVR's HMD submission and prevents Monado extrapolating a second time.
Only head tracking consumes the new API. Raw device/controller APIs, original tracking
sample timestamps, video pose/FOV metadata, FOV, crop, dimensions, encoding, bitrate,
Loft art and player behavior are unchanged. Removed the meaningless 60-nanosecond
subtraction in the HMD receipt timestamp. Companion reconstruction adds step 17.

## Validation

Two Rust regression tests passed: positive/negative yaw reach the expected display pose;
output velocities prevent double prediction; zero-latency startup and world-coordinate
velocity composition preserve expected poses. With 1 rad/s yaw and 60 ms pipeline delay,
the previous raw pose has a 0.06-radian discrepancy; the corrected pose matches the
expected display orientation in the test. This is a deterministic model, not a headset
measurement or proof that every cause of black borders is eliminated.

Server core build, generated C interface deployment and Monado build passed. One existing
Rust dead-code warning and existing cbindgen warnings remain. The final Monado build has
no new compiler warnings. Fresh 17-step companion reconstruction and repeat application
match current source after root-path normalization. Actual Quest trace shows
HEAD_DISPLAY_PREDICTION at startup and decoded frames. A short unattended session could
not sustain tracking or produce a yaw test. Temporary proximity override was restored
with automation_disable in a finally block (broadcast succeeded).

## Next acceptance boundary

Wear the Quest, use the existing client, and turn slowly left/right. Record nonzero
measured HEAD_DISPLAY_PREDICTION latency, synchronized center/left/right boundary captures,
client decoder/display logs and the user's visual result. If clipping remains, use those
captures to separate pre-encode coverage from Quest reprojection before touching FOV.
No new APK is required for this correction. Runtime and Loft are left running.

Concurrent changes to addons/xr-control-panel/server.py were observed during this task;
they are not part of this yaw change and were not staged or deployed by this task.
