#!/usr/bin/env bash
# Source this file. It loads config/xr-build.json into the current shell.
XR_CONFIG="${XR_CONFIG:-${INTEL_XR_ROOT:-/ai/intel-xr-prototype}/src/Monado-ALVR/config/xr-build.json}"
[[ -f "$XR_CONFIG" ]] || { echo "ERROR: XR config missing: $XR_CONFIG" >&2; return 1 2>/dev/null || exit 1; }
eval "$(python3 - "$XR_CONFIG" <<'PY'
import json, shlex, sys
c=json.load(open(sys.argv[1]))
p=c["paths"]; a=c["android"]
vals={
 "INTEL_XR_ROOT":p["root"],
 "JAVA_HOME":p["java_home"],
 "ANDROID_HOME":p["android_home"],
 "ANDROID_NDK_ROOT":f'{p["android_home"]}/ndk/{a["ndk_version"]}',
 "ANDROID_NDK_HOME":f'{p["android_home"]}/ndk/{a["ndk_version"]}',
 "XR_ANDROID_RUST_TARGET":a["rust_target"],
 "XR_ANDROID_PLATFORM_API":str(a["platform_api"]),
 "ALVR_LEGACY_PROTOCOL_TEST":"1" if c.get("alvr",{}).get("legacy_protocol_test",False) else "0",
}
for k,v in vals.items(): print(f'export {k}={shlex.quote(v)}')
print('unset ANDROID_SDK_ROOT')
print('export PATH="$JAVA_HOME/bin:$ANDROID_HOME/platform-tools:$HOME/.cargo/bin:$PATH"')
PY
)"
