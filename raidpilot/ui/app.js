"use strict";
const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];

// Im Programmfenster: pywebview. Im Browser (Entwicklung): kleiner HTTP-Server.
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
    return {ok: false, error: "Keine Verbindung zum Programm: " + error.message};
  }
}

const state = {settings: {}, choices: {}, running: false, lastLog: 0, generation: 0, lines: 0,
  auth: "in", user: null, polling: false};

function toast(text, bad = false) {
  const box = $("#toast");
  box.textContent = text;
  box.className = "show" + (bad ? " bad" : "");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => box.className = "", 3200);
}
async function must(method, ...args) {
  const result = await call(method, ...args);
  if (!result.ok) toast(result.error, true);
  return result;
}

function show(view) {
  for (const id of ["auth", "loading", "main", "tool"]) $("#view-" + id).hidden = id !== view;
}

const loot = n => n >= 1e9 ? (n / 1e9).toFixed(1) + " Mrd" : n >= 1e6 ? (n / 1e6).toFixed(1).replace(".", ",") + " Mio"
  : n >= 1e4 ? Math.round(n / 1e3) + "k" : String(n);
const duration = s => s >= 3600 ? `${Math.floor(s / 3600)}h ${Math.floor(s % 3600 / 60)}m` : `${Math.floor(s / 60)}m`;
const formats = {loot, sec: n => n + " s", secoff: n => +n ? n + " s" : "aus"};

function option(value, label) { return new Option(label, value); }

function paintSlider(input) {
  const min = +input.min, max = +input.max;
  input.style.setProperty("--fill", ((input.value - min) / (max - min) * 100) + "%");
  const out = input.closest("label").querySelector("output");
  if (out) out.textContent = formats[input.dataset.format](+input.value);
}

function applySettings(settings) {
  state.settings = settings;
  for (const el of $$("[data-setting]")) {
    const value = settings[el.dataset.setting];
    if (el.type === "checkbox") el.checked = value;
    else if (document.activeElement !== el) el.value = value;
    if (el.type === "range") paintSlider(el);
  }
  for (const group of $$("[data-segment]"))
    for (const b of $$("button", group)) b.classList.toggle("on", b.dataset.value === settings[group.dataset.segment]);
  $("#adb-path").textContent = settings.adb_path || "automatisch";
  $$("#slot-roles select").forEach((s, i) => s.value = settings.slot_roles[i]);
}

async function save(key, value) {
  const result = await must("save_setting", key, value);
  applySettings(result.ok ? result.settings : state.settings);
}

// ---------- Anmeldung ----------
function authMode(mode) {
  state.auth = mode;
  $$("#auth-tabs button").forEach(b => b.classList.toggle("on", b.dataset.auth === mode));
  $("#auth-title").textContent = mode === "in" ? "Willkommen zurück" : "Profil anlegen";
  $("#auth-submit").textContent = mode === "in" ? "Los geht's" : "Registrieren";
  $("#auth-error").textContent = "";
}

async function enter(user) {
  state.user = user;
  show("main");
  go("home");
  await call("set_size", "normal");
  if (!state.polling) { state.polling = true; poll(); }
  refreshDevices();
}

$("#auth-form").addEventListener("submit", async event => {
  event.preventDefault();
  const submit = $("#auth-submit");
  submit.disabled = true;
  const result = await call(state.auth === "in" ? "sign_in" : "sign_up",
    $("#auth-name").value, $("#auth-pass").value, $("#auth-remember").checked);
  submit.disabled = false;
  if (!result.ok) { $("#auth-error").textContent = result.error; return; }
  $("#auth-pass").value = "";
  enter(result.user);
});
$$("#auth-tabs button").forEach(b => b.onclick = () => authMode(b.dataset.auth));
$("#peek").onclick = () => {
  const input = $("#auth-pass"), hidden = input.type === "password";
  input.type = hidden ? "text" : "password";
  $("#peek").textContent = hidden ? "verbergen" : "zeigen";
};

// ---------- Navigation ----------
function go(page) {
  $$(".page").forEach(p => p.hidden = p.dataset.page !== page);
  $$("nav button").forEach(b => b.classList.toggle("on", b.dataset.nav === page));
  if (page === "profile") loadProfile();
  if (page === "log" && $("#autoscroll").checked) $("#log").scrollTop = $("#log").scrollHeight;
}
$$("nav button").forEach(b => b.onclick = () => go(b.dataset.nav));
$$("[data-action]").forEach(b => b.onclick = () => call(b.dataset.action));

// ---------- Laufende Anzeige ----------
async function poll() {
  if (!state.user) { state.polling = false; return; }
  const data = await call("poll", state.lastLog, state.generation);
  if (data.ok) {
    state.running = data.running;
    $("#view-main").classList.toggle("running", data.running);
    $("#power-label").textContent = data.running ? "Stoppen" : "Starten";
    $("#power").setAttribute("aria-label", data.running ? "Bot stoppen" : "Bot starten");
    $("#status").textContent = data.status;
    $("#bot-error").textContent = data.running ? "" : data.error;
    for (const key of ["gold", "elixir", "dark", "attacks", "walls"])
      $("#s-" + key).textContent = loot(data.session[key]);
    $("#s-runtime").textContent = duration(data.session.runtime);
    $("#device").disabled = data.running;
    if (data.generation !== state.generation) { $("#log").textContent = ""; state.lines = 0; state.lastLog = 0; state.generation = data.generation; }
    appendLog(data.log);
    const banner = $("#update-banner");
    banner.hidden = !data.update;
    if (data.update && !banner.disabled) banner.textContent = `Version ${data.update} installieren`;
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
  $("#line-count").textContent = state.lines === 1 ? "1 Zeile" : `${state.lines} Zeilen`;
  if (lines.length && $("#autoscroll").checked) box.scrollTop = box.scrollHeight;
}

$("#power").onclick = async () => {
  const button = $("#power");
  button.disabled = true;
  await must(state.running ? "stop" : "start");
  button.disabled = false;
};
$("#clear-log").onclick = () => call("clear_log");

// ---------- Geraete & Einstellungen ----------
async function refreshDevices(method = "devices") {
  const select = $("#device");
  select.replaceChildren(option("", "Suche…"));
  const result = await call(method);
  select.replaceChildren();
  if (!result.ok) { select.append(option("", "adb nicht gefunden")); if (method !== "devices") toast(result.error, true); return; }
  if (!result.devices.length) select.append(option("", "Kein Gerät"));
  for (const d of result.devices)
    select.append(option(d.serial, d.state === "device" ? d.serial : `${d.serial} (${d.state})`));
  if (result.selected) select.value = result.selected;
  $("#adb-path").textContent = state.settings.adb_path || result.adb;
}
$("#refresh").onclick = () => refreshDevices();
$("#restart-adb").onclick = () => refreshDevices("restart_adb");
$("#device").onchange = e => save("device", e.target.value);
$("#pick-adb").onclick = async () => { const r = await must("pick_adb"); if (r.ok) { applySettings(r.settings); refreshDevices(); } };

for (const el of $$("[data-setting]")) {
  if (el.type === "range") el.addEventListener("input", () => paintSlider(el));
  el.addEventListener("change", () => save(el.dataset.setting,
    el.type === "checkbox" ? el.checked : el.type === "number" || el.type === "range" ? Number(el.value) : el.value));
}
for (const group of $$("[data-segment]"))
  for (const b of $$("button", group)) b.onclick = () => save(group.dataset.segment, b.dataset.value);

// ---------- Profil ----------
async function loadProfile() {
  const result = await must("account");
  if (!result.ok) return;
  $("#p-name").textContent = result.name;
  $("#avatar").textContent = result.name[0].toUpperCase();
  $("#p-since").textContent = result.created ? "Dabei seit " + new Date(result.created * 1000).toLocaleDateString("de-DE") : "";
  for (const key of ["gold", "elixir", "dark", "attacks", "walls"]) $("#t-" + key).textContent = loot(result.lifetime[key]);
  $("#t-runtime").textContent = duration(result.lifetime.runtime);
}
$("#sign-out").onclick = async () => {
  await call("sign_out");
  state.user = null;
  authMode("in");
  show("auth");
};
$("#test-webhook").onclick = async () => { if ((await must("test_webhook")).ok) toast("Testmeldung gesendet."); };
$("#check-update").onclick = async () => {
  const r = await must("check_update");
  if (r.ok) toast(r.update ? `Version ${r.update} ist verfügbar.` : "Du hast die neueste Version.");
};
$("#open-folder").onclick = () => must("open_data_folder");
$("#update-banner").onclick = async e => {
  const banner = e.currentTarget;
  banner.disabled = true;
  banner.textContent = "Update wird geladen…";
  const r = await must("install_update");
  if (r.ok) banner.textContent = "Neustart…"; else banner.disabled = false;
};

// ---------- Einrichtungs-Werkzeug ----------
const canvas = $("#canvas"), ctx = canvas.getContext("2d");
const tool = {tab: "test", image: null, rect: null, drag: null, sides: {}, marks: null, first: null};
const roleNames = {auto: "Automatisch", troop: "Truppe", hero: "Held", siege: "Belagerung", spell: "Zauber", event: "Event", skip: "Auslassen"};

function draw() {
  const w = canvas.width, h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  if (!tool.image) return;
  ctx.drawImage(tool.image, 0, 0, w, h);
  const unit = w / 1280;
  ctx.lineWidth = 3 * unit;
  ctx.font = `bold ${18 * unit}px Segoe UI, sans-serif`;
  const label = (text, x, y, color) => {
    const width = ctx.measureText(text).width + 12 * unit;
    x = Math.max(0, Math.min(w - width, x - width / 2));
    ctx.fillStyle = "#0d111fdd"; ctx.fillRect(x, y - 20 * unit, width, 26 * unit);
    ctx.fillStyle = color; ctx.fillText(text, x + 6 * unit, y);
  };
  const dot = (x, y, color) => { ctx.fillStyle = color; ctx.beginPath(); ctx.arc(x, y, 7 * unit, 0, 7); ctx.fill(); };
  if (tool.tab === "test" && tool.marks) {
    for (const b of tool.marks.buttons) { dot(b.x * w, b.y * h, "#4ade9a"); label(b.title, b.x * w, b.y * h - 16 * unit, "#4ade9a"); }
    tool.marks.slots.forEach((s, i) => { dot(s.x * w, s.y * h, "#ff9f43"); label(roleNames[s.role], s.x * w, s.y * h - (i % 2 ? 100 : 74) * unit, "#ff9f43"); });
  }
  if (tool.tab === "sides") {
    for (const [key, line] of Object.entries(tool.sides)) {
      const active = key === $("#side-name").value;
      ctx.strokeStyle = active ? "#ff9f43" : "#ffffff88";
      ctx.beginPath(); ctx.moveTo(line[0][0] * w, line[0][1] * h); ctx.lineTo(line[1][0] * w, line[1][1] * h); ctx.stroke();
      line.forEach(p => dot(p[0] * w, p[1] * h, ctx.strokeStyle));
    }
    if (tool.first) dot(tool.first[0] * w, tool.first[1] * h, "#4ade9a");
  }
  if ((tool.tab === "button" || tool.tab === "troop") && tool.rect) {
    const [x0, y0, x1, y1] = tool.rect;
    ctx.strokeStyle = "#ff9f43"; ctx.strokeRect(x0 * w, y0 * h, (x1 - x0) * w, (y1 - y0) * h);
  }
}

function pointer(event) {
  const box = canvas.getBoundingClientRect();
  const clamp = v => Math.min(1, Math.max(0, v));
  return [clamp((event.clientX - box.left) / box.width), clamp((event.clientY - box.top) / box.height)];
}
canvas.addEventListener("pointerdown", async event => {
  if (!tool.image) return;
  const p = pointer(event);
  if (tool.tab === "sides") {
    if (!tool.first) { tool.first = p; $("#tool-hint").textContent = "Jetzt das Ende der Linie anklicken."; }
    else {
      const r = await must("set_side", $("#side-name").value, tool.first, p);
      tool.first = null;
      if (r.ok) { tool.sides = r.sides; $("#tool-hint").textContent = "Linie gespeichert."; }
    }
    return draw();
  }
  if (tool.tab === "button" || tool.tab === "troop") { tool.drag = p; tool.rect = null; canvas.setPointerCapture(event.pointerId); }
});
canvas.addEventListener("pointermove", event => {
  if (!tool.drag) return;
  const p = pointer(event), s = tool.drag;
  tool.rect = [Math.min(s[0], p[0]), Math.min(s[1], p[1]), Math.max(s[0], p[0]), Math.max(s[1], p[1])];
  draw();
});
canvas.addEventListener("pointerup", () => tool.drag = null);

async function busy(button, text, work) {
  const old = button.textContent;
  button.disabled = true; button.textContent = text; $("#tool-error").textContent = "";
  const result = await work();
  button.disabled = false; button.textContent = old;
  if (result && !result.ok) $("#tool-error").textContent = result.error;
  return result;
}

$("#capture").onclick = e => busy(e.currentTarget, "Nimmt auf…", async () => {
  const r = await call("capture");
  if (!r.ok) return r;
  const image = new Image();
  image.src = r.image;
  await image.decode();
  Object.assign(tool, {image, rect: null, marks: null, first: null});
  canvas.width = r.width; canvas.height = r.height;
  $("#result").replaceChildren();
  $("#tool-hint").textContent = `${r.width} × ${r.height}`;
  draw();
  return r;
});

$("#analyze").onclick = e => busy(e.currentTarget, "Prüft…", async () => {
  const r = await call("analyze");
  if (!r.ok) return r;
  tool.marks = r;
  const rows = [r.buttons.length ? "Knöpfe: " + r.buttons.map(b => b.title).join(", ") : "Keine Knöpfe erkannt."];
  if (r.loot) rows.push(`Gegnerbeute: ${loot(r.loot[0])} Gold, ${loot(r.loot[1])} Elixier, ${loot(r.loot[2])} Dunkles`);
  if (r.storage) rows.push(`Dein Lager: ${loot(r.storage[0])} Gold, ${loot(r.storage[1])} Elixier`);
  if (r.slots.length) rows.push("Leiste: " + r.slots.map((s, i) => `${i + 1}. ${roleNames[s.role]}${s.count != null ? " ×" + s.count : ""}`).join(" · "));
  $("#result").replaceChildren(...rows.map(text => Object.assign(document.createElement("div"), {textContent: text})));
  draw();
  return r;
});
$("#diagnose").onclick = e => busy(e.currentTarget, "Speichert…", async () => {
  const r = await call("save_diagnostics");
  if (r.ok) toast("Gespeichert unter " + r.folder);
  return r;
});

function listTemplates(templates) {
  for (const box of $$(".templates")) {
    const kinds = box.dataset.kinds.split(" ");
    box.replaceChildren(...templates.filter(t => kinds.includes(t.kind)).map(t => {
      const row = document.createElement("div"), name = document.createElement("span"), remove = document.createElement("button");
      name.textContent = t.kind === "button" ? state.buttons[t.name] || t.name : (t.kind === "event" ? "Event: " : "") + t.name;
      remove.textContent = "Löschen";
      remove.onclick = async () => { const r = await must("delete_template", t.file); if (r.ok) listTemplates(r.templates); };
      row.append(name, remove);
      return row;
    }));
  }
}
async function saveTemplate(kind, name) {
  $("#tool-error").textContent = "";
  if (!tool.rect) { $("#tool-error").textContent = "Rahme zuerst etwas im Bild ein."; return; }
  const r = await call("add_template", kind, name, tool.rect);
  if (!r.ok) { $("#tool-error").textContent = r.error; return; }
  tool.rect = null; draw(); listTemplates(r.templates); toast("Gespeichert.");
}
$("#save-button").onclick = () => saveTemplate("button", $("#button-name").value);
$("#save-troop").onclick = () => saveTemplate($("#troop-kind").value, $("#troop-army").selectedOptions[0].textContent);

$$("#tool-tabs button").forEach(b => b.onclick = () => {
  tool.tab = b.dataset.tool; tool.rect = null; tool.first = null;
  $$("#tool-tabs button").forEach(x => x.classList.toggle("on", x === b));
  $$("[data-panel]").forEach(p => p.hidden = p.dataset.panel !== tool.tab);
  $("#tool-error").textContent = "";
  draw();
});
$("#side-name").onchange = () => { tool.first = null; draw(); };
$("#reset-sides").onclick = async () => { const r = await must("reset_sides"); if (r.ok) { tool.sides = r.sides; draw(); } };
$("#open-tool").onclick = async () => {
  await call("set_size", "wide");
  show("tool");
  const r = await must("layout_info");
  if (r.ok) { tool.sides = r.sides; listTemplates(r.templates); draw(); }
};
$("#close-tool").onclick = async () => { await call("set_size", "normal"); show("main"); };

// ---------- Start ----------
async function boot() {
  const data = await call("boot");
  if (!data.ok) { toast(data.error, true); return; }
  state.buttons = data.buttons;
  $("#version").textContent = "v" + data.version;
  for (const [name, entries] of Object.entries(data.choices))
    for (const select of $$(`select[data-setting="${name}"]`))
      select.replaceChildren(...Object.entries(entries).map(([v, l]) => option(v, l)));
  $("#button-name").replaceChildren(...Object.entries(data.buttons).map(([v, l]) => option(v, l)));
  $("#troop-army").replaceChildren(...Object.entries(data.choices.army).filter(([v]) => v !== "all").map(([v, l]) => option(v, l)));
  $("#slot-roles").replaceChildren(...data.settings.slot_roles.map((_, i) => {
    const label = document.createElement("label"), select = document.createElement("select");
    select.append(...Object.entries(roleNames).map(([v, l]) => option(v, l)));
    select.onchange = () => { const roles = [...state.settings.slot_roles]; roles[i] = select.value; save("slot_roles", roles); };
    label.append(`Platz ${i + 1}`, select);
    return label;
  }));
  applySettings(data.settings);
  if (data.user) enter(data.user);
  else { authMode(data.has_users ? "in" : "up"); show("auth"); }
}
boot();
