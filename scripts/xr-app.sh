#!/usr/bin/env bash
# Start/stop the XR app streamed to the headset and, optionally, the runtime.
#   xr-app.sh start [checkerboard|loft]  ensure the Monado service, then launch one app
#                                        (default: checkerboard)
#   xr-app.sh stop      exit the running app (the headset returns to the ALVR lobby)
#   xr-app.sh stop-all  exit the app and stop the Monado service
#   xr-app.sh status    print app/runtime state
# The Loft (github.com/JLATORRE89/loft) is built into $ROOT/build/intel-xr-loft.
# Several headsets: XR_INSTANCE=<name> xr-app.sh ... acts on that runtime instance (see
# xr-instance.sh); without it, the default runtime. Apps of other instances are left alone.
set -Eeuo pipefail
ROOT="${INTEL_XR_ROOT:-/ai/intel-xr-prototype}"
MONADO="$ROOT/src/Monado-ALVR"
LOGDIR="$ROOT/logs"
# Process names as the kernel reports them (comm is truncated to 15 characters).
APP_COMMS=("intel_xr_checke" "intel_xr_loft")
LOFT_BIN="$ROOT/build/intel-xr-loft/intel_xr_loft"

INSTANCE="${XR_INSTANCE:-}"
if [[ -n "$INSTANCE" ]]; then
  ENV_FILE="$HOME/.config/intel-xr/instances/$INSTANCE.env"
  [[ -f "$ENV_FILE" ]] || { echo "Unknown runtime instance: $INSTANCE (see xr-instance.sh list)" >&2; exit 2; }
  INSTANCE_RUNTIME_DIR="$(sed -n 's/^XDG_RUNTIME_DIR=//p' "$ENV_FILE")"
  INSTANCE_INDEX="$(sed -n 's/^XR_INSTANCE_INDEX=//p' "$ENV_FILE")"
fi
# Lofts of all instances share this folder so their users see each other.
PRESENCE_DIR="/run/user/$(id -u)/xr-loft-presence"

# Only this instance's apps (their environment carries XR_INSTANCE; empty for the default runtime).
instance_of() { tr '\0' '\n' < "/proc/$1/environ" 2>/dev/null | sed -n 's/^XR_INSTANCE=//p'; }
pids_of() {
  local pid
  for pid in $(pgrep -x "$1" || true); do
    [[ "$(instance_of "$pid")" == "$INSTANCE" ]] && echo "$pid"
  done
}
app_pids() { for c in "${APP_COMMS[@]}"; do pids_of "$c"; done; }
app_name() {
  if [[ -n "$(pids_of intel_xr_loft)" ]]; then echo loft
  elif [[ -n "$(pids_of intel_xr_checke)" ]]; then echo checkerboard
  else echo none; fi
}
ensure_runtime() {
  if [[ -n "$INSTANCE" ]]; then
    bash "$MONADO/scripts/xr-instance.sh" start "$INSTANCE" >/dev/null
  else
    bash "$MONADO/scripts/monado-service.sh" ensure >/dev/null
  fi
}

stop_app() {
  local pids
  pids="$(app_pids)"
  if [[ -z "$pids" ]]; then
    echo "No app is running."
    return 0
  fi
  kill -TERM $pids
  for _ in $(seq 1 20); do
    [[ -z "$(app_pids)" ]] && { echo "App stopped."; return 0; }
    sleep 0.25
  done
  kill -KILL $(app_pids) 2>/dev/null || true
  echo "App killed after timeout."
}

case "${1:-status}" in
  start)
    want="${2:-checkerboard}"
    [[ "$want" == checkerboard || "$want" == loft ]] || { echo "Unknown app: $want (checkerboard|loft)" >&2; exit 2; }
    if [[ -n "$(app_pids)" ]]; then
      [[ "$(app_name)" == "$want" ]] && { echo "$want already running."; exit 0; }
      stop_app >/dev/null
    fi
    if [[ "$want" == loft && ! -x "$LOFT_BIN" ]]; then
      echo "Loft is not built: $LOFT_BIN (see github.com/JLATORRE89/loft README)" >&2
      exit 1
    fi
    ensure_runtime
    mkdir -p "$LOGDIR"
    log="$LOGDIR/$(date +%Y-%m-%d_%H-%M-%S)_xr-app-$want${INSTANCE:+-$INSTANCE}.log"
    if [[ "$want" == loft ]]; then
      # Exit from inside the Loft also closes the Quest client (back to Quest Home).
      XR_LOFT_ON_EXIT="${XR_LOFT_ON_EXIT-bash $MONADO/scripts/quest-client-close.sh}" \
      XR_LOFT_LAUNCH_HOOK="${XR_LOFT_LAUNCH_HOOK-bash $MONADO/scripts/xr-loft-launch.sh}" \
      XR_INSTANCE="$INSTANCE" XR_INSTANCE_INDEX="${INSTANCE_INDEX:-0}" XR_LOFT_PRESENCE_DIR="$PRESENCE_DIR" \
      PULSE_SERVER="unix:/run/user/$(id -u)/pulse/native" \
      XDG_RUNTIME_DIR="${INSTANCE_RUNTIME_DIR:-${XDG_RUNTIME_DIR:-/run/user/$(id -u)}}" \
      XR_RUNTIME_JSON="$ROOT/build/monado-alvr/openxr_monado-dev.json" \
      LD_LIBRARY_PATH="$ROOT/build/openxr-demo/src/loader:${LD_LIBRARY_PATH:-}" \
        setsid nohup "$LOFT_BIN" >"$log" 2>&1 </dev/null &
    else
      setsid nohup bash "$MONADO/scripts/run-video-test.sh" >"$log" 2>&1 </dev/null &
    fi
    for _ in $(seq 1 120); do
      [[ -n "$(app_pids)" ]] && { echo "Started $want (log $log)."; exit 0; }
      sleep 0.5
    done
    echo "$want did not start; see $log" >&2
    exit 1
    ;;
  stop)
    stop_app
    ;;
  stop-all)
    stop_app
    if [[ -n "$INSTANCE" ]]; then
      bash "$MONADO/scripts/xr-instance.sh" stop "$INSTANCE" >/dev/null
    else
      bash "$MONADO/scripts/monado-service.sh" stop
    fi
    echo "Runtime stopped."
    ;;
  status)
    pids="$(app_pids)"
    echo "app=$([[ -n "$pids" ]] && echo running || echo stopped)"
    echo "app_name=$(app_name)"
    unit="intel-xr-monado${INSTANCE:+@$INSTANCE}.service"
    echo "runtime=$(systemctl --user is-active "$unit" || true)"
    ;;
  *)
    echo "Usage: $0 {start [checkerboard|loft]|stop|stop-all|status}" >&2
    exit 2
    ;;
esac
