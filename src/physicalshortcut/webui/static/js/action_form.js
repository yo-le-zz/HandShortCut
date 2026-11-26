// action_form.js — éditeur de workflows : graphe de noeuds reliés par des ports, données
// partagées via {{ variables }}, inspecteur généré depuis le catalogue (steps.py).
"use strict";

(() => {
  const data = JSON.parse(document.getElementById("form-data").textContent);
  const initial = JSON.parse(document.getElementById("action-data").textContent);
  const SPECS = Object.fromEntries(data.steps.map((s) => [s.type, s]));
  const CATEGORIES = data.categories;
  const PLATFORM_LABELS = Object.fromEntries(data.platforms.map((p) => [p.key, p.label]));
  const PORT_LABELS = data.port_labels || {};
  const $ = (id) => document.getElementById(id);
  const esc = HSC.esc;
  const NW = 208;
  const GRID = 10;
  const BUILTINS = [
    ["gesture.value", "valeur du geste (doigts, chiffre dessiné…)"], ["gesture.name", "nom du geste"],
    ["gesture.label", "symbole dessiné"], ["gesture.confidence", "confiance de la reconnaissance"],
    ["now.date", "date du jour"], ["now.time", "heure"], ["now.hour", "heure (nombre)"],
    ["system.cpu_percent", "CPU (%)"], ["system.cpu_temp_c", "température CPU"], ["system.uptime_minutes", "uptime (min)"],
    ["system.ram_percent", "RAM (%)"], ["args", "arguments reçus (run_action)"], ["last", "sortie du dernier noeud"],
  ];

  let nodes = []; // {uid, data}
  let edges = []; // {from, port, to}
  let selected = null; // {kind: "node"|"edge", id}
  let dirty = false;
  let activeCategory = "all";
  let lastField = null;
  let runStatus = {};
  let uid = 0;

  const norm = (t) => String(t).normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const markDirty = () => { dirty = true; };
  const byId = (id) => nodes.find((n) => n.data.id === id);
  const portsOf = (type) => [...(SPECS[type]?.ports || [{ key: "out" }]).map((p) => p.key), "error"];
  const labelOf = (port) => PORT_LABELS[port] || { out: "suite", error: "erreur" }[port] || port;

  // ---------------------------------------------------------------- chargement
  function load() {
    let rawNodes = initial.nodes;
    let rawEdges = initial.edges;
    if (!rawNodes) { // ancien format : liste d'étapes -> chaîne verticale
      rawNodes = (initial.steps || []).map((s, i) => ({ ...s, id: `n${i + 1}` }));
      rawEdges = rawNodes.slice(1).map((n, i) => ({ from: rawNodes[i].id, port: "out", to: n.id }));
    }
    const kept = (rawNodes || []).filter((n) => SPECS[n.type] && n.type !== "trigger");
    if (kept.length < (rawNodes || []).length) HSC.toast("Des noeuds de type inconnu ont été ignorés.", "error");
    nodes = kept.map((n) => ({ uid: ++uid, data: { ...n } }));
    const ids = new Set(nodes.map((n) => n.data.id));
    edges = (rawEdges || []).filter((e) => ids.has(e.from) && ids.has(e.to)).map((e) => ({ ...e }));
    if (nodes.some((n) => n.data.x === undefined)) autoLayout(true);
    $("action-name").value = initial.name || "";
  }

  function newId() {
    let i = nodes.length + 1;
    while (byId(`n${i}`)) i += 1;
    return `n${i}`;
  }

  function autoName(type) {
    const spec = SPECS[type];
    if (!spec.output) return undefined;
    const base = { file_read: "contenu", http_request: "reponse", run_shell: "sortie", ai_ask: "ia", hand_info: "mains",
      clipboard_get: "texte", parse_json: "valeur", regex_extract: "extrait", system_metric: "mesure", screenshot: "capture" }[type] || type;
    let name = base; let i = 1;
    while (nodes.some((n) => n.data.name === name)) { i += 1; name = `${base}${i}`; }
    return name;
  }

  // ------------------------------------------------------------------ disposition
  function autoLayout(silent) {
    const incoming = new Set(edges.map((e) => e.to));
    const level = new Map();
    const queue = nodes.filter((n) => !incoming.has(n.data.id)).map((n) => n.data.id);
    if (!queue.length && nodes.length) queue.push(nodes[0].data.id);
    queue.forEach((id) => level.set(id, 0));
    for (let head = 0; head < queue.length; head += 1) {
      const id = queue[head];
      edges.filter((e) => e.from === id).forEach((e) => {
        if (!level.has(e.to) && level.size < 400) { level.set(e.to, level.get(id) + 1); queue.push(e.to); }
      });
    }
    nodes.forEach((n) => { if (!level.has(n.data.id)) level.set(n.data.id, Math.max(0, ...level.values()) + 1); });
    const rows = {};
    nodes.forEach((n) => { (rows[level.get(n.data.id)] ||= []).push(n); });
    Object.entries(rows).forEach(([lv, row]) => {
      row.forEach((n, i) => { n.data.x = 40 + i * (NW + 48); n.data.y = 40 + Number(lv) * 150; });
    });
    if (!silent) { markDirty(); render(); }
  }

  // --------------------------------------------------------------------- résumé
  const optionLabel = (field, value) => (field.option_labels && field.option_labels[value]) || value;
  function summarize(d) {
    const spec = SPECS[d.type];
    const parts = [];
    for (const field of spec.fields) {
      const value = d[field.key];
      if (value === undefined || value === null || value === "" || value === false) continue;
      if (Array.isArray(value) && !value.length) continue;
      if (field.kind === "select") parts.push(optionLabel(field, value));
      else if (field.kind === "action") {
        const found = data.actions.find((a) => a.id === value);
        parts.push(`→ ${found ? found.name : "introuvable"}`);
      } else if (field.kind === "list") parts.push(value.join(" "));
      else if (field.kind === "bool") parts.push(field.label.split(" ")[0].toLowerCase());
      else parts.push(String(value).replace(/\s+/g, " "));
    }
    const text = parts.join(" · ");
    return text.length > 46 ? `${text.slice(0, 44)}…` : text || spec.label;
  }

  // ----------------------------------------------------------------------- noeuds
  function nodeHtml(n) {
    const d = n.data;
    const spec = SPECS[d.type];
    const ports = portsOf(d.type);
    const incoming = edges.some((e) => e.to === d.id);
    const status = runStatus[d.id] ? `run-${runStatus[d.id]}` : "";
    const portHtml = ports.map((p, i) => `
      <div class="gport pc-${p}" data-port="${p}" data-pct="${((i + 1) / (ports.length + 1)) * 100}" title="${esc(labelOf(p))} : tire vers un autre noeud">
        ${p !== "out" ? `<span>${esc(labelOf(p))}</span>` : ""}<i></i></div>`).join("");
    return `
    <div class="gnode cat-${spec.category} ${selected?.kind === "node" && selected.id === d.id ? "selected" : ""} ${d.enabled === false ? "disabled-step" : ""} ${status}"
         data-id="${esc(d.id)}" data-x="${d.x}" data-y="${d.y}">
      ${incoming ? "" : `<span class="gnode-start">départ</span>`}
      <span class="gnode-in" data-in></span>
      <div class="gnode-head" data-drag>
        <span class="cat-chip w-7 h-7 rounded-md flex items-center justify-center">${HSC.icon(spec.icon, "w-4 h-4")}</span>
        <div class="min-w-0 flex-1"><div class="text-[13px] font-medium truncate">${esc(d.label || spec.label)}</div>
          ${d.name ? `<div class="text-[10px] font-mono text-accent truncate">{{ ${esc(d.name)} }}</div>` : ""}</div>
        ${d.only_on === "windows" || d.only_on === "linux" ? `<span class="chip chip-muted">${d.only_on === "windows" ? "Win" : "Lin"}</span>` : ""}
      </div>
      <div class="gnode-sum">${esc(summarize(d))}</div>
      <div class="gnode-ports">${portHtml}</div>
    </div>`;
  }

  // La CSP interdit les attributs style="" : les positions passent par le CSSOM.
  function placeNodes() {
    $("graph-nodes").querySelectorAll(".gnode").forEach((el) => {
      el.style.left = `${el.dataset.x}px`;
      el.style.top = `${el.dataset.y}px`;
    });
    $("graph-nodes").querySelectorAll(".gport").forEach((el) => { el.style.left = `${el.dataset.pct}%`; });
  }

  function render() {
    $("graph-nodes").innerHTML = nodes.map(nodeHtml).join("");
    placeNodes();
    sizeCanvas();
    renderEdges();
    renderInspector();
    $("graph-count").textContent = `${nodes.length} noeud${nodes.length > 1 ? "s" : ""}`;
    $("graph-edges").textContent = `${edges.length} lien${edges.length > 1 ? "s" : ""}`;
    $("graph-empty").classList.toggle("hidden", nodes.length > 0);
  }

  // ------------------------------------------------------------ zoom et déplacement
  const ZOOM_MIN = 0.25, ZOOM_MAX = 2;
  let zoom = 1;
  try { zoom = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, Number(localStorage.getItem("psc-graph-zoom")) || 1)); } catch { /* stockage indisponible */ }
  document.querySelector("main")?.style.setProperty("max-width", "1800px"); // l'éditeur profite de la largeur de l'écran

  function sizeCanvas() {
    const scroll = $("graph-scroll");
    // Le canvas dépasse toujours le contenu d'un écran entier : on peut se déplacer « dans le vide ».
    const w = Math.max(scroll.clientWidth / zoom, ...nodes.map((n) => n.data.x + NW + 40)) + scroll.clientWidth / zoom * 0.6;
    const h = Math.max(scroll.clientHeight / zoom, ...nodes.map((n) => n.data.y + 240)) + scroll.clientHeight / zoom * 0.6;
    const world = $("graph-world");
    world.style.width = `${w}px`;
    world.style.height = `${h}px`;
    world.style.transform = `scale(${zoom})`;
    const canvas = $("graph-canvas");
    canvas.style.width = `${w * zoom}px`;
    canvas.style.height = `${h * zoom}px`;
    $("zoom-label").textContent = `${Math.round(zoom * 100)} %`;
  }

  // Applique un nouveau zoom en gardant fixe le point (cx, cy) de l'écran (coordonnées du conteneur).
  function setZoom(next, cx, cy) {
    const scroll = $("graph-scroll");
    next = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, Math.round(next * 100) / 100));
    if (next === zoom) return;
    cx = cx ?? scroll.clientWidth / 2;
    cy = cy ?? scroll.clientHeight / 2;
    const wx = (scroll.scrollLeft + cx) / zoom, wy = (scroll.scrollTop + cy) / zoom;
    zoom = next;
    try { localStorage.setItem("psc-graph-zoom", String(zoom)); } catch { /* ignoré */ }
    sizeCanvas();
    scroll.scrollLeft = wx * zoom - cx;
    scroll.scrollTop = wy * zoom - cy;
  }

  function fitView() {
    const scroll = $("graph-scroll");
    if (!nodes.length) { zoom = 1; sizeCanvas(); return; }
    const minX = Math.min(...nodes.map((n) => n.data.x)), maxX = Math.max(...nodes.map((n) => n.data.x + NW));
    const minY = Math.min(...nodes.map((n) => n.data.y)), maxY = Math.max(...nodes.map((n) => n.data.y + 130));
    const fit = Math.min((scroll.clientWidth - 60) / (maxX - minX), (scroll.clientHeight - 60) / (maxY - minY), 1);
    zoom = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, Math.round(fit * 100) / 100));
    sizeCanvas();
    scroll.scrollLeft = Math.max(0, minX * zoom - 30);
    scroll.scrollTop = Math.max(0, minY * zoom - 30);
  }

  $("zoom-in").addEventListener("click", () => setZoom(zoom * 1.2));
  $("zoom-out").addEventListener("click", () => setZoom(zoom / 1.2));
  $("zoom-label").addEventListener("click", () => setZoom(1));
  $("zoom-fit").addEventListener("click", fitView);
  $("graph-scroll").addEventListener("wheel", (event) => {
    event.preventDefault();
    const r = $("graph-scroll").getBoundingClientRect();
    setZoom(zoom * (event.deltaY < 0 ? 1.1 : 1 / 1.1), event.clientX - r.left, event.clientY - r.top);
  }, { passive: false });
  $("graph-scroll").addEventListener("keydown", (event) => {
    if (event.target.closest("input, textarea, select")) return;
    if (event.key === "+" || event.key === "=") setZoom(zoom * 1.2);
    else if (event.key === "-") setZoom(zoom / 1.2);
    else if (event.key === "0") setZoom(1);
  });

  // Déplacement : on clique dans le vide et on bouge la souris.
  const isEmpty = (target) => target === $("graph-scroll") || target === $("graph-canvas") || target === $("graph-world")
    || target === $("graph-nodes") || target === $("graph-svg");
  let pan = null;
  $("graph-scroll").addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || !isEmpty(event.target)) return;
    const scroll = $("graph-scroll");
    pan = { x: event.clientX, y: event.clientY, left: scroll.scrollLeft, top: scroll.scrollTop, moved: false, id: event.pointerId };
    scroll.setPointerCapture?.(event.pointerId);
  });
  $("graph-scroll").addEventListener("pointermove", (event) => {
    if (!pan) return;
    const dx = event.clientX - pan.x, dy = event.clientY - pan.y;
    if (!pan.moved && Math.hypot(dx, dy) < 4) return;
    pan.moved = true;
    $("graph-scroll").classList.add("panning");
    $("graph-scroll").scrollLeft = pan.left - dx;
    $("graph-scroll").scrollTop = pan.top - dy;
  });
  const endPan = () => {
    if (!pan) return;
    const moved = pan.moved;
    pan = null;
    $("graph-scroll").classList.remove("panning");
    if (!moved && selected) select(null); // simple clic dans le vide : on désélectionne
  };
  $("graph-scroll").addEventListener("pointerup", endPan);
  $("graph-scroll").addEventListener("pointercancel", endPan);
  window.addEventListener("resize", sizeCanvas);

  const nodeEl = (id) => $("graph-nodes").querySelector(`.gnode[data-id="${CSS.escape(id)}"]`);

  function portPoint(id, port) {
    const n = byId(id);
    const el = nodeEl(id);
    const ports = portsOf(n.data.type);
    const i = Math.max(0, ports.indexOf(port));
    return { x: n.data.x + ((i + 1) / (ports.length + 1)) * NW, y: n.data.y + (el ? el.offsetHeight : 84) };
  }

  const PORT_COLORS = { out: "#a78bfa", true: "#34d399", false: "#fb923c", each: "#22d3ee", done: "#94a3b8", error: "#ff5c72", case1: "#60a5fa", case2: "#f472b6", case3: "#facc15", case4: "#2dd4bf", case5: "#c084fc", default: "#94a3b8" };
  const curve = (a, b) => {
    const dy = Math.max(40, Math.abs(b.y - a.y) / 2);
    return `M${a.x},${a.y} C${a.x},${a.y + dy} ${b.x},${b.y - dy} ${b.x},${b.y}`;
  };

  function references(d) { // noeuds dont la variable est utilisée dans les champs de d
    const used = new Set();
    const text = JSON.stringify(Object.entries(d).filter(([k]) => !["id", "x", "y", "type"].includes(k)));
    for (const other of nodes) {
      const name = other.data.name || (other.data.type === "set_variable" ? other.data.variable : "");
      if (!name || other.data.id === d.id) continue;
      if (new RegExp(`\\{\\{[^}]*\\b${name}\\b`).test(text)) used.add(other.data.id);
    }
    return used;
  }

  function renderEdges() {
    const svg = $("graph-svg");
    let html = "";
    nodes.forEach((n) => {
      references(n.data).forEach((srcId) => {
        const src = byId(srcId);
        if (!src) return;
        const a = { x: src.data.x + NW, y: src.data.y + 40 };
        const b = { x: n.data.x, y: n.data.y + 40 };
        html += `<path class="data-edge" d="M${a.x},${a.y} C${a.x + 60},${a.y} ${b.x - 60},${b.y} ${b.x},${b.y}"/>`;
      });
    });
    edges.forEach((e, i) => {
      if (!byId(e.from) || !byId(e.to)) return;
      const a = portPoint(e.from, e.port);
      const to = byId(e.to);
      const b = { x: to.data.x + NW / 2, y: to.data.y };
      const sel = selected?.kind === "edge" && selected.id === i;
      html += `<path class="edge ${sel ? "selected" : ""}" data-edge="${i}" stroke="${PORT_COLORS[e.port] || "#a78bfa"}"
        ${e.port === "error" ? 'stroke-dasharray="6 4"' : ""} d="${curve(a, b)}"/>`;
    });
    html += `<path id="temp-edge" class="edge" display="none" stroke="#a78bfa" stroke-dasharray="3 5" d=""/>`;
    svg.innerHTML = html;
  }

  // ------------------------------------------------------------------ interactions
  const canvasPoint = (event) => {
    const r = $("graph-canvas").getBoundingClientRect();
    return { x: (event.clientX - r.left) / zoom, y: (event.clientY - r.top) / zoom };
  };

  function select(kind, id) {
    selected = kind ? { kind, id } : null;
    render();
  }

  let drag = null;
  $("graph-nodes").addEventListener("pointerdown", (event) => {
    const nodeNode = event.target.closest(".gnode");
    if (!nodeNode) return;
    const id = nodeNode.dataset.id;
    const port = event.target.closest(".gport");
    if (port) {
      event.preventDefault();
      drag = { mode: "link", from: id, port: port.dataset.port };
      $("graph-scroll").setPointerCapture?.(event.pointerId);
      return;
    }
    if (event.target.closest("[data-drag]")) {
      const n = byId(id);
      const p = canvasPoint(event);
      drag = { mode: "move", id, dx: p.x - n.data.x, dy: p.y - n.data.y, moved: false };
      if (!(selected?.kind === "node" && selected.id === id)) {
        selected = { kind: "node", id };
        document.querySelectorAll(".gnode.selected").forEach((el) => el.classList.remove("selected"));
        nodeNode.classList.add("selected");
        renderInspector();
      }
    }
  });

  document.addEventListener("pointermove", (event) => {
    if (!drag) return;
    const p = canvasPoint(event);
    if (drag.mode === "move") {
      const n = byId(drag.id);
      n.data.x = Math.max(0, Math.round((p.x - drag.dx) / GRID) * GRID);
      n.data.y = Math.max(0, Math.round((p.y - drag.dy) / GRID) * GRID);
      drag.moved = true;
      const el = nodeEl(drag.id);
      el.style.left = `${n.data.x}px`;
      el.style.top = `${n.data.y}px`;
      renderEdges();
    } else {
      const temp = $("temp-edge");
      const a = portPoint(drag.from, drag.port);
      temp.removeAttribute("display");
      temp.setAttribute("d", curve(a, { x: p.x, y: p.y }));
      temp.setAttribute("stroke", PORT_COLORS[drag.port] || "#a78bfa");
    }
  });

  document.addEventListener("pointerup", (event) => {
    if (!drag) return;
    const current = drag;
    drag = null;
    if (current.mode === "move") {
      if (current.moved) { markDirty(); sizeCanvas(); }
      return;
    }
    const target = document.elementFromPoint(event.clientX, event.clientY)?.closest(".gnode");
    if (target && target.dataset.id !== current.from) connect(current.from, current.port, target.dataset.id);
    else renderEdges();
  });

  function connect(from, port, to) {
    if (edges.some((e) => e.from === from && e.port === port && e.to === to)) { renderEdges(); return; }
    edges.push({ from, port, to });
    markDirty();
    render();
  }

  $("graph-svg").addEventListener("click", (event) => {
    const path = event.target.closest("[data-edge]");
    if (path) select("edge", Number(path.dataset.edge));
  });
  $("graph-nodes").addEventListener("click", (event) => {
    const n = event.target.closest(".gnode");
    if (n && !event.target.closest(".gport") && !(selected?.kind === "node" && selected.id === n.dataset.id)) select("node", n.dataset.id);
  });
  function deleteSelected() {
    if (!selected) return;
    if (selected.kind === "edge") edges.splice(selected.id, 1);
    else {
      nodes = nodes.filter((n) => n.data.id !== selected.id);
      edges = edges.filter((e) => e.from !== selected.id && e.to !== selected.id);
    }
    selected = null;
    markDirty();
    render();
  }

  document.addEventListener("keydown", (event) => {
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName);
    if ((event.key === "Delete" || event.key === "Backspace") && !typing && selected) { event.preventDefault(); deleteSelected(); }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") { event.preventDefault(); save(); }
  });

  // ---------------------------------------------------------------------- champs
  function fieldHtml(n, field) {
    const id = `f-${field.key}`;
    const value = n.data[field.key];
    const wide = ["text", "path", "textarea", "list"].includes(field.kind) ? "col-span-2" : "";
    const label = `<label for="${id}" class="field-label flex items-center gap-1.5">${field.icon ? HSC.icon(field.icon, "w-3.5 h-3.5") : ""}${esc(field.label)}</label>`;
    const attrs = `id="${id}" data-key="${esc(field.key)}" data-kind="${field.kind}"`;
    let control;
    if (field.kind === "select") {
      control = `<select ${attrs} class="field-input">${field.options.map((o) =>
        `<option value="${esc(o)}" ${(value ?? field.default) === o ? "selected" : ""}>${esc(optionLabel(field, o))}</option>`).join("")}</select>`;
    } else if (field.kind === "monitor" && data.monitors.length) {
      control = `<select ${attrs} class="field-input">${data.monitors.map((m) =>
        `<option value="${m.index}" ${Number(value ?? field.default) === m.index ? "selected" : ""}>Écran ${m.index} — ${m.width}×${m.height}</option>`).join("")}</select>`;
    } else if (field.kind === "action") {
      control = `<select ${attrs} class="field-input"><option value="">— choisir un workflow —</option>${data.actions.map((a) =>
        `<option value="${esc(a.id)}" ${value === a.id ? "selected" : ""}>${esc(a.name)}</option>`).join("")}</select>`;
    } else if (field.kind === "bool") {
      return `<div class="col-span-2 flex items-center gap-3">
        <button type="button" role="switch" aria-checked="${value ? "true" : "false"}" ${attrs} class="switch" aria-label="${esc(field.label)}"></button>
        <span class="text-sm">${esc(field.label)}</span></div>`;
    } else if (field.kind === "textarea") {
      control = `<textarea ${attrs} rows="3" class="field-input font-mono" placeholder="${esc(field.placeholder)}">${esc(value ?? "")}</textarea>`;
    } else {
      const shown = field.kind === "list" ? (value || []).join(", ") : value ?? "";
      control = `<input ${attrs} type="text" class="field-input ${["path", "list", "number"].includes(field.kind) ? "font-mono" : ""}" ${field.kind === "number" ? 'inputmode="decimal"' : ""}
        placeholder="${esc(field.placeholder || (field.default ?? ""))}" value="${esc(shown)}" autocomplete="off" spellcheck="false">`;
    }
    const hint = field.help ? `<span class="field-hint">${esc(field.help)}</span>` : "";
    return `<div class="flex flex-col gap-1.5 ${wide}">${label}${control}${hint}</div>`;
  }

  function upstream(id) {
    const seen = new Set();
    const stack = [id];
    while (stack.length) {
      const cur = stack.pop();
      edges.filter((e) => e.to === cur).forEach((e) => { if (!seen.has(e.from)) { seen.add(e.from); stack.push(e.from); } });
    }
    return [...seen].map(byId).filter(Boolean);
  }

  function chipsHtml(d) {
    const chips = [];
    upstream(d.id).forEach((u) => {
      const spec = SPECS[u.data.type];
      const name = u.data.name || (u.data.type === "set_variable" ? u.data.variable : "");
      if (name) {
        chips.push([`{{ ${name} }}`, `${spec.label} : ${spec.output || "valeur"}`]);
        (spec.output_keys || []).forEach((k) => chips.push([`{{ ${name}.${k} }}`, `${spec.label} › ${k}`]));
      }
      if (u.data.type === "for_each") {
        chips.push([`{{ ${u.data.item_var || "item"} }}`, "élément courant de la boucle"], ["{{ loop.index }}", "numéro de l'élément"]);
      }
    });
    BUILTINS.forEach(([v, t]) => chips.push([`{{ ${v} }}`, t]));
    return chips.map(([v, t]) => `<button type="button" class="var-chip" data-insert="${esc(v)}" title="${esc(t)}">${esc(v.replace(/[{}]/g, "").trim())}</button>`).join("");
  }

  function renderInspector() {
    const box = $("inspector");
    if (!selected || selected.kind !== "node") {
      if (selected?.kind === "edge") {
        const e = edges[selected.id];
        box.innerHTML = e ? `<div class="space-y-3"><div class="text-sm font-medium">Lien sélectionné</div>
          <p class="text-sm text-on-surface-variant">${esc(byId(e.from)?.data.name || byId(e.from)?.data.type)} (${esc(labelOf(e.port))}) → ${esc(byId(e.to)?.data.name || byId(e.to)?.data.type)}</p>
          <button type="button" class="btn-danger w-full" data-act="delete">${HSC.icon("trash-2", "w-4 h-4")} Supprimer le lien</button></div>` : "";
        return;
      }
      box.innerHTML = `<div class="space-y-3 text-sm">
        <div class="font-medium flex items-center gap-2">${HSC.icon("workflow", "w-4 h-4")} Comment ça marche</div>
        <ul class="space-y-2 text-on-surface-variant list-disc pl-4">
          <li>Les noeuds sans lien entrant sont les <b>départs</b> : ils s'exécutent quand le geste est reconnu.</li>
          <li>Tire depuis un <b>point coloré</b> d'un noeud jusqu'à un autre pour les relier (<i>suite</i>, <i>vrai</i>, <i>faux</i>, <i>pour chaque</i>, <i>erreur</i>…).</li>
          <li>Donne un <b>nom</b> à un noeud : sa sortie devient une variable, utilisable partout avec <code class="font-mono text-accent">{{ nom }}</code>.</li>
          <li>Filtres : <code class="font-mono text-accent">{{ nom | upper }}</code>, <code class="font-mono text-accent">{{ gesture.value * 10 }}</code>…</li>
        </ul>
        <div class="field-label pt-2">Variables du geste</div>
        <div class="flex flex-wrap gap-1.5">${BUILTINS.map(([v, t]) => `<span class="var-chip" title="${esc(t)}">${esc(v)}</span>`).join("")}</div></div>`;
      return;
    }
    const n = byId(selected.id);
    const d = n.data;
    const spec = SPECS[d.type];
    box.innerHTML = `
      <div class="flex items-center gap-2 mb-3 cat-${spec.category}">
        <span class="cat-chip w-9 h-9 rounded-lg flex items-center justify-center">${HSC.icon(spec.icon, "w-5 h-5")}</span>
        <div class="min-w-0 flex-1"><div class="font-medium truncate">${esc(spec.label)}</div><div class="text-[11px] font-mono text-on-surface-variant">${esc(d.id)}</div></div>
        <button type="button" class="icon-btn" data-act="duplicate" title="Dupliquer">${HSC.icon("copy", "w-[18px] h-[18px]")}</button>
        <button type="button" class="icon-btn danger" data-act="delete" title="Supprimer le noeud">${HSC.icon("trash-2", "w-[18px] h-[18px]")}</button>
      </div>
      <p class="text-sm text-on-surface-variant mb-3">${esc(spec.description)}</p>
      ${spec.note ? `<p class="text-xs text-warning mb-3">${esc(spec.note)}</p>` : ""}
      ${spec.output ? `<div class="mb-3"><label for="f-name" class="field-label flex items-center gap-1.5">${HSC.icon("variable", "w-3.5 h-3.5")}Nom de la variable (sortie)</label>
        <input id="f-name" data-key="name" data-kind="name" type="text" class="field-input font-mono" placeholder="ex : contenu" value="${esc(d.name || "")}" maxlength="32" spellcheck="false">
        <span class="field-hint">${esc(spec.output)}${spec.output_keys.length ? ` — sous-champs : ${spec.output_keys.join(", ")}` : ""}</span></div>` : ""}
      <div class="grid grid-cols-2 gap-3">${spec.fields.map((f) => fieldHtml(n, f)).join("")}</div>
      <details class="mt-4 border-t border-outline pt-3"><summary class="cursor-pointer text-xs font-mono uppercase tracking-wider text-on-surface-variant">Options avancées</summary>
        <div class="grid grid-cols-2 gap-3 mt-3">
          <div class="flex flex-col gap-1.5 col-span-2"><label for="f-label" class="field-label">Titre affiché</label>
            <input id="f-label" data-key="label" data-kind="text" class="field-input" value="${esc(d.label || "")}" placeholder="${esc(spec.label)}" maxlength="60"></div>
          <div class="flex flex-col gap-1.5"><label for="f-wait_ms" class="field-label">Pause après (ms)</label>
            <input id="f-wait_ms" data-key="wait_ms" data-kind="number" inputmode="numeric" class="field-input font-mono" placeholder="0" value="${esc(d.wait_ms ?? "")}"></div>
          <div class="flex flex-col gap-1.5"><label for="f-only_on" class="field-label">Plateforme</label>
            <select id="f-only_on" data-key="only_on" data-kind="select" class="field-input">${Object.entries(PLATFORM_LABELS).map(([k, l]) =>
              `<option value="${k}" ${(d.only_on || "all") === k ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></div>
          <div class="flex flex-col gap-1.5 col-span-2"><label for="f-on_error" class="field-label">En cas d'erreur</label>
            <select id="f-on_error" data-key="on_error" data-kind="select" class="field-input">
              <option value="continue" ${d.on_error !== "stop" ? "selected" : ""}>Continuer la suite</option>
              <option value="stop" ${d.on_error === "stop" ? "selected" : ""}>Arrêter cette branche</option></select>
            <span class="field-hint">Un lien « erreur » prend la main à la place quand il existe.</span></div>
          <div class="col-span-2 flex items-center gap-3">
            <button type="button" role="switch" aria-checked="${d.enabled === false ? "false" : "true"}" id="f-enabled" data-key="enabled" data-kind="enabled" class="switch" aria-label="Noeud actif"></button>
            <span class="text-sm">Noeud actif</span></div>
        </div></details>
      <div class="mt-4 border-t border-outline pt-3">
        <div class="field-label mb-2 flex items-center gap-1.5">${HSC.icon("braces", "w-3.5 h-3.5")} Insérer une variable</div>
        <div class="flex flex-wrap gap-1.5" id="chips">${chipsHtml(d)}</div>
        <span class="field-hint block mt-2">Clique dans un champ, puis sur une variable. Elles viennent des noeuds reliés en amont.</span>
      </div>`;
  }

  $("inspector").addEventListener("focusin", (event) => {
    if (/^(INPUT|TEXTAREA)$/.test(event.target.tagName) && event.target.dataset.key) lastField = event.target;
  });

  $("inspector").addEventListener("click", (event) => {
    const chip = event.target.closest("[data-insert]");
    if (chip && lastField && document.body.contains(lastField)) {
      const el = lastField;
      const start = el.selectionStart ?? el.value.length;
      const end = el.selectionEnd ?? start;
      el.value = el.value.slice(0, start) + chip.dataset.insert + el.value.slice(end);
      el.focus();
      el.setSelectionRange(start + chip.dataset.insert.length, start + chip.dataset.insert.length);
      el.dispatchEvent(new Event("input", { bubbles: true }));
      return;
    }
    const sw = event.target.closest('button[role="switch"]');
    if (sw) {
      sw.setAttribute("aria-checked", sw.getAttribute("aria-checked") === "true" ? "false" : "true");
      readField(sw);
      return;
    }
    const act = event.target.closest("[data-act]")?.dataset.act;
    if (act === "delete") deleteSelected();
    if (act === "duplicate" && selected?.kind === "node") {
      const src = byId(selected.id);
      const copy = { uid: ++uid, data: { ...JSON.parse(JSON.stringify(src.data)), id: newId(), x: src.data.x + 30, y: src.data.y + 30 } };
      if (copy.data.name) copy.data.name = autoName(copy.data.type) || copy.data.name;
      nodes.push(copy);
      markDirty();
      select("node", copy.data.id);
    }
  });

  function parseNumber(text) {
    return /^-?\d+(\.\d+)?$/.test(text.trim()) ? Number(text) : text;
  }

  function readField(el) {
    if (!selected || selected.kind !== "node") return;
    const d = byId(selected.id).data;
    const key = el.dataset.key;
    const kind = el.dataset.kind;
    let value;
    if (kind === "bool" || kind === "enabled") value = el.getAttribute("aria-checked") === "true";
    else if (kind === "number" || kind === "monitor") value = el.value.trim() === "" ? undefined : parseNumber(el.value);
    else if (kind === "list") value = el.value.split(",").map((s) => s.trim()).filter(Boolean);
    else value = el.value;
    if (key === "only_on") {
      if (value === "all") delete d.only_on; else d.only_on = value;
    } else if (key === "enabled") {
      if (value) delete d.enabled; else d.enabled = false;
    } else if (key === "on_error") {
      if (value === "stop") d.on_error = "stop"; else delete d.on_error;
    } else if (value === undefined || value === "" || (Array.isArray(value) && !value.length) || (kind === "bool" && !value)) {
      delete d[key];
    } else {
      d[key] = value;
    }
    el.classList.remove("invalid");
    const card = nodeEl(d.id);
    if (card) card.querySelector(".gnode-sum").textContent = summarize(d);
    markDirty();
    if (["name", "label", "only_on", "enabled"].includes(key) || kind === "select" && key === "metric") {
      const keepField = el.id;
      render();
      const again = document.getElementById(keepField);
      if (again && /^(INPUT|TEXTAREA)$/.test(again.tagName)) { again.focus(); try { again.setSelectionRange(again.value.length, again.value.length); } catch { /* ignore */ } }
    } else {
      renderEdges();
    }
  }
  $("inspector").addEventListener("input", (event) => { if (event.target.dataset?.key && event.target.getAttribute("role") !== "switch") readField(event.target); });
  $("inspector").addEventListener("change", (event) => { if (event.target.dataset?.key && event.target.tagName === "SELECT") readField(event.target); });

  // ---------------------------------------------------------------------- palette
  function addNode(type) {
    const spec = SPECS[type];
    const raw = { id: newId(), type };
    spec.fields.forEach((f) => { if (f.default !== null && f.default !== undefined && f.kind !== "bool") raw[f.key] = f.default; });
    const name = autoName(type);
    if (name) raw.name = name;
    const parent = selected?.kind === "node" ? byId(selected.id) : (nodes.length ? nodes[nodes.length - 1] : null);
    raw.x = parent ? parent.data.x : 40;
    raw.y = parent ? parent.data.y + 150 : 40;
    while (nodes.some((n) => Math.abs(n.data.x - raw.x) < 30 && Math.abs(n.data.y - raw.y) < 30)) raw.x += NW + 48;
    const node = { uid: ++uid, data: raw };
    nodes.push(node);
    if (parent && !edges.some((e) => e.from === parent.data.id && e.port === "out")) {
      const port = portsOf(parent.data.type)[0];
      if (!edges.some((e) => e.from === parent.data.id && e.port === port)) edges.push({ from: parent.data.id, port, to: raw.id });
    }
    selected = { kind: "node", id: raw.id };
    markDirty();
    render();
    nodeEl(raw.id)?.scrollIntoView({ block: "center", inline: "center", behavior: "smooth" });
  }

  function renderPalette() {
    const query = norm($("palette-search").value.trim());
    const tabs = [{ key: "all", label: "Tous", icon: "layout-grid" }, ...CATEGORIES];
    $("palette-tabs").innerHTML = tabs.map((c) => `
      <button type="button" data-cat="${c.key}" title="${esc(c.label)}"
        class="chip border border-outline ${c.key === "all" ? "" : `cat-${c.key}`} ${activeCategory === c.key ? (c.key === "all" ? "chip-primary" : "cat-active") : "chip-muted"}">
        ${HSC.icon(c.icon, "w-3.5 h-3.5")}${c.key === "all" ? "Tous" : ""}</button>`).join("");
    let html = "";
    for (const category of CATEGORIES) {
      if (activeCategory !== "all" && activeCategory !== category.key) continue;
      const items = data.steps.filter((s) => !s.hidden && s.category === category.key && (!query ||
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
    $("palette").innerHTML = html || `<p class="text-sm text-on-surface-variant px-1 py-6 text-center">Aucun noeud ne correspond.</p>`;
  }
  $("palette-search").addEventListener("input", renderPalette);
  $("palette-tabs").addEventListener("click", (event) => {
    const tab = event.target.closest("[data-cat]");
    if (tab) { activeCategory = tab.dataset.cat; renderPalette(); }
  });
  $("palette").addEventListener("click", (event) => {
    const item = event.target.closest("[data-add]");
    if (item) addNode(item.dataset.add);
  });
  $("btn-layout").addEventListener("click", () => autoLayout(false));

  // ------------------------------------------------------ validation / test / envoi
  function validate() {
    let problems = 0;
    let first = null;
    nodes.forEach((n) => {
      const spec = SPECS[n.data.type];
      const empty = (key) => {
        const v = n.data[key];
        return v === undefined || v === null || v === "" || (Array.isArray(v) && !v.length);
      };
      const missing = new Set(spec.required.filter(empty));
      if (spec.any_of.length && spec.any_of.every(empty)) spec.any_of.forEach((k) => missing.add(k));
      n.missing = missing.size ? missing : null;
      if (missing.size) { problems += missing.size; first = first || n; }
    });
    if (first) {
      select("node", first.data.id);
      (first.missing || []).forEach((key) => document.getElementById(`f-${key}`)?.classList.add("invalid"));
    }
    return problems;
  }

  const payload = () => ({
    id: initial.id || null,
    name: $("action-name").value.trim(),
    nodes: nodes.map((n) => ({ ...n.data, x: Math.round(n.data.x), y: Math.round(n.data.y) })),
    edges: edges.map((e) => ({ from: e.from, port: e.port, to: e.to })),
    ...(initial.description ? { description: initial.description } : {}),
  });

  $("btn-test").addEventListener("click", async () => {
    if (!nodes.length) { HSC.toast("Ajoute d'abord des noeuds.", "error"); return; }
    const problems = validate();
    if (problems) { HSC.toast(`${problems} champ(s) à compléter.`, "error"); return; }
    try {
      const before = (await HSC.api("GET", "/api/events?since=999999999")).last_id;
      const result = await HSC.api("POST", "/api/actions/test", { ...payload(), name: payload().name || "Test" });
      const trace = (await HSC.api("GET", `/api/events?since=${before}`)).events.filter((e) => e.kind === "step");
      runStatus = {};
      trace.forEach((e) => { runStatus[e.node_id] = e.status; });
      render();
      showResult(result, trace);
      HSC.toast(result.success ? "Workflow exécuté." : "Exécuté avec des erreurs (voir le résultat).", result.success ? "success" : "error");
    } catch (err) {
      HSC.toast(err.message, "error");
    }
  });

  function showResult(result, trace) {
    $("test-result").classList.remove("hidden");
    $("test-summary").textContent = `${result.success ? "Succès" : "Terminé avec des erreurs"} en ${HSC.fmtMs(result.ms)} — ${trace.length} noeud(s) exécuté(s).`;
    const vars = Object.entries(result.vars || {}).filter(([k, v]) => !["gesture", "trigger", "args", "loop"].includes(k) && v !== null && v !== undefined);
    const lines = trace.map((e) => `<div class="${e.status === "error" ? "text-error" : "text-on-surface-variant"}">${esc(e.label)} · ${esc(e.status)} · ${HSC.fmtMs(e.ms)}${e.output ? ` → ${esc(e.output)}` : ""}${(e.errors || []).length ? ` — ${esc(e.errors.join(" | "))}` : ""}</div>`);
    $("test-vars").innerHTML = lines.join("") + (vars.length ? `<div class="pt-2 text-accent">Variables :</div>${vars.map(([k, v]) =>
      `<div><span class="text-accent">${esc(k)}</span> = ${esc(typeof v === "string" ? v : JSON.stringify(v)).slice(0, 300)}</div>`).join("")}` : "");
  }

  async function save() {
    const body = payload();
    if (!body.name) { $("action-name").focus(); HSC.toast("Donne un nom au workflow.", "error"); return; }
    if (!nodes.length) { HSC.toast("Le workflow est vide.", "error"); return; }
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
  $("action-name").addEventListener("input", markDirty);
  window.addEventListener("beforeunload", (event) => { if (dirty) { event.preventDefault(); event.returnValue = ""; } });
  window.addEventListener("resize", sizeCanvas);

  load();
  render();
  renderPalette();
})();
