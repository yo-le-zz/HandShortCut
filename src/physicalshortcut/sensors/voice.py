"""Reconnaissance vocale hors ligne avec Vosk (optionnelle).

Le modele (``vosk-model-small-fr-0.22``, ~40 Mo) se telecharge une fois sur
https://alphacephei.com/vosk/models et se depose dans le dossier ``models`` des donnees
(ou le chemin est indique dans Activite & reglages). Aucun son ne quitte l'ordinateur.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np

log = logging.getLogger("physicalshortcut.sensors.voice")


def find_model(configured: str = "", data_dir: Path | None = None) -> Path | None:
    """Dossier du modele Vosk : chemin configure, sinon premier ``vosk-model*`` de ``<donnees>/models``."""
    if configured:
        path = Path(configured).expanduser()
        return path if path.is_dir() else None
    if data_dir is not None:
        base = Path(data_dir) / "models"
        if base.is_dir():
            for child in sorted(base.iterdir()):
                if child.is_dir() and child.name.startswith("vosk-model"):
                    return child
    return None


def availability(configured: str = "", data_dir: Path | None = None) -> tuple[bool, str]:
    try:
        import vosk  # noqa: F401
    except ImportError:
        return False, "Module `vosk` absent : pip install \"physicalshortcut[audio]\"."
    model = find_model(configured, data_dir)
    if model is None:
        return False, "Modele vocal introuvable : telecharge vosk-model-small-fr-0.22 et place-le dans <donnees>/models/."
    return True, f"Modele : {model.name}"


class VoiceRecognizer:
    """Transforme des blocs de son (float32, 16 kHz) en phrases terminees."""

    def __init__(self, model_dir: Path, sample_rate: int = 16000) -> None:
        import vosk

        vosk.SetLogLevel(-1)
        self._rec = vosk.KaldiRecognizer(vosk.Model(str(model_dir)), sample_rate)

    def feed(self, samples: np.ndarray) -> str | None:
        pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()
        if self._rec.AcceptWaveform(pcm):
            text = json.loads(self._rec.Result()).get("text", "").strip()
            return text or None
        return None
