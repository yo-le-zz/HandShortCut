"""Reglages de l'application (``settings.json`` dans le dossier de donnees)."""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DEFAULTS: dict[str, Any] = {
    "notify_desktop": True,  # notification systeme quand un geste est reconnu
    "notify_in_app": True,  # notifications dans l'interface web
    "notify_errors": True,  # signaler les etapes en erreur
    "ai_base_url": "",  # API compatible OpenAI (Ollama : http://127.0.0.1:11434/v1)
    "ai_model": "",
    "ai_key_env": "",  # NOM de la variable d'environnement qui contient la cle (jamais la cle)
    "mic_enabled": False,  # le micro ne s'ouvre JAMAIS sans cet accord explicite
    "mic_device": "",  # nom ou numero du peripherique (vide = celui par defaut)
    "voice_model_path": "",  # dossier d'un modele Vosk (vide = <donnees>/models)
}
BOOL_KEYS = {"notify_desktop", "notify_in_app", "notify_errors", "mic_enabled"}
TEXT_KEYS = {"ai_base_url", "ai_model", "ai_key_env", "mic_device", "voice_model_path"}


class Settings:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else None
        self._lock = threading.Lock()
        self._values: dict[str, Any] = dict(DEFAULTS)
        if self.path and self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self._values.update({k: v for k, v in loaded.items() if k in DEFAULTS})
            except (OSError, ValueError):
                log.warning("settings.json illisible : valeurs par defaut")

    def get(self, key: str) -> Any:
        with self._lock:
            return self._values.get(key, DEFAULTS.get(key))

    def all(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._values)

    def update(self, patch: dict[str, Any]) -> dict[str, Any]:
        clean: dict[str, Any] = {}
        for key, value in patch.items():
            if key in BOOL_KEYS:
                clean[key] = bool(value)
            elif key in TEXT_KEYS:
                clean[key] = str(value or "").strip()[:300]
        with self._lock:
            self._values.update(clean)
            snapshot = dict(self._values)
        self._save(snapshot)
        return snapshot

    def _save(self, values: dict[str, Any]) -> None:
        if not self.path:
            return
        tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(values, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError as exc:
            log.error("Ecriture de settings.json impossible : %s", exc)


_current: Settings = Settings()


def current() -> Settings:
    return _current


def set_current(settings: Settings) -> None:
    global _current
    _current = settings
