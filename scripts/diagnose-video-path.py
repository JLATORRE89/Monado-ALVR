#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One-shot Intel XR black-screen diagnostic."""
from __future__ import annotations
import json, os, pathlib, re, shutil, subprocess, sys, time

def run(args, *, check=False, capture=True, timeout=None):
    p=subprocess.run(args, text=True, encoding="utf-8", errors="replace",
                     stdout=subprocess.PIPE if capture else None,
                     stderr=subprocess.STDOUT if capture else None,
                     check=False, timeout=timeout)
    if check and p.returncode: raise SystemExit(p.stdout or f"failed: {args}")
    return p

def root():
    if os.getenv("INTEL_XR_ROOT"): return pathlib.Path(os.environ["INTEL_XR_ROOT"]).resolve()
    for start in (pathlib.Path.cwd(), pathlib.Path(__file__).resolve().parent):
        for p in (start,*start.parents):
            if p.name=="intel-xr-prototype": return p
    raise SystemExit("ERROR: cannot locate intel-xr-prototype; set INTEL_XR_ROOT")

ROOT=root(); REPO=ROOT/"src/Monado-ALVR"; LOG=ROOT/"logs"; LOG.mkdir(parents=True,exist_ok=True)
stamp=time.strftime("%Y-%m-%d_%H-%M-%S"); out=LOG/f"{stamp}_video-path-diagnostic.log"
lines=[]
def note(s=""): print(s); lines.append(s)
def cmd(args):
    p=run(args); text=(p.stdout or "").rstrip(); lines.append("$ "+" ".join(map(str,args))+"\n"+text); return p,text

note(f"Intel XR one-shot video diagnostic | root={ROOT}")
adb=shutil.which("adb"); tcpdump=shutil.which("tcpdump")
if not adb: raise SystemExit("ERROR: adb not found")
_,state=cmd([adb,"get-state"])
if "device" not in state: raise SystemExit("ERROR: no authorized ADB device")

# Wake and fresh-launch the matched client.
cmd([adb,"shell","input","keyevent","KEYCODE_WAKEUP"]); time.sleep(1)
cmd([adb,"shell","am","force-stop","alvr.client.monado"]); time.sleep(1)
cmd([adb,"logcat","-c"])
_,launch=cmd([adb,"shell","monkey","-p","alvr.client.monado","-c","android.intent.category.LAUNCHER","1"])
if "Events injected: 1" not in launch:
    note("[Quest launch] monkey did not confirm launch")

pid=""
for _ in range(15):
    _,p=cmd([adb,"shell","pidof","alvr.client.monado"])
    pid=p.strip()
    if pid: break
    time.sleep(1)

if not pid:
    _,resolved=cmd([adb,"shell","cmd","package","resolve-activity","--brief","alvr.client.monado"])
    component=resolved.strip().splitlines()[-1] if resolved.strip() else "alvr.client.monado/android.app.NativeActivity"
    note(f"[Quest launch fallback] {component}")
    cmd([adb,"shell","am","start","-W","-n",component])
    for _ in range(10):
        _,p=cmd([adb,"shell","pidof","alvr.client.monado"])
        pid=p.strip()
        if pid: break
        time.sleep(1)

_,power=cmd([adb,"shell","dumpsys","power"])
wake=re.search(r"mWakefulness=(\\w+)",power); note(f"[Quest power] {wake.group(1) if wake else 'Unknown'}")
note(f"[Quest PID] {pid or 'missing'}")
if not pid:
    _,activities=cmd([adb,"shell","dumpsys","activity","activities"])
    lines.append("=== QUEST ACTIVITY ON LAUNCH FAILURE ===\\n"+"\\n".join(x for x in activities.splitlines() if "alvr.client.monado" in x)[-6000:])
    out.write_text("\\n".join(lines)+"\\n",encoding="utf-8")
    raise SystemExit(f"ERROR: ALVR client did not start after launch retries. Log: {out}")

# Start our deterministic OpenXR color source.
test=REPO/"scripts/run-video-test.sh"
proc=subprocess.Popen(["bash",str(test)],cwd=REPO,text=True,encoding="utf-8",
                      stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
time.sleep(8)
if proc.poll() is not None:
    txt=proc.stdout.read() if proc.stdout else ""; lines.append(txt); out.write_text("\n".join(lines),encoding="utf-8")
    raise SystemExit(f"ERROR: video test exited early ({proc.returncode}). Log: {out}")
note(f"[OpenXR test] running pid={proc.pid}")

# Capture outbound ALVR traffic. sudo -n intentionally avoids hanging for a password.
iface=os.getenv("XR_WIFI_DEV","wlx9cefd5fa3634")
quest=os.getenv("QUEST_IP","192.168.86.168")
pc=os.getenv("XR_PC_IP","192.168.86.151")
packets=0
if tcpdump:
    p=run(["sudo","-n","timeout","5","tcpdump","-qn","-i",iface,
           f"src host {pc} and dst host {quest} and udp port 9944"],timeout=8)
    m=re.search(r"(\d+) packets captured",p.stdout or "")
    packets=int(m.group(1)) if m else 0
    lines.append(p.stdout or "")
note(f"[PC -> Quest UDP/9944] {packets} packets captured")

# Collect Quest video logs. Prefer explicit client instrumentation when present.
p=run([adb,"logcat","-d","-v","time",f"--pid={pid}"])
raw=p.stdout or ""
explicit=[x for x in raw.splitlines() if "[INTEL-XR-VIDEO]" in x]
fallback_pat=re.compile(r"decoder|mediacodec|codec|\\bnal\\b|\\bidr\\b|video|frame.*received|frame.*decoded|surface|swapchain|csd|\\bsps\\b|\\bpps\\b|\\bvps\\b|stream starting|connected to server",re.I)
fallback=[x for x in raw.splitlines() if fallback_pat.search(x)]
video_logs=explicit if explicit else fallback
lines.append("=== QUEST VIDEO LOGS ===\\n"+"\\n".join(video_logs[-400:]))
note(f"[Quest explicit video events] {len(explicit)}")
if not explicit:
    note(f"[Quest fallback video log matches] {len(fallback)}")
    note("[Instrumentation] NOT PRESENT — checkpoint results below are UNKNOWN until the Quest APK contains [INTEL-XR-VIDEO] logging.")

def marked(*terms):
    if not explicit: return None
    return any(all(t.lower() in line.lower() for t in terms) for line in explicit)

checks=[
 ("Quest video packets", marked("packet","received")),
 ("Complete encoded frame", marked("complete","frame")),
 ("Codec config", marked("codec","config")),
 ("Keyframe/IDR", True if marked("idr") else (True if marked("keyframe") else False) if explicit else None),
 ("Decoder created", True if marked("decoder","created") else (True if marked("decoder","create","success") else False) if explicit else None),
 ("Decoder configured", marked("decoder","configured")),
 ("Decoder started", marked("decoder","started")),
 ("Decoder input", True if marked("decoder","input") else (True if marked("submitted","decoder") else False) if explicit else None),
 ("Decoder output", marked("decoder","output")),
 ("Displayed/presented frame", True if marked("presented","frame") else (True if marked("displayed","frame") else False) if explicit else None),
]
for name,value in checks:
    note(f"[{name}] "+("YES" if value is True else "NO" if value is False else "UNKNOWN"))

breakpoint=next((name for name,value in checks if value is False),None) if explicit else None
note(f"[VIDEO PATH BREAK] {breakpoint if breakpoint else 'UNKNOWN' if not explicit else 'none observed'}")

# State from ALVR registry.
p=run(["curl","-fsS","-H","X-ALVR: 1","http://127.0.0.1:8082/api/xr/clients"])
try:
    reg=json.loads(p.stdout or "{}"); matches=reg.get("clients",{})
    q=next((v for k,v in matches.items() if v.get("current_ip")==quest or k=="direct-"+quest),{})
    note(f"[ALVR state] {q.get('connection_state','Unknown')}")
except Exception: note("[ALVR state] unreadable")

# Stop only our local test process.
proc.terminate()
try: proc.wait(timeout=3)
except subprocess.TimeoutExpired: proc.kill()

# Classification. Explicit instrumentation wins; generic logs are never treated as decoder proof.
if explicit and breakpoint:
    verdict=f"EXPLICIT QUEST VIDEO INSTRUMENTATION FOUND; FIRST FAILED CHECKPOINT: {breakpoint}."
elif explicit:
    verdict="EXPLICIT QUEST VIDEO INSTRUMENTATION FOUND; no failed checkpoint observed in this sample."
elif packets>0:
    verdict="NETWORK VIDEO TRAFFIC PRESENT; QUEST VIDEO CHECKPOINTS UNKNOWN because instrumented APK is not installed yet."
else:
    verdict="NO PC→QUEST VIDEO TRAFFIC OBSERVED; inspect server encode/forward path or capture interface."
note("[Verdict] "+verdict)
out.write_text("\\n".join(lines)+"\\n",encoding="utf-8")
note(f"[Log] {out}")
