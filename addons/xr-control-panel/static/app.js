// XR Control Panel — client script (offline, no dependencies).
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

// Build DOM without innerHTML so server data is never interpreted as markup.
function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "dataset") Object.assign(node.dataset, v);
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) if (c !== null && c !== undefined) node.append(c.nodeType ? c : String(c));
  return node;
}

async function api(path, opts = {}) {
  const init = { method: opts.method || "GET", headers: {} };
  if (opts.json !== undefined) { init.headers["Content-Type"] = "application/json"; init.body = JSON.stringify(opts.json); }
  if (opts.body !== undefined) { init.body = opts.body; Object.assign(init.headers, opts.headers || {}); }
  const res = await fetch(path, init);
  let data = {};
  try { data = await res.json(); } catch { /* empty body */ }
  if (!res.ok) throw new Error(data.error || `${res.status} ${res.statusText}`);
  return data;
}

function toast(message, kind = "info") {
  const t = el("div", { class: `toast ${kind === "error" ? "error" : ""}`, role: "status" }, message);
  $("#toasts").append(t);
  setTimeout(() => t.remove(), kind === "error" ? 7000 : 3500);
}

// Run an action with a busy button, optional confirmation and a toast with the result.
async function run(button, fn) {
  const question = button && button.dataset.confirm;
  if (question && !confirm(question)) return;
  if (button) { button.setAttribute("aria-busy", "true"); button.disabled = true; }
  try {
    const result = await fn();
    if (result && result.message) toast(result.message);
    return result;
  } catch (e) {
    toast(e.message, "error");
  } finally {
    if (button) { button.removeAttribute("aria-busy"); button.disabled = false; }
  }
}

// ---------------------------------------------------------------- tabs
function showTab(name) {
  for (const b of $$(".tabs button")) b.setAttribute("aria-selected", String(b.dataset.tab === name));
  for (const s of $$(".tab")) s.hidden = s.id !== `tab-${name}`;
  location.hash = name;
  if (name === "captures") loadCaptures();
  if (name === "streaming") { loadClients(); loadLoftMenu(); refreshApkHeadsets(); }
  if (name === "settings") loadSettings();
  if (name === "devices") loadApproved();
  if (name === "gpu") loadGpu();
}
for (const b of $$(".tabs button")) b.addEventListener("click", () => showTab(b.dataset.tab));

// ---------------------------------------------------------------- status
let runtimeInstalled = false;
function pill(label, state) {
  const cls = { ok: "ok", ready: "ok", active: "ok", running: "ok", stopped: "", down: "bad", failed: "bad",
                inactive: "warn", missing: "bad" }[state] ?? "";
  return el("span", { class: `pill ${cls}` }, `${label}: ${state}`);
}
async function loadStatus() {
  try {
    const s = await api("/api/status");
    runtimeInstalled = s.runtime.installed;
    const pills = [pill("ADB", s.adb ? "ok" : "missing")];
    if (runtimeInstalled) {
      const app = s.runtime.app === "stopped" ? "stopped" : s.runtime.app;
      pills.push(pill("Runtime", s.runtime.service), pill("ALVR API", s.runtime.api),
                 el("span", { class: `pill ${app === "stopped" ? "" : "ok"}` }, `App: ${app}${s.runtime.loft_mode ? " · " + s.runtime.loft_mode : ""}`));
      $("#loftCard").hidden = s.runtime.app !== "loft";
      $("#loftMode").textContent = s.runtime.loft_mode ? `Mode: ${s.runtime.loft_mode}` : "";
      $("#startLoft").disabled = !s.runtime.loft_built;
      $("#startLoft").title = s.runtime.loft_built ? "" : "Build the Loft first (github.com/JLATORRE89/loft)";
    } else {
      pills.push(el("span", { class: "pill" }, "Runtime: not configured"));
    }
    $("#pills").replaceChildren(...pills);
    $("#runtime-missing").hidden = runtimeInstalled;
    for (const c of $$("[data-runtime]")) c.hidden = !runtimeInstalled;
  } catch (e) {
    $("#pills").replaceChildren(el("span", { class: "pill bad" }, "Panel offline"));
  }
}

// ---------------------------------------------------------------- headsets
const knownHeadsets = new Map();
function fact(label, value) { return el("div", { class: "fact" }, el("span", {}, label), el("strong", {}, value)); }
function actionButton(label, serial, action, cls = "btn", extra = {}) {
  return el("button", { class: cls, ...extra, onclick: (ev) => run(ev.currentTarget, async () => {
    const r = await api(`/api/headsets/${encodeURIComponent(serial)}/${action}`, { method: "POST" });
    await loadHeadsets(true);
    if (r.file) loadCaptures();
    return r;
  }) }, label);
}
function headsetCard(h) {
  const badges = [el("span", { class: "badge accent" }, h.transport === "wifi" ? "ADB Wi‑Fi" : "USB")];
  if (h.state !== "device") badges.push(el("span", { class: "badge warn" }, h.state));
  else if (!h.is_quest) badges.push(el("span", { class: "badge" }, "Not a Quest"));
  if (h.recording) badges.push(el("span", { class: "badge bad" }, "● Recording"));

  const card = el("article", { class: "card" },
    el("div", { class: "headset-head" },
      el("div", {}, el("p", { class: "headset-title" }, h.model || "Android device"), el("div", { class: "serial" }, h.serial)),
      el("div", { class: "badges" }, badges)));

  if (h.state !== "device") {
    card.append(el("p", { class: "muted" }, h.state === "unauthorized"
      ? "Put on the headset and allow USB debugging for this computer." : `ADB state: ${h.state}`));
    return card;
  }
  const alvr = (h.alvr || []).map(a => `${a.name} (${a.state || "?"})`).join(", ") || "—";
  card.append(el("div", { class: "facts" },
    fact("Battery", h.battery == null ? "—" : `${h.battery}%${h.charging ? " ⚡" : ""}`),
    fact("Display", h.awake ? "Awake" : "Asleep"),
    fact("Wi‑Fi IP", h.ip || "—"),
    fact("Client", h.client_installed ? (h.client_running ? "Running" : "Installed") : "Not installed"),
    fact("ALVR", alvr)));
  if (!h.is_quest) return card;

  card.append(el("div", { class: "actions" },
    actionButton("Screenshot", h.serial, "screenshot", "btn primary"),
    h.recording ? actionButton("Stop recording", h.serial, "record-stop", "btn recording")
                : actionButton("Start recording", h.serial, "record-start"),
    h.client_installed ? (h.client_running
      ? actionButton("Close client", h.serial, "client-close", "btn", { "data-confirm": "Close the ALVR client on this headset?" })
      : actionButton("Launch client", h.serial, "client-launch")) : null,
    h.awake ? null : actionButton("Wake", h.serial, "wake"),
    actionButton("Open panel in headset", h.serial, "panel-in-headset")));
  return card;
}
let headsetsBusy = false;
async function loadHeadsets(force = false) {
  if (headsetsBusy && !force) return;
  headsetsBusy = true;
  try {
    const data = await api("/api/headsets");
    const list = $("#headsets");
    if (!data.adb) list.replaceChildren(el("div", { class: "card empty" }, "adb was not found. Install Android platform-tools."));
    else if (!data.headsets.length) list.replaceChildren(el("div", { class: "card empty" },
      "No headsets connected. Connect a Quest by USB (developer mode on) or enable ADB over Wi‑Fi."));
    else list.replaceChildren(...data.headsets.map(headsetCard));
    for (const h of data.headsets) knownHeadsets.set(h.serial.replace(/[^A-Za-z0-9._-]/g, "_"), h.model || h.serial);
    refreshCaptureFilter();
  } catch (e) {
    $("#headsets").replaceChildren(el("div", { class: "card empty" }, `Could not read headsets: ${e.message}`));
  } finally {
    headsetsBusy = false;
  }
}

// ---------------------------------------------------------------- captures
function refreshCaptureFilter(extra = []) {
  const sel = $("#captureFilter");
  const current = sel.value;
  const ids = new Set([...knownHeadsets.keys(), ...extra]);
  sel.replaceChildren(el("option", { value: "" }, "All headsets"),
    ...[...ids].sort().map(id => el("option", { value: id }, knownHeadsets.get(id) ? `${knownHeadsets.get(id)} (${id})` : id)));
  sel.value = [...ids].includes(current) ? current : "";
}
async function loadCaptures() {
  const headset = $("#captureFilter").value;
  try {
    const data = await api("/api/captures" + (headset ? `?headset=${encodeURIComponent(headset)}` : ""));
    refreshCaptureFilter(data.captures.map(c => c.headset));
    const items = data.captures.map(c => {
      const url = `/captures/${encodeURIComponent(c.headset)}/${encodeURIComponent(c.file)}`;
      const media = c.type === "video"
        ? el("video", { src: url, controls: true, preload: "metadata" })
        : el("a", { href: url, target: "_blank", rel: "noopener" }, el("img", { src: url, alt: c.file, loading: "lazy" }));
      const when = new Date(c.mtime * 1000).toLocaleString();
      return el("figure", { class: "media" }, media,
        el("figcaption", { class: "meta" },
          el("span", {}, el("strong", {}, knownHeadsets.get(c.headset) || c.headset), el("br"), when),
          el("span", { class: "actions" },
            el("a", { href: url, download: c.file }, "Download"),
            el("button", { class: "btn danger small", "data-confirm": `Delete ${c.file}?`,
              onclick: e => run(e.currentTarget, async () => {
                const res = await api("/api/captures/delete", { method: "POST",
                  json: { headset: c.headset, file: c.file, on_headset: $("#deleteOnHeadset").checked } });
                loadCaptures();
                return res;
              }) }, "Delete"))));
    });
    $("#captures").replaceChildren(...(items.length ? items : [el("div", { class: "card empty" }, "No captures yet.")]));
  } catch (e) {
    toast(e.message, "error");
  }
}
$("#captureFilter").addEventListener("change", loadCaptures);

// ---------------------------------------------------------------- streaming
for (const b of $$("[data-app]")) b.addEventListener("click", () => run(b, async () => {
  const q = b.dataset.appname ? `?app=${encodeURIComponent(b.dataset.appname)}` : "";
  const r = await api(`/api/app/${b.dataset.app}${q}`, { method: "POST" });
  await loadStatus();
  return r;
}));
for (const b of $$("[data-loft]")) b.addEventListener("click", () => run(b, async () => {
  const r = await api(`/api/loft/${b.dataset.loft}`, { method: "POST" });
  setTimeout(loadStatus, 700);
  return r;
}));
async function loadClients() {
  if (!runtimeInstalled) return;
  try {
    const data = await api("/api/clients");
    $("#autoAccept").textContent = data.available ? `Auto‑accept ${data.auto_accept ? "on" : "off"}` : "ALVR API unavailable";
    $("#autoAccept").className = `badge ${data.available ? (data.auto_accept ? "ok" : "") : "bad"}`;
    const rows = Object.entries(data.clients || {}).map(([name, c]) => el("tr", {},
      el("td", {}, el("strong", {}, c.display_name || name), el("div", { class: "serial" }, name)),
      el("td", {}, c.current_ip || (c.manual_ips || []).join(", ") || "—"),
      el("td", {}, el("span", { class: `badge ${c.connection_state === "Streaming" ? "ok" : ""}` }, c.connection_state || "—")),
      el("td", {}, c.trusted ? "Yes" : "No"),
      el("td", {}, el("div", { class: "cell-actions" },
        c.trusted ? null : el("button", { class: "btn primary", onclick: (ev) => clientAction(ev.currentTarget, name, "Trust") }, "Approve"),
        el("button", { class: "btn danger", "data-confirm": `Forget ${name}?`,
          onclick: (ev) => clientAction(ev.currentTarget, name, "RemoveEntry") }, "Forget")))));
    $("#clients").replaceChildren(...(rows.length ? rows : [el("tr", {}, el("td", { colspan: 5, class: "muted" }, "No ALVR clients."))]));
  } catch (e) {
    toast(e.message, "error");
  }
}
function clientAction(button, name, action) {
  return run(button, async () => { const r = await api("/api/clients/action", { method: "POST", json: [name, action] }); loadClients(); return r; });
}
$("#clearClients").addEventListener("click", (ev) => run(ev.currentTarget, async () => {
  const r = await api("/api/clients/clear", { method: "POST" }); loadClients(); return r;
}));

// ---------------------------------------------------------------- settings
let settings = { values: {}, types: {} };
async function loadSettings() {
  if (!runtimeInstalled) return;
  try {
    settings = await api("/api/config");
    const sel = $("#settingSelect");
    const current = sel.value;
    sel.replaceChildren(el("option", { value: "" }, "Select a setting…"),
      ...Object.keys(settings.values).sort().map(k => el("option", { value: k }, k)));
    sel.value = current in settings.values ? current : "";
    renderSetting();
  } catch (e) {
    toast(e.message, "error");
  }
}
function renderSetting() {
  const key = $("#settingSelect").value;
  const editor = $("#settingEditor");
  $("#saveSetting").disabled = !key;
  if (!key) { editor.replaceChildren(); return; }
  const value = settings.values[key];
  const type = settings.types[key];
  const input = type === "bool"
    ? el("label", { class: "switch" }, el("input", { type: "checkbox", id: "settingValue", checked: value === true }), "Enabled")
    : el("label", { class: "field" }, el("span", {}, `Value (${type})`),
        el("input", { type: type === "int" ? "number" : "text", id: "settingValue", value: String(value) }));
  editor.replaceChildren(input);
}
$("#settingSelect").addEventListener("change", renderSetting);
$("#saveSetting").addEventListener("click", (ev) => run(ev.currentTarget, async () => {
  const key = $("#settingSelect").value;
  const input = $("#settingValue");
  const value = input.type === "checkbox" ? input.checked : input.value;
  const r = await api("/api/config", { method: "POST", json: { [key]: value } });
  await loadSettings();
  return r;
}));
$("#restartRuntime").addEventListener("click", (ev) => run(ev.currentTarget, () => api("/api/service/restart", { method: "POST" })));
$("#rebuildRuntime").addEventListener("click", (ev) => run(ev.currentTarget, () => api("/api/service/rebuild", { method: "POST" })));

// ---------------------------------------------------------------- approved devices
async function loadApproved() {
  try {
    const reg = await api("/api/approved");
    const rows = (reg.devices || []).map(d => el("tr", {},
      el("td", { class: "serial" }, d.mac_address), el("td", {}, d.name || "—"), el("td", {}, d.notes || "—"),
      el("td", {}, d.enabled === false ? "No" : "Yes"),
      el("td", {}, el("div", { class: "cell-actions" }, el("button", { class: "btn danger", "data-confirm": `Remove ${d.mac_address}?`,
        onclick: (ev) => run(ev.currentTarget, async () => {
          const r = await api("/api/approved/remove", { method: "POST", json: { mac_address: d.mac_address } });
          loadApproved(); return r;
        }) }, "Remove")))));
    $("#approved").replaceChildren(...(rows.length ? rows : [el("tr", {}, el("td", { colspan: 5, class: "muted" }, "No approved devices."))]));
  } catch (e) {
    toast(e.message, "error");
  }
}
$("#importFile").addEventListener("change", () => {
  const f = $("#importFile").files[0];
  $("#importName").textContent = f ? f.name : "";
  $("#importBtn").disabled = !f;
});
$("#importBtn").addEventListener("click", (ev) => run(ev.currentTarget, async () => {
  const f = $("#importFile").files[0];
  const r = await api("/api/approved/import", { method: "POST", body: await f.arrayBuffer(), headers: { "X-Filename": f.name } });
  loadApproved();
  return r;
}));

// ---------------------------------------------------------------- boot
$("#refresh").addEventListener("click", (ev) => run(ev.currentTarget, async () => {
  await Promise.all([loadStatus(), loadHeadsets(true)]);
  const tab = (location.hash || "#headsets").slice(1);
  if (tab !== "headsets") showTab(tab);
}));
function sizeTopbar() { document.documentElement.style.setProperty("--topbar-h", `${$(".topbar").offsetHeight}px`); }
window.addEventListener("resize", sizeTopbar);
(async () => {
  sizeTopbar();
  await loadStatus();
  const tab = (location.hash || "#headsets").slice(1);
  showTab($$(".tabs button").some(b => b.dataset.tab === tab) ? tab : "headsets");
  loadHeadsets();
  setInterval(loadStatus, 5000);
  setInterval(() => { if (!$("#tab-headsets").hidden) loadHeadsets(); }, 5000);
})();

// ---------------------------------------------------------------- GPU worker (optional add-on)
async function loadGpu() {
  try {
    const s = await api("/api/gpu/status");
    $("#gpuAddress").value = s.address;
    $("#gpuServerName").value = s.server_name;
    $("#gpuCaFile").value = s.ca_file;
    $("#gpuState").textContent = s.configured ? `Set up for ${s.address}; connection key saved.`
      : s.address ? "Add a connection key to finish setting up." : "Not set up yet.";
    const caps = (await api("/api/captures")).captures;
    $("#gpuSource").replaceChildren(el("option", { value: "" }, "None"),
      ...caps.filter(c => c.type === "image" || c.type === "video").map(c =>
        el("option", { value: `${c.headset}/${c.file}` }, `${c.file} (${knownHeadsets.get(c.headset) || c.headset})`)));
    renderGpuJobs((await api("/api/gpu/jobs")).jobs);
    if (s.configured && $("#gpuWorkflow").options.length <= 1) loadGpuWorkflows(null);
  } catch (e) {
    toast(e.message, "error");
  }
}
async function loadGpuWorkflows(button) {
  return run(button, async () => {
    const wf = (await api("/api/gpu/workflows")).workflows;
    const ids = Object.keys(wf).sort();
    $("#gpuWorkflow").replaceChildren(...(ids.length ? ids.map(id => {
      const refs = wf[id] && wf[id].reference_count;
      return el("option", { value: id }, refs ? `${id} (needs ${refs} image${refs > 1 ? "s" : ""})` : id);
    }) : [el("option", { value: "" }, "No workflows offered")]));
    return { message: `${ids.length} workflow${ids.length === 1 ? "" : "s"} available` };
  });
}
function renderGpuJobs(jobs) {
  const rows = jobs.map(j => el("div", { class: "job" },
    el("div", {}, el("strong", {}, j.workflow), " · ", el("span", { class: "muted" }, new Date(j.created * 1000).toLocaleString())),
    el("div", { class: "muted" }, j.source ? `Source: ${j.source}` : "No source", j.prompt ? ` · “${j.prompt}”` : ""),
    el("div", {}, "Status: ", el("strong", {}, j.status), j.error ? el("span", { class: "danger-text" }, ` — ${j.error}`) : null),
    j.outputs && j.outputs.length ? el("div", {}, "Saved to Captures: ",
      ...j.outputs.map(f => el("a", { href: `/captures/gpu-worker/${encodeURIComponent(f)}`, target: "_blank", rel: "noopener" }, f, " "))) : null,
    ["complete", "failed", "cancelled"].includes(j.status) && (j.outputs || []).length ? null :
      el("button", { class: "btn small", onclick: e => run(e.currentTarget, async () => {
        const res = await api(`/api/gpu/jobs/${j.request_id}/refresh`, { method: "POST" });
        renderGpuJobs((await api("/api/gpu/jobs")).jobs);
        return res;
      }) }, j.job_id ? "Check status" : "Retry submission")));
  $("#gpuJobs").replaceChildren(...(rows.length ? rows : [el("p", { class: "muted" }, "No jobs yet.")]));
}
$("#gpuSave").addEventListener("click", e => run(e.currentTarget, async () => {
  const res = await api("/api/gpu/config", { method: "POST", json: {
    address: $("#gpuAddress").value, server_name: $("#gpuServerName").value,
    ca_file: $("#gpuCaFile").value, key: $("#gpuKey").value } });
  $("#gpuKey").value = "";
  loadGpu();
  return res;
}));
$("#gpuForget").addEventListener("click", e => run(e.currentTarget, async () => {
  const res = await api("/api/gpu/config", { method: "POST", json: {
    address: $("#gpuAddress").value, server_name: $("#gpuServerName").value,
    ca_file: $("#gpuCaFile").value, clear_key: true } });
  loadGpu();
  return { message: "Connection key removed" };
}));
$("#gpuTest").addEventListener("click", e => run(e.currentTarget, () => api("/api/gpu/test", { method: "POST" })));
$("#gpuLoadWorkflows").addEventListener("click", e => loadGpuWorkflows(e.currentTarget));
$("#gpuSubmit").addEventListener("click", e => run(e.currentTarget, async () => {
  const src = $("#gpuSource").value;
  const [headset, file] = src ? src.split("/") : ["", ""];
  const res = await api("/api/gpu/jobs", { method: "POST", json: {
    workflow: $("#gpuWorkflow").value, prompt: $("#gpuPrompt").value, headset, file } });
  renderGpuJobs((await api("/api/gpu/jobs")).jobs);
  return res;
}));

// ---------------------------------------------------------------- Loft menu + media uploads
let loftMenu = [];
function slug(s) { return s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 32) || "app"; }
async function loadLoftMenu() {
  try {
    loftMenu = (await api("/api/loft/menu")).items;
    renderLoftMenu();
  } catch (e) {
    toast(e.message, "error");
  }
}
function renderLoftMenu() {
  const kinds = { builtin: "Built in", apk: "Quest app", pc: "PC mini-game" };
  $("#loftButtons").replaceChildren(el("button", { class: "btn", onclick: e => loftCmd(e.currentTarget, "lobby") }, "Lobby"),
    ...loftMenu.filter(i => i.enabled).map(i =>
      el("button", { class: "btn", onclick: e => loftCmd(e.currentTarget, `open:${i.id}`) }, i.title)));
  $("#loftMenuList").replaceChildren(...loftMenu.map((i, n) => el("div", { class: "menu-row" },
    el("label", { class: "check" }, el("input", { type: "checkbox", checked: i.enabled || null,
      onchange: e => { loftMenu[n].enabled = e.target.checked; saveLoftMenu(null); } }), el("strong", {}, i.title)),
    el("span", { class: "muted" }, `${kinds[i.type]}${i.type === "builtin" ? "" : " · " + i.target}`),
    i.type === "builtin" ? null : el("button", { class: "btn danger small", "data-confirm": `Remove ${i.title} from the menu?`,
      onclick: e => run(e.currentTarget, async () => { loftMenu.splice(n, 1); return saveLoftMenu(null); }) }, "Remove"))));
}
async function saveLoftMenu(button) {
  return run(button, async () => {
    const res = await api("/api/loft/menu", { method: "POST", json: { items: loftMenu } });
    await loadLoftMenu();
    return res;
  });
}
function loftCmd(button, cmd) {
  return run(button, () => api(`/api/loft/${cmd}`, { method: "POST" }));
}
function addMenuEntry(button, entry) {
  let id = slug(entry.title), n = 2;
  while (loftMenu.some(i => i.id === id)) id = `${slug(entry.title)}-${n++}`;
  loftMenu.push({ enabled: true, id, subtitle: "", ...entry });
  return saveLoftMenu(button);
}
$("#apkLoad").addEventListener("click", e => run(e.currentTarget, async () => {
  const serial = $("#apkHeadset").value;
  if (!serial) throw new Error("connect a headset first");
  const pk = (await api(`/api/headsets/${encodeURIComponent(serial)}/packages`)).packages;
  $("#apkPackage").replaceChildren(...pk.map(p => el("option", { value: p }, p)));
  return { message: `${pk.length} apps on the headset` };
}));
$("#apkAdd").addEventListener("click", e => {
  const pkg = $("#apkPackage").value, title = $("#apkTitle").value.trim() || pkg.split(".").pop();
  if (!pkg) return toast("load and pick an app first", "error");
  addMenuEntry(e.currentTarget, { type: "apk", title, subtitle: "Quest app", target: pkg });
});
$("#pcAdd").addEventListener("click", e => {
  const path = $("#pcPath").value.trim(), title = $("#pcTitle").value.trim() || path.split("/").pop();
  if (!path) return toast("enter the game's executable path", "error");
  addMenuEntry(e.currentTarget, { type: "pc", title, subtitle: "PC mini-game", target: path });
});
function refreshApkHeadsets() {
  $("#apkHeadset").replaceChildren(...[...knownHeadsets.entries()].map(([id, name]) => el("option", { value: id }, `${name} (${id})`)));
}
$("#uploadMedia").addEventListener("change", async e => {
  const files = [...e.target.files];
  const label = e.target.closest("label");
  label.setAttribute("aria-busy", "true");
  let ok = 0;
  for (const f of files) {
    try {
      const res = await fetch("/api/library/upload", { method: "POST", body: f,
        headers: { "X-Filename": encodeURIComponent(f.name), "Content-Type": "application/octet-stream" } });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(`${f.name}: ${data.error || res.status}`);
      ok++;
    } catch (err) {
      toast(err.message, "error");
    }
  }
  label.removeAttribute("aria-busy");
  e.target.value = "";
  if (ok) toast(`Uploaded ${ok} file${ok === 1 ? "" : "s"}; the Loft shows them in Pictures / Videos`);
  loadCaptures();
});
