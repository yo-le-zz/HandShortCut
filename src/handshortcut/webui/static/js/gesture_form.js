// gesture_form.js — création et édition d'un geste (réglages + enregistrement caméra).
"use strict";

(() => {
  const DEFAULTS = {
    static: { threshold: 0.16, hold_ms: 270, hint: "Pose statique : maintiens la position immobile pendant l'enregistrement." },
    sequence: { threshold: 0.22, hint: "Mouvement : effectue le geste complet, du début à la fin, pendant l'enregistrement." },
  };
  const $ = (id) => document.getElementById(id);
  const form = $("gesture-form");
  const gestureId = form.dataset.gestureId || null;
  const editing = Boolean(gestureId);
  const originalType = form.dataset.type;
  const legacyFps = Number(form.dataset.legacyFps) || 30;
  const initial = editing ? JSON.parse($("gesture-data").textContent) : null;

  let capture = null; // dernier enregistrement valide
  let recording = false;
  let liveFps = 0;
  let cameraOk = false;

  const currentType = () => document.querySelector('input[name="type"]:checked').value;
  const num = (id) => parseFloat($(id).value);

  function setStatus(text, dotClass) {
    $("rec-status").textContent = text;
    $("rec-dot").className = `w-1.5 h-1.5 rounded-full ${dotClass}`;
  }

  function updateHints() {
    const ms = num("hold_ms");
    if (Number.isFinite(ms)) {
      const fps = liveFps || legacyFps;
      const frames = Math.max(1, Math.round((ms * fps) / 1000));
      $("hold-hint").textContent = `${HSC.fmtMs(ms)} ≈ ${frames} image(s) à ${String(Math.round(fps * 10) / 10).replace(".", ",")} images/s`;
    }
    const cooldown = num("cooldown_seconds");
    $("cooldown-hint").textContent = Number.isFinite(cooldown) ? HSC.fmtSeconds(cooldown) : "";

    // mouvement : durée et cadence des images-clés (de l'enregistrement, sinon du geste enregistré)
    const duration = capture && capture.type === "sequence" ? capture.duration : Number(form.dataset.duration) || null;
    const keyframes = capture && capture.type === "sequence" ? capture.keyframes.length : Number(form.dataset.keyframes) || 10;
    if (currentType() === "sequence" && duration) {
      $("sequence-duration").textContent = `Mouvement enregistré : ${HSC.fmtSeconds(duration)}`;
      $("sequence-frames").textContent =
        `${keyframes} images-clés comparées, une toutes les ${Math.round((duration * 1000) / Math.max(1, keyframes - 1))} ms.`;
    } else {
      $("sequence-duration").textContent = "Enregistre le mouvement pour en connaître la durée.";
      $("sequence-frames").textContent = "";
    }
  }

  function needsCapture() {
    return !editing || currentType() !== originalType;
  }

  function updateSave() {
    const blocked = recording || (needsCapture() && !capture);
    $("btn-save").disabled = blocked;
  }

  function applyType(resetValues) {
    const type = currentType();
    $("type-hint").textContent = DEFAULTS[type].hint;
    $("hold-field").classList.toggle("hidden", type !== "static");
    $("sequence-info").classList.toggle("hidden", type !== "sequence");
    if (resetValues) {
      $("threshold").value = DEFAULTS[type].threshold;
      $("threshold-range").value = DEFAULTS[type].threshold;
      if (type === "static") { $("hold_ms").value = DEFAULTS.static.hold_ms; $("hold-range").value = DEFAULTS.static.hold_ms; }
    }
    if (capture && capture.type !== type) { capture = null; $("capture-info").classList.add("hidden"); }
    updateHints();
    updateSave();
  }

  // --- valeurs initiales ---
  const set = (id, value) => { $(id).value = value; };
  set("threshold", initial?.threshold ?? DEFAULTS[currentType()].threshold);
  set("threshold-range", $("threshold").value);
  set("hold_ms", initial?.hold_ms ?? DEFAULTS.static.hold_ms);
  set("hold-range", $("hold_ms").value);
  set("cooldown_seconds", initial?.cooldown_seconds ?? 10);
  applyType(false);

  // curseurs <-> champs numériques
  [["threshold-range", "threshold"], ["hold-range", "hold_ms"]].forEach(([range, field]) => {
    $(range).addEventListener("input", () => { $(field).value = $(range).value; updateHints(); });
    $(field).addEventListener("input", () => { $(range).value = $(field).value; updateHints(); });
  });
  $("cooldown_seconds").addEventListener("input", updateHints);
  document.querySelectorAll('input[name="type"]').forEach((r) => r.addEventListener("change", () => applyType(true)));

  // --- état de la caméra ---
  let cameraWasOk = false;
  document.addEventListener("camera-status", (event) => {
    cameraOk = event.detail.camera === "ok";
    liveFps = cameraOk ? event.detail.fps || 0 : 0;
    if (cameraOk && !cameraWasOk) $("video").src = `/video_feed?t=${Date.now()}`; // (re)connecte le flux
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
    try {
      await HSC.api("POST", "/api/record/start", { kind: currentType() });
    } catch (err) {
      HSC.toast(err.message, "error");
      return;
    }
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
    try {
      result = await HSC.api("POST", "/api/record/stop");
    } catch (err) {
      result = { error: err.message };
    }
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
      $("capture-text").textContent =
        `${result.frames} images · ${HSC.fmtMs(result.elapsed_ms)} · ${fps}`;
      $("capture-info").classList.remove("hidden");
    }
    updateHints();
    updateSave();
  });

  // Quitter la page pendant un enregistrement le laisserait actif (détection suspendue).
  window.addEventListener("pagehide", () => {
    if (recording) {
      fetch("/api/record/cancel", {
        method: "POST", keepalive: true,
        headers: { "Content-Type": "application/json", "X-HandShortCut": "1" },
      });
    }
  });

  // --- mesures en direct (édition) ---
  async function pollLive() {
    try {
      const data = await HSC.api("GET", "/api/live");
      liveFps = data.engine.camera === "ok" ? data.engine.fps || 0 : 0;
      const score = editing ? data.scores[gestureId] : null;
      const panel = $("live-panel");
      const visible = editing && !recording && !capture && Boolean(score);
      panel.classList.toggle("hidden", !visible);
      if (visible) {
        const limit = Math.max(score.threshold * 2, 0.001);
        const meter = $("live-meter");
        meter.firstElementChild.style.width = `${Math.min(100, (score.distance / limit) * 100)}%`;
        meter.firstElementChild.classList.toggle("over", score.distance > score.threshold);
        meter.lastElementChild.style.left = `${(score.threshold / limit) * 100}%`;
        $("live-distance").textContent = `distance ${score.distance.toFixed(3)} / seuil ${score.threshold}`;
        $("live-held").textContent = score.hold_ms !== undefined
          ? `tenue ${score.held_ms} / ${score.hold_ms} ms`
          : "mouvement en cours d'analyse";
      }
    } catch { /* serveur arrêté : on réessaie */ }
  }
  if (editing) setInterval(pollLive, 400);

  // --- enregistrement du geste ---
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const type = currentType();
    if (needsCapture() && !capture) {
      HSC.toast("Enregistre d'abord un geste valide.", "error");
      return;
    }
    const payload = {
      name: $("name").value.trim(),
      threshold: num("threshold"),
      cooldown_seconds: num("cooldown_seconds"),
      action_id: $("action_id").value || null,
    };
    if (type === "static") payload.hold_ms = Math.round(num("hold_ms"));
    if (capture) {
      payload.type = capture.type;
      if (capture.type === "static") payload.template = capture.template;
      else { payload.keyframes = capture.keyframes; payload.duration = capture.duration; }
    }
    try {
      if (editing) await HSC.api("PATCH", `/api/gestures/${encodeURIComponent(gestureId)}`, payload);
      else await HSC.api("POST", "/api/gestures", { ...payload, type });
      HSC.toast("Geste enregistré.", "success");
      setTimeout(() => { window.location.href = "/"; }, 400);
    } catch (err) {
      HSC.toast(err.message, "error");
    }
  });
})();
