#!/usr/bin/env python3
"""Minimal Chrome DevTools Protocol driver over --remote-debugging-pipe (stdlib only)."""
import json
import os
import subprocess
import time


def _setup_fds(r, w):
    # Move both pipe ends to high fds first so dup2 to 3/4 cannot clobber the other end.
    hr, hw = os.dup(r) + 100, os.dup(w) + 100
    os.dup2(r, hr); os.dup2(w, hw)
    os.dup2(hr, 3); os.dup2(hw, 4)
    os.set_inheritable(3, True); os.set_inheritable(4, True)


class Browser:
    def __init__(self, profile, width=412, height=900):
        r1, w1 = os.pipe()  # we write commands -> chrome fd 3
        r2, w2 = os.pipe()  # chrome writes responses fd 4 -> we read
        self.proc = subprocess.Popen(
            ["google-chrome", "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
             f"--user-data-dir={profile}", f"--window-size={width},{height}", "--remote-debugging-pipe",
             "about:blank"],
            pass_fds=(r1, w2, 3, 4), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            preexec_fn=lambda: _setup_fds(r1, w2))
        os.close(r1); os.close(w2)
        self.out = os.fdopen(w1, "wb", buffering=0)
        self.inp = os.fdopen(r2, "rb", buffering=0)
        self.buf = b""
        self.next_id = 0
        self.events = []
        self.dialog_answer = True
        self.dialogs = []
        tid = self.call("Target.createTarget", {"url": "about:blank"})["targetId"]
        self.session = self.call("Target.attachToTarget", {"targetId": tid, "flatten": True})["sessionId"]
        for domain in ("Page", "Runtime", "Log"):
            self.call(f"{domain}.enable", session=True)
        self.console = []

    def _read_msg(self):
        while b"\0" not in self.buf:
            chunk = self.inp.read(65536)
            if not chunk:
                raise EOFError("chrome closed the pipe")
            self.buf += chunk
        msg, self.buf = self.buf.split(b"\0", 1)
        return json.loads(msg)

    def _handle_event(self, msg):
        method = msg.get("method")
        if method == "Page.javascriptDialogOpening":
            self.dialogs.append(msg["params"]["message"])
            self.send("Page.handleJavaScriptDialog", {"accept": self.dialog_answer}, session=True)
        elif method == "Runtime.exceptionThrown":
            self.console.append("EXCEPTION " + json.dumps(msg["params"]["exceptionDetails"].get("exception", {}).get("description", ""))[:300])
        elif method == "Runtime.consoleAPICalled" and msg["params"]["type"] == "error":
            self.console.append("console.error " + json.dumps(msg["params"]["args"])[:300])
        else:
            self.events.append(msg)

    def send(self, method, params=None, session=False):
        self.next_id += 1
        msg = {"id": self.next_id, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = self.session
        self.out.write(json.dumps(msg).encode() + b"\0")
        return self.next_id

    def call(self, method, params=None, session=False, timeout=60):
        mid = self.send(method, params, session)
        deadline = time.time() + timeout
        while time.time() < deadline:
            msg = self._read_msg()
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})
            self._handle_event(msg)
        raise TimeoutError(method)

    def eval(self, expr, timeout=120):
        res = self.call("Runtime.evaluate", {"expression": expr, "awaitPromise": True, "returnByValue": True},
                        session=True, timeout=timeout)
        if "exceptionDetails" in res:
            raise RuntimeError(res["exceptionDetails"].get("exception", {}).get("description", "eval failed"))
        return res.get("result", {}).get("value")

    def goto(self, url):
        self.call("Page.navigate", {"url": url}, session=True)
        self.eval("new Promise(r => { if (document.readyState === 'complete') r(1); else addEventListener('load', () => r(1)); })")

    def screenshot(self, path):
        import base64
        data = self.call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}, session=True)["data"]
        with open(path, "wb") as f:
            f.write(base64.b64decode(data))

    def close(self):
        try:
            self.call("Browser.close")
        except Exception:
            pass
        self.proc.wait(timeout=10)
