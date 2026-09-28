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
  if (name === "settings") { loadSettings(); loadPanelAccess(); }
  if (name === "devices") loadApproved();
  if (name === "gpu") { loadGpu(); queueMicrotask(refreshVoiceHeadsets); }
  if (name === "updates") queueMicrotask(loadUpdates);
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
  const badges = [el("span", { class: "badge accent" }, h.transport === "wifi" ? "ADB Wi‑Fi" : h.transport === "usb" ? "USB" : "ADB")];
  if (h.state !== "device") badges.push(el("span", { class: "badge warn" }, h.state));
  else if (!h.is_quest) badges.push(el("span", { class: "badge" }, "Not a Quest"));
  if (h.recording) badges.push(el("span", { class: "badge bad" }, "● Recording"));

  const card = el("article", { class: "card headset-card" },
    el("div", { class: "headset-head" },
      el("div", {}, el("p", { class: "headset-title" }, h.model || "Android device"), el("div", { class: "serial" }, h.serial)),
      el("div", { class: "badges" }, badges)));

  if (h.state !== "device") {
    card.append(el("p", { class: "muted" }, h.state === "unauthorized"
      ? "Put on the headset and allow USB debugging for this computer." : `ADB state: ${h.state}`));
    return card;
  }
  const alvr = (h.alvr || []).map(a => `${a.name} (${a.state || "?"})`).join(", ") || "—";
  card.append(el("div", { class: "device-details" },
    el("div", { class: "device-status" },
      fact("Battery", h.battery == null ? "—" : `${h.battery}%${h.charging ? " ⚡" : ""}`),
      fact("Display", h.awake ? "Awake" : "Asleep"),
      fact("Client", h.client_installed ? (h.client_running ? "Running" : "Installed") : "Not installed")),
    el("div", { class: "device-network" },
      fact("Wi-Fi IPv4", h.ip || "—"),
      fact("Wi-Fi IPv6", (h.ipv6 || []).join("\n") || "—"),
      fact("ALVR", alvr))));
  if (!h.is_quest) return card;

  card.append(el("div", { class: "actions" },
    actionButton("Screenshot", h.serial, "screenshot", "btn primary"),
    h.recording ? actionButton("Stop recording", h.serial, "record-stop", "btn recording")
                : actionButton("Start recording", h.serial, "record-start"),
    h.client_installed ? (h.client_running
      ? actionButton("Close client", h.serial, "client-close", "btn", { "data-confirm": "Close the ALVR client on this headset?" })
      : actionButton("Launch client", h.serial, "client-launch")) : null,
    h.awake ? null : actionButton("Wake", h.serial, "wake"),
    actionButton("Open panel in headset", h.serial, "panel-in-headset"),
    actionButton("Pair headset for Wi-Fi", h.serial, "pair-wifi")));
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
          el("label", { class: "check" }, el("input", { type: "checkbox", name: "capturePick", dataset: { headset: c.headset, file: c.file }, onchange: updateCaptureSelection }), "Select for export"),
          el("span", {}, el("strong", {}, knownHeadsets.get(c.headset) || c.headset), el("br"), when),
          el("span", { class: "actions" },
            el("a", { href: url + "?download=1", download: c.file }, "Export file"),
            c.type === "video" && !c.file.includes("-headset") ? el("button", { class: "btn small",
              onclick: e => run(e.currentTarget, () => api("/api/captures/transcode", { method: "POST",
                json: { headset: c.headset, file: c.file, where: "auto" } })) }, "Prepare for headset") : null,
            el("button", { class: "btn danger small", "data-confirm": `Delete ${c.file}?`,
              onclick: e => run(e.currentTarget, async () => {
                const res = await api("/api/captures/delete", { method: "POST",
                  json: { headset: c.headset, file: c.file, on_headset: $("#deleteOnHeadset").checked } });
                loadCaptures();
                return res;
              }) }, "Delete"))));
    });
    $("#captures").replaceChildren(...(items.length ? items : [el("div", { class: "card empty" }, "No captures yet.")]));
    updateCaptureSelection();
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
  $("#restoreSetting").disabled = !key || !(key in (settings.defaults || {}));
  if (!key) { editor.replaceChildren(); return; }
  const value = settings.values[key];
  const type = settings.types[key];
  const input = type === "bool"
    ? el("label", { class: "switch" }, el("input", { type: "checkbox", id: "settingValue", checked: value === true }), "Enabled")
    : el("label", { class: "field" }, el("span", {}, `Value (${type})`),
        el("input", { type: type === "int" ? "number" : "text", id: "settingValue", value: String(value) }));
  editor.replaceChildren(input, el("p", { class: "muted" }, `Default: ${String(settings.defaults?.[key] ?? "unavailable")}`));
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
    j.review_serial ? el("div", {}, `Headset review: ${j.review_state || "waiting"}`, j.review_error ? ` — ${j.review_error}` : "",
      j.review_state === "failed" ? el("button", { class: "btn small", onclick: e => run(e.currentTarget, () => api("/api/gpu/retry-review", { method: "POST", json: { request_id: j.request_id } })) }, "Retry headset review") : null) : null,
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
    i.type === "builtin" ? null : el("input", { type: "text", value: i.title, maxlength: 40, "aria-label": `Title in the Loft for ${i.title}`,
      onchange: e => { loftMenu[n].title = e.target.value.trim(); saveLoftMenu(null); } }),
    el("span", { class: "muted" }, `${kinds[i.type]}${i.type === "builtin" ? "" : " · " + i.target}`),
    i.type === "builtin" ? null : el("button", { class: "btn danger small", "data-confirm": `Remove ${i.title} from the menu?`,
      onclick: e => run(e.currentTarget, async () => { loftMenu.splice(n, 1); return saveLoftMenu(null); }) }, "Remove from Loft"))));
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
  const data = await api(`/api/headsets/${encodeURIComponent(serial)}/packages`);
  const apps = data.apps || data.packages.map(p => ({ package: p, label: p }));
  $("#apkPackage").replaceChildren(...apps.map(a => el("option", { value: a.package, dataset: { label: a.label } },
    a.label === a.package ? a.package : `${a.label} (${a.package})`)));
  updateApkTitle();
  return { message: data.warning || `${apps.length} apps on the headset` };
}));
function updateApkTitle() {
  const option = $("#apkPackage").selectedOptions[0];
  $("#apkTitle").value = (option?.dataset.label || "").slice(0, 40);
}
$("#apkPackage").addEventListener("change", updateApkTitle);
$("#apkHeadset").addEventListener("change", () => {
  $("#apkPackage").replaceChildren(el("option", { value: "" }, "Load apps…"));
  $("#apkTitle").value = "";
});
$("#apkAdd").addEventListener("click", e => {
  const pkg = $("#apkPackage").value, title = $("#apkTitle").value.trim() || ($("#apkPackage").selectedOptions[0]?.dataset.label || pkg).slice(0, 40);
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

// ---------------------------------------------------------------- panel access (Wi-Fi pairing)
async function loadPanelAccess() {
  try {
    const a = await api("/api/panel/access");
    $("#lanAccess").checked = a.lan_access;
    $("#autoAuthorizeUsb").checked = a.auto_authorize_usb;
    const labels = { paired: "Authorized for Wi-Fi", pending: "Waiting for browser pairing", failed: "Manual pairing needed", revoked: "Access revoked" };
    $("#usbPairingDevices").replaceChildren(...(a.usb_devices || []).map(d =>
      el("p", { class: "muted" }, `${d.name || "Headset"} (${d.serial}): ${labels[d.state] || d.state}${d.error ? " — " + d.error : ""}`)));
    $("#lanState").textContent = a.lan_access
      ? `On: paired headsets can open this panel over ${a.ipv6_available ? "IPv4 or IPv6" : "IPv4"} Wi-Fi at port ${a.port}.`
      : "Off: only this PC and USB-connected headsets can open the panel.";
  } catch (e) {
    toast(e.message, "error");
  }
}
$("#lanAccess").addEventListener("change", e => run(null, async () => {
  const res = await api("/api/panel/lan", { method: "POST", json: { enabled: e.target.checked } });
  setTimeout(loadPanelAccess, 3000);
  return res;
}));
$("#autoAuthorizeUsb").addEventListener("change", e => run(e.currentTarget, async () => {
  try {
    return await api("/api/panel/auto-usb", { method: "POST", json: { enabled: e.target.checked } });
  } finally { await loadPanelAccess(); }
}));
$("#revokePairing").addEventListener("click", e => run(e.currentTarget, async () => {
  const result = await api("/api/panel/revoke", { method: "POST" });
  await loadPanelAccess();
  return result;
}));

setInterval(() => { if (!$("#tab-settings").hidden) loadPanelAccess(); }, 5000);

// ---------------------------------------------------------------- offline software updates
let updatesBusy = false;
async function loadUpdates() {
  if (updatesBusy) return;
  updatesBusy = true;
  try {
    const data = await api("/api/updates");
    $("#updateSources").replaceChildren(...data.sources.map(a => el("div", { class: "update-item" },
      el("strong", {}, `${a.name} ${a.version || ""}`), el("p", { class: "muted" }, a.url),
      el("button", { class: "btn danger", "data-confirm": `Remove ${a.name} from the exported download list?`, onclick: e => run(e.currentTarget, async () => {
        const r = await api("/api/updates/remove-source", { method: "POST", json: { sha256: a.sha256 } }); await loadUpdates(); return r;
      }) }, "Remove from download list"))));
    const select = $("#updateHeadset"), selected = select.value;
    select.replaceChildren(...data.devices.map(d => el("option", { value: d.serial }, `${d.model || "Headset"} (${d.serial}) · ${d.state}`)));
    if ([...select.options].some(o => o.value === selected)) select.value = selected;
    $("#updateStorageStatus").textContent = data.apk_inspection_available ? "Stored updates are available offline. Maximum file size: 16 GiB." : "APK inspection needs Android SDK aapt2 on this PC. Firmware storage is available.";
    $("#updateLibrary").replaceChildren(...(data.updates.length ? data.updates.map(u => {
      const invoke = (button, action, extra = {}) => run(button, async () => {
        const result = await api(`/api/updates/${action}`, { method: "POST", json: { id: u.id, serial: select.value, ...extra } });
        if (action === "prepare") $("#updatePreparation").textContent = result.message;
        else await loadUpdates();
        return result;
      });
      return el("article", { class: "update-item" }, el("h3", {}, `${u.label} · ${u.version}`),
        el("p", { class: "muted" }, `${u.kind === "apk" ? u.package : "Firmware for " + u.models} · ${Math.round(u.size / 1024 / 1024)} MiB · ${u.filename}`),
        el("details", {}, el("summary", {}, "File checksum"), el("code", {}, u.sha256)),
        el("div", { class: "actions" },
          u.kind === "firmware" ? el("button", { class: "btn", onclick: e => invoke(e.currentTarget, "prepare") }, "Check firmware compatibility") : null,
          el("button", { class: "btn primary", onclick: e => {
            if (!select.value) return toast("Connect and select a headset first", "error");
            if (confirm(`Install ${u.label} ${u.version} on ${select.value}? ${u.kind === "firmware" ? "This changes Quest system software. Keep USB connected until recovery completes." : "The app may close during its update."}`)) invoke(e.currentTarget, "install", { confirmed: true });
          } }, "Install stored update"),
          el("button", { class: "btn", onclick: () => {
            $("#sourceName").value = u.label; $("#sourceKind").value = u.kind; $("#sourceVersion").value = u.version;
            $("#sourceHash").value = u.sha256; $("#sourceUrl").value = "";
            $("#sourceName").closest("details").open = true; $("#sourceUrl").focus();
          } }, "Set download source"),
          el("a", { class: "btn", href: `/api/updates/${u.id}/download`, download: u.filename }, "Download copy"),
          el("button", { class: "btn danger", "data-confirm": `Remove stored ${u.filename}? Installed software will stay on headsets.`, onclick: e => invoke(e.currentTarget, "remove") }, "Remove stored file")));
    }) : [el("p", { class: "muted" }, "No updates stored yet.")]));
    $("#updateJobs").replaceChildren(...(data.jobs.length ? data.jobs.map(j => el("article", { class: "update-item" },
      el("strong", {}, `${j.label} · ${j.serial} · ${j.state.replaceAll("_", " ")}`), el("p", {}, j.message),
      ["awaiting_verification", "interrupted", "failed"].includes(j.state) ? el("div", { class: "actions" },
        ...[["verify", "Verify installed version"], ["close-job", "Close without verification"]].map(([action, text]) => el("button", {
          class: "btn", "data-confirm": action === "close-job" ? "Close this job without verifying success? Check the headset before retrying." : null,
          onclick: e => run(e.currentTarget, async () => { const r = await api(`/api/updates/${action}`, { method: "POST", json: { job: j.id } }); await loadUpdates(); return r; })
        }, text))) : null)) : [el("p", { class: "muted" }, "No update jobs yet.")]));
  } catch (e) { toast(e.message, "error"); }
  finally { updatesBusy = false; }
}
$("#updateRefresh").addEventListener("click", loadUpdates);
$("#updateUpload").addEventListener("click", e => run(e.currentTarget, async () => {
  const file = $("#updateFile").files[0];
  if (!file) throw new Error("Choose an update file first");
  $("#updateStorageStatus").textContent = "Uploading and checking the file…";
  const result = await api("/api/updates/upload", { method: "POST", body: file, headers: {
    "X-Filename": encodeURIComponent(file.name), "X-Update-Kind": $("#updateKind").value, "X-SHA256": $("#updateHash").value.trim()
  } });
  $("#updateFile").value = ""; await loadUpdates(); return result;
}));
setInterval(() => { if (!$("#tab-updates").hidden) loadUpdates(); }, 5000);

$("#sourceSave").addEventListener("click", e => run(e.currentTarget, async () => {
  const result = await api("/api/updates/source", { method: "POST", json: {
    name: $("#sourceName").value.trim(), kind: $("#sourceKind").value, version: $("#sourceVersion").value.trim(),
    url: $("#sourceUrl").value.trim(), sha256: $("#sourceHash").value.trim().toLowerCase()
  } }); await loadUpdates(); return result;
}));
$("#bundleImport").addEventListener("click", e => run(e.currentTarget, async () => {
  const file = $("#bundleFile").files[0];
  if (!file) throw new Error("Choose the tar.gz file from XR Downloader first");
  $("#updateStorageStatus").textContent = "Importing and validating the complete offline bundle…";
  const result = await api("/api/updates/import", { method: "POST", body: file });
  $("#bundleFile").value = ""; await loadUpdates(); return result;
}));

for (const [id, all] of [["#restoreSetting", false], ["#restoreAllSettings", true]]) {
  $(id).addEventListener("click", e => run(e.currentTarget, async () => {
    const key = all ? "*" : $("#settingSelect").value;
    const r = await api("/api/config/restore", { method: "POST", json: { key } });
    await loadSettings(); return r;
  }));
}

// Tap-to-speak is limited to the selected capture-analysis-return workflow.
let voiceRecognition = null, voiceCancelled = false;
function refreshVoiceHeadsets() {
  const select = $("#voiceHeadset"), current = select.value;
  select.replaceChildren(...[...knownHeadsets.entries()].map(([id, name]) => el("option", { value: id }, `${name} (${id})`)));
  if ([...select.options].some(o => o.value === current)) select.value = current;
}
async function sendScreenRequest(button) {
  return run(button, async () => {
    const serial = $("#voiceHeadset").value, workflow = $("#gpuWorkflow").value, prompt = $("#voiceRequest").value.trim();
    if (!serial || !workflow || !prompt) throw new Error("Select a headset and an image-analysis workflow, then speak or type a request");
    $("#voiceStatus").textContent = "Capturing the headset view and submitting your request…";
    try {
      const result = await api("/api/gpu/screen-request", { method: "POST", json: { serial, workflow, prompt } });
      $("#voiceStatus").textContent = result.message; return result;
    } catch (e) { $("#voiceStatus").textContent = e.message; throw e; }
  });
}
$("#voiceSend").addEventListener("click", e => sendScreenRequest(e.currentTarget));
const BrowserSpeech = window.SpeechRecognition || window.webkitSpeechRecognition;
if (!BrowserSpeech || !window.isSecureContext) {
  $("#voiceSpeak").disabled = true;
  $("#voiceStatus").textContent = !window.isSecureContext ? "Voice needs a secure browser page. Use Open panel in headset over USB, or HTTPS. You can type a request here." : "Speech recognition is unavailable in this browser. You can type a request here.";
}
$("#voiceSpeak").addEventListener("click", () => {
  if (!BrowserSpeech || voiceRecognition) return;
  if (!$("#voiceHeadset").value || !$("#gpuWorkflow").value) return toast("Select a headset and image-analysis workflow first", "error");
  stopMicTest("Microphone test stopped for voice input.");
  const recognition = new BrowserSpeech(); voiceRecognition = recognition; voiceCancelled = false;
  recognition.lang = navigator.language || "en-US"; recognition.interimResults = false; recognition.continuous = false;
  $("#voiceSpeak").disabled = true; $("#voiceStop").disabled = false; $("#voiceStatus").textContent = "Listening…";
  recognition.onresult = e => {
    if (voiceCancelled) return;
    const transcript = e.results[0][0].transcript;
    $("#voiceRequest").value = transcript; $("#voiceStatus").textContent = `Heard: ${transcript}`;
    sendScreenRequest($("#voiceSend"));
  };
  recognition.onerror = e => { $("#voiceStatus").textContent = `Speech recognition: ${e.error}. You can type your request.`; };
  recognition.onend = () => { voiceRecognition = null; $("#voiceSpeak").disabled = false; $("#voiceStop").disabled = true; };
  try { recognition.start(); } catch (e) { recognition.onend(); $("#voiceStatus").textContent = e.message; }
});
$("#voiceStop").addEventListener("click", () => {
  voiceCancelled = true; voiceRecognition?.abort(); $("#voiceStatus").textContent = "Listening stopped; no request submitted.";
});

for (const button of $$("#voiceExamples [data-find]")) {
  button.addEventListener("click", () => {
    $("#voiceRequest").value = `Find ${button.dataset.find} in my current field of view. Mark the matching objects in the captured image and return the result to my headset for review.`;
    sendScreenRequest(button);
  });
}

function updateCaptureSelection() {
  const selected = $$("#captures input[name=capturePick]:checked").map(input => ({ headset: input.dataset.headset, file: input.dataset.file }));
  $("#captureSelectionValue").value = JSON.stringify(selected);
  $("#captureExport").disabled = selected.length === 0;
  $("#captureSelectionCount").textContent = `${selected.length} selected`;
}
$("#captureExportForm").addEventListener("submit", e => {
  updateCaptureSelection();
  if ($("#captureExport").disabled) { e.preventDefault(); toast("Select at least one capture to export", "error"); }
});

// Microphone input is tested separately from speech recognition and GPU connectivity.
let micGeneration = 0, micStream = null, micContext = null, micFrame = null, micTimer = null;
function stopMicTest(message) {
  micGeneration++;
  if (micFrame !== null) cancelAnimationFrame(micFrame);
  clearTimeout(micTimer); micFrame = null; micTimer = null;
  micStream?.getTracks().forEach(track => track.stop()); micStream = null;
  micContext?.close().catch(() => {}); micContext = null;
  $("#micLevel").value = 0; $("#micTest").disabled = false; $("#micTestStop").disabled = true;
  if (message) $("#micStatus").textContent = message;
}
function microphoneError(error) {
  const messages = {
    NotAllowedError: "Microphone permission was denied. Allow Microphone for Meta Quest Browser in headset app permissions and allow it for this site, then try again.",
    NotFoundError: "No microphone is available to this browser. Check the headset microphone settings.",
    NotReadableError: "The microphone could not be opened. Unmute it in Quest Quick Settings and close another app using it, then retry.",
    SecurityError: "The browser blocked microphone access. Open this panel through the USB headset button or HTTPS."
  };
  return messages[error.name] || `Microphone test failed: ${error.message || error.name}`;
}
$("#micTest").addEventListener("click", async () => {
  voiceCancelled = true; voiceRecognition?.abort();
  stopMicTest();
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
    $("#micStatus").textContent = "Microphone access needs HTTPS or localhost. Connect USB and use Open panel in headset, then test here."; return;
  }
  const Audio = window.AudioContext || window.webkitAudioContext;
  if (!Audio) { $("#micStatus").textContent = "This browser cannot show a microphone meter."; return; }
  const generation = micGeneration;
  $("#micTest").disabled = true; $("#micTestStop").disabled = false;
  $("#micStatus").textContent = "Allow the microphone prompt in the headset. Then speak normally.";
  // Late permission grants after cancellation must not leave a microphone open.
  micTimer = setTimeout(() => stopMicTest("Microphone permission timed out. Allow the prompt, then start the test again."), 30000);
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true }, video: false });
    if (generation !== micGeneration) { stream.getTracks().forEach(track => track.stop()); return; }
    clearTimeout(micTimer); micStream = stream;
    micContext = new Audio();
    const context = micContext;
    await context.resume();
    if (generation !== micGeneration) return;
    const analyser = context.createAnalyser(); analyser.fftSize = 2048;
    context.createMediaStreamSource(stream).connect(analyser);
    const samples = new Uint8Array(analyser.fftSize); let peak = 0;
    $("#micStatus").textContent = "Microphone open. Speak now; the meter should move. Testing for 12 seconds…";
    function measure() {
      if (generation !== micGeneration) return;
      analyser.getByteTimeDomainData(samples);
      const rms = Math.sqrt(samples.reduce((sum, x) => sum + ((x - 128) / 128) ** 2, 0) / samples.length);
      peak = Math.max(peak, rms); $("#micLevel").value = Math.min(100, Math.round(rms * 500));
      micFrame = requestAnimationFrame(measure);
    }
    measure();
    micTimer = setTimeout(() => stopMicTest(peak > 0.008
      ? "Microphone signal detected. Input works; speech recognition is a separate check."
      : "Microphone permission was granted, but no clear input was detected. Unmute the Quest microphone and try speaking again."), 12000);
    stream.getAudioTracks().forEach(track => track.addEventListener("ended", () => {
      if (generation === micGeneration) stopMicTest("Microphone disconnected or permission was revoked. Start another test when ready.");
    }));
  } catch (error) {
    if (generation === micGeneration) stopMicTest(microphoneError(error));
  }
});
$("#micTestStop").addEventListener("click", () => stopMicTest("Microphone test stopped. Nothing was recorded or uploaded."));
window.addEventListener("pagehide", () => { stopMicTest(); voiceCancelled = true; voiceRecognition?.abort(); });
document.addEventListener("visibilitychange", () => { if (document.hidden) stopMicTest("Microphone test stopped because the page is hidden."); });
