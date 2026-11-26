// gesture_form.js — création et édition d'un geste : pose enregistrée, mouvement, doigts levés,
// comptage, dessin dans l'air, deux mains, conditions système.
"use strict";

(() => {
  const DEFAULTS = {
    static: { threshold: 0.16, hold_ms: 270, hint: "Pose statique : maintiens la position immobile pendant l'enregistrement." },
    sequence: { threshold: 0.22, hint: "Mouvement : effectue le geste complet, du début à la fin, pendant l'enregistrement." },
    pose: { hold_ms: 400, hint: "Doigts levés : choisis quels doigts doivent être levés ou baissés. Aucun enregistrement nécessaire." },
    count: { hold_ms: 700, hint: "Comptage : le nombre de doigts levés est transmis au workflow ({{ gesture.value }})." },
    draw: { hint: "Dessin : trace un chiffre ou une forme dans l'air avec l'index ; le résultat est transmis au workflow." },
    sound: { hold_ms: 300, hint: "Son : claquements (simple, double, triple) ou niveau sonore, via le micro (à autoriser dans les réglages)." },
    voice: { hint: "Voix : dis une phrase, reconnue hors ligne. Le texte et un éventuel nombre sont transmis au workflow." },
    fingerprint: { hint: "Empreinte : se déclenche quand le lecteur reconnaît (ou refuse) un doigt." },
    device: { hint: "Branchement : USB, Bluetooth, secteur, capot ou Wi-Fi qui change d'état." },
    sensor: { hold_ms: 0, hint: "Capteur : se déclenche quand une mesure passe un seuil (lumière, secousse, température, capteur externe…)." },
  };
  const PHYSICAL = ["sound", "voice", "fingerprint", "device", "sensor"];
  const RECORDED = ["static", "sequence"];
  const FINGERS = ["Pouce", "Index", "Majeur", "Annulaire", "Auriculaire"];
  const PRESETS = { "Poing": [0, 0, 0, 0, 0], "Main ouverte": [1, 1, 1, 1, 1], "Pouce levé": [1, 0, 0, 0, 0], "Index": [0, 1, 0, 0, 0],
    "Victoire": [0, 1, 1, 0, 0], "Trois": [0, 1, 1, 1, 0], "Quatre": [0, 1, 1, 1, 1], "Rock": [0, 1, 0, 0, 1], "Téléphone": [1, 0, 0, 0, 1] };
  const $ = (id) => document.getElementById(id);
  const esc = HSC.esc;
  const form = $("gesture-form");
  const gestureId = form.dataset.gestureId || null;
  const editing = Boolean(gestureId);
  const originalType = form.dataset.type;
  const legacyFps = Number(form.dataset.legacyFps) || 30;
  const initial = editing ? JSON.parse($("gesture-data").textContent) : {};
  const options = JSON.parse($("gesture-options").textContent);
  const SHAPE_NAMES = { cercle: "Cercle", carre: "Carré", triangle: "Triangle", coche: "Coche", croix: "Croix", plus: "Plus",
    etoile: "Étoile", fleche: "Flèche", ligne: "Ligne", zigzag: "Zigzag", coeur: "Cœur" };

  let capture = null;
  let recording = false;
  let liveFps = 0;
  let cameraOk = false;
  let fingers = [initial.fingers ? [...initial.fingers] : [1, 0, 0, 0, 0], initial.fingers_second ? [...initial.fingers_second] : [null, null, null, null, null]];
  let conditions = (initial.conditions || []).map((c) => ({ ...c }));
  let chosenLabels = new Set(initial.labels || []);
  let learning = false;

  const currentType = () => document.querySelector('input[name="type"]:checked').value;
  const num = (id) => parseFloat($(id).value);
  const isRecorded = () => RECORDED.includes(currentType());

  function setStatus(text, dotClass) {
    $("rec-status").textContent = text;
    $("rec-dot").className = `w-1.5 h-1.5 rounded-full ${dotClass}`;
  }

  // ---------------------------------------------------------------- doigts
  function fingerRow(hand) {
    return `<div class="flex gap-1.5">${FINGERS.map((name, i) => {
      const v = fingers[hand][i];
      const cls = v === 1 ? "border-success bg-success/15 text-success" : v === 0 ? "border-error bg-error/10 text-error" : "border-outline text-on-surface-variant";
      return `<button type="button" data-finger="${hand}:${i}" class="flex-1 border rounded-lg py-2 text-xs ${cls}">
        <div class="font-medium">${name}</div><div class="font-mono mt-0.5">${v === 1 ? "levé" : v === 0 ? "baissé" : "peu importe"}</div></button>`;
    }).join("")}</div>`;
  }
  function renderPose() {
    $("pose-main").innerHTML = `<div class="text-xs text-on-surface-variant mb-1.5">${$("hands").value === "2" ? "Première main (à gauche de l'image)" : "Main"}</div>${fingerRow(0)}`;
    $("pose-second").innerHTML = `<div class="text-xs text-on-surface-variant mb-1.5">Seconde main (à droite de l'image)</div>${fingerRow(1)}`;
    $("pose-second").classList.toggle("hidden", $("hands").value !== "2");
    $("pose-presets").innerHTML = Object.keys(PRESETS).map((n) => `<button type="button" data-preset="${esc(n)}" class="chip chip-muted border border-outline">${esc(n)}</button>`).join("");
  }
  document.addEventListener("click", (event) => {
    const f = event.target.closest("[data-finger]");
    if (f) {
      const [hand, i] = f.dataset.finger.split(":").map(Number);
      const order = [1, 0, null];
      fingers[hand][i] = order[(order.indexOf(fingers[hand][i]) + 1) % 3];
      renderPose();
      return;
    }
    const p = event.target.closest("[data-preset]");
    if (p) {
      fingers[0] = [...PRESETS[p.dataset.preset]];
      if ($("hands").value === "2") fingers[1] = [...PRESETS[p.dataset.preset]];
      renderPose();
    }
  });

  // --------------------------------------------------------------- symboles
  function renderLabels() {
    const set = options.charsets[$("charset").value] || [];
    const all = [...set, ...options.custom_labels.filter((l) => !set.includes(l))];
    $("labels").innerHTML = all.map((l) => {
      const on = chosenLabels.has(l);
      return `<button type="button" data-label="${esc(l)}" class="chip border ${on ? "border-primary bg-primary/15 text-accent" : "border-outline chip-muted"}">${esc(SHAPE_NAMES[l] || l)}</button>`;
    }).join("");
    $("custom-list").innerHTML = options.custom_labels.map((l) => `<span class="chip chip-primary">${esc(l)}
      <button type="button" data-forget="${esc(l)}" class="ml-1 hover:text-error" title="Oublier ce tracé">×</button></span>`).join("");
  }
  document.addEventListener("click", async (event) => {
    const l = event.target.closest("[data-label]");
    if (l) { chosenLabels.has(l.dataset.label) ? chosenLabels.delete(l.dataset.label) : chosenLabels.add(l.dataset.label); renderLabels(); return; }
    const f = event.target.closest("[data-forget]");
    if (f) {
      try {
        await HSC.api("DELETE", `/api/drawings/${encodeURIComponent(f.dataset.forget)}`);
        options.custom_labels = options.custom_labels.filter((x) => x !== f.dataset.forget);
        chosenLabels.delete(f.dataset.forget);
        renderLabels();
      } catch (err) { HSC.toast(err.message, "error"); }
    }
  });
  $("charset").addEventListener("change", renderLabels);
  $("min_confidence").addEventListener("input", () => { $("conf-label").textContent = `${Math.round($("min_confidence").value * 100)} %`; });

  // L'apprentissage d'un tracé réutilise le suivi du stylo : le dernier trait vu par la caméra devient un modèle.
  $("btn-learn").addEventListener("click", () => {
    const name = $("learn-name").value.trim();
    if (!name) { $("learn-name").focus(); HSC.toast("Donne d'abord un nom au symbole.", "error"); return; }
    learning = true;
    $("btn-learn").disabled = true;
    HSC.toast("Dessine maintenant ton symbole avec l'index (puis baisse la main).", "info", { ms: 5000 });
  });
  let lastTrailLength = 0;
  let lastTrail = [];
  async function finishLearning() {
    if (!learning || lastTrail.length < 8) return;
    learning = false;
    $("btn-learn").disabled = false;
    const name = $("learn-name").value.trim();
    try {
      const reply = await HSC.api("POST", "/api/drawings", { label: name, strokes: [lastTrail] });
      options.custom_labels = reply.custom;
      chosenLabels.add(name);
      $("learn-name").value = "";
      renderLabels();
      HSC.toast(`Tracé « ${name} » appris.`, "success");
    } catch (err) { HSC.toast(err.message, "error"); }
  }

  // ------------------------------------------------------------- conditions
  const METRICS = options.metrics.metrics;
  const OPS = options.metrics.operators;
  const metricOf = (key) => METRICS.find((m) => m.key === key) || METRICS[0];
  function renderConditions() {
    $("cond-empty").classList.toggle("hidden", conditions.length > 0);
    $("cond-mode-row").classList.toggle("hidden", conditions.length < 2);
    $("conditions").innerHTML = conditions.map((c, i) => {
      const m = metricOf(c.metric);
      return `<div class="border border-outline rounded-lg p-2.5 space-y-2" data-cond="${i}">
        <div class="flex items-center gap-2">
          <select data-c="metric" class="field-input flex-1">${METRICS.map((x) => `<option value="${x.key}" ${x.key === c.metric ? "selected" : ""}>${esc(x.label)}</option>`).join("")}</select>
          <button type="button" data-c-del class="icon-btn danger" title="Retirer">${HSC.icon("trash-2", "w-4 h-4")}</button></div>
        <div class="flex items-center gap-2">
          ${m.kind === "bool" ? `<select data-c="value" class="field-input"><option value="true" ${c.value !== false ? "selected" : ""}>oui</option><option value="false" ${c.value === false ? "selected" : ""}>non</option></select>`
            : `<select data-c="op" class="field-input w-20">${OPS.map((o) => `<option ${o === c.op ? "selected" : ""}>${esc(o)}</option>`).join("")}</select>
               <input data-c="value" type="number" step="any" class="field-input" value="${esc(c.value ?? 0)}"><span class="text-xs text-on-surface-variant font-mono">${esc(m.unit || "")}</span>`}
        </div>
        ${m.arg_label ? `<input data-c="arg" class="field-input font-mono" placeholder="${esc(m.arg_label)}" value="${esc(c.arg || "")}">` : ""}
        <label class="flex items-center gap-2 text-xs text-on-surface-variant"><input type="checkbox" data-c="pass" class="accent-primary" ${c.on_unknown === "pass" ? "checked" : ""}> Ignorer cette condition si la mesure est indisponible (ex : capteur de température absent)</label>
        <div class="field-hint" data-now="${i}">${esc(m.help || "")}</div>
      </div>`;
    }).join("");
  }
  $("btn-add-cond").addEventListener("click", () => {
    const m = METRICS.find((x) => x.key === "cpu_percent") || METRICS[0];
    conditions.push({ metric: m.key, op: "<", value: m.kind === "bool" ? true : 70 });
    renderConditions();
  });
  $("conditions").addEventListener("click", (event) => {
    if (event.target.closest("[data-c-del]")) { conditions.splice(Number(event.target.closest("[data-cond]").dataset.cond), 1); renderConditions(); }
  });
  $("conditions").addEventListener("change", (event) => {
    const el = event.target.closest("[data-c]");
    if (!el) return;
    const i = Number(el.closest("[data-cond]").dataset.cond);
    const c = conditions[i];
    const key = el.dataset.c;
    if (key === "metric") {
      const m = metricOf(el.value);
      conditions[i] = { metric: m.key, op: m.kind === "bool" ? "==" : "<", value: m.kind === "bool" ? true : 0 };
      renderConditions();
    } else if (key === "value") c.value = metricOf(c.metric).kind === "bool" ? el.value === "true" : Number(el.value);
    else if (key === "pass") { if (el.checked) c.on_unknown = "pass"; else delete c.on_unknown; }
    else if (key === "arg") c.arg = el.value;
    else c[key] = el.value;
  });
  $("conditions").addEventListener("input", (event) => {
    const el = event.target.closest('[data-c="arg"], [data-c="value"]');
    if (el) el.dispatchEvent(new Event("change", { bubbles: true }));
  });
  async function showMetricValues() {
    try {
      const { values } = await HSC.api("GET", "/api/system/metrics");
      conditions.forEach((c, i) => {
        const el = document.querySelector(`[data-now="${i}"]`);
        const v = values[c.metric];
        if (el && v !== undefined) el.textContent = v === null ? "Mesure indisponible sur cet ordinateur." : `Valeur actuelle : ${typeof v === "boolean" ? (v ? "oui" : "non") : Math.round(v * 10) / 10}`;
      });
    } catch { /* ignore */ }
  }
  setInterval(showMetricValues, 4000);

  // -------------------------------------------------------------- affichage
  function updateHints() {
    const ms = num("hold_ms");
    if (Number.isFinite(ms)) {
      const fps = liveFps || legacyFps;
      const frames = Math.max(1, Math.round((ms * fps) / 1000));
      $("hold-hint").textContent = `${HSC.fmtMs(ms)} ≈ ${frames} image(s) à ${String(Math.round(fps * 10) / 10).replace(".", ",")} images/s`;
    }
    const cooldown = num("cooldown_seconds");
    $("cooldown-hint").textContent = Number.isFinite(cooldown) ? HSC.fmtSeconds(cooldown) : "";
    const duration = capture && capture.type === "sequence" ? capture.duration : Number(form.dataset.duration) || null;
    const keyframes = capture && capture.type === "sequence" ? capture.keyframes.length : Number(form.dataset.keyframes) || 10;
    if (currentType() === "sequence" && duration) {
      $("sequence-duration").textContent = `Mouvement enregistré : ${HSC.fmtSeconds(duration)}`;
      $("sequence-frames").textContent = `${keyframes} images-clés comparées, une toutes les ${Math.round((duration * 1000) / Math.max(1, keyframes - 1))} ms.`;
    } else {
      $("sequence-duration").textContent = "Enregistre le mouvement pour en connaître la durée.";
      $("sequence-frames").textContent = "";
    }
  }

  const needsCapture = () => isRecorded() && (!editing || currentType() !== originalType);
  function updateSave() { $("btn-save").disabled = recording || (needsCapture() && !capture); }

  function applyType(resetValues) {
    const type = currentType();
    $("type-hint").textContent = DEFAULTS[type].hint;
    $("threshold-field").classList.toggle("hidden", !isRecorded());
    $("sequence-info").classList.toggle("hidden", type !== "sequence");
    $("record-buttons").classList.toggle("hidden", !isRecorded());
    $("pose-panel").classList.toggle("hidden", type !== "pose");
    $("count-panel").classList.toggle("hidden", type !== "count");
    $("draw-options").classList.toggle("hidden", type !== "draw");
    $("draw-panel").classList.toggle("hidden", type !== "draw");
    $("hands-field").classList.toggle("hidden", type === "draw" || type === "sequence" || PHYSICAL.includes(type));
    const physical = PHYSICAL.includes(type);
    $("camera-col").classList.toggle("hidden", physical);
    $("sensor-col").classList.toggle("hidden", !physical);
    ["sound", "voice", "fingerprint", "device", "sensor"].forEach((k) => $(`${k}-panel`).classList.toggle("hidden", type !== k));
    const loudness = type === "sound" && ["loud", "silence"].includes($("sound").value);
    $("hold-field").classList.toggle("hidden", !(["static", "pose", "count"].includes(type) || loudness || type === "sensor"));
    $("sensitivity-field").classList.toggle("hidden", loudness);
    $("level-field").classList.toggle("hidden", !loudness);
    syncMetric();
    $("hands-any").classList.toggle("hidden", type !== "count");
    $("hands-any").disabled = type !== "count";
    if ($("hands").value === "any" && type !== "count") $("hands").value = "1";
    if (resetValues) {
      if (DEFAULTS[type].threshold) { $("threshold").value = DEFAULTS[type].threshold; $("threshold-range").value = DEFAULTS[type].threshold; }
      if (DEFAULTS[type].hold_ms !== undefined) { $("hold_ms").value = DEFAULTS[type].hold_ms; $("hold-range").value = DEFAULTS[type].hold_ms; }
    }
    if (capture && capture.type !== type) { capture = null; $("capture-info").classList.add("hidden"); }
    renderPose();
    updateHints();
    updateSave();
  }

  // ------------------------------------------------------ capteurs physiques
  const SENSOR_METRICS = METRICS;
  $("metric").innerHTML = SENSOR_METRICS.map((m) => `<option value="${m.key}">${esc(m.label)}</option>`).join("");
  $("op").innerHTML = OPS.map((o) => `<option>${esc(o)}</option>`).join("");
  function syncMetric() {
    const m = metricOf($("metric").value);
    $("metric_arg").classList.toggle("hidden", !m.arg_label);
    $("metric_arg").placeholder = m.arg_label || "";
    $("sensor_bool").classList.toggle("hidden", m.kind !== "bool");
    $("sensor_value").classList.toggle("hidden", m.kind === "bool");
    $("op").classList.toggle("hidden", m.kind === "bool");
    $("metric-unit").textContent = m.unit || "";
  }
  async function pollSensors() {
    if (!PHYSICAL.includes(currentType())) return;
    try {
      const st = await HSC.api("GET", "/api/sensors/status");
      const lines = [];
      lines.push(`micro : ${st.mic.open ? `ouvert, ${st.mic.level_db === null ? "—" : st.mic.level_db.toFixed(0)} dB` : st.mic.enabled ? "fermé (aucun déclencheur Son/Voix enregistré)" : "désactivé"}`);
      Object.entries(st.errors || {}).forEach(([k, v]) => lines.push(`⚠ ${k} : ${v}`));
      if (currentType() === "sensor") {
        const { values } = await HSC.api("GET", "/api/system/metrics");
        const v = values[$("metric").value];
        lines.push(`${metricOf($("metric").value).label} : ${v === null || v === undefined ? "indisponible sur cette machine" : v}`);
      }
      $("sensor-live").innerHTML = lines.map((l) => `<div>${esc(l)}</div>`).join("");
    } catch { /* serveur arrêté */ }
  }
  setInterval(pollSensors, 1500);
  $("metric").addEventListener("change", syncMetric);
  $("sound").addEventListener("change", () => applyType(false));
  $("sensitivity").addEventListener("input", () => { $("sens-label").textContent = `${Math.round($("sensitivity").value * 100)} %`; });

  // --- valeurs initiales ---
  const set = (id, value) => { $(id).value = value; };
  const startType = currentType();
  set("threshold", initial.threshold ?? DEFAULTS[startType].threshold ?? 0.16);
  set("threshold-range", $("threshold").value);
  set("hold_ms", initial.hold_ms ?? DEFAULTS[startType].hold_ms ?? 270);
  set("hold-range", $("hold_ms").value);
  set("cooldown_seconds", initial.cooldown_seconds ?? 10);
  set("hands", String(initial.hands ?? 1));
  set("min_value", initial.min_value ?? 1);
  set("max_value", initial.max_value ?? 10);
  set("charset", initial.charset ?? "digits");
  set("recognizer", initial.recognizer ?? "local");
  set("pen", initial.pen ?? "index");
  set("idle_ms", initial.idle_ms ?? 800);
  set("min_confidence", initial.min_confidence ?? 0.7);
  $("conf-label").textContent = `${Math.round($("min_confidence").value * 100)} %`;
  set("conditions_mode", initial.conditions_mode ?? "all");
  set("sound", initial.sound ?? "double_clap");
  set("sensitivity", initial.sensitivity ?? 0.5);
  $("sens-label").textContent = `${Math.round($("sensitivity").value * 100)} %`;
  set("level_db", initial.level_db ?? -20);
  set("phrases", (initial.phrases || []).join("\n"));
  set("match", initial.match ?? "contains");
  set("result", initial.result ?? "match");
  set("finger", initial.finger ?? "");
  set("event", initial.event ?? "usb_plugged");
  set("device_match", initial.type === "device" ? (initial.match ?? "") : "");
  set("metric", initial.metric ?? METRICS[0].key);
  set("metric_arg", initial.arg ?? "");
  set("op", initial.op ?? ">");
  set("sensor_value", typeof initial.value === "number" ? initial.value : 0);
  set("sensor_bool", initial.value === false ? "false" : "true");
  set("edge", initial.edge ?? "rising");
  if (initial.type === "voice") set("match", initial.match ?? "contains");
  renderLabels();
  renderConditions();
  applyType(false);

  [["threshold-range", "threshold"], ["hold-range", "hold_ms"]].forEach(([range, field]) => {
    $(range).addEventListener("input", () => { $(field).value = $(range).value; updateHints(); });
    $(field).addEventListener("input", () => { $(range).value = $(field).value; updateHints(); });
  });
  $("cooldown_seconds").addEventListener("input", updateHints);
  $("hands").addEventListener("change", renderPose);
  document.querySelectorAll('input[name="type"]').forEach((r) => r.addEventListener("change", () => applyType(true)));

  // --- état de la caméra ---
  let cameraWasOk = false;
  document.addEventListener("camera-status", (event) => {
    cameraOk = event.detail.camera === "ok";
    liveFps = cameraOk ? event.detail.fps || 0 : 0;
    if (cameraOk && !cameraWasOk) $("video").src = `/video_feed?t=${Date.now()}`;
    cameraWasOk = cameraOk;
    const overlay = $("camera-overlay");
    overlay.classList.toggle("hidden", cameraOk);
    overlay.classList.toggle("flex", !cameraOk);
    $("camera-overlay-text").textContent = event.detail.error || "Caméra indisponible.";
    if (!recording) {
      $("btn-start").disabled = !cameraOk;
      setStatus(cameraOk ? "Prêt" : "Caméra indisponible", cameraOk ? "bg-success" : "bg-error");
    }
    updateHints();
  });

  // --- enregistrement ---
  $("btn-start").addEventListener("click", async () => {
    try { await HSC.api("POST", "/api/record/start", { kind: currentType() }); } catch (err) { HSC.toast(err.message, "error"); return; }
    recording = true;
    capture = null;
    $("capture-info").classList.add("hidden");
    setStatus("Enregistrement en cours…", "bg-error animate-pulse");
    $("btn-start").disabled = true;
    $("btn-stop").disabled = false;
    updateSave();
  });
  $("btn-stop").addEventListener("click", async () => {
    let result;
    try { result = await HSC.api("POST", "/api/record/stop"); } catch (err) { result = { error: err.message }; }
    recording = false;
    $("btn-start").disabled = false;
    $("btn-stop").disabled = true;
    if (result.error) {
      capture = null;
      setStatus(result.error, "bg-error");
    } else {
      capture = result;
      setStatus("Geste capturé, prêt à enregistrer.", "bg-success");
      const fps = result.fps ? `${String(result.fps).replace(".", ",")} images/s` : "cadence inconnue";
      const hands = result.hands ? ` · ${result.hands} main(s)` : "";
      $("capture-text").textContent = `${result.frames} images · ${HSC.fmtMs(result.elapsed_ms)} · ${fps}${hands}`;
      $("capture-info").classList.remove("hidden");
      if (result.hands === 2 || result.hands === 1) set("hands", String(result.hands));
    }
    updateHints();
    updateSave();
  });
  window.addEventListener("pagehide", () => {
    if (recording) {
      fetch("/api/record/cancel", { method: "POST", keepalive: true, headers: { "Content-Type": "application/json", "X-PhysicalShortCut": "1" } });
    }
  });

  // --- mesures en direct ---
  const canvas = $("draw-canvas");
  const ctx = canvas.getContext("2d");
  function drawTrail(trail) {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.strokeStyle = "#a78bfa";
    ctx.lineWidth = 4;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.beginPath();
    trail.forEach(([x, y], i) => {
      const px = (1 - x) * canvas.width; // l'image caméra est en miroir
      const py = y * canvas.height;
      if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
    });
    ctx.stroke();
  }

  function handsHtml(hands) {
    if (!hands.length) return `<span class="text-on-surface-variant">Aucune main visible.</span>`;
    return hands.map((h, i) => `<div class="flex items-center gap-3"><span class="text-xs font-mono text-on-surface-variant w-14">Main ${i + 1}</span>
      <div class="flex gap-1">${h.fingers.map((v, k) => `<span title="${FINGERS[k]}" class="w-7 h-7 rounded-md flex items-center justify-center text-[11px] font-mono ${v ? "bg-success/20 text-success" : "bg-white/5 text-on-surface-variant"}">${FINGERS[k][0]}</span>`).join("")}</div>
      <span class="font-mono text-sm">${h.count}</span></div>`).join("") +
      (hands.length > 1 ? `<div class="text-xs font-mono text-on-surface-variant">Total : ${hands.reduce((s, h) => s + h.count, 0)}</div>` : "");
  }

  async function pollLive() {
    try {
      const data = await HSC.api("GET", "/api/live");
      liveFps = data.engine.camera === "ok" ? data.engine.fps || 0 : 0;
      $("hands-readout").innerHTML = handsHtml(data.hands || []);
      const draw = data.draw || {};
      if (!$("draw-panel").classList.contains("hidden")) {
        drawTrail(draw.trail || []);
        $("draw-pen").textContent = (draw.trail || []).length ? `trait en cours (${draw.trail.length} points)` : "stylo levé";
        $("draw-last").textContent = draw.last ? `dernier : ${draw.last.label || "non reconnu"}${draw.last.confidence ? ` ${Math.round(draw.last.confidence * 100)} %` : ""}` : "—";
      }
      if ((draw.trail || []).length) { lastTrail = draw.trail; lastTrailLength = draw.trail.length; }
      else if (lastTrailLength) { lastTrailLength = 0; finishLearning(); }
      const score = editing ? data.scores[gestureId] : null;
      const visible = editing && !recording && !capture && Boolean(score) && isRecorded();
      $("live-panel").classList.toggle("hidden", !visible);
      if (visible) {
        const limit = Math.max(score.threshold * 2, 0.001);
        const meter = $("live-meter");
        meter.firstElementChild.style.width = `${Math.min(100, (score.distance / limit) * 100)}%`;
        meter.firstElementChild.classList.toggle("over", score.distance > score.threshold);
        meter.lastElementChild.style.left = `${(score.threshold / limit) * 100}%`;
        $("live-distance").textContent = `distance ${score.distance.toFixed(3)} / seuil ${score.threshold}`;
        $("live-held").textContent = score.hold_ms !== undefined ? `tenue ${score.held_ms} / ${score.hold_ms} ms` : "mouvement en cours d'analyse";
      }
    } catch { /* serveur arrêté : on réessaie */ }
  }
  setInterval(pollLive, 350);

  // --- enregistrement du geste ---
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const type = currentType();
    if (needsCapture() && !capture) { HSC.toast("Enregistre d'abord un geste valide.", "error"); return; }
    const payload = {
      name: $("name").value.trim(),
      type,
      cooldown_seconds: num("cooldown_seconds"),
      action_id: $("action_id").value || null,
      conditions: conditions.map((c) => ({ ...c })),
      conditions_mode: $("conditions_mode").value,
    };
    if (isRecorded()) payload.threshold = num("threshold");
    if (["static", "pose", "count", "sound", "sensor"].includes(type)) payload.hold_ms = Math.round(num("hold_ms"));
    const hands = $("hands").value;
    if (type === "static") payload.hands = Number(hands) || 1;
    if (type === "pose") {
      payload.hands = Number(hands) || 1;
      payload.fingers = fingers[0];
      if (payload.hands === 2) payload.fingers_second = fingers[1];
    }
    if (type === "count") {
      payload.hands = hands === "any" ? "any" : Number(hands) || 1;
      payload.min_value = Math.round(num("min_value"));
      payload.max_value = Math.round(num("max_value"));
    }
    if (type === "draw") {
      Object.assign(payload, {
        charset: $("charset").value, recognizer: $("recognizer").value, pen: $("pen").value,
        idle_ms: Math.round(num("idle_ms")), min_confidence: num("min_confidence"), labels: [...chosenLabels],
      });
    }
    if (type === "sound") Object.assign(payload, { sound: $("sound").value, sensitivity: num("sensitivity"), level_db: num("level_db") });
    if (type === "voice") Object.assign(payload, { phrases: $("phrases").value.split("\n").map((x) => x.trim()).filter(Boolean), match: $("match").value });
    if (type === "fingerprint") Object.assign(payload, { result: $("result").value, finger: $("finger").value.trim() });
    if (type === "device") Object.assign(payload, { event: $("event").value, match: $("device_match").value.trim() });
    if (type === "sensor") {
      const m = metricOf($("metric").value);
      Object.assign(payload, { metric: m.key, op: m.kind === "bool" ? "==" : $("op").value, edge: $("edge").value,
        value: m.kind === "bool" ? $("sensor_bool").value === "true" : num("sensor_value") });
      if (m.arg_label) payload.arg = $("metric_arg").value.trim();
    }
    if (capture) {
      if (capture.type === "static") payload.template = capture.template;
      else { payload.keyframes = capture.keyframes; payload.duration = capture.duration; }
    }
    try {
      if (editing) await HSC.api("PATCH", `/api/gestures/${encodeURIComponent(gestureId)}`, payload);
      else await HSC.api("POST", "/api/gestures", payload);
      HSC.toast("Geste enregistré.", "success");
      setTimeout(() => { window.location.href = "/"; }, 400);
    } catch (err) {
      HSC.toast(err.message, "error");
    }
  });
})();
