// activity.js — journal d'activité en direct + réglages (notifications, IA) + mesures système.
"use strict";

(() => {
  const esc = HSC.esc;
  const feed = document.getElementById("feed");
  const MAX = 150;
  let items = []; // {key, kind, ts, ...}
  const runs = new Map();

  const time = (ts) => new Date(ts * 1000).toLocaleTimeString("fr-FR");

  function add(event) {
    if (event.kind === "gesture" || event.kind === "gesture_blocked" || event.kind === "drawing") {
      items.push({ ...event });
    } else if (event.kind === "action_start") {
      const run = { ...event, kind: "run", steps: [], done: false };
      runs.set(event.run_id, run);
      items.push(run);
    } else if (event.kind === "step") {
      const run = runs.get(event.run_id);
      if (run) run.steps.push(event);
    } else if (event.kind === "action_end") {
      const run = runs.get(event.run_id);
      if (run) Object.assign(run, { done: true, ok: event.ok, ms: event.ms, errors: event.errors });
    } else if (event.kind === "log") {
      const run = [...runs.values()].pop();
      if (run && !run.done) run.steps.push({ ...event, status: "log", label: "Journal" });
    }
    if (items.length > MAX) items = items.slice(-MAX);
  }

  function itemHtml(it) {
    if (it.kind === "gesture") {
      const value = it.value !== null && it.value !== undefined && it.value !== "" ? ` · valeur <b>${esc(it.value)}</b>` : "";
      return `<div class="card p-3 flex items-center gap-3 border-l-2 border-l-primary">
        <span class="cat-chip cat-logic w-8 h-8 rounded-lg flex items-center justify-center bg-primary/15 text-accent">${HSC.icon("hand", "w-[18px] h-[18px]")}</span>
        <div class="flex-1 text-sm">Geste <b>${esc(it.gesture)}</b>${value}${it.action ? ` → ${esc(it.action)}` : " (aucune action liée)"}</div>
        <span class="text-xs font-mono text-on-surface-variant">${time(it.ts)}</span></div>`;
    }
    if (it.kind === "gesture_blocked") {
      return `<div class="card p-3 flex items-center gap-3 border-l-2 border-l-warning">
        <span class="w-8 h-8 rounded-lg flex items-center justify-center bg-warning/15 text-warning">${HSC.icon("shield-alert", "w-[18px] h-[18px]")}</span>
        <div class="flex-1 text-sm">Geste <b>${esc(it.gesture)}</b> reconnu mais bloqué : ${esc((it.reasons || []).join(" · "))}</div>
        <span class="text-xs font-mono text-on-surface-variant">${time(it.ts)}</span></div>`;
    }
    if (it.kind === "drawing") {
      const ok = it.label;
      return `<div class="card p-3 flex items-center gap-3 border-l-2 ${ok ? "border-l-success" : "border-l-outline-strong"}">
        <span class="w-8 h-8 rounded-lg flex items-center justify-center bg-white/5">${HSC.icon("pencil", "w-[18px] h-[18px]")}</span>
        <div class="flex-1 text-sm">${ok ? `Dessin reconnu : <b>${esc(it.label)}</b> (${Math.round(it.confidence * 100)} %, ${esc(it.source)})` : "Dessin non reconnu"}
          ${(it.candidates || []).length ? `<span class="text-xs text-on-surface-variant"> — ${it.candidates.map((c) => `${esc(c.label)} ${Math.round(c.confidence * 100)} %`).join(", ")}</span>` : ""}</div>
        <span class="text-xs font-mono text-on-surface-variant">${time(it.ts)}</span></div>`;
    }
    const state = !it.done ? "en cours" : it.ok ? "terminé" : `${it.errors} erreur(s)`;
    const color = !it.done ? "text-warning" : it.ok ? "text-success" : "text-error";
    return `<details class="card p-3"><summary class="flex items-center gap-3 cursor-pointer list-none">
        <span class="w-8 h-8 rounded-lg flex items-center justify-center bg-white/5 ${color}">${HSC.icon(it.ok === false ? "circle-alert" : "workflow", "w-[18px] h-[18px]")}</span>
        <div class="flex-1 text-sm">Workflow <b>${esc(it.action)}</b>${it.trigger ? ` <span class="text-on-surface-variant">(${esc(it.trigger)})</span>` : ""}
          <span class="${color} text-xs font-mono ml-2">${state}${it.ms !== undefined ? ` · ${HSC.fmtMs(it.ms)}` : ""}</span></div>
        <span class="text-xs font-mono text-on-surface-variant">${time(it.ts)}</span></summary>
      <div class="mt-3 pl-11 space-y-1 font-mono text-xs">${it.steps.map((s) => s.status === "log"
        ? `<div class="text-on-surface-variant">› ${esc(s.message)}</div>`
        : `<div class="${s.status === "error" ? "text-error" : s.status === "skipped" ? "text-on-surface-variant/60" : "text-on-surface-variant"}">${esc(s.label)} · ${esc(s.status)} · ${HSC.fmtMs(s.ms)}${s.output ? ` → ${esc(s.output)}` : ""}${(s.errors || []).length ? ` — ${esc(s.errors.join(" | "))}` : ""}</div>`).join("") || "<div class='text-on-surface-variant'>Aucun détail.</div>"}</div></details>`;
  }

  function render() {
    feed.innerHTML = items.slice().reverse().map(itemHtml).join("");
    document.getElementById("feed-empty").classList.toggle("hidden", items.length > 0);
  }

  document.addEventListener("hsc-events", (event) => { event.detail.forEach(add); render(); });
  document.getElementById("btn-clear").addEventListener("click", () => { items = []; runs.clear(); render(); });

  // --- réglages ---
  async function loadSettings() {
    const settings = await HSC.api("GET", "/api/settings");
    document.querySelectorAll("[data-setting]").forEach((sw) => sw.setAttribute("aria-checked", settings[sw.dataset.setting] ? "true" : "false"));
    document.querySelectorAll("[data-setting-text]").forEach((input) => { input.value = settings[input.dataset.settingText] || ""; });
  }
  async function patch(body) {
    try {
      await HSC.api("PATCH", "/api/settings", body);
      appSettings = { ...appSettings, ...body };
      HSC.toast("Réglage enregistré.", "success");
    } catch (err) { HSC.toast(err.message, "error"); }
  }
  document.addEventListener("click", (event) => {
    const sw = event.target.closest("[data-setting]");
    if (!sw) return;
    const on = sw.getAttribute("aria-checked") !== "true";
    sw.setAttribute("aria-checked", on ? "true" : "false");
    patch({ [sw.dataset.setting]: on });
  });
  document.addEventListener("change", (event) => {
    const input = event.target.closest("[data-setting-text]");
    if (input) patch({ [input.dataset.settingText]: input.value.trim() });
  });

  // --- mesures ---
  const LABELS = { uptime_minutes: ["Allumé depuis", "min"], cpu_percent: ["Processeur", "%"], cpu_temp_c: ["Température CPU", "°C"],
    ram_percent: ["Mémoire", "%"], disk_percent: ["Disque", "%"], load_1m: ["Charge (1 min)", ""], battery_percent: ["Batterie", "%"],
    on_battery: ["Sur batterie", ""], hour: ["Heure", "h"], weekday: ["Jour (1 = lundi)", ""],
    idle_minutes: ["Inactivité", "min"], ambient_light_lux: ["Lumière", "lux"], gpu_temp_c: ["Température GPU", "°C"], fan_rpm: ["Ventilateur", "tr/min"], lid_closed: ["Capot fermé", ""] };
  async function loadMetrics() {
    try {
      const { values } = await HSC.api("GET", "/api/system/metrics");
      document.getElementById("metrics").innerHTML = Object.entries(LABELS).map(([k, [label, unit]]) => {
        const v = values[k];
        const shown = v === null || v === undefined ? "indisponible" : typeof v === "boolean" ? (v ? "oui" : "non") : `${Math.round(v * 10) / 10} ${unit}`;
        return `<div class="flex justify-between"><span class="text-on-surface-variant">${label}</span><span>${shown}</span></div>`;
      }).join("");
    } catch { /* ignore */ }
  }

  // --- capteurs ---
  async function loadSensors() {
    try {
      const [{ items }, st] = await Promise.all([HSC.api("GET", "/api/sensors/report"), HSC.api("GET", "/api/sensors/status")]);
      document.getElementById("sensor-report").innerHTML = items.map((i) => `<div class="flex items-start gap-2">
        <span class="mt-1 w-2 h-2 rounded-full shrink-0 ${i.present ? "bg-success" : "bg-outline"}"></span>
        <div><div>${HSC.esc(i.label)}</div><div class="field-hint">${HSC.esc(i.detail)}</div></div></div>`).join("");
      document.getElementById("sensor-errors").innerHTML = Object.entries(st.errors || {}).map(([k, v]) => `<div>⚠ ${HSC.esc(k)} : ${HSC.esc(v)}</div>`).join("");
      document.getElementById("external-values").innerHTML = Object.entries(st.external || {}).map(([name, s]) =>
        `<div class="flex justify-between"><span class="text-on-surface-variant">${HSC.esc(name)}</span><span>${s.value === null ? (s.error ? "⚠ " + HSC.esc(s.error) : "—") : `${s.value} ${HSC.esc(s.unit || "")}`}</span></div>`).join("");
    } catch { /* ignore */ }
  }
  async function loadExternal() {
    try {
      const { sensors } = await HSC.api("GET", "/api/sensors/external");
      document.getElementById("external-json").value = JSON.stringify(sensors, null, 2);
    } catch { /* ignore */ }
  }
  document.getElementById("btn-save-external").addEventListener("click", async () => {
    let parsed;
    try { parsed = JSON.parse(document.getElementById("external-json").value || "[]"); }
    catch { HSC.toast("JSON invalide.", "error"); return; }
    try {
      const reply = await HSC.api("PUT", "/api/sensors/external", { sensors: parsed });
      document.getElementById("external-json").value = JSON.stringify(reply.sensors, null, 2);
      HSC.toast("Capteurs externes enregistrés.", "success");
      loadSensors();
    } catch (err) { HSC.toast(err.message, "error"); }
  });

  (async () => {
    document.body.dataset.noToasts = ""; // le journal est déjà sous les yeux : pas de bulles en double
    try {
      const reply = await HSC.api("GET", "/api/events?since=0");
      reply.events.forEach(add);
      render();
    } catch { /* ignore */ }
    loadSettings();
    loadMetrics();
    setInterval(loadMetrics, 5000);
    loadExternal();
    loadSensors();
    setInterval(loadSensors, 5000);
  })();
})();
