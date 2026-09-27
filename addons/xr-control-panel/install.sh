#!/usr/bin/env bash
# Install the XR Control Panel add-on as a systemd user service.
#
#   bash install.sh [--runtime-root DIR] [--port N] [--bind ADDR] [--prefix DIR]
#
# The panel is independent of the Intel XR runtime: without --runtime-root it manages
# headsets only (ADB screenshots/recordings, client launch/close). Uninstall with
# uninstall.sh; the runtime keeps working either way.
set -Eeuo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="$HOME/.local/share/xr-control-panel/app"
CONFIG_DIR="$HOME/.config/xr-control-panel"
CONFIG="$CONFIG_DIR/config.json"
UNIT_DIR="$HOME/.config/systemd/user"
UNIT="$UNIT_DIR/xr-control-panel.service"
PORT=""
BIND=""
RUNTIME_ROOT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --runtime-root) RUNTIME_ROOT="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --bind) BIND="$2"; shift 2 ;;
    --prefix) PREFIX="$2"; shift 2 ;;
    -h|--help) sed -n 2,9p "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

PYTHON="$(command -v python3 || true)"
[[ -n "$PYTHON" ]] || { echo "ERROR: python3 is required" >&2; exit 1; }
command -v adb >/dev/null || echo "NOTE: adb not on PATH; set \"adb\" in $CONFIG if it is installed elsewhere."

echo "Installing XR Control Panel to $PREFIX"
mkdir -p "$PREFIX/static" "$CONFIG_DIR" "$UNIT_DIR"
install -m 0755 "$SRC/server.py" "$SRC/approved_devices.py" "$PREFIX/"
install -m 0644 "$SRC/static/index.html" "$SRC/static/app.css" "$SRC/static/app.js" "$PREFIX/static/"
install -m 0644 "$SRC/README.md" "$PREFIX/"

# Create or update the config (only the options given on the command line change).
"$PYTHON" - "$CONFIG" "$RUNTIME_ROOT" "$PORT" "$BIND" <<'PY'
import json, sys
from pathlib import Path
path, root, port, bind = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
cfg = json.loads(path.read_text()) if path.is_file() else {"bind": "127.0.0.1", "port": 8083, "runtime_root": None}
if root: cfg["runtime_root"] = root
if port: cfg["port"] = int(port)
if bind: cfg["bind"] = bind
path.write_text(json.dumps(cfg, indent=2) + "\n")
print(f"Config: {path} -> {cfg}")
PY

# Replace the earlier built-in UI service if present.
if [[ -f "$UNIT_DIR/intel-xr-client-ui.service" ]]; then
  echo "Removing the old built-in client UI service"
  systemctl --user disable --now intel-xr-client-ui.service 2>/dev/null || true
  rm -f "$UNIT_DIR/intel-xr-client-ui.service"
fi

sed -e "s#@PYTHON@#$PYTHON#g" -e "s#@PREFIX@#$PREFIX#g" "$SRC/xr-control-panel.service.in" > "$UNIT"
systemctl --user daemon-reload
systemctl --user enable xr-control-panel.service >/dev/null
systemctl --user restart xr-control-panel.service

URL="$("$PYTHON" -c 'import json,sys; c=json.load(open(sys.argv[1])); print("http://%s:%s/" % (c.get("bind","127.0.0.1"), c.get("port",8083)))' "$CONFIG")"
for _ in $(seq 1 20); do
  if curl -fsS -o /dev/null "$URL" 2>/dev/null; then
    echo "XR Control Panel is running: $URL"
    exit 0
  fi
  sleep 0.5
done
echo "ERROR: panel did not start; see: journalctl --user -u xr-control-panel.service -n 50" >&2
exit 1
