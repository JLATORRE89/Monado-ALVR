#!/usr/bin/env bash
# Voice chat between headsets on this PC: link every runtime instance's headset microphone
# ("ALVR Microphone" / "ALVR Microphone (<instance>)") into every OTHER instance's headset audio
# ("ALVR Audio" / "ALVR Audio (<instance>)"), never into its own. ALVR creates these PipeWire
# nodes only while a headset streams, so `watch` re-checks every few seconds.
#   xr-voice.sh link     link once, print what was linked
#   xr-voice.sh watch    keep linking (run by intel-xr-voice.service)
#   xr-voice.sh unlink   remove all microphone -> headset audio links
#   xr-voice.sh status   list current voice links
set -Eeuo pipefail
command -v pw-link >/dev/null || { echo "pw-link not found (PipeWire tools)"; exit 1; }

# Node name -> instance ("primary" for the unsuffixed default runtime).
instance_of() {
  local n="$1"
  if [[ "$n" =~ \((.+)\)$ ]]; then echo "${BASH_REMATCH[1]}"; else echo primary; fi
}
# Ports as "node:port" lines.
mic_ports()  { pw-link -o 2>/dev/null | grep -E '^ALVR Microphone( \([^)]*\))?:' || true; }
sink_ports() { pw-link -i 2>/dev/null | grep -E '^ALVR Audio( \([^)]*\))?:' || true; }
channel()    { local p="${1##*:}"; echo "${p##*_}"; }   # capture_MONO -> MONO, playback_FL -> FL

link_all() {
  local made=0 mic sink mnode snode
  local mics sinks
  mics="$(mic_ports)"; sinks="$(sink_ports)"
  [[ -n "$mics" && -n "$sinks" ]] || return 0
  while IFS= read -r mic; do
    mnode="${mic%%:*}"
    local mic_count
    mic_count="$(grep -c "^$mnode:" <<<"$mics")"
    while IFS= read -r sink; do
      snode="${sink%%:*}"
      [[ "$(instance_of "$mnode")" == "$(instance_of "$snode")" ]] && continue   # never hear yourself
      # Mono microphone -> every channel; otherwise pair matching channels.
      if [[ "$mic_count" -gt 1 && "$(channel "$mic")" != "$(channel "$sink")" ]]; then continue; fi
      if pw-link "$mic" "$sink" 2>/dev/null; then
        echo "linked $mic -> $sink"; made=$((made + 1))
      fi
    done <<<"$sinks"
  done <<<"$mics"
  return 0
}

case "${1:-link}" in
  link) link_all ;;
  watch) while true; do link_all; sleep 3; done ;;
  unlink)
    pw-link -l 2>/dev/null |
      awk '/^[^ ]/ {src = ($0 ~ /^ALVR Microphone/) ? $0 : ""; next} /\|->/ && src != "" {sub(/^ *\|-> */, ""); print src "\t" $0}' |
      while IFS=$'\t' read -r src dst; do
        [[ "$dst" == "ALVR Audio"* ]] && pw-link -d "$src" "$dst" && echo "unlinked $src -> $dst"
      done || true ;;
  status)
    pw-link -l 2>/dev/null |
      awk '/^[^ ]/ {src = ($0 ~ /^ALVR Microphone/) ? $0 : ""; next} /\|->/ && src != "" {sub(/^ *\|-> */, ""); print src " -> " $0; n++} END {if (!n) print "no voice links"}' ;;
  *) echo "Usage: $0 {link|watch|unlink|status}"; exit 2 ;;
esac
