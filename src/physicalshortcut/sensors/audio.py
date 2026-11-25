"""Son : niveau sonore, detection de claquements de mains et flux micro (sounddevice, optionnel).

* ``ClapDetector`` et ``LevelMeter`` sont du calcul pur (numpy) : testables sans micro.
* ``AudioMonitor`` ouvre le micro **uniquement** quand un declencheur sonore ou vocal existe.
  Rien n'est enregistre sur le disque ni envoye : les blocs audio sont traites en memoire puis jetes.
"""

from __future__ import annotations

import contextlib
import logging
import math
import queue
import threading
from collections.abc import Callable
from typing import Any

import numpy as np

log = logging.getLogger("physicalshortcut.sensors.audio")

SAMPLE_RATE = 16000
BLOCK = 256  # echantillons par bloc d'analyse (16 ms a 16 kHz)


def to_db(value: float) -> float:
    return 20.0 * math.log10(max(float(value), 1e-9))


class LevelMeter:
    """Niveau sonore lisse en dBFS (0 = pleine echelle, ~ -60 = piece calme)."""

    def __init__(self, smoothing: float = 0.5) -> None:
        self.smoothing = smoothing
        self._level = -90.0
        self._lock = threading.Lock()

    def feed(self, samples: np.ndarray) -> float:
        if samples.size == 0:
            return self._level
        rms = float(np.sqrt(np.mean(np.square(samples.astype(np.float32)))))
        db = to_db(rms)
        with self._lock:
            self._level = self.smoothing * self._level + (1 - self.smoothing) * db if self._level > -89 else db
            return self._level

    @property
    def level_db(self) -> float:
        with self._lock:
            return self._level


class ClapDetector:
    """Detecte des claquements (bruit bref et sec) et les regroupe : 1, 2, 3... claquements.

    Un claquement = pic net au-dessus du bruit de fond, qui retombe en moins de ~120 ms
    (une musique ou une voix forte ne retombe pas : elle est ignoree). Les claquements separes de
    moins de ``gap`` secondes forment un groupe, annonce apres ce delai.
    """

    def __init__(self, sensitivity: float = 0.5, sample_rate: int = SAMPLE_RATE, gap: float = 0.6) -> None:
        self.sample_rate = sample_rate
        self.gap = gap
        self.set_sensitivity(sensitivity)
        self._samples = 0  # horloge : nombre d'echantillons recus (deterministe, testable)
        self._background = 0.005
        self._pending: tuple[float, float, float] | None = None  # (t0, rms du pic, max apres 60 ms)
        self._last_refractory = -1.0
        self._claps: list[float] = []

    def set_sensitivity(self, sensitivity: float) -> None:
        s = min(max(float(sensitivity), 0.0), 1.0)
        self.peak_threshold = 0.5 - 0.42 * s  # 0.5 (peu sensible) -> 0.08 (tres sensible), pleine echelle = 1

    @property
    def now(self) -> float:
        return self._samples / self.sample_rate

    def feed(self, samples: np.ndarray) -> list[int]:
        """Renvoie la liste des groupes de claquements termines (ex : ``[2]`` = double claquement)."""
        out: list[int] = []
        data = samples.astype(np.float32)
        for start in range(0, len(data), BLOCK):
            block = data[start : start + BLOCK]
            if not len(block):
                continue
            self._samples += len(block)
            t = self.now
            peak = float(np.max(np.abs(block)))
            rms = float(np.sqrt(np.mean(np.square(block))))
            if self._pending is None:
                is_onset = (
                    peak >= self.peak_threshold
                    and rms >= self._background * 4
                    and t - self._last_refractory > 0.08
                )
                if is_onset:
                    self._pending = (t, rms, 0.0)
                else:
                    self._background = 0.98 * self._background + 0.02 * max(rms, 0.0005)
            else:
                t0, rms0, tail = self._pending
                if t - t0 >= 0.06:
                    tail = max(tail, rms)
                    self._pending = (t0, rms0, tail)
                if t - t0 >= 0.13:
                    if tail < 0.5 * rms0:
                        self._claps.append(t0)
                    self._last_refractory = t
                    self._pending = None
            if self._claps and self._pending is None and t - self._claps[-1] >= self.gap:
                out.append(len(self._claps))
                self._claps = []
        return out


class AudioUnavailable(RuntimeError):
    """Micro ou bibliotheque audio indisponible (message affichable)."""


def availability() -> tuple[bool, str]:
    """(disponible, explication) sans ouvrir le micro."""
    try:
        import sounddevice as sd
    except ImportError:
        return False, "Module `sounddevice` absent : pip install \"physicalshortcut[audio]\"."
    except OSError:
        return False, "Bibliotheque PortAudio absente (Linux : sudo dnf install portaudio / sudo apt install libportaudio2)."
    try:
        devices = [d for d in sd.query_devices() if d.get("max_input_channels", 0) > 0]
    except Exception as exc:  # noqa: BLE001 - PortAudio remonte des erreurs variees
        return False, f"Impossible de lister les micros : {exc}"
    if not devices:
        return False, "Aucun micro detecte."
    return True, f"{len(devices)} entree(s) audio detectee(s) (micro par defaut : {devices[0]['name']})."


class AudioMonitor:
    """Flux micro partage : distribue les blocs a plusieurs consommateurs (niveau, claquements, voix)."""

    def __init__(self, device: str | int | None = None, sample_rate: int = SAMPLE_RATE) -> None:
        self.device = device or None
        self.sample_rate = sample_rate
        self.meter = LevelMeter()
        self._sinks: list[Callable[[np.ndarray], None]] = []
        self._queue: queue.Queue = queue.Queue(maxsize=200)
        self._stream: Any = None
        self._worker: threading.Thread | None = None
        self._stop = threading.Event()
        self.error: str | None = None

    @property
    def running(self) -> bool:
        return self._stream is not None

    def add_sink(self, sink: Callable[[np.ndarray], None]) -> None:
        if sink not in self._sinks:
            self._sinks.append(sink)

    def remove_sink(self, sink: Callable[[np.ndarray], None]) -> None:
        if sink in self._sinks:
            self._sinks.remove(sink)

    def start(self) -> None:
        if self._stream is not None:
            return
        ok, why = availability()
        if not ok:
            self.error = why
            raise AudioUnavailable(why)
        import sounddevice as sd

        def callback(indata, frames, time_info, status):  # noqa: ARG001 - signature imposee
            with contextlib.suppress(queue.Full):  # on prefere perdre un bloc que bloquer le thread audio
                self._queue.put_nowait(indata[:, 0].copy())

        try:
            self._stream = sd.InputStream(
                samplerate=self.sample_rate, channels=1, dtype="float32", blocksize=1600, device=self.device, callback=callback
            )
            self._stream.start()
        except Exception as exc:  # noqa: BLE001
            self._stream = None
            self.error = f"Micro inaccessible : {exc}"
            raise AudioUnavailable(self.error) from exc
        self.error = None
        self._stop.clear()
        self._worker = threading.Thread(target=self._pump, name="audio-pump", daemon=True)
        self._worker.start()
        log.info("Micro ouvert (%d Hz)", self.sample_rate)

    def stop(self) -> None:
        self._stop.set()
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:  # noqa: BLE001
                log.debug("Fermeture du micro", exc_info=True)
            self._stream = None
            log.info("Micro ferme")
        if self._worker:
            self._worker.join(timeout=2)
            self._worker = None

    def _pump(self) -> None:
        while not self._stop.is_set():
            try:
                block = self._queue.get(timeout=0.3)
            except queue.Empty:
                continue
            self.meter.feed(block)
            for sink in list(self._sinks):
                try:
                    sink(block)
                except Exception:  # noqa: BLE001
                    log.exception("Erreur dans un consommateur audio")
