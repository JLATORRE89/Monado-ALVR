#!/usr/bin/env bash
# Distance-limited Loft voice. Never broadcast microphones to unknown/distant users.
set -Eeuo pipefail
exec python3 "$(dirname "$(readlink -f "$0")")/xr-voice.py" "${1:-link}"
