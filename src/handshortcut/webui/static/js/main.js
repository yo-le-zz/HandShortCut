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
      headers: { "Content-Type": "application/json", "X-HandShortCut": "1" },
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

  /** Petite notification en bas à droite. */
  toast(message, kind = "info") {
    const colors = { info: "border-outline-strong", success: "border-success", error: "border-error" };
    const icons = { info: "lightbulb", success: "circle-check", error: "circle-alert" };
    const el = document.createElement("div");
    el.setAttribute("role", kind === "error" ? "alert" : "status");
    el.className = `fixed bottom-6 right-6 z-50 max-w-sm flex items-start gap-2.5 bg-surface-high border ${colors[kind]} rounded-lg px-4 py-3 text-sm shadow-glow`;
    el.innerHTML = `${HSC.icon(icons[kind], "mt-0.5")}<span>${HSC.esc(message)}</span>`;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), kind === "error" ? 6000 : 3000);
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
});


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
    await HSC.api("POST", "/api/import", { bundle });
    HSC.toast("Configuration importée.", "success");
    setTimeout(() => location.reload(), 600);
  } catch (err) {
    HSC.toast(`Import impossible : ${err.message}`, "error");
  }
});
