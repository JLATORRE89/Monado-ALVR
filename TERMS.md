# Terms — building Android / Quest / PC-VR apps in this project

Plain-language definitions, each with an example of how it shows up here.
Paths are relative to `/ai/intel-xr-prototype` unless noted.

---

## Rust and its tooling

**Rust** — the programming language ALVR is written in (server core, Quest client, networking).
*Example:* `src/alvr-monado/alvr/server_core/src/connection.rs` is Rust.

**Crate** — Rust's unit of code: one library or program, with its own `Cargo.toml`. A project is
usually many crates. *Example:* ALVR has crates `alvr_server_core`, `alvr_client_openxr`,
`alvr_sockets`, `alvr_common`. A fix in `alvr_sockets` affects both the PC server and the Quest
client, because both use that crate.

**Cargo** — Rust's build tool and package manager. *Example:*
`cargo build -p alvr_server_core` builds only the server-core crate; `-p` means "package".

**`Cargo.toml` / `Cargo.lock`** — a crate's manifest (name, dependencies) and the exact pinned
versions of every dependency. *Example:* `alvr/client_openxr/Cargo.toml` lists
`android-activity = "0.6"` and `jni = "0.21"`.

**Dependency** — another crate your crate uses. Downloaded from crates.io into
`~/.cargo/registry`. *Example:* the in-headset exit uses the `jni` dependency to call Android's
`Activity.finish()`.

**xtask** — ALVR's own build-helper program, run through Cargo. *Example:*
`cargo xtask build-server-lib` builds and copies the server library into `build/`;
`cargo xtask build-client` builds the Quest APK.

**Target / target triple** — the CPU + OS a build is for. The PC is `x86_64-unknown-linux-gnu`; the
Quest is `aarch64-linux-android`. *Example:* `rustup target list --installed` must include the
Android target before building the client.

**rustup** — installs Rust toolchains and targets.

**`target/` directory** — where Cargo writes build outputs. *Example:*
`src/alvr-monado/target/debug/libalvr_server_core.so` (fresh build) vs.
`src/alvr-monado/build/alvr_server_core/libalvr_server_core.so` (the deployed copy Monado loads).
We compare their SHA-256 hashes to be sure the deployed one is the new one.

**Debug vs release build** — debug builds are faster to compile and easier to debug; release
builds are optimized. *Example:* the server core here is a debug build (`target/debug`).

**Warning / `cargo check`** — compiler warnings don't stop the build but often point at bugs;
`cargo check` type-checks without producing binaries (fast). *Example:*
`cargo check -p alvr_client_core` before the slow Android build.

---

## C/C++ side (Monado, alvr_render)

**CMake / Ninja** — CMake generates build files; Ninja runs them. *Example:*
`cmake --build build/monado-alvr --parallel $(nproc)` rebuilds Monado incrementally.

**Shared library (`.so`)** — compiled code loaded by a program at runtime (Linux/Android's
equivalent of a Windows `.dll`). *Example:* `monado-service` loads `libalvr_server_core.so`;
`ldd monado-service | grep alvr` shows which file.

**C ABI / FFI** — the calling convention that lets C/C++ and Rust call each other.
*Example:* alvr_render (C++) calls Rust functions such as `alvr_send_video_nal()` and
`alvr_poll_event()`.

**cbindgen / generated header** — a tool that writes a C header from Rust code. *Example:*
`build/alvr_server_core/alvr_server_core.h`; `alvr_render/src/alvr_binding.h` is a symlink to it.
Never edit it by hand — rebuilding regenerates it.

**Companion patch** — our term for an idempotent Python script that applies a change to
`src/alvr_render` (a pinned, detached checkout we don't commit to). *Example:*
`python3 scripts/apply-alvr-render-idr-dedup.py`; running it twice changes nothing the second time.

**Detached HEAD / pinned revision** — a Git checkout of a specific commit rather than a branch.
*Example:* `src/alvr_render` is detached at `ecb2812`.

---

## Android and Quest

**Android** — the OS the Quest runs (Meta Horizon OS is based on it).

**SDK (Android SDK)** — Google's tools and libraries for building Android apps.
*Example:* `/ai/android-sdk/platform-tools/adb`.

**NDK (Native Development Kit)** — compilers and libraries to build native (C/C++/Rust) code for
Android. *Example:* Rust code for the Quest client is compiled with the NDK's linker for
`aarch64-linux-android`.

**APK** — the Android app package file (a zip with code, native libraries, resources and a
signature). *Example:* `src/alvr-monado/target/debug/apk/alvr_client_openxr.apk`;
`unzip -l` shows `lib/arm64-v8a/*.so` inside.

**Package name / application ID** — an app's unique ID on the device. *Example:*
`alvr.client.monado`; `adb shell pidof alvr.client.monado` shows if it is running.

**Signing / keystore** — every APK is signed; an update must be signed with the same key as the
installed app. *Example:* installing the release build failed with
`INSTALL_FAILED_UPDATE_INCOMPATIBLE` because the headset has the debug-signed build.

**Gradle** — Android's usual build system (ALVR's xtask drives the Android packaging for us).

**Activity / NativeActivity** — an Android screen/app component. `NativeActivity` lets native
code (our Rust) run an app without Java UI code. *Example:*
`adb shell am start -n alvr.client.monado/android.app.NativeActivity` launches the client.

**JNI (Java Native Interface)** — how native code calls Java/Android APIs. *Example:* the
in-headset exit calls `Activity.finish()` through JNI.

**ADB (Android Debug Bridge)** — command-line link to the device over USB or Wi-Fi.
*Examples:* `adb devices`, `adb -s 1WMHHA42R81461 install -r app.apk`,
`adb -s 1WMHHA42R81461 logcat`. Always use `-s <serial>` here because a phone is also attached.

**ADB port forwarding** — tunnels a TCP port from the PC to the device over USB. *Example:*
`adb forward tcp:9943 tcp:9943` — ALVR's wired (USB) mode does this for ports 9943/9944.

**logcat** — Android's system log. *Example:* `adb -s 1WMHHA42R81461 logcat -d | grep INTEL-XR`
shows the client's markers such as `VIDEO_PACKET_RECEIVED`.

**Developer mode / USB debugging** — Quest settings that allow ADB and installing apps outside the
store ("sideloading").

**Proximity sensor** — detects whether the headset is worn; when removed, apps pause/stop.

---

## XR (virtual reality) runtime

**OpenXR** — the standard API VR apps use to talk to a VR runtime. *Example:*
`demo/checkerboard/main.c` is an OpenXR app.

**Runtime** — the program implementing OpenXR for a device. On the PC it is **Monado**; on the
Quest it is Meta's runtime. *Example:* `XR_RUNTIME_JSON=build/monado-alvr/openxr_monado-dev.json`
points apps at Monado.

**OpenXR loader** — the library apps link against; it finds and loads the runtime.

**Session / session states** — an app's connection to the runtime; it moves through
READY → SYNCHRONIZED → VISIBLE → FOCUSED (and STOPPING → IDLE → EXITING). *Example:* the
checkerboard logs `SESSION_STATE=5` (FOCUSED); the Quest client logs `OPENXR_STATE FOCUSED`.

**Swapchain** — the set of images an app renders into and hands to the runtime.

**Compositor** — the runtime part that combines app layers into the final image.

**Reprojection / timewarp** — shifting the last image to match the latest head pose. With high
latency the shifted image runs out of pixels at the edges ("edge clipping").

**Monado** — the open-source OpenXR runtime we run on the PC as `monado-service`.

**ALVR** — software that streams PC VR to standalone headsets: a **server** on the PC (inside
Monado here) and a **client** app on the Quest.

**Tracking / pose** — headset/controller position and orientation, sent from the Quest to the PC.

---

## Video and streaming

**Encoder / decoder** — the encoder compresses frames on the PC (Intel GPU via VAAPI); the
decoder decompresses them on the Quest (MediaCodec).

**Codec / H.264** — the compression format; we use H.264.

**VAAPI** — Linux API for GPU video encoding/decoding (Intel/AMD). *Example:* `h264_vaapi`.

**FFmpeg / libavcodec** — the library alvr_render uses to drive VAAPI. The system version
(6.1) only applies bitrate when the encoder opens, so we re-open it on bitrate changes.

**MediaCodec** — Android's hardware video decoder API. *Example:* logcat
`MEDIACODEC_STARTED software=false`.

**Keyframe (IDR) vs P-frame** — an IDR frame is complete on its own; P-frames only describe
changes and need earlier frames. After loss, the decoder needs a new IDR. *Example:* the grey
screen was P-frames decoded without an IDR.

**NAL unit / Annex-B** — the pieces an H.264 stream is made of, separated by `00 00 00 01` start
codes. **SPS/PPS** (the "decoder config") are NAL units describing the stream.

**Bitrate / CBR / adaptive bitrate** — bits per second of video. CBR (constant bitrate) pads
every frame to the same size; adaptive bitrate changes the target with network conditions.
*Example:* 30 Mbit/s at 72 fps = 52,084 bytes per frame.

**Frame rate / frame budget** — frames per second (72 on Quest 2 here) and bytes per frame.

**Latency** — delay from head movement to the photon on screen. *Example:*
`python3 scripts/alvr-stats.py 10` prints network and total latency.

**UDP vs TCP** — UDP sends packets with no retransmission (low latency, can lose data; ALVR over
Wi-Fi); TCP retransmits and orders (reliable; ALVR over USB).

**Shard / packet / MTU** — a video frame is split into ~1400-byte shards so each fits in one network
packet (MTU ≈ 1500 bytes).

**Packet pacing** — spreading a frame's shards over time instead of one burst, to avoid overflowing
Wi-Fi queues.

**Bufferbloat / send queue** — too much data waiting in buffers, adding delay. *Example:*
`ss -uanpm | grep -A1 :9944` shows the PC's queued bytes (`t…`).

**Congestion / AIMD** — when the link is overloaded; "additive increase, multiplicative decrease"
cuts the bitrate quickly and raises it slowly.

**mDNS** — discovery of devices on the local network by name. *Example:*
`5747.client.local` is the Quest client.

**2.4 GHz vs 5 GHz Wi-Fi** — 2.4 GHz reaches farther but is slower and more crowded; 5 GHz is faster.

---

## Linux services and tools

**systemd user service** — a background program managed by `systemctl --user`. *Example:*
`intel-xr-monado.service` runs `monado-service`; `bash scripts/monado-service.sh restart`.

**journal / journalctl** — systemd's log. *Example:*
`journalctl --user -u intel-xr-monado.service -n 100`.

**PipeWire** — Linux's audio/video routing system; ALVR uses it to capture PC audio.

**Signal (SIGBUS, SIGSEGV, EINTR)** — OS notifications to a process; SIGBUS/SIGSEGV are crashes;
EINTR means a system call was interrupted by a signal and should be retried.

**Core dump / backtrace** — a saved crash image / the list of function calls at the crash.
*Example:* our `[INTEL-XR-FAULT]` handler prints a backtrace to the journal.

**gdb** — the debugger.

---

## Project-specific words

**INTEL-XR markers** — log lines we added to prove each step, e.g. `ENCODED_IDR`,
`VIDEO_PACKET_SENT`, `VIDEO_PACKET_RECEIVED`, `STREAM_RENDER first_decoded_frame`.

**Wired client** — ALVR session entry `client.wired`; enables USB streaming via ADB forwarding.

**Checkerboard** — the test OpenXR app (`demo/checkerboard`): red left eye, blue right eye.
Start/exit it with `bash scripts/xr-app.sh start|stop` or the web UI at http://127.0.0.1:8083.

**In-headset exit** — hold the left controller menu (≡) button for 2 s while streaming.
