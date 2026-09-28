// Tablet Loft client: shows the frames the panel relays from this tablet's Loft renderer and sends
// touch, keyboard and game controller input back (see tablet_client.py for the protocol).
"use strict";

const canvas = document.getElementById("view");
const ctx = canvas.getContext("2d");
const statusEl = document.getElementById("status");
const standBtn = document.getElementById("stand");
const stick = document.getElementById("stick");
const knob = document.getElementById("knob");
const hint = document.querySelector(".hint");

const LOOK_PER_PX = 0.005;      // radians per dragged CSS pixel
const PAD_LOOK_SPEED = 2.4;     // radians per second at full right stick
const PAD_DEADZONE = 0.18;

let ws = null, retry = 0, frameRect = null, lastState = null, padIndex = null;
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
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const w = Math.round(window.innerWidth * dpr), h = Math.round(window.innerHeight * dpr);
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(`${proto}//${location.host}/api/tablet/ws?w=${w}&h=${h}`);
  ws.binaryType = "blob";
  setStatus("Connecting…");
  ws.onopen = () => { retry = 0; };
  ws.onmessage = async (ev) => {
    if (typeof ev.data === "string") {
      const msg = JSON.parse(ev.data);
      if (msg.t === "hello") setStatus("Joining the Loft…");
      else if (msg.t === "state") showState(msg);
      else if (msg.t === "error") setStatus(msg.message, true);
      return;
    }
    try {
      const bmp = await createImageBitmap(ev.data);
      draw(bmp);
      bmp.close();
    } catch (e) { /* a damaged frame: skip it */ }
    send({ t: "ack" });
  };
  ws.onclose = () => {
    ws = null;
    retry = Math.min(retry + 1, 6);
    setStatus(retry > 2 ? "Disconnected — retrying…" : "Reconnecting…", retry > 2);
    setTimeout(connect, 400 * retry);
  };
}

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

// Keyboard (a tablet keyboard or this PC): WASD / arrows walk, Q/E turn, Enter selects, Esc stands.
const keys = new Set();
window.addEventListener("keydown", (e) => {
  keys.add(e.key.toLowerCase());
  if (e.key === "Enter") tapAt(window.innerWidth / 2, window.innerHeight / 2);
  if (e.key === "Escape") send({ t: "stand" });
});
window.addEventListener("keyup", (e) => keys.delete(e.key.toLowerCase()));
function keyboardMove() {
  const k = (a, b) => (keys.has(a) || keys.has(b) ? 1 : 0);
  return { f: k("w", "arrowup") - k("s", "arrowdown"), r: k("d", "arrowright") - k("a", "arrowleft"),
           turn: k("q", "") - k("e", "") };
}

// ---------------------------------------------------------------- game controller (Xbox layout)
// Standard mapping: left stick walks, right stick looks, A selects the centre dot (sit / greet),
// B stands up. Chrome only exposes controllers to secure pages, hence the HTTPS note.
const padPrev = [];
function deadzone(v) {
  const a = Math.abs(v);
  return a < PAD_DEADZONE ? 0 : Math.sign(v) * (a - PAD_DEADZONE) / (1 - PAD_DEADZONE);
}
function pollPad(dt) {
  const pads = navigator.getGamepads ? navigator.getGamepads() : [];
  const pad = padIndex !== null ? pads[padIndex] : null;
  if (!pad || !pad.connected) return null;
  const pressed = (i) => !!(pad.buttons[i] && pad.buttons[i].pressed);
  const edge = (i) => pressed(i) && !padPrev[i];
  if (edge(0)) tapAt(window.innerWidth / 2, window.innerHeight / 2);       // A
  if (edge(1)) send({ t: "stand" });                                          // B
  for (let i = 0; i < pad.buttons.length; i++) padPrev[i] = pressed(i);
  // Right stick: pushing right turns right (the renderer's positive yaw turns left).
  look.dx += -deadzone(pad.axes[2] || 0) * PAD_LOOK_SPEED * dt;
  look.dy += -deadzone(pad.axes[3] || 0) * PAD_LOOK_SPEED * dt;
  return { f: -deadzone(pad.axes[1] || 0), r: deadzone(pad.axes[0] || 0) };
}
function showPad() {
  stick.hidden = padIndex !== null;
  hint.textContent = padIndex !== null
    ? "Controller: left stick walks · right stick looks · A sits on the chair at the dot or greets the bartender · B stands up"
    : "Drag to look around · stick to walk · tap a chair to sit · tap the bartender to say hello";
}
window.addEventListener("gamepadconnected", (e) => { padIndex = e.gamepad.index; showPad(); });
window.addEventListener("gamepaddisconnected", (e) => {
  if (e.gamepad.index === padIndex) { padIndex = null; showPad(); }
});
if (!window.isSecureContext) {
  hint.textContent += ` · For a game controller open https://${location.hostname}:8483/tablet`;
}

// ---------------------------------------------------------------- send loop (~30 Hz)
let lastTick = performance.now();
function tick(now) {
  const dt = Math.min((now - lastTick) / 1000, 0.1);
  lastTick = now;
  const pad = pollPad(dt);
  const kb = keyboardMove();
  look.dx += kb.turn * PAD_LOOK_SPEED * dt; // Q turns left (positive yaw)
  let m = move;
  if (kb.f || kb.r) m = { f: kb.f, r: kb.r };
  else if (pad && (pad.f || pad.r)) m = pad;
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
document.getElementById("fullscreen").addEventListener("click", () => {
  if (document.fullscreenElement) document.exitFullscreen();
  else document.documentElement.requestFullscreen({ navigationUI: "hide" }).catch(() => {});
});
showPad();
connect();
