#!/usr/bin/env python3
"""Click-through test of the XR Control Panel in headless Chrome (DevTools over pipe).

Exercises every control through the real UI: captures, recording, client launch/close,
test app start/exit/stop-runtime, settings, runtime restart, approved devices, refresh,
offline check. It stops/starts the runtime and the test app; run it with a headset attached
and awake. Usage: XR_PANEL_TEST_SERIAL=<adb serial> python3 test_panel.py
"""
import hashlib
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(__file__))
from cdp import Browser  # noqa: E402

URL = "http://127.0.0.1:8083/"
QUEST = os.environ.get("XR_PANEL_TEST_SERIAL", "1WMHHA42R81461")
SCRATCH = os.environ.get("XR_PANEL_TEST_TMP", "/tmp/xr-panel-test")
os.makedirs(SCRATCH, exist_ok=True)
CONFIG = "/ai/intel-xr-prototype/src/Monado-ALVR/config/xr-build.json"
results = []


def record(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}", flush=True)


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def api(path):
    with urllib.request.urlopen(URL.rstrip("/") + path, timeout=30) as r:
        return json.loads(r.read())


b = Browser(os.path.join(SCRATCH, "cdp-prof"), 412, 900)
b.call("Network.enable", session=True)
b.goto(URL)
b.eval("""(() => { window.__log = []; new MutationObserver(ms => ms.forEach(m => m.addedNodes.forEach(n => {
  if (n.classList && n.classList.contains('toast')) window.__log.push((n.classList.contains('error') ? 'ERR ' : 'OK ') + n.textContent); })))
  .observe(document.getElementById('toasts'), {childList: true}); return 1; })()""")


def wait(expr, timeout=60, interval=0.3):
    deadline = time.time() + timeout
    while time.time() < deadline:
        v = b.eval(expr)
        if v:
            return v
        time.sleep(interval)
    return None


def click_and_toast(selector_js, timeout=60, accept=True):
    b.dialog_answer = accept
    n = b.eval("window.__log.length")
    b.eval(f"({selector_js}).click(), 1")
    msg = wait(f"window.__log.length > {n} && window.__log[{n}]", timeout)
    return msg or "NO TOAST"


def tab(name):
    b.eval(f"document.querySelector('.tabs button[data-tab={name}]').click(), 1")
    time.sleep(0.8)


def card_button(label):
    return (f"[...document.querySelectorAll('#headsets article')].find(a => a.textContent.includes('{QUEST}'))"
            f".querySelector('button') && [...[...document.querySelectorAll('#headsets article')].find(a => a.textContent.includes('{QUEST}'))"
            f".querySelectorAll('button')].find(x => x.textContent.trim() === '{label}')")


# 1 load + status pills
pills = wait("document.querySelectorAll('#pills .pill').length >= 4 && [...document.querySelectorAll('#pills .pill')].map(p => p.textContent).join(' | ')", 20)
record("status pills", bool(pills) and "ADB: ok" in pills and "Runtime: active" in pills, pills or "")

# 2 headsets
cards = wait(f"document.querySelector('#headsets').textContent.includes('{QUEST}') && document.querySelector('#headsets').textContent", 30)
record("headset card (Quest)", bool(cards) and "Battery" in cards, (cards or "")[:160].replace("\n", " "))
record("phone listed as not a Quest", "Not a Quest" in (cards or "") or "0B191FDD4000Q2" not in (cards or ""), "")

# 2b wake (captures need the display on)
if b.eval(f"!!({card_button('Wake')})"):
    msg = click_and_toast(card_button("Wake"), 30)
    awake = False
    for _ in range(20):
        time.sleep(1)
        h = [x for x in api("/api/headsets")["headsets"] if x["serial"] == QUEST][0]
        if h.get("awake"):
            awake = True
            break
    record("wake button", msg.startswith("OK Wake sent") and awake, f"{msg}; awake={awake}")
    time.sleep(3)
else:
    record("wake button", True, "headset already awake (button correctly hidden)")

# 3 screenshot
before = len(api("/api/captures")["captures"])
msg = click_and_toast(card_button("Screenshot"), 30)
after = len(api("/api/captures")["captures"])
record("screenshot button", msg.startswith("OK Screenshot saved") and after == before + 1, f"{msg}; captures {before}->{after}")

# 4 recording
msg = click_and_toast(card_button("Start recording"), 30)
has_stop = wait(f"!!({card_button('Stop recording')})", 15)
record("start recording", msg.startswith("OK Recording started") and bool(has_stop), msg)
time.sleep(4)
msg = click_and_toast(card_button("Stop recording"), 60)
record("stop recording (saved)", msg.startswith("OK Recording saved"), msg)

# 5 captures tab + filter
tab("captures")
n_all = wait("document.querySelectorAll('#captures figure').length", 15) or 0
vids = b.eval("document.querySelectorAll('#captures video').length")
imgs_ok = wait("[...document.querySelectorAll('#captures img')].every(i => i.complete && i.naturalWidth > 0)", 15)
b.eval(f"(() => {{ const s = document.getElementById('captureFilter'); s.value = '{QUEST}'; s.dispatchEvent(new Event('change')); return 1; }})()")
time.sleep(1.5)
n_q = b.eval("document.querySelectorAll('#captures figure').length")
record("captures gallery + filter", n_all >= 2 and vids >= 1 and bool(imgs_ok) and n_q == n_all,
       f"all={n_all} videos={vids} images_loaded={bool(imgs_ok)} filtered={n_q}")

# 6 client close / launch
tab("headsets")
wait(f"!!({card_button('Close client')}) || !!({card_button('Launch client')})", 20)
if b.eval(f"!!({card_button('Close client')})"):
    msg = click_and_toast(card_button("Close client"), 30)
    record("close client (confirm)", msg.startswith("OK Client closed") and bool(b.dialogs), msg)
    wait(f"!!({card_button('Launch client')})", 20)
msg = click_and_toast(card_button("Launch client"), 30)
record("launch client", msg.startswith("OK Client launched"), msg)

# 7 streaming: test app
tab("streaming")
msg = click_and_toast("document.querySelector('[data-app=stop]')", 60)
record("exit test app", msg.startswith("OK ") and "stopped" in msg.lower(), msg)
msg = click_and_toast("document.querySelector('[data-app=start]')", 120)
record("start test app", msg.startswith("OK ") and "started" in msg.lower(), msg)
msg = click_and_toast("document.querySelector('[data-app=stop-all]')", 60)
record("exit app + stop runtime (confirm)", msg.startswith("OK ") and "Runtime stopped" in msg, msg)
msg = click_and_toast("document.querySelector('[data-app=start]')", 180)
record("start test app (restarts runtime)", msg.startswith("OK ") and "started" in msg.lower(), msg)

# 8 ALVR connections (read-only here)
rows = wait("document.querySelectorAll('#clients tr').length", 20) or 0
record("ALVR connections table", rows >= 1, f"rows={rows} badge={b.eval('document.getElementById(\"autoAccept\").textContent')}")

# 9 settings
tab("settings")
opts = wait("document.querySelectorAll('#settingSelect option').length > 1 && document.querySelectorAll('#settingSelect option').length", 15)
record("settings dropdown enumerates", (opts or 0) - 1 == 20, f"options={(opts or 1) - 1}")
h0 = sha(CONFIG)
b.eval("(() => { const s = document.getElementById('settingSelect'); s.value = 'video.test_pattern_mode'; s.dispatchEvent(new Event('change')); return 1; })()")
val = b.eval("document.getElementById('settingValue') && document.getElementById('settingValue').value")
msg = click_and_toast("document.getElementById('saveSetting')", 20)
record("edit+save text setting (unchanged value)", val == "static-bars" and msg.startswith("OK Saved") and sha(CONFIG) == h0, f"value={val}; {msg}")
b.eval("(() => { const s = document.getElementById('settingSelect'); s.value = 'android.usb_stay_awake'; s.dispatchEvent(new Event('change')); return 1; })()")
chk = b.eval("document.getElementById('settingValue').type + ':' + document.getElementById('settingValue').checked")
msg = click_and_toast("document.getElementById('saveSetting')", 20)
record("edit+save bool setting (unchanged value)", chk == "checkbox:true" and msg.startswith("OK Saved") and sha(CONFIG) == h0, f"{chk}; {msg}")

# 10 restart runtime
msg = click_and_toast("document.getElementById('restartRuntime')", 20)
ok = msg.startswith("OK Runtime restart requested")
ready = False
for _ in range(60):
    time.sleep(1)
    try:
        s = api("/api/status")
        if s["runtime"]["service"] == "active" and s["runtime"]["api"] == "ready":
            ready = True
            break
    except Exception:
        pass
record("restart runtime (confirm)", ok and ready, f"{msg}; api ready={ready}")

# 11 approved devices: CSV import, XLSX graceful error, remove
tab("devices")
csv_path = os.path.join(SCRATCH, "panel-test.csv")
open(csv_path, "w").write("MAC Address,Name,Notes\nAA-BB-CC-DD-EE-42,Panel test,delete me\n")
node = b.call("Runtime.evaluate", {"expression": "document.getElementById('importFile')"}, session=True)["result"]["objectId"]
b.call("DOM.enable", session=True)
b.call("DOM.setFileInputFiles", {"files": [csv_path], "objectId": node}, session=True)
b.eval("document.getElementById('importFile').dispatchEvent(new Event('change')), 1")
msg = click_and_toast("document.getElementById('importBtn')", 20)
row = wait("document.getElementById('approved').textContent.includes('AA:BB:CC:DD:EE:42')", 10)
record("import CSV", msg.startswith("OK Saved") and bool(row), msg)
xlsx_path = os.path.join(SCRATCH, "panel-test.xlsx")
open(xlsx_path, "wb").write(b"not really xlsx")
b.call("DOM.setFileInputFiles", {"files": [xlsx_path], "objectId": node}, session=True)
b.eval("document.getElementById('importFile').dispatchEvent(new Event('change')), 1")
msg = click_and_toast("document.getElementById('importBtn')", 20)
record("import XLSX without openpyxl -> clear error", msg.startswith("ERR ") and "openpyxl" in msg, msg)
msg = click_and_toast("[...document.querySelectorAll('#approved button')].find(x => x.closest('tr').textContent.includes('AA:BB:CC:DD:EE:42'))", 20)
gone = wait("!document.getElementById('approved').textContent.includes('AA:BB:CC:DD:EE:42')", 10)
record("remove approved device (confirm)", msg.startswith("OK Saved") and bool(gone), msg)

# 12 refresh
msg_n = b.eval("window.__log.length")
b.eval("document.getElementById('refresh').click(), 1")
time.sleep(3)
record("refresh button", b.eval(f"window.__log.slice({msg_n}).every(m => !m.startsWith('ERR'))"), "")

# 13 offline: every request stays on the panel origin
urls = sorted({e["params"]["request"]["url"] for e in b.events if e.get("method") == "Network.requestWillBeSent"})
external = [u for u in urls if not (u.startswith(URL) or u.startswith("data:") or u == "about:blank")]
record("offline: no external requests", not external, f"{len(urls)} requests; external={external}")

# 14 script errors
record("no page script errors", not b.console, "; ".join(b.console)[:300])

# screenshots for visual review
b.screenshot(os.path.join(SCRATCH, "panel-mobile-devices.png"))
tab("headsets")
time.sleep(1)
b.screenshot(os.path.join(SCRATCH, "panel-mobile-headsets.png"))
b.call("Emulation.setDeviceMetricsOverride", {"width": 1280, "height": 900, "deviceScaleFactor": 1, "mobile": False}, session=True)
time.sleep(1)
b.screenshot(os.path.join(SCRATCH, "panel-desktop-headsets.png"))
tab("captures")
time.sleep(2)
b.screenshot(os.path.join(SCRATCH, "panel-desktop-captures.png"))
b.close()

print("\nSUMMARY", sum(ok for _, ok, _ in results), "/", len(results), "passed")
