#!/usr/bin/env bash
set -Eeuo pipefail

# ============================================================
# Intel XR Prototype Bootstrap
#
# Target:
#   Ubuntu 24.04
#   Intel Arc A750
#   Quest 2
#   ALVR + Monado/OpenXR
#
# Explicitly NOT using SteamVR.
#
# Project:
#   /ai/intel-xr-prototype
# ============================================================

ROOT="/ai/intel-xr-prototype"
SRC="$ROOT/src"
BUILD="$ROOT/build"
INSTALL="$ROOT/local"
LOGS="$ROOT/logs"
SCRIPTS="$ROOT/scripts"

MONADO="$SRC/Monado-ALVR"
ALVR="$SRC/alvr-monado"
ALVR_RENDER="$SRC/alvr_render"

MONADO_BUILD="$BUILD/monado-alvr"

# ------------------------------------------------------------
# Safety
# ------------------------------------------------------------

if [[ $EUID -eq 0 ]]; then
    echo
    echo "ERROR: Do not run this script as root."
    echo
    echo "Run it as your normal desktop user:"
    echo
    echo "    ./bootstrap-intel-xr.sh"
    echo
    exit 1
fi

echo "============================================================"
echo " Intel XR Prototype Bootstrap"
echo "============================================================"
echo
echo "User:       $USER"
echo "Root:       $ROOT"
echo "SteamVR:    NOT USED"
echo "XR runtime: Monado-ALVR"
echo

# ------------------------------------------------------------
# 1. Create project tree
# ------------------------------------------------------------

echo "[1/10] Creating project directories..."

if [[ ! -d /ai ]]; then
    sudo mkdir -p /ai
    sudo chown "$USER":"$(id -gn)" /ai
fi

if [[ ! -w /ai ]]; then
    echo "/ai is not writable by $USER."
    echo "Creating project directory with appropriate ownership..."

    sudo mkdir -p "$ROOT"
    sudo chown -R "$USER":"$(id -gn)" "$ROOT"
fi

mkdir -p \
    "$SRC" \
    "$BUILD" \
    "$INSTALL" \
    "$LOGS" \
    "$SCRIPTS"

LOG="$LOGS/bootstrap-intel-xr.log"

exec > >(tee "$LOG") 2>&1

echo "Log: $LOG"
echo

# ------------------------------------------------------------
# 2. Verify OS and hardware
# ------------------------------------------------------------

echo "[2/10] Verifying host..."

source /etc/os-release

echo "OS:     $PRETTY_NAME"
echo "Kernel: $(uname -r)"
echo

if [[ "${VERSION_ID:-}" != "24.04" ]]; then
    echo "WARNING: Designed for Ubuntu 24.04."
fi

echo "Graphics devices:"
lspci -nn | grep -Ei 'VGA|3D|Display' || true
echo

if ! lspci -nn | grep -Ei 'VGA|3D|Display' | grep -qi Intel; then
    echo "ERROR: Intel GPU not detected."
    exit 1
fi

echo "GPU driver:"
lspci -nnk | grep -A5 -Ei 'VGA|3D|Display' || true

# ------------------------------------------------------------
# 3. Install build dependencies
# ------------------------------------------------------------

echo
echo "[3/10] Installing build dependencies..."
echo
echo "This WILL NOT replace:"
echo "  - Mesa"
echo "  - Linux kernel"
echo "  - Intel GPU driver"
echo
echo "This WILL NOT install SteamVR."
echo

sudo apt-get update

sudo apt-get install -y \
    build-essential \
    git \
    curl \
    cmake \
    ninja-build \
    pkg-config \
    python3 \
    python3-dev \
    libeigen3-dev \
    glslang-tools \
    glslc \
    libvulkan-dev \
    vulkan-tools \
    libgl1-mesa-dev \
    libegl1-mesa-dev \
    libx11-dev \
    libx11-xcb-dev \
    libxcb1-dev \
    libxcb-randr0-dev \
    libxcb-shm0-dev \
    libxcb-keysyms1-dev \
    libxcb-composite0-dev \
    libxcb-xfixes0-dev \
    libxcb-glx0-dev \
    libwayland-dev \
    wayland-protocols \
    libxrandr-dev \
    libxxf86vm-dev \
    libudev-dev \
    libusb-1.0-0-dev \
    libv4l-dev \
    libdrm-dev \
    libgbm-dev \
    libsystemd-dev \
    libsdl2-dev \
    libhidapi-dev \
    libjpeg-dev \
    libbluetooth-dev \
    libbsd-dev \
    zlib1g-dev \
    libssl-dev \
    libpipewire-0.3-dev \
    libspa-0.2-dev \
    libavcodec-dev \
    libavdevice-dev \
    libavfilter-dev \
    libavformat-dev \
    libavutil-dev \
    libswresample-dev \
    libswscale-dev \
    libx264-dev \
    clang \
    libclang-dev

# ------------------------------------------------------------
# 4. Rust
# ------------------------------------------------------------

echo
echo "[4/10] Checking Rust toolchain..."

if ! command -v cargo >/dev/null 2>&1; then

    echo "Cargo not found."
    echo "Installing Rust using rustup for user $USER..."

    curl --proto '=https' \
         --tlsv1.2 \
         -sSf \
         https://sh.rustup.rs \
         | sh -s -- -y

    # shellcheck disable=SC1090
    source "$HOME/.cargo/env"

else

    echo "Cargo already installed:"
    cargo --version

fi

if [[ -f "$HOME/.cargo/env" ]]; then
    # shellcheck disable=SC1090
    source "$HOME/.cargo/env"
fi

echo "Rust:"
rustc --version

echo "Cargo:"
cargo --version

# ------------------------------------------------------------
# 5. Clone Monado-ALVR
# ------------------------------------------------------------

echo
echo "[5/10] Obtaining Monado-ALVR..."

if [[ -d "$MONADO/.git" ]]; then

    echo "Existing Monado-ALVR checkout found."

    git -C "$MONADO" fetch origin
    git -C "$MONADO" checkout main
    git -C "$MONADO" pull --ff-only origin main

else

    git clone \
        --branch intel-arc-linux \
        --single-branch \
        git@github.com:JLATORRE89/Monado-ALVR.git \
        "$MONADO"

fi

# ------------------------------------------------------------
# 6. Clone ALVR MONADO branch
# ------------------------------------------------------------

echo
echo "[6/10] Obtaining ALVR monado branch..."

if [[ -d "$ALVR/.git" ]]; then

    git -C "$ALVR" fetch origin

    git -C "$ALVR" checkout monado

    git -C "$ALVR" pull \
        --ff-only \
        origin monado

else

    git clone \
        --branch monado \
        --single-branch \
        https://github.com/alvr-org/ALVR.git \
        "$ALVR"

fi

# ------------------------------------------------------------
# 7. Clone alvr_render
# ------------------------------------------------------------

echo
echo "[7/10] Obtaining alvr_render..."

if [[ -d "$ALVR_RENDER/.git" ]]; then

    git -C "$ALVR_RENDER" fetch origin
    git -C "$ALVR_RENDER" checkout master
    git -C "$ALVR_RENDER" pull --ff-only origin master

else

    git clone \
        https://github.com/The-personified-devil/alvr_render.git \
        "$ALVR_RENDER"

fi

echo
echo "Source tree:"
echo

ls -ld \
    "$MONADO" \
    "$ALVR" \
    "$ALVR_RENDER"

echo
echo "Revisions:"
echo

echo "--- Monado-ALVR ---"
git -C "$MONADO" log -1 --oneline

echo
echo "--- ALVR monado ---"
git -C "$ALVR" log -1 --oneline

echo
echo "--- alvr_render ---"
git -C "$ALVR_RENDER" log -1 --oneline

# ------------------------------------------------------------
# IMPORTANT
#
# Upstream Monado-ALVR expects:
#
#     Monado-ALVR/
#     alvr-monado/
#     alvr_render/
#
# to be siblings.
#
# ------------------------------------------------------------

echo
echo "Verifying required sibling layout..."

test -d "$MONADO" || {
    echo "ERROR: Monado-ALVR missing."
    exit 1
}

test -d "$ALVR" || {
    echo "ERROR: alvr-monado missing."
    exit 1
}

test -d "$ALVR_RENDER" || {
    echo "ERROR: alvr_render missing."
    exit 1
}

# ------------------------------------------------------------
# 8. Build ALVR server library
# ------------------------------------------------------------

echo
echo "[8/10] Building ALVR server library..."
echo

cd "$ALVR"

cargo xtask build-server-lib

echo
echo "ALVR server library build completed."

# ------------------------------------------------------------
# 9. Configure Monado-ALVR
# ------------------------------------------------------------

echo
echo "[9/10] Configuring Monado-ALVR..."
echo

rm -rf "$MONADO_BUILD"
mkdir -p "$MONADO_BUILD"

cmake \
    -S "$MONADO" \
    -B "$MONADO_BUILD" \
    -G Ninja \
    -DCMAKE_BUILD_TYPE=RelWithDebInfo \
    -DCMAKE_INSTALL_PREFIX="$INSTALL" \
    -DXRT_BUILD_DRIVER_ALVR=ON \
    -DXRT_FEATURE_OPENXR=ON \
    -DXRT_MODULE_COMPOSITOR=ON \
    -DXRT_MODULE_COMPOSITOR_MAIN=ON \
    -DXRT_MODULE_MONADO_CLI=ON \
    -DXRT_FEATURE_SERVICE=ON \
    -DXRT_OPENXR_INSTALL_ACTIVE_RUNTIME=OFF \
    -DXRT_FEATURE_STEAMVR_PLUGIN=OFF \
    -DXRT_BUILD_DRIVER_STEAMVR_LIGHTHOUSE=OFF

CACHE="$MONADO_BUILD/CMakeCache.txt"

echo
echo "Verifying CMake configuration..."

if [[ ! -f "$CACHE" ]]; then
    echo "ERROR: CMake cache wasn't generated."
    exit 1
fi

if ! grep -q 'XRT_BUILD_DRIVER_ALVR:BOOL=ON' "$CACHE"; then
    echo "ERROR: ALVR driver isn't enabled."
    exit 1
fi

if grep -q 'XRT_FEATURE_STEAMVR_PLUGIN:BOOL=ON' "$CACHE"; then
    echo "ERROR: SteamVR plugin unexpectedly enabled."
    exit 1
fi

if grep -q 'XRT_BUILD_DRIVER_STEAMVR_LIGHTHOUSE:BOOL=ON' "$CACHE"; then
    echo "ERROR: SteamVR Lighthouse unexpectedly enabled."
    exit 1
fi

echo
echo "Configuration:"
echo "  OpenXR:             ON"
echo "  ALVR driver:        ON"
echo "  Vulkan compositor:  ON"
echo "  Monado service:     ON"
echo "  SteamVR plugin:     OFF"
echo "  SteamVR Lighthouse: OFF"

# ------------------------------------------------------------
# 10. Build
# ------------------------------------------------------------

echo
echo "[10/10] Building Monado-ALVR..."
echo

cmake \
    --build "$MONADO_BUILD" \
    --parallel "$(nproc)"

echo
echo "Installing into project-local prefix..."
echo

cmake \
    --install "$MONADO_BUILD"

# ------------------------------------------------------------
# Locate important outputs
# ------------------------------------------------------------

echo
echo "============================================================"
echo " BUILD OUTPUT"
echo "============================================================"

echo
echo "OpenXR manifests:"

find "$MONADO_BUILD" "$INSTALL" \
    -type f \
    \( -name 'openxr_monado-dev.json' \
       -o -name '*openxr*.json' \
       -o -name '*monado*.json' \) \
    -print 2>/dev/null || true

echo
echo "Monado service:"

find "$MONADO_BUILD" "$INSTALL" \
    -type f \
    -name 'monado-service' \
    -print 2>/dev/null || true

echo
echo "Monado CLI:"

find "$MONADO_BUILD" "$INSTALL" \
    -type f \
    -name 'monado-cli' \
    -print 2>/dev/null || true

# ------------------------------------------------------------
# Environment helper
# ------------------------------------------------------------

cat > "$SCRIPTS/env.sh" <<EOF
#!/usr/bin/env bash

export INTEL_XR_ROOT="$ROOT"
export MONADO_SOURCE="$MONADO"
export MONADO_BUILD="$MONADO_BUILD"
export MONADO_INSTALL="$INSTALL"
export ALVR_SOURCE="$ALVR"
export ALVR_RENDER_SOURCE="$ALVR_RENDER"

export PATH="$INSTALL/bin:\$PATH"

export LD_LIBRARY_PATH="$INSTALL/lib:$INSTALL/lib/x86_64-linux-gnu:\${LD_LIBRARY_PATH:-}"

echo
echo "Intel XR prototype environment loaded."
echo
echo "Root:"
echo "  \$INTEL_XR_ROOT"
echo
echo "SteamVR:"
echo "  NOT USED"
echo
EOF

chmod +x "$SCRIPTS/env.sh"

# ------------------------------------------------------------
# Status helper
# ------------------------------------------------------------

cat > "$SCRIPTS/status.sh" <<'EOF'
#!/usr/bin/env bash

ROOT="/ai/intel-xr-prototype"

echo "============================================================"
echo " Intel XR Status"
echo "============================================================"

echo
echo "GPU:"
lspci -nn | grep -Ei 'VGA|3D|Display' || true

echo
echo "Driver:"
lspci -nnk | grep -A5 -Ei 'VGA|3D|Display' || true

echo
echo "Vulkan:"
vulkaninfo --summary 2>&1 |
    grep -E \
    'deviceName|driverName|driverInfo|deviceType' || true

echo
echo "Sources:"

for repo in \
    "$ROOT/src/Monado-ALVR" \
    "$ROOT/src/alvr-monado" \
    "$ROOT/src/alvr_render"
do
    echo
    echo "$repo"

    if [[ -d "$repo/.git" ]]; then
        git -C "$repo" log -1 --oneline
    else
        echo "MISSING"
    fi
done

echo
echo "OpenXR manifests:"

find \
    "$ROOT/build" \
    "$ROOT/local" \
    -type f \
    -name '*openxr*.json' \
    -print 2>/dev/null || true

echo
echo "Monado service:"

find \
    "$ROOT/build" \
    "$ROOT/local" \
    -type f \
    -name 'monado-service' \
    -print 2>/dev/null || true

echo
echo "SteamVR:"
echo "NOT USED"
EOF

chmod +x "$SCRIPTS/status.sh"

# ------------------------------------------------------------
# README
# ------------------------------------------------------------

cat > "$ROOT/README.md" <<EOF
# Intel XR Prototype

Target:

    Quest 2
       |
      ALVR
       |
    Monado-ALVR
       |
     OpenXR
       |
     Vulkan
       |
 Intel Arc A750

SteamVR is intentionally excluded.

## Source layout

$SRC/

    Monado-ALVR/
    alvr-monado/
    alvr_render/

## Environment

    source $SCRIPTS/env.sh

## Status

    $SCRIPTS/status.sh

## Important

The bootstrap DOES NOT make Monado the global OpenXR runtime.

The next phase will use XR_RUNTIME_JSON to select the
development runtime for individual test applications.

That allows testing without replacing the system OpenXR
configuration.
EOF

echo
echo
echo "============================================================"
echo " INTEL XR BOOTSTRAP COMPLETE"
echo "============================================================"
echo
echo "Project:"
echo "  $ROOT"
echo
echo "Sources:"
echo "  $MONADO"
echo "  $ALVR"
echo "  $ALVR_RENDER"
echo
echo "Build:"
echo "  $MONADO_BUILD"
echo
echo "Install:"
echo "  $INSTALL"
echo
echo "Log:"
echo "  $LOG"
echo
echo "Next:"
echo
echo "  source $SCRIPTS/env.sh"
echo "  $SCRIPTS/status.sh"
echo
echo "DO NOT configure a global OpenXR runtime yet."
echo
echo "SteamVR was NOT installed or enabled."
