// templates.js — installation des modèles de workflows et de gestes.
"use strict";

document.addEventListener("click", async (event) => {
  const filter = event.target.closest("[data-filter]");
  if (filter) {
    document.querySelectorAll("[data-filter]").forEach((b) => {
      b.classList.toggle("chip-primary", b === filter);
      b.classList.toggle("chip-muted", b !== filter);
    });
    document.querySelectorAll("[data-tpl-card]").forEach((card) => {
      card.classList.toggle("hidden", filter.dataset.filter !== "all" && card.dataset.category !== filter.dataset.filter);
    });
    return;
  }
  const button = event.target.closest("[data-install]");
  if (!button) return;
  button.disabled = true;
  try {
    const result = await HSC.api("POST", `/api/templates/${encodeURIComponent(button.dataset.install)}/install`, {
      gestures: !button.hasAttribute("data-no-gestures"),
    });
    HSC.toast(`Installé : 1 workflow${result.gesture_ids.length ? ` et ${result.gesture_ids.length} geste(s)` : ""}.`, "success");
    setTimeout(() => { location.href = "/"; }, 900);
  } catch (err) {
    HSC.toast(err.message, "error");
    button.disabled = false;
  }
});
