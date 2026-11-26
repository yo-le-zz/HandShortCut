// main.js — utilitaires partagés par toutes les pages (aucune dépendance).
"use strict";

const HSC = {
  /** Échappe une valeur avant insertion dans du HTML. */
  esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (c) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
    ));
  },

  /** Icône Lucide du sprite /static/icons.svg. */
  icon(name, cls = "") {
    return `<svg class="icon ${cls}" aria-hidden="true"><use href="/static/icons.svg#${name}"/></svg>`;
  },

  /** Durée lisible en secondes ET millisecondes : « 0,27 s (270 ms) ». */
  fmtMs(value) {
    const ms = Math.round(Number(value));
    if (!Number.isFinite(ms)) return "—";
    const seconds = String(Math.round(ms / 10) / 100).replace(".", ",");
    return `${seconds} s (${ms.toLocaleString("fr-FR")} ms)`;
  },

  fmtSeconds(value) {
    return HSC.fmtMs(Number(value) * 1000);
  },

  /** Appel JSON vers l'API ; lève une Error avec le message du serveur. */
  async api(method, url, body, options = {}) {
    const response = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json", "X-PhysicalShortCut": "1" },
      body: body === undefined ? undefined : JSON.stringify(body),
      ...options,
    });
    let data = null;
    try { data = await response.json(); } catch { /* corps vide */ }
    if (!response.ok || (data && data.ok === false)) {
      throw new Error((data && data.error) || `Erreur ${response.status}`);
    }
    return data;
  },

  /** Notification empilée en bas à droite. */
  toast(message, kind = "info", options = {}) {
    const colors = { info: "border-outline-strong", success: "border-success", error: "border-error", gesture: "border-primary" };
    const icons = { info: "lightbulb", success: "circle-check", error: "circle-alert", gesture: "hand" };
    let stack = document.getElementById("toast-stack");
    if (!stack) {
      stack = document.createElement("div");
      stack.id = "toast-stack";
      stack.className = "toast-stack";
      document.body.appendChild(stack);
    }
    const el = document.createElement("div");
    el.setAttribute("role", kind === "error" ? "alert" : "status");
    el.className = `toast-card ${colors[kind] || colors.info}`;
    const title = options.title ? `<div class="font-medium">${HSC.esc(options.title)}</div>` : "";
    el.innerHTML = `${HSC.icon(options.icon || icons[kind] || icons.info, "mt-0.5")}<div>${title}<span>${HSC.esc(message)}</span></div>`;
    stack.appendChild(el);
    while (stack.children.length > 5) stack.firstChild.remove();
    setTimeout(() => el.remove(), options.ms || (kind === "error" ? 6000 : 3000));
  },
};

// --- état de la caméra (pastille de l'en-tête + éventuels éléments de page) ---
const CAMERA_STATES = {
  ok: { label: "Caméra active", dot: "bg-success", text: "text-success" },
  starting: { label: "Démarrage…", dot: "bg-warning", text: "text-warning" },
  error: { label: "Caméra indisponible", dot: "bg-error", text: "text-error" },
  stopped: { label: "Arrêtée", dot: "bg-on-surface-variant", text: "text-on-surface-variant" },
};
const DOT_CLASSES = ["bg-success", "bg-warning", "bg-error", "bg-on-surface-variant"];

async function refreshStatus() {
  let engine = { camera: "error", error: "Serveur injoignable." };
  try {
    engine = (await HSC.api("GET", "/api/status")).engine;
  } catch { /* on garde l'état d'erreur */ }
  const state = CAMERA_STATES[engine.camera] || CAMERA_STATES.error;

  document.querySelectorAll("[data-camera-dot]").forEach((el) => {
    el.classList.remove(...DOT_CLASSES);
    el.classList.add(state.dot);
  });
  document.querySelectorAll("[data-camera-label]").forEach((el) => { el.textContent = state.label; });
  document.querySelectorAll("[data-fps]").forEach((el) => {
    el.textContent = engine.camera === "ok" && engine.fps > 0
      ? `${String(engine.fps).replace(".", ",")} img/s · ${Math.round(1000 / engine.fps)} ms`
      : "—";
  });
  document.querySelectorAll("[data-camera-badge]").forEach((el) => { el.title = engine.error || ""; });
  document.querySelectorAll("[data-camera-text]").forEach((el) => {
    el.className = `flex items-center gap-1.5 ${state.text}`;
    el.textContent = state.label.replace("Caméra ", "");
    el.title = engine.error || "";
  });
  document.dispatchEvent(new CustomEvent("camera-status", { detail: engine }));
}

document.addEventListener("DOMContentLoaded", () => {
  refreshStatus();
  setInterval(refreshStatus, 3000);
  startActivityToasts();
});

// --- notifications en direct : geste reconnu, action lancée, erreurs (journal /api/events) ---
let lastEventId = null;
let appSettings = { notify_in_app: true, notify_errors: true };

async function startActivityToasts() {
  try {
    appSettings = await HSC.api("GET", "/api/settings");
    lastEventId = (await HSC.api("GET", "/api/events?since=999999999")).last_id;
  } catch { return; }
  setInterval(async () => {
    try {
      const reply = await HSC.api("GET", `/api/events?since=${lastEventId}`);
      lastEventId = reply.last_id || lastEventId;
      reply.events.forEach(handleEvent);
      if (reply.events.length) document.dispatchEvent(new CustomEvent("hsc-events", { detail: reply.events }));
    } catch { /* serveur arrêté : on réessaie */ }
  }, 1000);
}

function handleEvent(event) {
  if (document.body.dataset.noToasts !== undefined) return;
  if (event.kind === "gesture" && appSettings.notify_in_app) {
    const value = event.value !== null && event.value !== undefined && event.value !== "" ? ` · valeur ${event.value}` : "";
    HSC.toast(event.action ? `Action : ${event.action}${value}` : `Aucune action liée${value}`, "gesture", { title: `Geste « ${event.gesture} »`, ms: 3500 });
  } else if (event.kind === "gesture_blocked" && appSettings.notify_in_app) {
    HSC.toast((event.reasons || []).join(" · "), "info", { title: `« ${event.gesture} » bloqué`, icon: "shield-alert", ms: 4000 });
  } else if (event.kind === "drawing" && appSettings.notify_in_app) {
    HSC.toast(event.label ? `${event.label} (${Math.round(event.confidence * 100)} %)` : "Dessin non reconnu", "info", { title: "Dessin", icon: "pencil" });
  } else if (event.kind === "action_end" && event.ok === false && appSettings.notify_errors) {
    HSC.toast(`${event.errors} erreur(s) dans « ${event.action} »`, "error", { title: "Workflow en erreur" });
  }
}


// --- import d'une configuration exportée (barre latérale) ---
document.addEventListener("click", (event) => {
  if (event.target.closest("[data-import-open]")) document.querySelector("[data-import-file]").click();
});
document.addEventListener("change", async (event) => {
  const input = event.target.closest("[data-import-file]");
  if (!input || !input.files.length) return;
  const file = input.files[0];
  input.value = "";
  try {
    const bundle = JSON.parse(await file.text());
    const gestures = (bundle.gestures || []).length;
    const actions = (bundle.actions || []).length;
    if (!confirm(`Importer ${gestures} geste(s) et ${actions} action(s) ?\nLes éléments de même identifiant seront remplacés.`)) return;
    const result = await HSC.api("POST", "/api/import", { bundle });
    const conv = result.conversion || {};
    const note = conv.converted ? ` Converti de ${conv.source_os} vers ${conv.target_os} (${(conv.notes || []).length} adaptation(s)).` : "";
    HSC.toast(`Configuration importée.${note}`, "success", { ms: conv.converted ? 6000 : 3000 });
    if (conv.converted && (conv.notes || []).length) console.info("Conversion :\n" + conv.notes.join("\n"));
    setTimeout(() => location.reload(), conv.converted ? 2500 : 600);
  } catch (err) {
    HSC.toast(`Import impossible : ${err.message}`, "error");
  }
});
