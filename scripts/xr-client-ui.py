#!/usr/bin/env python3
import json, os, re, time, urllib.request, subprocess, tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
API=os.environ.get("ALVR_API","http://127.0.0.1:8082")
PORT=int(os.environ.get("XR_CLIENT_UI_PORT","8083"))
CONFIG="/ai/intel-xr-prototype/src/Monado-ALVR/config/xr-build.json"
EDITABLE={
 "paths.root":str,"paths.android_home":str,"paths.java_home":str,
 "android.ndk_version":str,"android.rust_target":str,"android.platform_api":int,
 "android.openxr_sdk_repo":str,"android.openxr_sdk_ref":str,"android.usb_stay_awake":bool,
 "alvr.legacy_protocol_test":bool,
 "network.quest_ip":str,"network.direct_ip_fallback":bool,"network.mdns":bool,
 "network.legacy_udp":bool,"network.usb":bool,
 "video.test_pattern":bool,"video.test_pattern_mode":str,
}
SHOTS_DIR="/ai/intel-xr-prototype/logs/headset-screenshots"
QUEST_SHOTS="/sdcard/Oculus/Screenshots"
QUEST_VIDEOS="/sdcard/Oculus/VideoShots"
SHOT_NAME=re.compile(r"^[A-Za-z0-9._-]+\.(jpg|png|mp4)$")
ADB=__import__("shutil").which("adb") or "/ai/android-sdk/platform-tools/adb"
def adb(*args,timeout=20):
    return subprocess.run([ADB,*args],capture_output=True,text=True,timeout=timeout)
def quest_serial():
    # First attached device that has the Quest system capture service (skips phones).
    for line in adb("devices").stdout.splitlines()[1:]:
        bits=line.split()
        if len(bits)>=2 and bits[1]=="device":
            if "package:" in adb("-s",bits[0],"shell","pm","path","com.oculus.metacam").stdout:
                return bits[0]
    raise RuntimeError("No Quest connected over ADB (USB or ADB over Wi-Fi)")
def quest_shots(serial,folder=QUEST_SHOTS):
    out=adb("-s",serial,"shell","ls","-t",folder).stdout.split()
    return [x for x in out if SHOT_NAME.match(x)]
CAPTURE_SERVICE="com.oculus.metacam/.capture.CaptureService"
recording={"serial":None,"before":set()}
def start_headset_recording():
    serial=quest_serial()
    recording["serial"]=serial
    recording["before"]=set(quest_shots(serial,QUEST_VIDEOS))
    # Horizon OS action names (START_CAPTURE/STOP_CAPTURE are rejected as invalid).
    adb("-s",serial,"shell","am","startservice","-n",CAPTURE_SERVICE,"-a","START_INTERNAL_CAPTURE_TO_DISK")
def stop_headset_recording():
    serial=recording["serial"] or quest_serial()
    adb("-s",serial,"shell","am","startservice","-n",CAPTURE_SERVICE,"-a","STOP_INTERNAL_CAPTURE_TO_DISK")
    for _ in range(60):
        time.sleep(0.5)
        new=[x for x in quest_shots(serial,QUEST_VIDEOS) if x not in recording["before"]]
        if new:
            time.sleep(1.0)  # let the muxer finalize the MP4
            os.makedirs(SHOTS_DIR,exist_ok=True)
            res=adb("-s",serial,"pull",QUEST_VIDEOS+"/"+new[0],os.path.join(SHOTS_DIR,new[0]),timeout=300)
            if res.returncode!=0: raise RuntimeError(res.stderr.strip() or "adb pull failed")
            recording["serial"]=None
            return new[0]
    raise RuntimeError("No recording was saved (was recording started? is the headset awake?)")
def take_headset_screenshot():
    serial=quest_serial()
    before=set(quest_shots(serial))
    adb("-s",serial,"shell","am","startservice","-n","com.oculus.metacam/.capture.CaptureService","-a","TAKE_SCREENSHOT")
    for _ in range(40):
        time.sleep(0.25)
        new=[x for x in quest_shots(serial) if x not in before]
        if new:
            time.sleep(0.5)  # let the capture finish writing
            os.makedirs(SHOTS_DIR,exist_ok=True)
            res=adb("-s",serial,"pull",QUEST_SHOTS+"/"+new[0],os.path.join(SHOTS_DIR,new[0]),timeout=60)
            if res.returncode!=0: raise RuntimeError(res.stderr.strip() or "adb pull failed")
            return new[0]
    raise RuntimeError("Headset did not produce a screenshot (is it awake?)")
def list_shots():
    if not os.path.isdir(SHOTS_DIR): return []
    names=[x for x in os.listdir(SHOTS_DIR) if SHOT_NAME.match(x)]
    return sorted(names,key=lambda x: os.path.getmtime(os.path.join(SHOTS_DIR,x)),reverse=True)[:24]
def config_load(): return json.load(open(CONFIG))
def config_save(data):
    tmp=CONFIG+".tmp"
    with open(tmp,"w") as x: json.dump(data,x,indent=2); x.write("\n")
    os.replace(tmp,CONFIG)
def set_path(obj,path,value):
    cur=obj
    bits=path.split(".")
    for b in bits[:-1]: cur=cur[b]
    cur[bits[-1]]=value
def req(path, method="GET", data=None):
    body=None if data is None else json.dumps(data).encode()
    r=urllib.request.Request(API+path,data=body,method=method,headers={"X-ALVR":"1","Content-Type":"application/json"})
    with urllib.request.urlopen(r,timeout=3) as x:return x.read()
PAGE="""<!doctype html><meta charset=utf-8><title>Intel XR Clients</title>
<meta name=viewport content="width=device-width,initial-scale=1">
<style>
:root{color-scheme:light dark;--bg:#f6f7f9;--fg:#15171a;--card:#fff;--line:#c9ced6;--accent:#2457d6;--danger:#b3261e}
@media (prefers-color-scheme:dark){:root{--bg:#121417;--fg:#e8eaed;--card:#1d2025;--line:#3a3f47;--accent:#7aa2ff;--danger:#ff8a80}}
*{box-sizing:border-box}
body{font:18px/1.45 system-ui,sans-serif;margin:0;padding:12px 16px 48px;background:var(--bg);color:var(--fg)}
h1{font-size:1.5rem;margin:8px 0 12px}h2{font-size:1.2rem;margin:24px 0 8px}
#stack,.card,section{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin:10px 0}
button,input,select{font:inherit;width:100%;min-height:56px;margin:6px 0;padding:12px 16px;border-radius:12px;border:1px solid var(--line);background:var(--card);color:var(--fg)}
button{background:var(--accent);color:#fff;border:0;font-weight:600;cursor:pointer}
button:active{transform:scale(.98)}
button.danger{background:var(--danger)}
pre{background:var(--bg);padding:12px;border-radius:8px;overflow-x:auto;font-size:.85rem}
#appmsg,#setmsg,#msg{display:block;min-height:1.4em;font-size:.95rem}
@media (min-width:720px){body{max-width:960px;margin:0 auto}button{width:auto;min-width:200px;margin:6px 8px 6px 0}input,select{width:auto;min-width:320px}}
</style>
<h1>Intel XR Clients</h1><div id=stack>Checking stack...</div>
<section><h2>Headset capture</h2><p>Screenshots and video (with audio) of what the headset wearer sees (any app). Needs ADB (USB or ADB over Wi-Fi). Saved to <code>logs/headset-screenshots/</code>.</p><button onclick="shot()">Take headset screenshot</button><button onclick="rec('start')">Start recording</button><button class=danger onclick="rec('stop')">Stop recording</button><span id=shotmsg></span><div id=shots></div></section>
<section><h2>Test app</h2><button onclick="app('start')">Start test app</button><button onclick="app('stop')">Exit test app</button><button class=danger onclick="app('stop-all')">Exit app + stop runtime</button><span id=appmsg></span></section><p>Default policy: <b>auto-accept protocol-valid ALVR clients</b>.</p>
<h2>Settings</h2><p>Edit any item in <code>config/xr-build.json</code>.</p><select id=settingSelect onchange="showSetting()"><option value="">Select a setting...</option></select><span id=settingEditor></span><button onclick="saveSelectedSetting()">Update setting</button><button onclick="service('restart')">Restart services</button><button class=danger onclick="if(confirm('Rebuild runs build-intel-xr.sh, which resets alvr_render (reset --hard) and checks ALVR out at a pinned old revision, discarding the companion fixes. Continue?'))service('rebuild')">Rebuild runtime (destructive)</button><span id=setmsg></span><h2>Approved MAC devices</h2><input id=file type=file accept=".json,.xlsx"><button onclick="upload()">Import JSON/XLSX</button><pre id=approved></pre>
<h2>ALVR clients</h2><button onclick="clearClients()">Clear client cache</button><span id=msg></span><div id=x>Loading...</div>
<script>
async function stackStatus(){try{let r=await fetch('/api/status');let j=await r.json();stack.innerHTML='<b>Runtime:</b> '+j.runtime+' &nbsp; <b>API:</b> '+j.api+' &nbsp; <b>Test app:</b> '+j.app+' &nbsp; <b>UI:</b> READY'}catch(e){stack.textContent='Stack status unavailable: '+e}}
async function shot(){shotmsg.textContent=' Capturing...';try{let r=await fetch('/api/headset/screenshot',{method:'POST'});let j=await r.json();shotmsg.textContent=' '+(r.ok?'Saved '+j.file:'Failed: '+(j.error||r.status));loadShots()}catch(e){shotmsg.textContent=' Failed: '+e}}
async function rec(a){shotmsg.textContent=a=='start'?' Starting recording...':' Stopping and downloading...';try{let r=await fetch('/api/headset/recording/'+a,{method:'POST'});let j=await r.json();shotmsg.textContent=' '+(r.ok?(j.file?'Saved '+j.file:'Recording...'):'Failed: '+(j.error||r.status));loadShots()}catch(e){shotmsg.textContent=' Failed: '+e}}
async function loadShots(){try{let r=await fetch('/api/headset/screenshots');let j=await r.json();shots.innerHTML=(j.files||[]).map(f=>(f.endsWith('.mp4')?'<video src="/shots/'+f+'" controls preload=metadata style="width:100%;max-width:420px;border-radius:8px;margin:6px 0"></video>':'<a href="/shots/'+f+'" target=_blank><img src="/shots/'+f+'" alt="'+f+'" loading=lazy style="width:100%;max-width:420px;border-radius:8px;margin:6px 0"></a>')+'<div style="font-size:.8rem">'+f+'</div>').join('')}catch(e){}}
async function app(a){appmsg.textContent=' '+a+'...';try{let r=await fetch('/api/app/'+a,{method:'POST'});let j=await r.json();appmsg.textContent=' '+(r.ok?j.message:'Failed: '+(j.error||r.status))}catch(e){appmsg.textContent=' Failed: '+e}stackStatus()}
async function service(a){setmsg.textContent=' '+a+'...';let r=await fetch('/api/service/'+a,{method:'POST'});let j=await r.json();setmsg.textContent=r.ok?' '+j.message:' Failed: '+(j.error||r.status);stackStatus();load()}
let configValues={};
async function loadSettings(){try{let r=await fetch('/api/config',{cache:'no-store'});let j=await r.json();if(!r.ok)throw Error(j.error||r.status);configValues=j.values||{};let sel=document.getElementById('settingSelect');sel.replaceChildren(new Option('Select a setting...',''));for(let k of Object.keys(configValues).sort())sel.add(new Option(k,k));document.getElementById('settingEditor').innerHTML='';document.getElementById('setmsg').textContent=' Loaded '+Object.keys(configValues).length+' settings.'}catch(e){document.getElementById('setmsg').textContent=' Config error: '+e}}
function showSetting(){let k=settingSelect.value;if(!k){settingEditor.innerHTML='';return}let v=configValues[k];if(typeof v==='boolean'){settingEditor.innerHTML='<label><input id=settingValue type=checkbox '+(v?'checked':'')+'> '+String(v)+'</label>'}else{settingEditor.innerHTML='<input id=settingValue style="min-width:360px" value="'+String(v).replaceAll('"','&quot;')+'">'}}
async function saveSelectedSetting(){let k=settingSelect.value;if(!k){setmsg.textContent=' Select a setting first.';return}let el=document.getElementById('settingValue');let v=el.type==='checkbox'?el.checked:el.value;setmsg.textContent=' Saving...';let r=await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({[k]:v})});let j=await r.json();if(r.ok){configValues[k]=v;setmsg.textContent=' Saved '+k+'. '+j.action;showSetting()}else setmsg.textContent=' Save failed: '+(j.error||r.status)}
function esc(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
async function load(){try{let r=await fetch('/api/clients');let j=await r.json();if(!r.ok)throw Error(j.error||r.status);let ar=await fetch('/api/approved');let a=await ar.json();approved.textContent=JSON.stringify(a,null,2);let h='<p>Auto-accept: <b>'+(j.auto_accept?'ON':'OFF')+'</b></p>';for(const [n,c] of Object.entries(j.clients||{})){h+='<div class=card><b>'+n+'</b><pre>'+JSON.stringify(c,null,2)+'</pre><button data-name="'+esc(n)+'" data-act="Trust" onclick="act(this.dataset.name,this.dataset.act)">Approve</button><button data-name="'+esc(n)+'" data-act="RemoveEntry" onclick="act(this.dataset.name,this.dataset.act)">Reject / Forget</button></div>'}x.innerHTML=h||'No clients';msg.textContent=''}catch(e){x.innerHTML='<b>API error:</b> '+e;msg.textContent=''}}
async function act(n,a){await fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify([n,a])});load()}
async function clearClients(){if(!confirm('Clear cached ALVR client entries? Approved MAC devices are preserved.'))return;msg.textContent=' Clearing...';try{let r=await fetch('/api/clients/clear',{method:'POST'});let t=await r.text();if(!r.ok)throw Error(t||r.status);msg.textContent=' Client cache cleared.';await load()}catch(e){msg.textContent=' Clear failed: '+e}}
async function upload(){let f=file.files[0];if(!f)return;let r=await fetch('/api/approved/import',{method:'POST',headers:{'X-Filename':f.name},body:await f.arrayBuffer()});if(!r.ok)alert(await r.text());load()}
stackStatus();loadSettings();load();loadShots();setInterval(()=>{stackStatus();load()},3000)
</script>"""
class H(BaseHTTPRequestHandler):
    def log_message(self,*a):pass
    def sendx(self,code,body,typ="application/json"):
        self.send_response(code);self.send_header("Content-Type",typ);self.end_headers();self.wfile.write(body)
    def do_GET(self):
        if self.path=="/":return self.sendx(200,PAGE.encode(),"text/html; charset=utf-8")
        if self.path=="/api/headset/screenshots":
            return self.sendx(200,json.dumps({"files":list_shots()}).encode())
        if self.path.startswith("/shots/"):
            name=self.path[len("/shots/"):]
            path=os.path.join(SHOTS_DIR,name)
            if not SHOT_NAME.match(name) or not os.path.isfile(path): return self.sendx(404,b"{}")
            with open(path,"rb") as f: data=f.read()
            typ="video/mp4" if name.endswith(".mp4") else "image/png" if name.endswith(".png") else "image/jpeg"
            return self.sendx(200,data,typ)
        if self.path=="/api/status":
            runtime=subprocess.run(["systemctl","--user","is-active","intel-xr-monado.service"],capture_output=True,text=True).stdout.strip()
            try:req("/api/ping"); api="READY"
            except Exception:api="DOWN"
            app=subprocess.run(["pgrep","-x","intel_xr_checke"],capture_output=True,text=True).stdout.strip()
            return self.sendx(200,json.dumps({"runtime":runtime or "unknown","api":api,"app":"RUNNING" if app else "STOPPED"}).encode())
        if self.path=="/api/config":
            try:
                cfg=config_load(); vals={}
                for key in EDITABLE:
                    cur=cfg
                    for bit in key.split("."): cur=cur[bit]
                    vals[key]=cur
                return self.sendx(200,json.dumps({"values":vals}).encode())
            except Exception as e:return self.sendx(500,json.dumps({"error":str(e)}).encode())
        if self.path=="/api/approved":
            try:
                out=subprocess.check_output(["/usr/bin/python3","/ai/intel-xr-prototype/src/Monado-ALVR/scripts/xr-approved-devices.py","list"])
                return self.sendx(200,out)
            except Exception as e:return self.sendx(502,json.dumps({"error":str(e)}).encode())
        if self.path=="/api/clients":
            try:return self.sendx(200,req("/api/xr/clients"))
            except Exception as e:
                # Keep the UI usable if the enhanced registry endpoint is absent
                # or temporarily unavailable. Session clients are the fallback.
                try:
                    raw=req("/api/session")
                    session=json.loads(raw)
                    clients=session.get("client_connections",session.get("clients",{}))
                    return self.sendx(200,json.dumps({"auto_accept":False,"clients":clients,"source":"session-fallback","registry_error":str(e)}).encode())
                except Exception as e2:return self.sendx(502,json.dumps({"error":str(e),"fallback_error":str(e2)}).encode())
        self.sendx(404,b"{}")
    def do_POST(self):
        if self.path=="/api/headset/recording/start":
            try:start_headset_recording();return self.sendx(200,json.dumps({"recording":True}).encode())
            except Exception as e:return self.sendx(500,json.dumps({"error":str(e)}).encode())
        if self.path=="/api/headset/recording/stop":
            try:return self.sendx(200,json.dumps({"file":stop_headset_recording()}).encode())
            except Exception as e:return self.sendx(500,json.dumps({"error":str(e)}).encode())
        if self.path=="/api/headset/screenshot":
            try:return self.sendx(200,json.dumps({"file":take_headset_screenshot()}).encode())
            except Exception as e:return self.sendx(500,json.dumps({"error":str(e)}).encode())
        if self.path in ("/api/app/start","/api/app/stop","/api/app/stop-all"):
            action=self.path.rsplit("/",1)[1]
            try:
                out=subprocess.run(["bash","/ai/intel-xr-prototype/src/Monado-ALVR/scripts/xr-app.sh",action],capture_output=True,text=True,timeout=90)
                msg=(out.stdout.strip() or out.stderr.strip()).splitlines()
                code=200 if out.returncode==0 else 500
                return self.sendx(code,json.dumps({"message":" ".join(msg[-2:]),"error":out.stderr.strip()}).encode())
            except Exception as e:return self.sendx(500,json.dumps({"error":str(e)}).encode())
        if self.path in ("/api/service/restart","/api/service/rebuild"):
            try:
                if self.path.endswith("restart"):
                    subprocess.Popen(["bash","/ai/intel-xr-prototype/src/Monado-ALVR/scripts/monado-service.sh","restart"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                    return self.sendx(202,json.dumps({"message":"Restart requested."}).encode())
                subprocess.Popen(["bash","/ai/intel-xr-prototype/src/Monado-ALVR/scripts/build-intel-xr.sh"],stdout=open("/ai/intel-xr-prototype/logs/webui-build.log","ab"),stderr=subprocess.STDOUT)
                return self.sendx(202,json.dumps({"message":"Build started; progress is logged to logs/webui-build.log."}).encode())
            except Exception as e:return self.sendx(500,json.dumps({"error":str(e)}).encode())
        if self.path=="/api/config":
            try:
                raw=json.loads(self.rfile.read(int(self.headers.get("Content-Length","0"))))
                cfg=config_load()
                for key,val in raw.items():
                    if key not in EDITABLE: raise ValueError("setting not editable: "+key)
                    typ=EDITABLE[key]
                    if typ is bool: parsed=bool(val)
                    elif typ is int: parsed=int(val)
                    else: parsed=str(val)
                    set_path(cfg,key,parsed)
                config_save(cfg)
                return self.sendx(200,json.dumps({"saved":True,"action":"Runtime/network changes may require service restart; toolchain/version changes require rebuild."}).encode())
            except Exception as e:return self.sendx(400,json.dumps({"error":str(e)}).encode())
        if self.path=="/api/clients/clear":
            try:
                clients=json.loads(req("/api/xr/clients")).get("clients",{})
                errors=[]
                for name in list(clients):
                    try:req("/api/session/client-connections","POST",[name,"RemoveEntry"])
                    except Exception as e:errors.append(f"{name}: {e}")
                if errors:return self.sendx(502,json.dumps({"errors":errors}).encode())
                return self.sendx(204,b"")
            except Exception as e:return self.sendx(502,json.dumps({"error":str(e)}).encode())
        if self.path=="/api/approved/import":
            try:
                n=int(self.headers.get("Content-Length","0")); raw=self.rfile.read(n)
                typ=self.headers.get("X-Filename","devices.json")
                suffix=".xlsx" if typ.lower().endswith(".xlsx") else ".json"
                with tempfile.NamedTemporaryFile(suffix=suffix,delete=False) as t: t.write(raw); name=t.name
                subprocess.run(["/usr/bin/python3","/ai/intel-xr-prototype/src/Monado-ALVR/scripts/xr-approved-devices.py","import",name],check=True)
                os.unlink(name); return self.sendx(204,b"")
            except Exception as e:return self.sendx(400,json.dumps({"error":str(e)}).encode())

        if self.path!="/api/action":return self.sendx(404,b"{}")
        try:
            data=json.loads(self.rfile.read(int(self.headers.get("Content-Length","0"))))
            req("/api/session/client-connections","POST",data);self.sendx(204,b"")
        except Exception as e:self.sendx(502,json.dumps({"error":str(e)}).encode())
ThreadingHTTPServer(("127.0.0.1",PORT),H).serve_forever()
