#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unattended Intel XR Quest/Monado video-path diagnostic."""
from __future__ import annotations
import json, os, pathlib, re, shutil, subprocess, sys, time

def run(args, *, timeout=None, binary=False):
    kw={"stdout":subprocess.PIPE,"stderr":subprocess.STDOUT,"check":False,"timeout":timeout}
    if not binary: kw.update(text=True,encoding="utf-8",errors="replace")
    return subprocess.run(args,**kw)

def root():
    if os.getenv("INTEL_XR_ROOT"): return pathlib.Path(os.environ["INTEL_XR_ROOT"]).resolve()
    for start in (pathlib.Path.cwd(),pathlib.Path(__file__).resolve().parent):
        for p in (start,*start.parents):
            if p.name=="intel-xr-prototype": return p
    raise SystemExit("ERROR: cannot locate intel-xr-prototype; set INTEL_XR_ROOT")

ROOT=root(); REPO=ROOT/"src/Monado-ALVR"; LOG=ROOT/"logs"; LOG.mkdir(parents=True,exist_ok=True)
stamp=time.strftime("%Y-%m-%d_%H-%M-%S")
out=LOG/f"{stamp}_video-path-diagnostic.log"
lines=[]
def note(s=""): print(s,flush=True); lines.append(s)
def cmd(args):
    p=run(args); txt=(p.stdout or "").rstrip(); lines.append("$ "+" ".join(map(str,args))+"\n"+txt); return p,txt

adb=shutil.which("adb"); tcpdump=shutil.which("tcpdump")
if not adb: raise SystemExit("ERROR: adb not found")
note(f"Intel XR unattended diagnostic | root={ROOT}")
_,state=cmd([adb,"get-state"])
if "device" not in state: raise SystemExit("ERROR: no authorized ADB device")

# Fresh launch. User can now keep the headset on for the whole experiment.
cmd([adb,"shell","input","keyevent","KEYCODE_WAKEUP"])
cmd([adb,"shell","am","force-stop","alvr.client.monado"]); time.sleep(1)
cmd([adb,"logcat","-c"])
# Clear completion marker from any prior diagnostic.
cmd([adb,"shell","rm","-f","/sdcard/intel-xr-diagnostic.done"])
_,launch=cmd([adb,"shell","monkey","-p","alvr.client.monado","-c","android.intent.category.LAUNCHER","1"])
pid=""
for _ in range(20):
    _,p=cmd([adb,"shell","pidof","alvr.client.monado"]); pid=p.strip()
    if pid: break
    time.sleep(.5)
if not pid: raise SystemExit("ERROR: ALVR client did not start")
note(f"[Quest PID] {pid}")

def lifecycle_snapshot(label):
    _,power=cmd([adb,"shell","dumpsys","power"])
    m=re.search(r"mWakefulness=(\w+)",power)
    _,acts=cmd([adb,"shell","dumpsys","activity","activities"])
    focused=("ResumedActivity:" in acts and "alvr.client.monado/android.app.NativeActivity" in acts)
    note(f"[{label} power] {m.group(1) if m else 'Unknown'}")
    note(f"[{label} ALVR resumed] {'YES' if focused else 'NO'}")
    return focused

initial_focus=lifecycle_snapshot("Before test")

# Allow lobby/HUD to settle before starting PC OpenXR application.
note("[Countdown] starting OpenXR checkerboard in 3 seconds; keep headset worn")
time.sleep(3)
test=REPO/"scripts/run-video-test.sh"
proc=subprocess.Popen(["bash",str(test)],cwd=REPO,text=True,encoding="utf-8",
                      stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
time.sleep(6)
if proc.poll() is not None:
    txt=proc.stdout.read() if proc.stdout else ""
    lines.append("=== OPENXR TEST OUTPUT ===\n"+txt)
    out.write_text("\n".join(lines)+"\n",encoding="utf-8")
    raise SystemExit(f"ERROR: OpenXR test exited early ({proc.returncode}); log={out}")
note(f"[OpenXR test] running pid={proc.pid}")

# Capture three timed Android screenshots without taking the headset off.
shots=[]
def screenshot(seq):
    remote=f"/sdcard/intel-xr-diag-{seq}.png"
    local=LOG/f"{stamp}_{seq}_quest-screen.png"
    run([adb,"shell","rm","-f",remote])
    cap=run([adb,"shell","screencap","-p",remote])
    pull=run([adb,"pull",remote,str(local)]) if cap.returncode==0 else cap
    run([adb,"shell","rm","-f",remote])
    if pull.returncode==0 and local.exists():
        data=local.read_bytes()
        # Accept PNG by actual signature. Keep unexpected bytes for inspection.
        if data[:8]==bytes.fromhex("89504e470d0a1a0a"):
            note(f"[Screenshot {seq}] {local} ({len(data)} bytes)")
            shots.append(local); return
        raw=local.with_suffix(".capture"); local.replace(raw)
        note(f"[Screenshot {seq}] unknown format ({len(data)} bytes header={data[:16].hex()}) kept={raw}")
        shots.append(raw); return
    note(f"[Screenshot {seq}] FAILED")

screenshot("01")
time.sleep(2); screenshot("02")

# Network sample while app remains running.
iface=os.getenv("XR_WIFI_DEV","wlx9cefd5fa3634"); quest=os.getenv("QUEST_IP","192.168.86.168"); pc=os.getenv("XR_PC_IP","192.168.86.151")
packets=0
if tcpdump:
    p=run(["sudo","-n","timeout","5","tcpdump","-qn","-i",iface,
           f"src host {pc} and dst host {quest} and udp port 9944"],timeout=8)
    lines.append("=== TCPDUMP ===\n"+(p.stdout or ""))
    m=re.search(r"(\d+) packets captured",p.stdout or ""); packets=int(m.group(1)) if m else 0
note(f"[PC -> Quest UDP/9944] {packets} packets captured")
screenshot("03")

final_focus=lifecycle_snapshot("After test")

# Collect process-specific markers plus system lifecycle/doff evidence.
p=run([adb,"logcat","-d","-v","time",f"--pid={pid}"]); raw=p.stdout or ""
markers=[x for x in raw.splitlines() if "[INTEL-XR-" in x]
lines.append("=== INTEL XR MARKERS ===\n"+"\n".join(markers[-1000:]))
syslog=run([adb,"logcat","-d","-v","time"]).stdout or ""
doff_lines=[x for x in syslog.splitlines() if re.search(r"DOFF|TOP_SLEEPING|activity paused during WaitFrame|onActivityPaused|XR_SESSION_STATE_.*STOPPING",x,re.I)]
lines.append("=== DOFF / FOCUS EVIDENCE ===\n"+"\n".join(doff_lines[-250:]))
doff=bool(doff_lines)
note(f"[Headset remained FOCUSED] {'YES' if initial_focus and final_focus and not doff else 'NO'}")
note(f"[DOFF detected] {'YES' if doff else 'NO'}")

video=[x for x in markers if "[INTEL-XR-VIDEO]" in x]
def has(*terms): return any(all(t.lower() in x.lower() for t in terms) for x in video)
checks=[
 ("Streaming started",has("STREAMING_STARTED")),
 ("Codec config",has("DECODER_CONFIG")),
 ("Decoder create begun",has("DECODER_CREATE_BEGIN")),
 ("MediaCodec created",has("MEDIACODEC_CREATE")),
 ("MediaCodec configured",has("MEDIACODEC_CONFIGURED")),
 ("MediaCodec started",has("MEDIACODEC_STARTED")),
 ("Decoder input",has("MEDIACODEC_INPUT") or has("DECODER_INPUT")),
 ("Decoder output",has("MEDIACODEC_OUTPUT") or has("DECODER_OUTPUT")),
 ("ImageReader frame",has("IMAGE_READER_FRAME")),
 ("Stream rendered decoded frame",has("STREAM_RENDER decoded_frame")),
]
for name,val in checks: note(f"[{name}] {'YES' if val else 'NO'}")
breakpoint=next((name for name,val in checks if not val),None)
note(f"[VIDEO PATH BREAK] {breakpoint or 'none observed'}")

p=run(["curl","-fsS","-H","X-ALVR: 1","http://127.0.0.1:8082/api/xr/clients"])
try:
    reg=json.loads(p.stdout or "{}"); clients=reg.get("clients",{})
    q=next((v for k,v in clients.items() if v.get("current_ip")==quest or k=="direct-"+quest),{})
    note(f"[ALVR state] {q.get('connection_state','Unknown')}")
except Exception: note("[ALVR state] unreadable")

proc.terminate()
try: proc.wait(timeout=3)
except subprocess.TimeoutExpired: proc.kill()

if doff:
    verdict="TEST CONTAMINATED BY HEADSET DOFF/SLEEP; rerun while continuously worn."
elif not initial_focus or not final_focus:
    verdict="QUEST CLIENT DID NOT REMAIN RESUMED/FOCUSED."
elif breakpoint:
    verdict=f"FIRST MISSING EXPLICIT VIDEO CHECKPOINT: {breakpoint}."
else:
    verdict="ALL INSTRUMENTED VIDEO CHECKPOINTS OBSERVED."
note("[Verdict] "+verdict)

# Signal the Quest client only after all evidence has been collected.
cmd([adb,"shell","touch","/sdcard/intel-xr-diagnostic.done"])
note("[Headset message] TEST COMPLETE - YOU MAY REMOVE HEADSET")
time.sleep(3)
out.write_text("\n".join(lines)+"\n",encoding="utf-8")
note(f"[Log] {out}")
for p in shots: note(f"[Screenshot] {p}")
