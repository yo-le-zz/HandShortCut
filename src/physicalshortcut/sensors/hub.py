"""Chef d'orchestre des capteurs.

Le hub lit les gestes enregistres et n'active que ce qui est necessaire : le micro n'est ouvert que
si un declencheur Son ou Voix existe, le lecteur d'empreintes que si un declencheur Empreinte existe,
etc. Quand un declencheur se produit, il appelle ``fire(geste, contexte)`` (le moteur applique les
conditions, la temporisation et lance l'action liee).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .. import system_metrics
from . import audio, devices, fingerprint, hardware, voice, voice_text
from .external import ExternalSensors

log = logging.getLogger("physicalshortcut.sensors.hub")

SENSOR_TYPES = ("sound", "voice", "fingerprint", "device", "sensor")
POLL_INTERVAL = 0.25
CLAP_SOUNDS = {"clap": 1, "double_clap": 2, "triple_clap": 3}


def clap_matches(sound: str, groups: list[int]) -> bool:
    """Un groupe de ``n`` claquements correspond-il au declencheur ``sound`` ?"""
    if sound == "any_clap":
        return bool(groups)
    count = CLAP_SOUNDS.get(sound)
    return count is not None and count in groups


class SensorHub:
    def __init__(
        self,
        store,
        fire: Callable[[dict, dict], bool],
        data_dir: Path,
        settings_get: Callable[[str], Any] | None = None,
        external: ExternalSensors | None = None,
    ) -> None:
        self.store = store
        self.fire = fire
        self.data_dir = Path(data_dir)
        self.settings_get = settings_get or (lambda _k: "")
        self.external = external or ExternalSensors(self.data_dir / "sensors.json")
        self.audio: audio.AudioMonitor | None = None
        self.claps: audio.ClapDetector | None = None
        self.voice: voice.VoiceRecognizer | None = None
        self.watcher = devices.DeviceWatcher(self._on_device)
        self.finger: fingerprint.FingerprintListener | None = None
        self.errors: dict[str, str] = {}
        self._wanted: dict[str, bool] = {}
        self._level_since: dict[str, float | None] = {}
        self._prev_value: dict[str, bool] = {}
        self._last_fired: dict[str, float] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        system_metrics.set_provider("sound_level_db", self._level_provider)
        system_metrics.set_provider("external", lambda name: self.external.get(name) if name else None)

    # ------------------------------------------------------------ cycle de vie
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self.external.start()
        self.watcher.start()
        self._thread = threading.Thread(target=self._loop, name="sensor-hub", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        self._shutdown_components()
        self.watcher.stop()
        self.external.stop()

    def _shutdown_components(self) -> None:
        if self.audio:
            self.audio.stop()
            self.audio = None
        self.claps = None
        self.voice = None
        if self.finger:
            self.finger.stop()
            self.finger = None

    # ----------------------------------------------------------------- besoins
    def gestures_of(self, kind: str) -> list[dict]:
        return [g for g in self.store.get_gestures() if g.get("type") == kind and g.get("id")]

    def needs(self) -> dict[str, Any]:
        sound, voice_g = self.gestures_of("sound"), self.gestures_of("voice")
        events = {g.get("event") for g in self.gestures_of("device") if g.get("event")}
        mic_needed = bool(voice_g) or bool(sound) or any(
            g.get("metric") == "sound_level_db" for g in self.gestures_of("sensor")
        )
        return {
            "mic": mic_needed and bool(self.settings_get("mic_enabled")),
            "mic_blocked": mic_needed and not self.settings_get("mic_enabled"),
            "claps": any(g.get("sound") in (*CLAP_SOUNDS, "any_clap") for g in sound),
            "voice": bool(voice_g),
            "fingerprint": bool(self.gestures_of("fingerprint")),
            "families": devices.families_for(events),
        }

    def sync(self) -> None:
        """Aligne les composants actifs sur les declencheurs presents."""
        need = self.needs()
        with self._lock:
            self.errors.pop("micro", None)
            if need["mic_blocked"]:
                self.errors["micro"] = "Un déclencheur Son/Voix existe mais le micro est désactivé (Activité & réglages)."
            if need["mic"]:
                self._ensure_audio(need)
            elif self.audio:
                self._shutdown_audio()
            self.watcher.set_families(need["families"])
            self._ensure_fingerprint(need["fingerprint"])

    def _ensure_audio(self, need: dict) -> None:
        device = str(self.settings_get("mic_device") or "") or None
        if self.audio and self.audio.device != (device or None):
            self._shutdown_audio()
        if self.audio is None:
            self.audio = audio.AudioMonitor(device=int(device) if device and device.isdigit() else device)
            try:
                self.audio.start()
            except audio.AudioUnavailable as exc:
                self.errors["micro"] = str(exc)
                self.audio = None
                return
        if need["claps"] and self.claps is None:
            self.claps = audio.ClapDetector(sensitivity=self._clap_sensitivity())
            self.audio.add_sink(self._on_clap_block)
        elif not need["claps"] and self.claps is not None:
            self.audio.remove_sink(self._on_clap_block)
            self.claps = None
        if need["voice"] and self.voice is None:
            ok, why = voice.availability(str(self.settings_get("voice_model_path") or ""), self.data_dir)
            if not ok:
                self.errors["voix"] = why
            else:
                try:
                    model = voice.find_model(str(self.settings_get("voice_model_path") or ""), self.data_dir)
                    self.voice = voice.VoiceRecognizer(model)  # type: ignore[arg-type]
                    self.audio.add_sink(self._on_voice_block)
                    self.errors.pop("voix", None)
                except Exception as exc:  # noqa: BLE001
                    self.errors["voix"] = f"Modèle vocal inutilisable : {exc}"
        elif not need["voice"] and self.voice is not None:
            self.audio.remove_sink(self._on_voice_block)
            self.voice = None

    def _shutdown_audio(self) -> None:
        if self.audio:
            self.audio.stop()
        self.audio = None
        self.claps = None
        self.voice = None

    def _ensure_fingerprint(self, wanted: bool) -> None:
        if wanted and self.finger is None:
            self.finger = fingerprint.FingerprintListener(self._on_finger)
            self.finger.start()
        elif not wanted and self.finger is not None:
            self.finger.stop()
            self.finger = None
        if self.finger and self.finger.error:
            self.errors["empreinte"] = self.finger.error
        else:
            self.errors.pop("empreinte", None)

    def _clap_sensitivity(self) -> float:
        values = [float(g.get("sensitivity", 0.5)) for g in self.gestures_of("sound") if g.get("sound") in (*CLAP_SOUNDS, "any_clap")]
        return max(values) if values else 0.5

    # ---------------------------------------------------------------- sources
    def _on_clap_block(self, block) -> None:
        claps = self.claps
        if claps is None:
            return
        groups = claps.feed(block)
        for count in groups:
            for g in self.gestures_of("sound"):
                if clap_matches(g.get("sound", ""), [count]):
                    self._trigger(g, {"value": count, "claps": count})

    def _on_voice_block(self, block) -> None:
        recognizer = self.voice
        if recognizer is None:
            return
        text = recognizer.feed(block)
        if text:
            self.handle_speech(text)

    def handle_speech(self, text: str) -> None:
        """Compare une phrase reconnue aux declencheurs vocaux (aussi utilise par les tests et le « Tester »)."""
        for g in self.gestures_of("voice"):
            phrases = g.get("phrases") or []
            hit = voice_text.match_phrase(text, phrases, g.get("match", "contains"))
            if hit is not None:
                number = voice_text.extract_number(text)
                self._trigger(g, {"text": text, "phrase": hit, "value": number})

    def _on_finger(self, result: str, finger: str) -> None:
        for g in self.gestures_of("fingerprint"):
            wanted_result = g.get("result", "match")
            wanted_finger = (g.get("finger") or "").strip().lower()
            if wanted_result != "any" and wanted_result != result:
                continue
            if wanted_finger and wanted_finger not in finger.lower():
                continue
            self._trigger(g, {"finger": finger, "result": result})

    def _on_device(self, event: str, ident: str, name: str) -> None:
        for g in self.gestures_of("device"):
            if g.get("event") != event:
                continue
            needle = (g.get("match") or "").strip().lower()
            if needle and needle not in f"{ident} {name}".lower():
                continue
            self._trigger(g, {"device": name, "device_id": ident, "event": event})

    def _level_provider(self, _arg: str) -> float | None:
        return self.audio.meter.level_db if self.audio and self.audio.running else None

    # -------------------------------------------------------- capteurs a seuil
    def _loop(self) -> None:
        last_sync = 0.0
        while not self._stop.wait(POLL_INTERVAL):
            now = time.monotonic()
            try:
                if now - last_sync > 2.0:
                    last_sync = now
                    self.sync()
                self._poll_thresholds(now)
            except Exception:
                log.exception("Boucle des capteurs")

    def _poll_thresholds(self, now: float) -> None:
        for g in self.gestures_of("sensor") + self.gestures_of("sound"):
            metric, cond = self._threshold_of(g)
            if cond is None:
                continue
            gid = g["id"]
            value = system_metrics.read_metric(metric, g.get("arg", ""))
            ok = False
            if value is not None:
                ok, _ = system_metrics.evaluate({**cond, "metric": metric, "arg": g.get("arg", "")})
            if not ok:
                self._level_since[gid] = None
                self._prev_value[gid] = False
                continue
            since = self._level_since.get(gid) or now
            self._level_since[gid] = since
            held = (now - since) * 1000 >= int(g.get("hold_ms", 0))
            if not held:
                continue
            edge = g.get("edge", "rising") == "rising"
            if edge and self._prev_value.get(gid):
                continue
            self._prev_value[gid] = True
            self._trigger(g, {"value": value, "metric": metric})

    @staticmethod
    def _threshold_of(g: dict) -> tuple[str, dict | None]:
        if g.get("type") == "sensor":
            if not g.get("metric"):
                return "", None
            return g["metric"], {"op": g.get("op", ">"), "value": g.get("value", 0)}
        if g.get("sound") == "loud":
            return "sound_level_db", {"op": ">", "value": g.get("level_db", -20)}
        if g.get("sound") == "silence":
            return "sound_level_db", {"op": "<", "value": g.get("level_db", -50)}
        return "", None

    def _trigger(self, gesture: dict, ctx: dict) -> None:
        gid = gesture["id"]
        self._last_fired[gid] = time.time()
        try:
            self.fire(gesture, ctx)
        except Exception:
            log.exception("Declenchement du capteur %r", gesture.get("name"))

    # ----------------------------------------------------------------- rapport
    def status(self) -> dict:
        need = self.needs()
        return {
            "mic": {"enabled": bool(self.settings_get("mic_enabled")), "open": bool(self.audio and self.audio.running),
                    "level_db": self.audio.meter.level_db if self.audio and self.audio.running else None},
            "voice": {"active": self.voice is not None},
            "fingerprint": {"active": self.finger is not None},
            "families": sorted(need["families"]),
            "errors": dict(self.errors),
            "external": self.external.snapshot(),
        }

    def report(self) -> list[dict]:
        """Faisabilite sur CETTE machine, par capteur (affiche dans l'interface)."""
        mic_ok, mic_why = audio.availability()
        voice_ok, voice_why = voice.availability(str(self.settings_get("voice_model_path") or ""), self.data_dir)
        finger_ok, finger_why = fingerprint.availability()
        items = [
            {"id": "sound", "label": "Son (claquements, bruit fort, silence)", "present": mic_ok,
             "detail": "Micro utilisable." if mic_ok else mic_why},
            {"id": "voice", "label": "Voix (commandes parlées)", "present": mic_ok and voice_ok,
             "detail": voice_why if mic_ok else mic_why},
            {"id": "fingerprint", "label": "Empreinte digitale", "present": finger_ok, "detail": finger_why},
        ]
        items += hardware.inventory()
        items.append({"id": "external", "label": "Capteurs externes (gaz, humidité, mouvement PIR…)",
                      "present": bool(self.external.config),
                      "detail": f"{len(self.external.config)} déclaré(s)." if self.external.config
                      else "Un PC n'en a pas : branche un Arduino/ESP32 (série) ou une commande. Voir Capteurs."})
        return items
