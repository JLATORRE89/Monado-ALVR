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
cmd([adb,"shell","monkey","-p","alvr.client.monado","-c","android.intent.category.LAUNCHER","1"])
time.sleep(4)

_,power=cmd([adb,"shell","dumpsys","power"])
wake=re.search(r"mWakefulness=(\w+)",power); note(f"[Quest power] {wake.group(1) if wake else 'Unknown'}")
_,pid=cmd([adb,"shell","pidof","alvr.client.monado"]); pid=pid.strip(); note(f"[Quest PID] {pid or 'missing'}")
if not pid: raise SystemExit("ERROR: ALVR client did not start")

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

# Collect focused decoder lifecycle logs.
p=run([adb,"logcat","-d","-v","time",f"--pid={pid}"])
raw=p.stdout or ""
pat=re.compile(r"decoder|mediacodec|codec|\bnal\b|\bidr\b|video|frame.*received|frame.*decoded|surface|swapchain|csd|\bsps\b|\bpps\b|\bvps\b|stream starting|connected to server",re.I)
decoder=[x for x in raw.splitlines() if pat.search(x)]
lines.append("=== QUEST VIDEO LOGS ===\n"+"\n".join(decoder[-250:]))
note(f"[Quest decoder/video log matches] {len(decoder)}")

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

# Classification, intentionally evidence-based.
decoder_signal=any(re.search(r"decoder|mediacodec|decoded|csd|\bsps\b|\bpps\b|\bvps\b",x,re.I) for x in decoder)
if packets>0 and not decoder_signal:
    verdict="NETWORK VIDEO TRAFFIC PRESENT; DECODER START/CONFIG NOT OBSERVED — inspect Quest receive/config/MediaCodec path."
elif packets>0 and decoder_signal:
    verdict="NETWORK AND DECODER SIGNALS PRESENT — inspect decoded-frame import/OpenXR presentation next."
elif packets==0:
    verdict="NO PC→QUEST VIDEO TRAFFIC OBSERVED — inspect server encode/forward path or capture interface."
else:
    verdict="INCONCLUSIVE."
note("[Verdict] "+verdict)
out.write_text("\n".join(lines)+"\n",encoding="utf-8")
note(f"[Log] {out}")
