// Tablet Loft client: shows the frames the panel relays from this tablet's Loft renderer and sends
// touch, keyboard and game controller input back (see tablet_client.py for the protocol). Also the
// Pictures/Videos menu (the panel's captures) and voice chat with the headsets.
"use strict";

const $ = (s) => document.querySelector(s);
const canvas = $("#view");
const ctx = canvas.getContext("2d");
const statusEl = $("#status");
const standBtn = $("#stand");
const voiceBtn = $("#voice");
const soundBtn = $("#sound");
const stick = $("#stick");
const knob = $("#knob");
const hint = $(".hint");
const menu = $("#menu");
const grid = $("#grid");
const viewer = $("#viewer");
const pic = $("#pic");
const vid = $("#vid");

const LOOK_PER_PX = 0.005;      // radians per dragged CSS pixel
const PAD_LOOK_SPEED = 2.4;     // radians per second at full right stick
const PAD_DEADZONE = 0.18;
const VOICE_RATE = 24000, VOICE_CHUNK = 960; // 40 ms of mono, as tablet_client.py

let ws = null, retry = 0, frameRect = null, lastState = null, padIndex = null, voiceAvailable = false;
let reconnectTimer = null;
let look = { dx: 0, dy: 0 }, move = { f: 0, r: 0 }, moveSentZero = true;

function setStatus(text, error = false) {
  statusEl.textContent = text;
  statusEl.classList.toggle("error", error);
}

function send(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
}

// ---------------------------------------------------------------- connection and frames
function connect() {
  if (document.hidden || (ws && ws.readyState < WebSocket.CLOSING)) return;
  clearTimeout(reconnectTimer);
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const w = Math.round(window.innerWidth * dpr), h = Math.round(window.innerHeight * dpr);
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(`${proto}//${location.host}/api/tablet/ws?w=${w}&h=${h}`);
  const socket = ws;
  ws.binaryType = "arraybuffer";
  setStatus("Connecting…");
  ws.onopen = () => { retry = 0; };
  ws.onmessage = async (ev) => {
    if (ws !== socket) return;
    if (typeof ev.data === "string") {
      const msg = JSON.parse(ev.data);
      if (msg.t === "hello") {
        setStatus("Joining the Loft…");
        voiceAvailable = !!msg.voice;
        voiceBtn.hidden = !voiceAvailable;
        soundBtn.hidden = !voiceAvailable;
        if (voice.wanted) send({ t: "voice", on: true }); // reconnected: keep talking
      } else if (msg.t === "state") showState(msg);
      else if (msg.t === "voice") voiceState(msg.on);
      else if (msg.t === "error") setStatus(msg.message, true);
      return;
    }
    const kind = new Uint8Array(ev.data, 0, 1)[0];
    if (kind === 0x41) { playVoice(ev.data); return; } // "A"
    try {
      const bmp = await createImageBitmap(new Blob([new Uint8Array(ev.data, 1)], { type: "image/jpeg" }));
      if (ws === socket && !document.hidden) draw(bmp);
      bmp.close();
    } catch (e) { /* a damaged frame: skip it */ }
    if (ws === socket) send({ t: "ack" });
  };
  ws.onclose = (ev) => {
    if (ws !== socket) return;
    ws = null;
    voiceState(false, true);
    if (ev.code === 4001) {
      setStatus("Loft is open in another tab. Return to this tab to resume.");
      return;
    }
    if (document.hidden) return;
    retry = Math.min(retry + 1, 6);
    setStatus(retry > 2 ? "Disconnected — retrying…" : "Reconnecting…", retry > 2);
    reconnectTimer = setTimeout(connect, 400 * retry);
  };
}

// A device has one Loft user. Hidden tabs must not reclaim its renderer or keep
// sending held controller input. Returning to the tab resumes the same user.
document.addEventListener("visibilitychange", () => {
  clearTimeout(reconnectTimer);
  if (document.hidden) {
    keys.clear();
    drags.clear();
    move = { f: 0, r: 0 };
    look = { dx: 0, dy: 0 };
    stickId = null;
    knob.style.transform = "";
    send({ t: "move", f: 0, r: 0 });
    const old = ws;
    ws = null;
    if (old) old.close();
    stopVoice();
    voiceState(false, true);
  } else connect();
});

function draw(bmp) {
  const dpr = window.devicePixelRatio || 1;
  const cw = Math.round(window.innerWidth * dpr), ch = Math.round(window.innerHeight * dpr);
  if (canvas.width !== cw || canvas.height !== ch) { canvas.width = cw; canvas.height = ch; }
  // Fit the frame (letterboxed); taps are mapped through the same rectangle.
  const s = Math.min(cw / bmp.width, ch / bmp.height);
  const w = bmp.width * s, h = bmp.height * s, x = (cw - w) / 2, y = (ch - h) / 2;
  ctx.fillStyle = "#0f1115";
  ctx.fillRect(0, 0, cw, ch);
  ctx.drawImage(bmp, x, y, w, h);
  frameRect = { x: x / dpr, y: y / dpr, w: w / dpr, h: h / dpr };
  if (padIndex !== null) { // centre dot: what the A button selects
    ctx.beginPath();
    ctx.arc(cw / 2, ch / 2, 5 * dpr, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(122,162,255,.95)";
    ctx.strokeStyle = "rgba(0,0,0,.6)";
    ctx.lineWidth = 2 * dpr;
    ctx.fill();
    ctx.stroke();
  }
}

function showState(st) {
  lastState = st;
  const n = st.peers || 0;
  const others = n === 0 ? "Nobody else here yet" : n === 1 ? "1 other person here" : `${n} other people here`;
  setStatus(st.seated ? `Seated: ${st.seated} · ${others}` : `In the Loft · ${others}`);
  standBtn.hidden = !st.seated;
}

let resizeTimer = null;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => { if (ws) ws.close(); }, 500); // reconnects at the new size
});

// ---------------------------------------------------------------- input: look, tap, walk
function tapAt(clientX, clientY) {
  if (!frameRect) return;
  const u = (clientX - frameRect.x) / frameRect.w, v = (clientY - frameRect.y) / frameRect.h;
  if (u >= 0 && u <= 1 && v >= 0 && v <= 1) send({ t: "tap", u, v });
}
const tapCentre = () => tapAt(window.innerWidth / 2, window.innerHeight / 2);

const drags = new Map(); // pointerId -> {x, y, sx, sy, t}
canvas.addEventListener("pointerdown", (e) => {
  canvas.setPointerCapture(e.pointerId);
  drags.set(e.pointerId, { x: e.clientX, y: e.clientY, sx: e.clientX, sy: e.clientY, t: performance.now() });
});
canvas.addEventListener("pointermove", (e) => {
  const d = drags.get(e.pointerId);
  if (!d) return;
  // Drag the world: moving the finger right turns the view left.
  look.dx += (e.clientX - d.x) * LOOK_PER_PX;
  look.dy += (e.clientY - d.y) * LOOK_PER_PX;
  d.x = e.clientX;
  d.y = e.clientY;
});
function endDrag(e) {
  const d = drags.get(e.pointerId);
  if (!d) return;
  drags.delete(e.pointerId);
  if (e.type === "pointerup" && performance.now() - d.t < 300 && Math.hypot(e.clientX - d.sx, e.clientY - d.sy) < 12)
    tapAt(e.clientX, e.clientY);
}
canvas.addEventListener("pointerup", endDrag);
canvas.addEventListener("pointercancel", endDrag);

let stickId = null;
function stickTo(e) {
  const r = stick.getBoundingClientRect(), R = r.width / 2;
  let x = e.clientX - (r.left + R), y = e.clientY - (r.top + R);
  const m = Math.hypot(x, y);
  if (m > R) { x *= R / m; y *= R / m; }
  knob.style.transform = `translate(${x}px, ${y}px)`;
  move = { f: -y / R, r: x / R };
}
stick.addEventListener("pointerdown", (e) => { stickId = e.pointerId; stick.setPointerCapture(e.pointerId); stickTo(e); });
stick.addEventListener("pointermove", (e) => { if (e.pointerId === stickId) stickTo(e); });
function stickEnd(e) {
  if (e.pointerId !== stickId) return;
  stickId = null;
  knob.style.transform = "";
  move = { f: 0, r: 0 };
}
stick.addEventListener("pointerup", stickEnd);
stick.addEventListener("pointercancel", stickEnd);

// Keyboard (a tablet keyboard or this PC): WASD / arrows walk, Q/E turn, Enter selects, Esc stands
// (or closes the menu), M opens the menu.
const keys = new Set();
window.addEventListener("keydown", (e) => {
  if (menuOpen()) {
    const nav = { ArrowLeft: "left", ArrowRight: "right", ArrowUp: "up", ArrowDown: "down", Enter: "select",
                  Escape: "back", Backspace: "back", m: "menu", M: "menu", "[": "prevTab", "]": "nextTab" }[e.key];
    if (nav) { e.preventDefault(); menuInput(nav); }
    return;
  }
  keys.add(e.key.toLowerCase());
  if (e.key === "Enter") tapCentre();
  if (e.key === "Escape") send({ t: "stand" });
  if (e.key === "m" || e.key === "M") openMenu();
});
window.addEventListener("keyup", (e) => keys.delete(e.key.toLowerCase()));
function keyboardMove() {
  const k = (a, b) => (keys.has(a) || keys.has(b) ? 1 : 0);
  return { f: k("w", "arrowup") - k("s", "arrowdown"), r: k("d", "arrowright") - k("a", "arrowleft"),
           turn: k("q", "") - k("e", "") };
}

// ---------------------------------------------------------------- menu: Pictures and Videos
// The panel's captures (per-headset screenshots/recordings, uploads, GPU results), newest first.
let items = [], kind = "image", focusIdx = 0, viewing = -1;
const menuOpen = () => !menu.hidden;

async function openMenu() {
  menu.hidden = false;
  move = { f: 0, r: 0 };
  keys.clear();
  try {
    const r = await fetch("/api/captures", { cache: "no-store" });
    items = r.ok ? (await r.json()).captures || [] : [];
  } catch (e) { items = []; }
  items.sort((a, b) => b.mtime - a.mtime);
  showKind(kind);
}
function closeMenu() {
  closeViewer();
  menu.hidden = true;
}
function listed() { return items.filter((c) => c.type === kind); }
function mediaUrl(c) { return `/captures/${encodeURIComponent(c.headset)}/${encodeURIComponent(c.file)}`; }
function showKind(k) {
  kind = k;
  for (const b of menu.querySelectorAll(".tab")) b.setAttribute("aria-selected", String(b.dataset.kind === k));
  const list = listed();
  grid.replaceChildren(...list.map((c, i) => {
    const b = document.createElement("button");
    b.className = "tile";
    b.addEventListener("click", () => openViewer(i));
    if (c.type === "image") {
      const img = document.createElement("img");
      img.loading = "lazy";
      img.alt = "";
      img.src = mediaUrl(c);
      b.append(img);
    } else {
      const play = document.createElement("span");
      play.className = "play";
      play.textContent = "▶";
      b.append(play);
    }
    const cap = document.createElement("span");
    cap.className = "cap";
    cap.textContent = new Date(c.mtime * 1000).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
    b.append(cap);
    return b;
  }));
  $("#menu-empty").hidden = list.length > 0;
  $("#menu-empty").textContent = k === "image" ? "No pictures yet. Screenshots and uploads from the panel appear here."
                                               : "No videos yet. Recordings and uploads from the panel appear here.";
  focusIdx = 0;
  focusTile();
}
function focusTile() {
  const tiles = grid.querySelectorAll(".tile");
  tiles.forEach((t, i) => t.classList.toggle("focus", i === focusIdx && padIndex !== null));
  if (tiles[focusIdx] && padIndex !== null && menuOpen() && viewer.hidden) tiles[focusIdx].focus();
}
function gridColumns() {
  return getComputedStyle(grid).gridTemplateColumns.split(" ").filter(Boolean).length || 1;
}
function openViewer(i) {
  const list = listed();
  if (!list[i]) return;
  viewing = i;
  const c = list[i];
  viewer.hidden = false;
  pic.hidden = c.type !== "image";
  vid.hidden = c.type !== "video";
  if (c.type === "image") { vid.pause(); vid.removeAttribute("src"); pic.src = mediaUrl(c); }
  else { pic.removeAttribute("src"); vid.src = mediaUrl(c); vid.play().catch(() => {}); }
  $("#viewer-cap").textContent = `${i + 1} / ${list.length}`;
}
function closeViewer() {
  if (viewer.hidden) return;
  vid.pause();
  vid.removeAttribute("src");
  vid.load();
  viewer.hidden = true;
  viewing = -1;
  focusTile();
}
function menuInput(action) {
  const n = listed().length;
  if (!viewer.hidden) {
    if (action === "left" && viewing > 0) openViewer(viewing - 1);
    else if (action === "right" && viewing < n - 1) openViewer(viewing + 1);
    else if (action === "select" && !vid.hidden) vid.paused ? vid.play() : vid.pause();
    else if (action === "back") closeViewer();
    else if (action === "menu") closeMenu();
    return;
  }
  const cols = gridColumns();
  if (action === "left") focusIdx = Math.max(0, focusIdx - 1);
  else if (action === "right") focusIdx = Math.min(n - 1, focusIdx + 1);
  else if (action === "up") focusIdx = Math.max(0, focusIdx - cols);
  else if (action === "down") focusIdx = Math.min(n - 1, focusIdx + cols);
  else if (action === "select") return openViewer(focusIdx);
  else if (action === "prevTab" || action === "nextTab") return showKind(kind === "image" ? "video" : "image");
  else if (action === "back" || action === "menu") return closeMenu();
  focusIdx = Math.max(0, focusIdx);
  focusTile();
}
$("#menu-btn").addEventListener("click", openMenu);
$("#menu-close").addEventListener("click", closeMenu);
for (const b of menu.querySelectorAll(".tab")) b.addEventListener("click", () => showKind(b.dataset.kind));
$("#viewer-prev").addEventListener("click", () => menuInput("left"));
$("#viewer-next").addEventListener("click", () => menuInput("right"));
$("#viewer-back").addEventListener("click", closeViewer);

// ---------------------------------------------------------------- voice chat with the headsets
// The microphone streams to the panel as 16-bit PCM (24 kHz mono); others' voices come back the same
// way and are scheduled on a short jitter buffer. Listening joins automatically;
// playback needs a browser gesture. The microphone is separately opt-in; X mutes it.
const voice = { wanted: true, on: false, muted: false, ctx: null, stream: null, node: null, buf: [], next: 0, micStarting: false, soundMuted: false };

const WORKLET = `class Mic extends AudioWorkletProcessor {
  process(inputs) { const ch = inputs[0][0]; if (ch) this.port.postMessage(ch.slice(0)); return true; }
}
registerProcessor("loft-mic", Mic);`;
let workletLoaded = false;

// Receiving does not request microphone permission. Browsers may require a tap
// before AudioContext can play; the first page interaction unlocks room sound.
async function startSound() {
  if (document.hidden || voice.soundMuted) return;
  try {
    voice.ctx = voice.ctx || new AudioContext({ sampleRate: VOICE_RATE });
    await voice.ctx.resume();
    soundBtn.textContent = voice.ctx.state === "running" ? "Sound on" : "Enable sound";
    soundBtn.setAttribute("aria-pressed", String(voice.ctx.state === "running"));
  } catch (e) {
    soundBtn.textContent = "Enable sound";
  }
}
window.addEventListener("pointerdown", (e) => { if (e.target !== soundBtn && voice.ctx?.state !== "running") startSound(); });
window.addEventListener("keydown", () => { if (voice.ctx?.state !== "running") startSound(); });
soundBtn.addEventListener("click", () => {
  if (voice.ctx?.state === "running" && !voice.soundMuted) {
    voice.soundMuted = true;
    if (voice.output) voice.output.gain.value = 0;
    voice.next = 0;
    soundBtn.textContent = "Sound off";
    soundBtn.setAttribute("aria-pressed", "false");
  } else {
    voice.soundMuted = false;
    if (voice.output) voice.output.gain.value = 1;
    startSound();
  }
});

async function startVoice() {
  if (voice.micStarting || voice.stream) return;
  voice.micStarting = true;
  voiceBtn.textContent = "Mic…";
  try {
    voice.ctx = voice.ctx || new AudioContext({ sampleRate: VOICE_RATE });
    await voice.ctx.resume();
    if (!voice.soundMuted) await startSound();
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 } });
    if (document.hidden) { stream.getTracks().forEach(t => t.stop()); return; }
    voice.stream = stream;
    if (!workletLoaded) {
      const url = URL.createObjectURL(new Blob([WORKLET], { type: "text/javascript" }));
      try { await voice.ctx.audioWorklet.addModule(url); } finally { URL.revokeObjectURL(url); }
      workletLoaded = true;
    }
    const src = voice.ctx.createMediaStreamSource(voice.stream);
    voice.node = new AudioWorkletNode(voice.ctx, "loft-mic");
    voice.node.port.onmessage = (e) => micSamples(e.data);
    src.connect(voice.node);
    voice.muted = false;
  } catch (e) {
    stopVoice();
    setStatus(window.isSecureContext ? "Microphone not available: " + e.message
                                     : "Microphone needs HTTPS (or the USB-opened page)", true);
  } finally {
    voice.micStarting = false;
    voiceState(voice.on);
  }
}
function stopVoice() {
  // Turning off the microphone must not turn off incoming room sound.
  voice.muted = false;
  if (voice.stream) voice.stream.getTracks().forEach((t) => t.stop());
  if (voice.node) voice.node.disconnect();
  voice.stream = voice.node = null;
  voice.buf = [];
  voiceState(voice.on);
}
function voiceState(on, reconnecting = false) {
  voice.on = on;
  const talking = on && !!voice.stream && !voice.muted;
  voiceBtn.classList.toggle("primary", talking);
  voiceBtn.textContent = !voice.stream ? "Mic off" : voice.muted ? "Mic muted" : "Mic on";
  voiceBtn.setAttribute("aria-pressed", String(talking));
}
function micSamples(f32) {
  if (!voice.on || voice.muted || !voice.stream || document.hidden) return;
  for (const v of f32) voice.buf.push(v);
  while (voice.buf.length >= VOICE_CHUNK) {
    const chunk = voice.buf.splice(0, VOICE_CHUNK);
    const out = new Uint8Array(1 + VOICE_CHUNK * 2);
    out[0] = 0x41;
    const pcm = new DataView(out.buffer, 1);
    chunk.forEach((v, i) => pcm.setInt16(i * 2, Math.max(-1, Math.min(1, v)) * 32767, true));
    if (ws && ws.readyState === WebSocket.OPEN && ws.bufferedAmount < 256 * 1024) ws.send(out);
  }
}
function playVoice(buf) {
  if (!voice.ctx || !voice.on || voice.soundMuted || voice.ctx.state !== "running" || document.hidden) return;
  const n = (buf.byteLength - 1) >> 1;
  if (!n) return;
  const pcm = new DataView(buf, 1);
  const ab = voice.ctx.createBuffer(1, n, VOICE_RATE);
  const ch = ab.getChannelData(0);
  for (let i = 0; i < n; i++) ch[i] = pcm.getInt16(i * 2, true) / 32768;
  const src = voice.ctx.createBufferSource();
  src.buffer = ab;
  if (!voice.output) { voice.output = voice.ctx.createGain(); voice.output.connect(voice.ctx.destination); }
  src.connect(voice.output);
  const now = voice.ctx.currentTime;
  if (voice.next < now + 0.03 || voice.next > now + 0.4) voice.next = now + 0.08; // (re)start or drop lag
  src.start(voice.next);
  voice.next += ab.duration;
}
function toggleMute() {
  if (!voice.stream) return;
  voice.muted = !voice.muted;
  voice.buf = [];
  voice.stream.getAudioTracks().forEach(t => { t.enabled = !voice.muted; });
  voiceState(voice.on);
}
voiceBtn.addEventListener("click", () => {
  if (!voice.stream) startVoice();
  else stopVoice();
});

// ---------------------------------------------------------------- game controller (Xbox layout)
// Standard mapping: left stick walks, right stick looks, A selects the centre dot (drink / sit /
// greet), B stands up, Y opens the menu, X mutes voice. In the menu: D-pad or left stick moves,
// A opens, B goes back, LB/RB switch Pictures/Videos. Chrome only exposes controllers to secure pages.
const padPrev = [];
let navHeld = null, navNext = 0;
function deadzone(v) {
  const a = Math.abs(v);
  return a < PAD_DEADZONE ? 0 : Math.sign(v) * (a - PAD_DEADZONE) / (1 - PAD_DEADZONE);
}
function pollPad(dt, now) {
  const pads = navigator.getGamepads ? navigator.getGamepads() : [];
  const pad = padIndex !== null ? pads[padIndex] : null;
  if (!pad || !pad.connected) return null;
  const pressed = (i) => !!(pad.buttons[i] && pad.buttons[i].pressed);
  const edges = pad.buttons.map((_, i) => pressed(i) && !padPrev[i]);
  for (let i = 0; i < pad.buttons.length; i++) padPrev[i] = pressed(i);
  if (menuOpen()) {
    if (edges[0]) menuInput("select");
    if (edges[1]) menuInput("back");
    if (edges[3]) menuInput("menu");
    if (edges[4]) menuInput("prevTab");
    if (edges[5]) menuInput("nextTab");
    // D-pad or left stick, repeating while held.
    const ax = pad.axes[0] || 0, ay = pad.axes[1] || 0;
    const dir = pressed(14) || ax < -0.6 ? "left" : pressed(15) || ax > 0.6 ? "right"
              : pressed(12) || ay < -0.6 ? "up" : pressed(13) || ay > 0.6 ? "down" : null;
    if (dir && (dir !== navHeld || now >= navNext)) {
      menuInput(dir);
      navNext = now + (dir !== navHeld ? 400 : 160);
    }
    navHeld = dir;
    return null;
  }
  navHeld = null;
  if (edges[0]) tapCentre();          // A
  if (edges[1]) send({ t: "stand" });  // B
  if (edges[2]) toggleMute();          // X
  if (edges[3]) openMenu();            // Y
  // Right stick: pushing right turns right (the renderer's positive yaw turns left).
  look.dx += -deadzone(pad.axes[2] || 0) * PAD_LOOK_SPEED * dt;
  look.dy += -deadzone(pad.axes[3] || 0) * PAD_LOOK_SPEED * dt;
  return { f: -deadzone(pad.axes[1] || 0), r: deadzone(pad.axes[0] || 0) };
}
function showPad() {
  stick.hidden = padIndex !== null;
  hint.textContent = padIndex !== null
    ? "Controller: left stick walks · right stick looks · A drinks, sits or greets at the dot · B stands · Y menu · X mute"
    : "Drag to look · stick to walk · tap a glass to drink, a chair to sit, the bartender to say hello";
  if (!window.isSecureContext)
    hint.textContent += ` · For a controller or voice open https://${location.hostname}:8483/tablet`;
  focusTile();
}
window.addEventListener("gamepadconnected", (e) => { padIndex = e.gamepad.index; showPad(); });
window.addEventListener("gamepaddisconnected", (e) => {
  if (e.gamepad.index === padIndex) { padIndex = null; showPad(); }
});

// ---------------------------------------------------------------- send loop (~30 Hz)
let lastTick = performance.now();
function tick(now) {
  if (document.hidden) { lastTick = now; return; }
  const dt = Math.min((now - lastTick) / 1000, 0.1);
  lastTick = now;
  const pad = pollPad(dt, now);
  let m = { f: 0, r: 0 };
  if (!menuOpen()) {
    const kb = keyboardMove();
    look.dx += kb.turn * PAD_LOOK_SPEED * dt; // Q turns left (positive yaw)
    m = move;
    if (kb.f || kb.r) m = { f: kb.f, r: kb.r };
    else if (pad && (pad.f || pad.r)) m = pad;
  } else {
    look = { dx: 0, dy: 0 };
  }
  if (m.f || m.r) {
    send({ t: "move", f: m.f, r: m.r });
    moveSentZero = false;
  } else if (!moveSentZero) {
    send({ t: "move", f: 0, r: 0 });
    moveSentZero = true;
  }
  if (look.dx || look.dy) {
    send({ t: "look", dx: look.dx, dy: look.dy });
    look = { dx: 0, dy: 0 };
  }
}
setInterval(() => tick(performance.now()), 33);

standBtn.addEventListener("click", () => send({ t: "stand" }));
$("#fullscreen").addEventListener("click", () => {
  if (document.fullscreenElement) document.exitFullscreen();
  else document.documentElement.requestFullscreen({ navigationUI: "hide" }).catch(() => {});
});
showPad();
connect();
