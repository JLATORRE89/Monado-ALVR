#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="${INTEL_XR_ROOT:-/ai/intel-xr-prototype}"
LOGDIR="$ROOT/logs"; mkdir -p "$LOGDIR"
source "$ROOT/src/Monado-ALVR/scripts/xr-log.sh"
xr_init_log "$(basename "$0" .sh)"
QUEST_IP="${QUEST_IP:-192.168.86.168}"
API="${ALVR_API:-http://127.0.0.1:8082}"

echo "=== Trust ALVR client ==="
echo "API: $API"

if ! curl -fsS -H 'X-ALVR: 1' "$API/api/ping" >/dev/null; then
  echo "ERROR: ALVR API ping failed."
  exit 1
fi

# GET /api/session/ emits the session over the events channel; it does not return JSON.
# Discover client identity from ALVR server events instead.
EVENTS="$(mktemp)"
trap 'rm -f "$EVENTS"' EXIT
timeout 3 curl -NsS -H 'X-ALVR: 1' "$API/api/events" >"$EVENTS" 2>/dev/null || true

HOST="$(python3 - "$EVENTS" "$QUEST_IP" <<'PY'
import json,sys
ip=sys.argv[2]
hosts=[]
for line in open(sys.argv[1], errors="ignore"):
    try: obj=json.loads(line)
    except: continue
    s=json.dumps(obj)
    if ip in s:
        # Walk dicts looking for hostname-ish keys near this event.
        stack=[obj]
        while stack:
            x=stack.pop()
            if isinstance(x,dict):
                for k,v in x.items():
                    if k in ("hostname","host_name") and isinstance(v,str): hosts.append(v)
                    stack.append(v)
            elif isinstance(x,list): stack.extend(x)
if hosts: print(hosts[-1])
PY
)"
if [[ -z "$HOST" ]]; then
  echo "ERROR: ALVR API is healthy, but no discovered Quest client identity was found yet."
  exit 1
fi

echo "Client hostname: $HOST"
PAYLOAD="$(python3 - "$HOST" <<'PY'
import json,sys
print(json.dumps([sys.argv[1],"Trust"]))
PY
)"
curl -fsS -X POST -H 'X-ALVR: 1' -H 'Content-Type: application/json' --data "$PAYLOAD" "$API/api/session/client-connections"
echo
echo "Trust request sent for $HOST."
