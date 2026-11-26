"""Capteurs externes : Arduino / ESP32 / micro:bit (port serie) ou n'importe quel script.

Aucun PC ne possede de capteur de gaz, d'humidite ou de mouvement (PIR) : on les branche. Deux ponts :

* **serie** : la carte envoie une ligne par mesure : ``gaz=412``, ``gaz:412``, ``{"gaz": 412}`` ou un nombre seul ;
* **commande** : un programme lance periodiquement, qui affiche un nombre (``python lire_capteur.py``).

La valeur se retrouve ensuite comme mesure ``external`` (argument = nom du capteur) : conditions,
declencheurs « Capteur » et variable ``{{ system.external }}`` des workflows.
"""

from __future__ import annotations

import json
import logging
import re
import shlex
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("physicalshortcut.sensors.external")

NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,31}$")
NUMBER_RE = re.compile(r"-?\d+(?:[.,]\d+)?")
MAX_SENSORS = 20


def parse_line(line: str, default_name: str = "") -> list[tuple[str, float]]:
    """``gaz=412`` / ``gaz:412`` / ``{"gaz": 412, "temp": 21.5}`` / ``412`` -> [(nom, valeur)]."""
    line = line.strip()
    if not line:
        return []
    if line.startswith("{"):
        try:
            data = json.loads(line)
        except ValueError:
            return []
        return [(k, float(v)) for k, v in data.items() if NAME_RE.match(str(k)) and isinstance(v, (int, float)) and not isinstance(v, bool)]
    pairs = re.findall(r"([A-Za-z][A-Za-z0-9_]*)\s*[=:]\s*(-?\d+(?:[.,]\d+)?)", line)
    if pairs:
        return [(name, float(value.replace(",", "."))) for name, value in pairs]
    match = NUMBER_RE.fullmatch(line)
    if match and default_name:
        return [(default_name, float(line.replace(",", ".")))]
    return []


def validate_sensors(data: Any) -> list[dict]:
    """Valide la liste de capteurs externes (venant de l'interface)."""
    if not isinstance(data, list) or len(data) > MAX_SENSORS:
        raise ValueError(f"Capteurs : liste de {MAX_SENSORS} maximum attendue.")
    clean, seen = [], set()
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("Capteur : objet attendu.")
        name = str(item.get("name", "")).strip()
        if not NAME_RE.match(name) or name in seen:
            raise ValueError("Capteur : nom unique de 1 a 32 caracteres (lettres, chiffres, _), commencant par une lettre.")
        seen.add(name)
        kind = item.get("kind")
        if kind not in ("serial", "command"):
            raise ValueError("Capteur : type serial ou command.")
        entry: dict[str, Any] = {"name": name, "kind": kind, "unit": str(item.get("unit", ""))[:10]}
        if kind == "serial":
            port = str(item.get("port", "")).strip()
            if not port or len(port) > 200:
                raise ValueError("Capteur serie : port requis (ex : /dev/ttyACM0 ou COM3).")
            baud = int(item.get("baud", 9600))
            if not 300 <= baud <= 2_000_000:
                raise ValueError("Capteur serie : vitesse invalide.")
            entry.update(port=port, baud=baud)
        else:
            command = str(item.get("command", "")).strip()
            if not command or len(command) > 500:
                raise ValueError("Capteur commande : commande requise.")
            interval = float(item.get("interval_s", 5))
            if not 0.5 <= interval <= 3600:
                raise ValueError("Capteur commande : intervalle de 0,5 s a 1 h.")
            entry.update(command=command, interval_s=interval)
        clean.append(entry)
    return clean


class ExternalSensors:
    """Lit les capteurs declares dans ``sensors.json`` et garde la derniere valeur de chacun."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else None
        self._values: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._errors: dict[str, str] = {}
        self.config: list[dict] = []
        self.load()

    # ---- configuration
    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8")) if self.path and self.path.exists() else []
            self.config = validate_sensors(raw)
        except (OSError, ValueError):
            self.config = []

    def save(self, config: list[dict]) -> list[dict]:
        self.config = validate_sensors(config)
        if self.path:
            self.path.write_text(json.dumps(self.config, indent=2, ensure_ascii=False), encoding="utf-8")
        return self.config

    # ---- valeurs
    def set_value(self, name: str, value: float) -> None:
        with self._lock:
            self._values[name] = (float(value), time.time())

    def get(self, name: str, max_age: float = 120.0) -> float | None:
        with self._lock:
            item = self._values.get(name)
        if item is None or time.time() - item[1] > max_age:
            return None
        return item[0]

    def snapshot(self) -> dict[str, dict]:
        with self._lock:
            values = dict(self._values)
        return {
            c["name"]: {"value": values.get(c["name"], (None, 0))[0], "age": (time.time() - values[c["name"]][1]) if c["name"] in values else None,
                        "error": self._errors.get(c["name"]), "kind": c["kind"], "unit": c.get("unit", "")}
            for c in self.config
        }

    # ---- lecture
    def start(self) -> None:
        self.stop()
        self._stop.clear()
        for sensor in self.config:
            target = self._serial_loop if sensor["kind"] == "serial" else self._command_loop
            thread = threading.Thread(target=target, args=(sensor,), name=f"sensor-{sensor['name']}", daemon=True)
            thread.start()
            self._threads.append(thread)

    def stop(self) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=2)
        self._threads = []

    def _serial_loop(self, sensor: dict) -> None:
        name = sensor["name"]
        try:
            import serial
        except ImportError:
            self._errors[name] = "Module pyserial absent : pip install \"physicalshortcut[serial]\"."
            return
        while not self._stop.is_set():
            try:
                with serial.Serial(sensor["port"], sensor["baud"], timeout=1) as port:
                    self._errors.pop(name, None)
                    while not self._stop.is_set():
                        raw = port.readline().decode("utf-8", "replace")
                        for key, value in parse_line(raw, name):
                            self.set_value(key, value)
            except Exception as exc:  # noqa: BLE001 - port absent, debranche...
                self._errors[name] = f"Port {sensor['port']} : {exc}"
                self._stop.wait(3)

    def _command_loop(self, sensor: dict) -> None:
        name = sensor["name"]
        while not self._stop.is_set():
            try:
                done = subprocess.run(  # noqa: S603 - commande ecrite par l'utilisateur, comme l'etape run_shell
                    shlex.split(sensor["command"], posix=(not _is_windows())), capture_output=True, text=True, timeout=30, check=False
                )
                lines = (done.stdout or "").strip().splitlines()
                parsed = parse_line(lines[-1], name) if lines else []
                if parsed:
                    self._errors.pop(name, None)
                    for key, value in parsed:
                        self.set_value(key, value)
                else:
                    self._errors[name] = (done.stderr or "La commande n'a affiche aucun nombre.").strip()[:200]
            except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
                self._errors[name] = str(exc)[:200]
            self._stop.wait(float(sensor.get("interval_s", 5)))


def _is_windows() -> bool:
    import sys

    return sys.platform == "win32"
