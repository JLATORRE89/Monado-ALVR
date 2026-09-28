#!/usr/bin/env bash
# Extra runtime instances for more headsets on this PC (the default runtime keeps serving the
# first headset). Each instance is intel-xr-monado@<name> with its own Monado IPC directory,
# ALVR config (trusted headset, web/stream ports), logs, USB port offset and audio node names.
#   xr-instance.sh create <name> [--serial ADB_SERIAL] [--ip QUEST_IP]
#   xr-instance.sh start|stop|status|remove <name>
#   xr-instance.sh list
# Launch the Loft into an instance: XR_INSTANCE=<name> bash scripts/xr-app.sh start loft
# Starting an instance also starts intel-xr-voice.service (xr-voice.sh watch): each headset hears
# the others through its ALVR audio.
set -Eeuo pipefail
ROOT="${INTEL_XR_ROOT:-/ai/intel-xr-prototype}"
MONADO="$ROOT/src/Monado-ALVR"
INST_DIR="$HOME/.config/intel-xr/instances"
UNIT_DIR="$HOME/.config/systemd/user"
PRIMARY_SESSION="$HOME/.config/alvr/session.json"
ACTION="${1:-list}"
NAME="${2:-}"

need_name() {
  [[ "$NAME" =~ ^[a-z0-9][a-z0-9_-]{0,23}$ && "$NAME" != primary ]] ||
    { echo "Instance names: lower-case letters, digits, - or _ (not 'primary')" >&2; exit 2; }
}
install_unit() {
  mkdir -p "$UNIT_DIR"
  cp "$MONADO/systemd/intel-xr-monado@.service" "$MONADO/systemd/intel-xr-voice.service" "$UNIT_DIR/"
  systemctl --user daemon-reload
}
index_of() { sed -n 's/^XR_INSTANCE_INDEX=//p' "$INST_DIR/$1.env"; }

case "$ACTION" in
  create)
    need_name
    shift 2
    serial="" ip=""
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --serial) serial="$2"; shift 2 ;;
        --ip) ip="$2"; shift 2 ;;
        *) echo "unknown option $1" >&2; exit 2 ;;
      esac
    done
    [[ -z "$serial" || "$serial" =~ ^[A-Za-z0-9._:-]{1,64}$ ]] || { echo "invalid serial" >&2; exit 2; }
    [[ -z "$ip" || "$ip" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] || { echo "invalid IPv4 address" >&2; exit 2; }
    [[ -n "$serial" || -n "$ip" ]] || { echo "give --serial (USB) and/or --ip (Wi-Fi) for this headset" >&2; exit 2; }
    [[ -f "$INST_DIR/$NAME.env" ]] && { echo "instance $NAME already exists" >&2; exit 1; }
    [[ -f "$PRIMARY_SESSION" ]] || { echo "no ALVR session to copy ($PRIMARY_SESSION)" >&2; exit 1; }
    mkdir -p "$INST_DIR"
    # Next free index (1..9); each gets distinct ports.
    idx=1
    while grep -qs "^XR_INSTANCE_INDEX=$idx\$" "$INST_DIR"/*.env; do idx=$((idx + 1)); done
    [[ $idx -le 9 ]] || { echo "at most 9 extra instances" >&2; exit 1; }
    conf="$HOME/.config/alvr-$NAME"
    mkdir -p "$conf"
    python3 - "$PRIMARY_SESSION" "$conf/session.json" "$idx" "$ip" <<'PY'
import json, sys
src, dst, idx, ip = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
s = json.load(open(src))
c = s["session_settings"]["connection"]
c["web_server_port"] = 8090 + idx          # 8082 = default runtime, 8083 = control panel
c["stream_port"] = 9944 + 20 * idx         # UDP bind on this PC must differ per instance
# Trust only this instance's headset: the wired entry follows ALVR_WIRED_SERIAL; Wi-Fi by IP.
clients = {}
if "client.wired" in s.get("client_connections", {}):
    clients["client.wired"] = dict(s["client_connections"]["client.wired"], connection_state="Disconnected")
if ip:
    clients["direct-" + ip] = {"display_name": "Quest", "current_ip": None, "manual_ips": [],
                               "trusted": True, "connection_state": "Disconnected"}
s["client_connections"] = clients
json.dump(s, open(dst, "w"), indent=2)
PY
    {
      echo "XR_INSTANCE_INDEX=$idx"
      echo "XR_INSTANCE=$NAME"
      echo "XDG_RUNTIME_DIR=/run/user/$(id -u)/xr-$NAME"
      echo "PIPEWIRE_RUNTIME_DIR=/run/user/$(id -u)"
      echo "ALVR_CONFIG_DIR=$conf"
      echo "ALVR_LOG_DIR=$ROOT/logs/instance-$NAME"
      echo "ALVR_INSTANCE_NAME=$NAME"
      echo "ALVR_WIRED_PORT_OFFSET=$((20 * idx))"
      [[ -n "$serial" ]] && echo "ALVR_WIRED_SERIAL=$serial"
      [[ -n "$ip" ]] && echo "ALVR_DIRECT_CLIENT_IP=$ip"
      echo "ALVR_LEGACY_PROTOCOL_TEST=1"
    } > "$INST_DIR/$NAME.env"
    install_unit
    echo "Created instance $NAME (index $idx): web port $((8090 + idx)), stream port $((9944 + 20 * idx)), USB control port $((9943 + 20 * idx))"
    echo "Start it:  bash $MONADO/scripts/xr-instance.sh start $NAME"
    echo "Loft:      XR_INSTANCE=$NAME bash $MONADO/scripts/xr-app.sh start loft"
    ;;
  start)
    need_name; [[ -f "$INST_DIR/$NAME.env" ]] || { echo "unknown instance $NAME" >&2; exit 2; }
    install_unit
    systemctl --user start "intel-xr-monado@$NAME.service"
    systemctl --user start intel-xr-voice.service   # voice between all streaming headsets
    systemctl --user is-active "intel-xr-monado@$NAME.service"
    ;;
  stop)
    need_name
    systemctl --user stop "intel-xr-monado@$NAME.service" || true
    ;;
  status)
    need_name
    systemctl --user --no-pager status "intel-xr-monado@$NAME.service" | head -12 || true
    ;;
  remove)
    need_name
    systemctl --user stop "intel-xr-monado@$NAME.service" 2>/dev/null || true
    rm -f "$INST_DIR/$NAME.env"
    echo "Removed instance $NAME (kept its ALVR config in ~/.config/alvr-$NAME and its logs)"
    ;;
  list)
    echo "primary  intel-xr-monado.service  $(systemctl --user is-active intel-xr-monado.service || true)"
    for f in "$INST_DIR"/*.env; do
      [[ -f "$f" ]] || continue
      n="$(basename "$f" .env)"
      echo "$n  intel-xr-monado@$n.service  $(systemctl --user is-active "intel-xr-monado@$n.service" || true)  $(grep -E '^ALVR_(WIRED_SERIAL|DIRECT_CLIENT_IP)=' "$f" | tr '\n' ' ')"
    done
    ;;
  *) echo "Usage: $0 {create|start|stop|status|remove|list} [name] [--serial S] [--ip IP]" >&2; exit 2 ;;
esac
