#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${INTEL_XR_ROOT:-/ai/intel-xr-prototype}"
SRC="$ROOT/src"
MONADO="$SRC/Monado-ALVR"
ALVR="$SRC/alvr-monado"
ALVR_RENDER="$SRC/alvr_render"
LOGDIR="$ROOT/logs"
LOG="$LOGDIR/$(date +%Y-%m-%d_%H-%M-%S)_bootstrap-intel-xr.log"

[[ $EUID -ne 0 ]] || { echo "ERROR: run as your normal desktop user, not root."; exit 1; }

if [[ ! -d /ai ]]; then sudo mkdir -p /ai; sudo chown "$USER":"$(id -gn)" /ai; fi
if [[ ! -w /ai ]]; then sudo mkdir -p "$ROOT"; sudo chown -R "$USER":"$(id -gn)" "$ROOT"; fi
mkdir -p "$SRC" "$ROOT/build" "$ROOT/local" "$LOGDIR"
exec > >(tee "$LOG") 2>&1

echo "=== Intel XR bootstrap ==="
source /etc/os-release
echo "OS: $PRETTY_NAME"
echo "Kernel: $(uname -r)"
[[ "${VERSION_ID:-}" == "24.04" ]] || echo "WARNING: designed for Ubuntu 24.04."
lspci -nn | grep -Ei 'VGA|3D|Display' || true
lspci -nn | grep -Ei 'VGA|3D|Display' | grep -qi Intel || { echo "ERROR: Intel GPU not detected."; exit 1; }

echo "=== Install dependencies ==="
sudo apt-get update
sudo apt-get install -y  build-essential git curl cmake ninja-build pkg-config python3 python3-dev  libeigen3-dev glslang-tools glslc libvulkan-dev vulkan-tools  libgl1-mesa-dev libegl1-mesa-dev libx11-dev libx11-xcb-dev libxcb1-dev  libxcb-randr0-dev libxcb-shm0-dev libxcb-keysyms1-dev libxcb-composite0-dev  libxcb-xfixes0-dev libxcb-glx0-dev libwayland-dev wayland-protocols  libxrandr-dev libxxf86vm-dev libudev-dev libusb-1.0-0-dev libv4l-dev  libdrm-dev libgbm-dev libsystemd-dev libsdl2-dev libhidapi-dev libjpeg-dev  libbluetooth-dev libbsd-dev zlib1g-dev libssl-dev libpipewire-0.3-dev  libspa-0.2-dev libavcodec-dev libavdevice-dev libavfilter-dev libavformat-dev  libavutil-dev libswresample-dev libswscale-dev libx264-dev clang libclang-dev

if ! command -v cargo >/dev/null 2>&1; then
 curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
fi
source "$HOME/.cargo/env" 2>/dev/null || true
command -v cbindgen >/dev/null 2>&1 || cargo install cbindgen --locked

echo "=== Obtain project repositories ==="
if [[ -d "$MONADO/.git" ]]; then
 git -C "$MONADO" remote set-url origin git@github.com:JLATORRE89/Monado-ALVR.git
 git -C "$MONADO" fetch origin
 git -C "$MONADO" checkout intel-arc-linux
 git -C "$MONADO" pull --ff-only origin intel-arc-linux
else
 git clone --branch intel-arc-linux --single-branch git@github.com:JLATORRE89/Monado-ALVR.git "$MONADO"
fi

if [[ ! -d "$ALVR/.git" ]]; then
 git clone https://github.com/alvr-org/ALVR.git "$ALVR"
fi
if [[ ! -d "$ALVR_RENDER/.git" ]]; then
 git clone https://github.com/The-personified-devil/alvr_render.git "$ALVR_RENDER"
fi

echo "=== Build ==="
bash "$MONADO/scripts/build-intel-xr.sh"

echo
echo "BOOTSTRAP SUCCESS"
echo "Status: bash $MONADO/scripts/status-intel-xr.sh"
echo "Test:   bash $MONADO/scripts/test-intel-xr.sh"
