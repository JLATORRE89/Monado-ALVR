# Shared logging helper for Intel XR support scripts.
xr_init_log() {
  local name="$1"
  local root="${INTEL_XR_ROOT:-/ai/intel-xr-prototype}"
  mkdir -p "$root/logs"
  if [[ -z "${XR_SESSION_LOG:-}" ]]; then
    export XR_SESSION_LOG="$root/logs/$(date +%Y-%m-%d_%H-%M-%S)_${name}.log"
    export XR_LOG_OWNER=1
    exec > >(tee "$XR_SESSION_LOG") 2>&1
  fi
  echo "Log: $XR_SESSION_LOG"
}
