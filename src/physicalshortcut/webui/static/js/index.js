// index.js — tableau de bord : suppression, duplication, test, liaison geste -> action, mesures live.
"use strict";

document.addEventListener("click", async (event) => {
  const del = event.target.closest("[data-delete-gesture], [data-delete-action]");
  if (del) {
    const isGesture = del.hasAttribute("data-delete-gesture");
    const id = del.dataset.deleteGesture || del.dataset.deleteAction;
    if (!confirm(isGesture ? "Supprimer ce geste ?" : "Supprimer cette action ?")) return;
    try {
      await HSC.api("DELETE", `/api/${isGesture ? "gestures" : "actions"}/${encodeURIComponent(id)}`);
      location.reload();
    } catch (err) {
      HSC.toast(err.message, "error");
    }
    return;
  }

  const dup = event.target.closest("[data-duplicate-gesture], [data-duplicate-action]");
  if (dup) {
    const isGesture = dup.hasAttribute("data-duplicate-gesture");
    const id = dup.dataset.duplicateGesture || dup.dataset.duplicateAction;
    try {
      await HSC.api("POST", `/api/${isGesture ? "gestures" : "actions"}/${encodeURIComponent(id)}/duplicate`);
      location.reload();
    } catch (err) {
      HSC.toast(err.message, "error");
    }
    return;
  }

  const run = event.target.closest("[data-run-action]");
  if (run) {
    try {
      await HSC.api("POST", `/api/actions/${encodeURIComponent(run.dataset.runAction)}/run`);
      HSC.toast("Action lancée.", "success");
    } catch (err) {
      HSC.toast(err.message, "error");
    }
  }
});

document.addEventListener("change", async (event) => {
  const select = event.target.closest("[data-gesture-action]");
  if (!select) return;
  try {
    await HSC.api("PATCH", `/api/gestures/${encodeURIComponent(select.dataset.gestureAction)}`, {
      action_id: select.value || null,
    });
    HSC.toast("Liaison enregistrée.", "success");
  } catch (err) {
    HSC.toast(err.message, "error");
  }
});

// Barres de distance en direct : se remplissent quand la main s'éloigne du geste.
async function pollScores() {
  try {
    const { scores } = await HSC.api("GET", "/api/live");
    document.querySelectorAll("[data-live-meter]").forEach((meter) => {
      const score = scores[meter.dataset.liveMeter];
      meter.classList.toggle("hidden", !score);
      if (!score) return;
      const limit = Math.max(score.threshold * 2, 0.001);
      meter.firstElementChild.style.width = `${Math.min(100, (score.distance / limit) * 100)}%`;
      meter.firstElementChild.classList.toggle("over", score.distance > score.threshold);
      meter.lastElementChild.style.left = `${(score.threshold / limit) * 100}%`;
    });
  } catch { /* serveur indisponible */ }
}
if (document.querySelector("[data-live-meter]")) setInterval(pollScores, 600);
