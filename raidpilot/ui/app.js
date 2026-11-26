"use strict";
const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];

// In the program window: pywebview. In a browser (development): a small HTTP server.
const bridge = new Promise(resolve => {
  const ready = () => window.pywebview?.api?.boot;
  if (ready()) return resolve("window");
  window.addEventListener("pywebviewready", () => resolve("window"), {once: true});
  if (location.search.includes("dev")) resolve("http");
});

async function call(method, ...args) {
  try {
    if (await bridge === "window") return await window.pywebview.api[method](...args);
    const response = await fetch("/api/" + method, {method: "POST", body: JSON.stringify(args)});
    return await response.json();
  } catch (error) {
    return {ok: false, error: "No connection to the program: " + error.message};
  }
}

const state = {settings: {}, running: false, lastLog: 0, generation: 0, lines: 0};

function toast(text, bad = false, time = 3500) {
  const box = $("#toast");
  box.textContent = text;
  box.className = "show" + (bad ? " bad" : "");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => box.className = "", time);
}
async function must(method, ...args) {
  const result = await call(method, ...args);
  if (!result.ok) toast(result.error, true);
  return result;
}

// 914000 -> "914k", 21900000 -> "21.9M"
const amount = n => n >= 1e9 ? (n / 1e9).toFixed(2) + "B" : n >= 1e6 ? (n / 1e6).toFixed(1) + "M"
  : n >= 1e3 ? Math.round(n / 1e3) + "k" : String(n);
const duration = s => s >= 3600 ? `${Math.floor(s / 3600)}h ${Math.floor(s % 3600 / 60)}m` : `${Math.floor(s / 60)}m`;

function paintSlider(input) {
  const min = +input.min, max = +input.max;
  input.style.setProperty("--fill", ((input.value - min) / (max - min) * 100) + "%");
  $("output", input.closest("label")).textContent = amount(+input.value);
}

function applySettings(settings) {
  state.settings = settings;
  for (const el of $$("[data-setting]")) {
    const value = settings[el.dataset.setting];
    if (el.type === "checkbox") el.checked = value;
    else if (document.activeElement !== el || el.tagName === "SELECT") el.value = value;
    if (el.type === "range") paintSlider(el);
  }
  const connected = !!settings.webhook;
  $("#discord").textContent = connected ? "Discord Connected ✓" : "Connect Discord Account";
  $("#webhook-remove").hidden = !connected;
}

async function save(key, value) {
  const result = await must("save_setting", key, value);
  applySettings(result.ok ? result.settings : state.settings);
}
for (const el of $$("[data-setting]")) {
  if (el.type === "range") el.addEventListener("input", () => paintSlider(el));
  el.addEventListener("change", () => save(el.dataset.setting,
    el.type === "checkbox" ? el.checked : el.type === "range" ? Number(el.value) : el.value));
}

// ---------- navigation ----------
function go(page) {
  $$(".page").forEach(p => p.hidden = p.dataset.page !== page);
  $$("nav button").forEach(b => b.classList.toggle("on", b.dataset.nav === page));
  if (page === "settings") refreshDevices();
  if (page === "log" && $("#autoscroll").checked) $("#log").scrollTop = $("#log").scrollHeight;
}
$$("nav button").forEach(b => b.onclick = () => go(b.dataset.nav));
$$("[data-action]").forEach(b => b.onclick = () => call(b.dataset.action));

// ---------- live view ----------
async function poll() {
  const data = await call("poll", state.lastLog, state.generation);
  if (data.ok) {
    state.running = data.running;
    const power = $("#power");
    power.textContent = data.running ? "STOP" : "START";
    power.classList.toggle("running", data.running);
    $("#status").textContent = data.status;
    $("#bot-error").textContent = data.running ? "" : data.error;
    for (const key of ["gold", "elixir", "attacks", "walls"]) {
      $("#s-" + key).textContent = amount(data.session[key]);
      $("#t-" + key).textContent = amount(data.lifetime[key]);
    }
    $("#s-runtime").textContent = duration(data.session.runtime);
    $("#t-runtime").textContent = duration(data.lifetime.runtime);
    $("#player").textContent = data.player || "Player";
    $("#player-hint").hidden = !!data.player;
    for (const el of [$("#device"), $("#restart-adb")]) el.disabled = data.running;
    if (data.generation !== state.generation) {
      $("#log").replaceChildren();
      state.lines = 0; state.lastLog = 0; state.generation = data.generation;
    }
    appendLog(data.log);
    const banner = $("#update-banner");
    banner.hidden = !data.update && !banner.disabled;
    if (data.update && !banner.disabled) banner.textContent = `Install version ${data.update}`;
    if (data.auto_update && !banner.disabled) installUpdate(true);
  }
  setTimeout(poll, 800);
}

function appendLog(lines) {
  const box = $("#log");
  for (const line of lines) {
    if (line.id <= state.lastLog) continue;
    const row = document.createElement("div"), time = document.createElement("time");
    row.className = line.level;
    time.textContent = line.time;
    row.append(time, line.text);
    box.append(row);
    state.lastLog = line.id;
    state.lines++;
  }
  while (box.childElementCount > 600) box.firstChild.remove();
  $("#line-count").textContent = state.lines === 1 ? "1 line" : `${state.lines} lines`;
  if (lines.length && $("#autoscroll").checked) box.scrollTop = box.scrollHeight;
}

$("#power").onclick = async () => {
  const button = $("#power");
  button.disabled = true;
  await must(state.running ? "stop" : "start");
  button.disabled = false;
};
$("#clear-log").onclick = () => call("clear_log");

// ---------- devices ----------
let searching = false;
async function refreshDevices(method = "devices") {
  if (searching) return;
  searching = true;
  const select = $("#device"), status = $("#device-status");
  status.textContent = method === "restart_adb" ? "Restarting ADB…" : "Searching…";
  status.className = "device-status";
  const result = await call(method);
  searching = false;
  if (!result.ok) {
    status.textContent = result.error;
    if (method !== "devices") toast(result.error, true);
    return;
  }
  const auto = new Option(result.mumu ? "Automatic (MuMu Player #0)" : "Automatic", "");
  select.replaceChildren(auto, ...result.devices.map(d =>
    new Option(d.state === "device" ? d.serial : `${d.serial} (${d.state})`, d.serial)));
  select.value = result.selected;
  status.textContent = result.status;
  status.classList.toggle("good", result.good);
}
$("#refresh").onclick = () => refreshDevices();
$("#restart-adb").onclick = () => refreshDevices("restart_adb");
$("#device").onchange = async e => { await save("device", e.target.value); refreshDevices(); };

// ---------- event troop ----------
function showSaved(count) {
  $("#saved-events").hidden = !count;
  $("#saved-events span").textContent = count === 1 ? "1 event troop icon saved" : `${count} event troop icons saved`;
}
$("#capture-event").onclick = async e => {
  const button = e.currentTarget;
  button.disabled = true;
  button.textContent = "Capturing…";
  const result = await must("capture_event");
  button.disabled = false;
  button.textContent = "Capture Event Troop";
  if (!result.ok) return;
  $("#capture-panel").hidden = false;
  const image = $("#shot");
  image.src = result.image;
  await image.decode();
  // Show the troop bar first
  image.parentElement.scrollTo(0, image.parentElement.scrollHeight);
};
$("#shot").onclick = async e => {
  const box = e.currentTarget.getBoundingClientRect();
  const result = await must("save_event_troop", (e.clientX - box.left) / box.width, (e.clientY - box.top) / box.height);
  if (!result.ok) return;
  $("#capture-panel").hidden = true;
  showSaved(result.event_troops);
  toast("Event troop saved.");
};
$("#close-capture").onclick = () => $("#capture-panel").hidden = true;
$("#clear-events").onclick = async () => { const r = await must("clear_event_troops"); if (r.ok) showSaved(0); };

// ---------- Discord ----------
$("#discord").onclick = () => {
  const panel = $("#discord-panel");
  panel.hidden = !panel.hidden;
  if (!panel.hidden) { $("#webhook").value = state.settings.webhook; panel.scrollIntoView({block: "end"}); }
};
$("#discord-panel").onsubmit = async e => {
  e.preventDefault();
  const button = $("#webhook-save");
  button.disabled = true;
  const result = await must("connect_discord", $("#webhook").value);
  button.disabled = false;
  if (!result.ok) return;
  applySettings(result.settings);
  $("#discord-panel").hidden = true;
  toast("Discord connected.");
};
$("#webhook-remove").onclick = async () => {
  const result = await must("disconnect_discord");
  if (result.ok) { applySettings(result.settings); $("#webhook").value = ""; $("#discord-panel").hidden = true; }
};

// auto: right after the start, without a click
async function installUpdate(auto = false) {
  const banner = $("#update-banner");
  banner.disabled = true;
  banner.hidden = false;
  banner.textContent = "Downloading update…";
  const result = await must("install_update", auto);
  if (result.ok && result.result) banner.textContent = "Restarting…"; else banner.disabled = false;
}
$("#update-banner").onclick = () => installUpdate();

$("#check-update").onclick = async e => {
  const button = e.currentTarget, note = $("#update-state");
  button.disabled = true;
  note.className = "hint";
  note.textContent = "Checking…";
  const result = await call("check_update");
  button.disabled = false;
  if (!result.ok) { note.className = "hint bad"; note.textContent = result.error; return; }
  note.className = "hint good";
  note.textContent = result.update ? `Version ${result.update} is available. Click "Install" at the top.`
    : "You are up to date.";
};

// ---------- start ----------
async function boot() {
  const data = await call("boot");
  if (!data.ok) { toast(data.error, true); return; }
  for (const [name, entries] of Object.entries(data.choices))
    for (const select of $$(`select[data-setting="${name}"]`))
      select.replaceChildren(...Object.entries(entries).map(([value, label]) => {
        const option = new Option(label, value);
        option.disabled = (data.unavailable[name] || []).includes(value);
        return option;
      }));
  $("#version").textContent = data.version;
  if (data.updated) {
    const text = `Updated to version ${data.version}.`;
    $("#update-state").textContent = text;
    toast(text, false, 8000);
  }
  applySettings(data.settings);
  showSaved(data.event_troops);
  poll();
}
boot();
