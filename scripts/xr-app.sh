#!/usr/bin/env bash
# Start/stop the XR test application (checkerboard) and, optionally, the runtime.
#   xr-app.sh start     ensure the Monado service, then launch one checkerboard
#   xr-app.sh stop      exit the checkerboard (the headset returns to the ALVR lobby)
#   xr-app.sh stop-all  exit the checkerboard and stop the Monado service
#   xr-app.sh status    print app/runtime state
set -Eeuo pipefail
ROOT="${INTEL_XR_ROOT:-/ai/intel-xr-prototype}"
MONADO="$ROOT/src/Monado-ALVR"
LOGDIR="$ROOT/logs"
# Process name as the kernel reports it (comm is truncated to 15 characters).
APP_COMM="intel_xr_checke"

app_pids() { pgrep -x "$APP_COMM" || true; }

stop_app() {
  local pids
  pids="$(app_pids)"
  if [[ -z "$pids" ]]; then
    echo "Test app is not running."
    return 0
  fi
  kill -TERM $pids
  for _ in $(seq 1 20); do
    [[ -z "$(app_pids)" ]] && { echo "Test app stopped."; return 0; }
    sleep 0.25
  done
  kill -KILL $(app_pids) 2>/dev/null || true
  echo "Test app killed after timeout."
}

case "${1:-status}" in
  start)
    if [[ -n "$(app_pids)" ]]; then
      echo "Test app already running (pid $(app_pids | tr '\n' ' '))."
      exit 0
    fi
    bash "$MONADO/scripts/monado-service.sh" ensure >/dev/null
    mkdir -p "$LOGDIR"
    log="$LOGDIR/$(date +%Y-%m-%d_%H-%M-%S)_xr-app.log"
    setsid nohup bash "$MONADO/scripts/run-video-test.sh" >"$log" 2>&1 </dev/null &
    for _ in $(seq 1 120); do
      [[ -n "$(app_pids)" ]] && { echo "Test app started (log $log)."; exit 0; }
      sleep 0.5
    done
    echo "Test app did not start; see $log" >&2
    exit 1
    ;;
  stop)
    stop_app
    ;;
  stop-all)
    stop_app
    bash "$MONADO/scripts/monado-service.sh" stop
    echo "Runtime stopped."
    ;;
  status)
    pids="$(app_pids)"
    echo "app=$([[ -n "$pids" ]] && echo running || echo stopped)"
    echo "runtime=$(systemctl --user is-active intel-xr-monado.service || true)"
    ;;
  *)
    echo "Usage: $0 {start|stop|stop-all|status}" >&2
    exit 2
    ;;
esac
