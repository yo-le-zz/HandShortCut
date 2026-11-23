// action_form.js — éditeur d'actions : palette d'étapes, champs générés depuis le catalogue
// (steps.py), réordonnancement par glisser-déposer, test sans enregistrer.
"use strict";

(() => {
  const data = JSON.parse(document.getElementById("form-data").textContent);
  const initial = JSON.parse(document.getElementById("action-data").textContent);
  const SPECS = Object.fromEntries(data.steps.map((s) => [s.type, s]));
  const CATEGORIES = data.categories;
  const CATEGORY_BY_KEY = Object.fromEntries(CATEGORIES.map((c) => [c.key, c]));
  const $ = (id) => document.getElementById(id);
  const esc = HSC.esc;

  const PLATFORM_LABELS = Object.fromEntries(data.platforms.map((p) => [p.key, p.label]));

  let uid = 0;
  let steps = [];
  let dirty = false;
  let activeCategory = "all";

  const hydrate = (raw) => ({ uid: ++uid, open: false, data: { ...raw } });
  steps = (initial.steps || []).filter((s) => SPECS[s.type]).map(hydrate);
  const skipped = (initial.steps || []).length - steps.length;
  if (skipped) HSC.toast(`${skipped} étape(s) de type inconnu ignorée(s).`, "error");
  $("action-name").value = initial.name || "";

  const norm = (text) => String(text).normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const markDirty = () => { dirty = true; };

  // ---------------------------------------------------------------- résumé
  function optionLabel(field, value) {
    return (field.option_labels && field.option_labels[value]) || value;
  }

  function summarize(step) {
    const spec = SPECS[step.data.type];
    const parts = [];
    for (const field of spec.fields) {
      const value = step.data[field.key];
      if (value === undefined || value === null || value === "" || value === false) continue;
      if (Array.isArray(value) && !value.length) continue;
      if (field.kind === "select") parts.push(optionLabel(field, value));
      else if (field.kind === "monitor") parts.push(`écran ${value}`);
      else if (field.kind === "action") {
        const found = data.actions.find((a) => a.id === value);
        parts.push(`→ ${found ? found.name : "action introuvable"}`);
      } else if (field.kind === "list") parts.push(value.join(" "));
      else if (field.kind === "bool") parts.push(field.label.split(" ")[0].toLowerCase());
      else if (field.kind === "number" && /\(ms\)/.test(field.label)) parts.push(HSC.fmtMs(value));
      else parts.push(String(value).replace(/\s+/g, " "));
    }
    const text = parts.join(" · ");
    return text.length > 90 ? `${text.slice(0, 87)}…` : text || spec.description;
  }

  // ----------------------------------------------------------------- champs
  function fieldHtml(step, field) {
    const id = `f-${step.uid}-${field.key}`;
    const value = step.data[field.key];
    const wide = ["text", "path", "textarea", "list"].includes(field.kind) ? "sm:col-span-2" : "";
    const label = `<label for="${id}" class="field-label flex items-center gap-1.5">${field.icon ? HSC.icon(field.icon, "w-3.5 h-3.5") : ""}${esc(field.label)}</label>`;
    const attrs = `id="${id}" data-uid="${step.uid}" data-key="${esc(field.key)}" data-kind="${field.kind}"`;
    let control;
    if (field.kind === "select") {
      control = `<select ${attrs} class="field-input">${field.options.map((o) =>
        `<option value="${esc(o)}" ${(value ?? field.default) === o ? "selected" : ""}>${esc(optionLabel(field, o))}</option>`).join("")}</select>`;
    } else if (field.kind === "monitor" && data.monitors.length) {
      control = `<select ${attrs} class="field-input">${data.monitors.map((m) =>
        `<option value="${m.index}" ${Number(value ?? field.default) === m.index ? "selected" : ""}>Écran ${m.index} — ${m.width}×${m.height}${m.is_primary ? " (principal)" : ""}</option>`).join("")}</select>`;
    } else if (field.kind === "action") {
      control = `<select ${attrs} class="field-input"><option value="">— choisir une action —</option>${data.actions.map((a) =>
        `<option value="${esc(a.id)}" ${value === a.id ? "selected" : ""}>${esc(a.name)}</option>`).join("")}</select>`;
    } else if (field.kind === "bool") {
      return `<div class="sm:col-span-2 flex items-center gap-3">
        <button type="button" role="switch" aria-checked="${value ? "true" : "false"}" ${attrs} class="switch" aria-label="${esc(field.label)}"></button>
        <span class="text-sm">${esc(field.label)}</span></div>`;
    } else if (field.kind === "textarea") {
      control = `<textarea ${attrs} rows="3" class="field-input font-mono" placeholder="${esc(field.placeholder)}">${esc(value ?? "")}</textarea>`;
    } else if (field.kind === "number" || field.kind === "monitor") {
      const range = `${field.min !== null ? `min="${field.min}"` : ""} ${field.max !== null ? `max="${field.max}"` : ""}`;
      control = `<input ${attrs} type="number" ${range} class="field-input" placeholder="${esc(field.placeholder || (field.default ?? ""))}" value="${esc(value ?? "")}">`;
    } else {
      const shown = field.kind === "list" ? (value || []).join(", ") : value ?? "";
      control = `<input ${attrs} type="text" class="field-input ${field.kind === "path" || field.kind === "list" ? "font-mono" : ""}" placeholder="${esc(field.placeholder)}" value="${esc(shown)}" autocomplete="off" spellcheck="false">`;
    }
    const hint = /\(ms\)/.test(field.label)
      ? `<span class="field-hint" data-hint="${id}">${value !== undefined && value !== "" ? HSC.fmtMs(value) : ""}</span>`
      : field.help ? `<span class="field-hint">${esc(field.help)}</span>` : "";
    return `<div class="flex flex-col gap-1.5 ${wide}">${label}${control}${hint}</div>`;
  }

  function commonHtml(step) {
    const waitId = `f-${step.uid}-wait_ms`;
    const wait = step.data.wait_ms;
    return `
      <div class="flex flex-col gap-1.5">
        <label for="${waitId}" class="field-label flex items-center gap-1.5">${HSC.icon("clock", "w-3.5 h-3.5")}Pause après cette étape (ms)</label>
        <input id="${waitId}" data-uid="${step.uid}" data-key="wait_ms" data-kind="number" type="number" min="0" max="3600000" step="50" class="field-input" placeholder="0" value="${esc(wait ?? "")}">
        <span class="field-hint" data-hint="${waitId}">${wait ? HSC.fmtMs(wait) : ""}</span>
      </div>
      <div class="flex flex-col gap-1.5">
        <label for="f-${step.uid}-only_on" class="field-label flex items-center gap-1.5">${HSC.icon("monitor", "w-3.5 h-3.5")}Plateforme</label>
        <select id="f-${step.uid}-only_on" data-uid="${step.uid}" data-key="only_on" data-kind="select" class="field-input">
          ${Object.entries(PLATFORM_LABELS).map(([k, l]) => `<option value="${k}" ${(step.data.only_on || "all") === k ? "selected" : ""}>${esc(l)}</option>`).join("")}
        </select>
        <span class="field-hint">Une même action peut contenir des étapes Windows et Linux.</span>
      </div>`;
  }

  // ----------------------------------------------------------------- cartes
  function cardHtml(step, index) {
    const d = step.data;
    const spec = SPECS[d.type];
    const disabled = d.enabled === false;
    const badges = [
      d.only_on === "windows" || d.only_on === "linux"
        ? `<span class="chip chip-muted ml-2">${d.only_on === "windows" ? "Windows" : "Linux"}</span>` : "",
      disabled ? `<span class="chip chip-muted ml-2">désactivée</span>` : "",
    ].join("");
    return `
    <li class="step-card cat-${spec.category} cat-edge ${disabled ? "disabled-step" : ""}" data-uid="${step.uid}">
      <div class="flex items-center gap-2 px-3 py-2.5">
        <button type="button" class="icon-btn drag-handle" data-handle title="Glisser pour réordonner (ou flèches haut/bas)" aria-label="Réordonner l'étape ${index + 1}">${HSC.icon("grip-vertical", "w-[18px] h-[18px]")}</button>
        <span class="text-xs font-mono text-on-surface-variant w-5 text-right">${index + 1}</span>
        <span class="cat-chip w-8 h-8 rounded-lg flex items-center justify-center">${HSC.icon(spec.icon, "w-[18px] h-[18px]")}</span>
        <button type="button" class="flex-1 min-w-0 text-left" data-act="toggle" aria-expanded="${step.open}">
          <div class="text-sm font-medium truncate">${esc(spec.label)}${badges}</div>
          <div class="text-xs text-on-surface-variant truncate" data-summary>${esc(summarize(step))}</div>
        </button>
        <button type="button" class="icon-btn" data-act="enable" title="${disabled ? "Activer" : "Désactiver"} l'étape">${HSC.icon(disabled ? "eye-off" : "eye", "w-[18px] h-[18px]")}</button>
        <button type="button" class="icon-btn" data-act="duplicate" title="Dupliquer">${HSC.icon("copy", "w-[18px] h-[18px]")}</button>
        <button type="button" class="icon-btn danger" data-act="delete" title="Supprimer">${HSC.icon("trash-2", "w-[18px] h-[18px]")}</button>
        <button type="button" class="icon-btn" data-act="toggle" aria-label="Déplier">${HSC.icon(step.open ? "chevron-up" : "chevron-down", "w-[18px] h-[18px]")}</button>
      </div>
      <div class="${step.open ? "" : "hidden"} border-t border-outline px-4 py-4 space-y-4" data-body>
        <p class="text-sm text-on-surface-variant">${esc(spec.description)}</p>
        ${spec.note ? `<p class="text-xs text-warning flex items-start gap-1.5">${HSC.icon("info", "w-4 h-4 mt-px")}<span>${esc(spec.note)}</span></p>` : ""}
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">${spec.fields.map((f) => fieldHtml(step, f)).join("")}</div>
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-4 border-t border-outline pt-4">${commonHtml(step)}</div>
        <div class="flex gap-2 pt-1">
          <button type="button" class="btn-secondary py-1.5 text-xs" data-act="up">${HSC.icon("arrow-up", "w-4 h-4")} Monter</button>
          <button type="button" class="btn-secondary py-1.5 text-xs" data-act="down">${HSC.icon("arrow-down", "w-4 h-4")} Descendre</button>
        </div>
      </div>
    </li>`;
  }

  function updateStats() {
    const count = steps.length;
    $("steps-count").textContent = `${count} étape${count > 1 ? "s" : ""}`;
    const wait = steps.reduce((sum, s) => {
      if (s.data.enabled === false) return sum;
      return sum + (s.data.type === "wait" ? Number(s.data.ms) || 0 : 0) + (Number(s.data.wait_ms) || 0);
    }, 0);
    $("steps-wait").textContent = `pauses : ${HSC.fmtMs(wait)}`;
    $("steps-empty").classList.toggle("hidden", count > 0);
  }

  function render(focusUid, focusSelector) {
    $("steps").innerHTML = steps.map(cardHtml).join("");
    updateStats();
    if (focusUid) {
      const el = document.querySelector(`.step-card[data-uid="${focusUid}"] ${focusSelector || "[data-handle]"}`);
      if (el) el.focus();
    }
  }

  const find = (uidValue) => steps.find((s) => s.uid === Number(uidValue));
  function move(from, to) {
    if (to < 0 || to >= steps.length || from === to) return;
    steps.splice(to, 0, steps.splice(from, 1)[0]);
    markDirty();
  }

  // ------------------------------------------------------------ interactions
  const list = $("steps");

  list.addEventListener("click", (event) => {
    const button = event.target.closest("[data-act]");
    if (!button) return;
    const card = button.closest(".step-card");
    const step = find(card.dataset.uid);
    const index = steps.indexOf(step);
    switch (button.dataset.act) {
      case "toggle": step.open = !step.open; render(step.uid, `[data-act="toggle"]`); break;
      case "enable":
        if (step.data.enabled === false) delete step.data.enabled; else step.data.enabled = false;
        markDirty(); render(step.uid, `[data-act="enable"]`); break;
      case "duplicate": {
        const copy = hydrate(JSON.parse(JSON.stringify(step.data)));
        copy.open = step.open;
        steps.splice(index + 1, 0, copy);
        markDirty(); render(copy.uid, `[data-act="toggle"]`); break;
      }
      case "delete": steps.splice(index, 1); markDirty(); render(); break;
      case "up": move(index, index - 1); render(step.uid, `[data-act="up"]`); break;
      case "down": move(index, index + 1); render(step.uid, `[data-act="down"]`); break;
    }
  });

  function readField(el) {
    const step = find(el.dataset.uid);
    if (!step) return;
    const key = el.dataset.key;
    const kind = el.dataset.kind;
    const spec = SPECS[step.data.type];
    const field = spec.fields.find((f) => f.key === key);
    let value;
    if (kind === "bool") value = el.getAttribute("aria-checked") === "true";
    else if (kind === "number" || kind === "monitor") value = el.value === "" ? undefined : Number(el.value);
    else if (kind === "list") value = el.value.split(",").map((s) => s.trim()).filter(Boolean);
    else value = el.value;

    if (key === "only_on") {
      if (value === "all") delete step.data.only_on; else step.data.only_on = value;
    } else if (value === undefined || value === "" || (Array.isArray(value) && !value.length) || (kind === "bool" && !value)) {
      delete step.data[key];
    } else {
      step.data[key] = value;
    }
    el.classList.remove("invalid");
    const hint = document.querySelector(`[data-hint="${el.id}"]`);
    if (hint) hint.textContent = step.data[key] !== undefined ? HSC.fmtMs(step.data[key]) : "";
    const card = el.closest(".step-card");
    card.querySelector("[data-summary]").textContent = summarize(step);
    if (key === "only_on") render(step.uid, `#${el.id}`);
    else updateStats();
    markDirty();
    return field;
  }

  list.addEventListener("input", (event) => { if (event.target.dataset.key) readField(event.target); });
  list.addEventListener("change", (event) => { if (event.target.dataset.key) readField(event.target); });
  list.addEventListener("click", (event) => {
    const sw = event.target.closest('button[role="switch"]');
    if (!sw) return;
    sw.setAttribute("aria-checked", sw.getAttribute("aria-checked") === "true" ? "false" : "true");
    readField(sw);
  });

  // --- glisser-déposer (poignée) et clavier ---
  let dragUid = null;
  list.addEventListener("pointerdown", (event) => {
    const handle = event.target.closest("[data-handle]");
    if (handle) handle.closest(".step-card").draggable = true;
  });
  list.addEventListener("pointerup", () => list.querySelectorAll(".step-card[draggable=true]").forEach((c) => { c.draggable = false; }));
  list.addEventListener("dragstart", (event) => {
    const card = event.target.closest(".step-card");
    if (!card || !card.draggable) return;
    dragUid = card.dataset.uid;
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", dragUid);
    requestAnimationFrame(() => card.classList.add("dragging"));
  });
  const clearMarks = () => list.querySelectorAll(".drop-before, .drop-after").forEach((c) => c.classList.remove("drop-before", "drop-after"));
  list.addEventListener("dragover", (event) => {
    if (dragUid === null) return;
    event.preventDefault();
    const card = event.target.closest(".step-card");
    clearMarks();
    if (!card || card.dataset.uid === dragUid) return;
    const rect = card.getBoundingClientRect();
    card.classList.add(event.clientY < rect.top + rect.height / 2 ? "drop-before" : "drop-after");
  });
  list.addEventListener("drop", (event) => {
    if (dragUid === null) return;
    event.preventDefault();
    const card = event.target.closest(".step-card");
    if (card && card.dataset.uid !== dragUid) {
      const rect = card.getBoundingClientRect();
      const after = event.clientY >= rect.top + rect.height / 2;
      const from = steps.indexOf(find(dragUid));
      let to = steps.indexOf(find(card.dataset.uid)) + (after ? 1 : 0);
      if (from < to) to -= 1;
      move(from, to);
    }
    const moved = dragUid;
    dragUid = null;
    render(moved);
  });
  list.addEventListener("dragend", () => {
    dragUid = null;
    clearMarks();
    list.querySelectorAll(".dragging").forEach((c) => c.classList.remove("dragging"));
    list.querySelectorAll(".step-card[draggable=true]").forEach((c) => { c.draggable = false; });
  });
  list.addEventListener("keydown", (event) => {
    const handle = event.target.closest("[data-handle]");
    if (!handle || !["ArrowUp", "ArrowDown"].includes(event.key)) return;
    event.preventDefault();
    const step = find(handle.closest(".step-card").dataset.uid);
    const index = steps.indexOf(step);
    move(index, index + (event.key === "ArrowUp" ? -1 : 1));
    render(step.uid);
  });

  $("btn-collapse").addEventListener("click", () => {
    const open = steps.some((s) => s.open);
    steps.forEach((s) => { s.open = !open; });
    render();
  });

  // ----------------------------------------------------------------- palette
  function addStep(type) {
    const spec = SPECS[type];
    const raw = { type };
    spec.fields.forEach((f) => { if (f.default !== null && f.kind !== "bool") raw[f.key] = f.default; });
    const step = hydrate(raw);
    step.open = true;
    steps.push(step);
    markDirty();
    render();
    const card = document.querySelector(`.step-card[data-uid="${step.uid}"]`);
    card.scrollIntoView({ behavior: "smooth", block: "center" });
    const first = card.querySelector("[data-body] input, [data-body] textarea, [data-body] select");
    if (first) first.focus({ preventScroll: true });
  }

  function renderPalette() {
    const query = norm($("palette-search").value.trim());
    const tabs = [{ key: "all", label: "Toutes", icon: "layout-grid" }, ...CATEGORIES];
    $("palette-tabs").innerHTML = tabs.map((c) => `
      <button type="button" data-cat="${c.key}" title="${esc(c.label)}"
        class="chip border border-outline ${c.key === "all" ? "" : `cat-${c.key}`} ${activeCategory === c.key ? (c.key === "all" ? "chip-primary" : "cat-active") : "chip-muted"}">
        ${HSC.icon(c.icon, "w-3.5 h-3.5")}${c.key === "all" ? "Toutes" : ""}</button>`).join("");

    let html = "";
    for (const category of CATEGORIES) {
      if (activeCategory !== "all" && activeCategory !== category.key) continue;
      const items = data.steps.filter((s) => s.category === category.key && (!query ||
        norm([s.label, s.description, s.type, ...s.keywords].join(" ")).includes(query)));
      if (!items.length) continue;
      html += `<div class="cat-${category.key}">
        <div class="flex items-center gap-1.5 text-[11px] font-mono uppercase tracking-wider cat-text mb-1.5 px-1">${HSC.icon(category.icon, "w-3.5 h-3.5")}${esc(category.label)}</div>
        <div class="space-y-0.5">${items.map((s) => `
          <button type="button" class="palette-item cat-hover" data-add="${s.type}" title="${esc(s.description)}">
            <span class="cat-chip w-7 h-7 rounded-md flex items-center justify-center">${HSC.icon(s.icon, "w-4 h-4")}</span>
            <span class="min-w-0"><span class="block truncate">${esc(s.label)}</span></span>
          </button>`).join("")}</div></div>`;
    }
    $("palette").innerHTML = html || `<p class="text-sm text-on-surface-variant px-1 py-6 text-center">Aucune étape ne correspond.</p>`;
  }
  $("palette-search").addEventListener("input", renderPalette);
  $("palette-tabs").addEventListener("click", (event) => {
    const tab = event.target.closest("[data-cat]");
    if (tab) { activeCategory = tab.dataset.cat; renderPalette(); }
  });
  $("palette").addEventListener("click", (event) => {
    const item = event.target.closest("[data-add]");
    if (item) addStep(item.dataset.add);
  });

  // ------------------------------------------------- validation, test, envoi
  function validate() {
    let problems = 0;
    steps.forEach((step) => {
      const spec = SPECS[step.data.type];
      const empty = (key) => {
        const v = step.data[key];
        return v === undefined || v === null || v === "" || (Array.isArray(v) && !v.length);
      };
      const missing = new Set(spec.required.filter(empty));
      if (spec.any_of.length && spec.any_of.every(empty)) spec.any_of.forEach((k) => missing.add(k));
      if (missing.size) {
        problems += missing.size;
        step.open = true;
        step.missing = missing;
      } else {
        step.missing = null;
      }
    });
    render();
    steps.forEach((step) => {
      (step.missing || []).forEach((key) => {
        const el = document.getElementById(`f-${step.uid}-${key}`);
        if (el) el.classList.add("invalid");
      });
    });
    const firstBad = document.querySelector(".field-input.invalid");
    if (firstBad) firstBad.scrollIntoView({ behavior: "smooth", block: "center" });
    return problems;
  }

  function payload() {
    return {
      id: initial.id || null,
      name: $("action-name").value.trim(),
      steps: steps.map((s) => s.data),
    };
  }

  $("btn-test").addEventListener("click", async () => {
    if (!steps.length) { HSC.toast("Ajoute d'abord des étapes.", "error"); return; }
    const problems = validate();
    if (problems) { HSC.toast(`${problems} champ(s) à compléter.`, "error"); return; }
    try {
      await HSC.api("POST", "/api/actions/test", { ...payload(), name: payload().name || "Test" });
      HSC.toast("Action lancée.", "success");
    } catch (err) {
      HSC.toast(err.message, "error");
    }
  });

  async function save() {
    const body = payload();
    if (!body.name) { $("action-name").focus(); HSC.toast("Donne un nom à l'action.", "error"); return; }
    const problems = validate();
    if (problems) { HSC.toast(`${problems} champ(s) à compléter.`, "error"); return; }
    try {
      await HSC.api("POST", "/api/actions", body);
      dirty = false;
      window.location.href = "/";
    } catch (err) {
      HSC.toast(err.message, "error");
    }
  }
  $("btn-save").addEventListener("click", save);
  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") { event.preventDefault(); save(); }
  });
  $("action-name").addEventListener("input", markDirty);
  window.addEventListener("beforeunload", (event) => { if (dirty) { event.preventDefault(); event.returnValue = ""; } });

  render();
  renderPalette();
})();
