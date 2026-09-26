#!/usr/bin/env bash
set -u
ROOT="${INTEL_XR_ROOT:-/ai/intel-xr-prototype}"
SERVICE="$ROOT/build/monado-alvr/src/xrt/targets/service/monado-service"
LOG="$ROOT/logs/$(date +%Y-%m-%d_%H-%M-%S)_test-intel-xr.log"
mkdir -p "$ROOT/logs"
if [[ ! -x "$SERVICE" ]]; then echo "ERROR: monado-service not built: $SERVICE"; exit 1; fi
echo "Starting Monado-ALVR. Press Ctrl+C to stop."
echo "Log: $LOG"
XRT_LOG="${XRT_LOG:-debug}" "$SERVICE" 2>&1 | tee "$LOG"
