"""Mesures du systeme et conditions (« uptime > 10 min », « CPU < 70 % », « temperature < 50 °C »).

Les conditions servent a :
* **conditionner un geste** : il ne se declenche que si toutes (ou l'une) sont remplies ;
* alimenter les workflows : ``{{ system.cpu_percent }}`` dans un champ ou une expression.

Une mesure indisponible sur le systeme (ex. temperature CPU sous Windows sans droits) vaut
``None`` : la condition echoue, sauf si elle est reglee sur ``on_unknown = "pass"``.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

OPERATORS = (">", ">=", "<", "<=", "==", "!=")
CONDITION_MODES = ("all", "any")
MAX_CONDITIONS = 12


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    unit: str
    kind: str  # "number" | "bool"
    icon: str
    help: str = ""
    arg_label: str = ""  # renseigne : la mesure a besoin d'un argument (nom de processus...)
    ttl: float = 1.0


METRICS: tuple[Metric, ...] = (
    Metric("uptime_minutes", "Système allumé depuis", "min", "number", "power", "Durée depuis le dernier démarrage de l'ordinateur."),
    Metric("cpu_percent", "Utilisation du processeur", "%", "number", "cpu", "Moyenne depuis la mesure précédente.", ttl=2.0),
    Metric("cpu_temp_c", "Température du processeur", "°C", "number", "thermometer", "Linux : capteurs lm-sensors ; Windows : selon la machine.", ttl=5.0),
    Metric("ram_percent", "Mémoire utilisée", "%", "number", "memory-stick", ""),
    Metric("disk_percent", "Disque système utilisé", "%", "number", "hard-drive", "Disque du dossier personnel."),
    Metric("load_1m", "Charge moyenne (1 min)", "", "number", "gauge", "Linux et macOS uniquement."),
    Metric("battery_percent", "Niveau de batterie", "%", "number", "battery", "Absent sur un poste fixe."),
    Metric("on_battery", "Sur batterie (non branché)", "", "bool", "battery-low", "Vrai si l'ordinateur n'est pas branché au secteur."),
    Metric("hour", "Heure de la journée", "h", "number", "clock", "0 à 23."),
    Metric("weekday", "Jour de la semaine", "", "number", "calendar", "1 = lundi ... 7 = dimanche."),
    Metric("process_running", "Un processus tourne", "", "bool", "activity", "", arg_label="Nom du processus"),
    Metric("window_exists", "Une fenêtre est ouverte", "", "bool", "app-window", "", arg_label="Le titre contient"),
    Metric("file_exists", "Un fichier existe", "", "bool", "file", "", arg_label="Chemin"),
    # --- capteurs physiques (absents = valeur inconnue ; voir docs/CAPTEURS.md)
    Metric("idle_minutes", "Inactivité clavier / souris", "min", "number", "timer", "Linux : `xprintidle` (X11) ou systemd-logind.", ttl=5.0),
    Metric("ambient_light_lux", "Lumière ambiante", "lux", "number", "sun", "Capteur de lumière de la machine (tablettes, 2-en-1).", ttl=1.0),
    Metric("accel_motion_g", "Secousse / mouvement", "g", "number", "move", "Accéléromètre : 0 = immobile, > 0,3 = secousse.", ttl=0.2),
    Metric("ambient_temp_c", "Température de la pièce", "°C", "number", "thermometer-sun", "Rare sur PC : capteur IIO ou capteur externe nommé `ambient`.", ttl=5.0),
    Metric("gpu_temp_c", "Température du GPU", "°C", "number", "thermometer", "", ttl=5.0),
    Metric("disk_temp_c", "Température du disque (NVMe)", "°C", "number", "hard-drive", "", ttl=10.0),
    Metric("fan_rpm", "Vitesse du ventilateur", "tr/min", "number", "fan", "", ttl=3.0),
    Metric("lid_closed", "Capot fermé", "", "bool", "laptop", "Portables uniquement.", ttl=1.0),
    Metric("wifi_is", "Connecté au Wi-Fi", "", "bool", "wifi", "", arg_label="Nom du Wi-Fi (SSID)", ttl=5.0),
    Metric("sound_level_db", "Niveau sonore du micro", "dB", "number", "volume-2", "Actif seulement si un déclencheur Son/Voix ouvre le micro.", ttl=0.0),
    Metric("external", "Capteur externe (Arduino…)", "", "number", "cpu", "Valeur d'un capteur déclaré dans Capteurs.", arg_label="Nom du capteur", ttl=0.0),
)
METRIC_BY_KEY: dict[str, Metric] = {m.key: m for m in METRICS}

# ------------------------------------------------------------------ mesures

_cache: dict[tuple[str, str], tuple[float, Any]] = {}
_cache_lock = threading.Lock()
_cpu_primed_at = 0.0


def _psutil():
    import psutil

    return psutil


def _uptime_minutes(_arg: str) -> float | None:
    return max(0.0, (time.time() - _psutil().boot_time()) / 60.0)


def _cpu_percent(_arg: str) -> float | None:
    global _cpu_primed_at
    psutil = _psutil()
    if _cpu_primed_at == 0.0:  # la premiere mesure psutil vaut toujours 0 : on amorce et on attend un peu
        psutil.cpu_percent(interval=None)
        _cpu_primed_at = time.monotonic()
        time.sleep(0.4)
    return float(psutil.cpu_percent(interval=None))


def _cpu_temp(_arg: str) -> float | None:
    psutil = _psutil()
    sensors = getattr(psutil, "sensors_temperatures", None)
    if sensors is not None:
        try:
            data = sensors() or {}
        except (OSError, RuntimeError):
            data = {}
        for name in ("coretemp", "k10temp", "zenpower", "cpu_thermal", "cpu-thermal", "acpitz", "soc_thermal"):
            readings = data.get(name)
            if readings:
                values = [r.current for r in readings if r.current is not None]
                if values:
                    return float(max(values))
        values = [r.current for rs in data.values() for r in rs if r.current is not None]
        if values:
            return float(max(values))
    if sys.platform == "win32":
        return _windows_temp()
    return None


def _windows_temp() -> float | None:
    script = (
        "Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature "
        "| Select-Object -First 1 -ExpandProperty CurrentTemperature"
    )
    try:
        out = subprocess.run(  # noqa: S603
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],  # noqa: S607
            capture_output=True, text=True, timeout=6, check=False,
        ).stdout.strip()
        return float(out) / 10.0 - 273.15 if out else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _ram_percent(_arg: str) -> float | None:
    return float(_psutil().virtual_memory().percent)


def _disk_percent(_arg: str) -> float | None:
    return float(_psutil().disk_usage(str(Path.home())).percent)


def _load_1m(_arg: str) -> float | None:
    try:
        return float(os.getloadavg()[0])
    except (AttributeError, OSError):
        return None


def _battery(_arg: str) -> float | None:
    battery = _psutil().sensors_battery() if hasattr(_psutil(), "sensors_battery") else None
    return float(battery.percent) if battery is not None else None


def _on_battery(_arg: str) -> bool | None:
    battery = _psutil().sensors_battery() if hasattr(_psutil(), "sensors_battery") else None
    if battery is None or battery.power_plugged is None:
        return None
    return not battery.power_plugged


def _hour(_arg: str) -> float | None:
    return float(time.localtime().tm_hour)


def _weekday(_arg: str) -> float | None:
    return float(time.localtime().tm_wday + 1)


def _process_running(arg: str) -> bool | None:
    name = arg.strip().lower()
    if not name:
        return None
    for proc in _psutil().process_iter(["name"]):
        try:
            if name in (proc.info.get("name") or "").lower():
                return True
        except Exception:  # noqa: BLE001 - processus disparu / acces refuse
            continue
    return False


def _window_exists(arg: str) -> bool | None:
    if not arg.strip():
        return None
    from . import platform_utils as pu

    return bool(pu.window_exists(arg))


def _file_exists(arg: str) -> bool | None:
    if not arg.strip():
        return None
    from . import platform_utils as pu

    return Path(pu.expand_path(arg)).exists()


_READERS: dict[str, Callable[[str], Any]] = {
    "uptime_minutes": _uptime_minutes,
    "cpu_percent": _cpu_percent,
    "cpu_temp_c": _cpu_temp,
    "ram_percent": _ram_percent,
    "disk_percent": _disk_percent,
    "load_1m": _load_1m,
    "battery_percent": _battery,
    "on_battery": _on_battery,
    "hour": _hour,
    "weekday": _weekday,
    "process_running": _process_running,
    "window_exists": _window_exists,
    "file_exists": _file_exists,
}


def _hw(name: str):
    def reader(_arg: str) -> Any:
        from .sensors import hardware

        return getattr(hardware, name)()

    return reader


_PROVIDERS: dict[str, Any] = {}


def set_provider(key: str, func) -> None:
    """Branche une source dynamique (micro, capteurs externes) ; ``func(arg)`` renvoie la valeur ou ``None``."""
    _PROVIDERS[key] = func


def _provided(key: str):
    def reader(arg: str) -> Any:
        func = _PROVIDERS.get(key)
        return func(arg) if func else None

    return reader


def _ambient_temp(arg: str) -> float | None:
    value = _hw("ambient_temp_c")(arg)
    if value is None and _PROVIDERS.get("external"):
        value = _PROVIDERS["external"]("ambient")
    return value


def _wifi_is(arg: str) -> bool | None:
    from .sensors import hardware

    ssid = hardware.wifi_ssid()
    if ssid is None:
        return False if not arg else None
    return ssid.lower() == arg.lower() if arg else True


_READERS.update({
    "idle_minutes": _hw("idle_minutes"),
    "ambient_light_lux": _hw("ambient_light_lux"),
    "accel_motion_g": _hw("accel_motion_g"),
    "ambient_temp_c": _ambient_temp,
    "gpu_temp_c": _hw("gpu_temp_c"),
    "disk_temp_c": _hw("disk_temp_c"),
    "fan_rpm": _hw("fan_rpm"),
    "lid_closed": _hw("lid_closed"),
    "wifi_is": _wifi_is,
    "sound_level_db": _provided("sound_level_db"),
    "external": _provided("external"),
})


def read_metric(key: str, arg: str = "") -> Any:
    """Valeur courante d'une mesure (``None`` si indisponible), avec un cache de quelques secondes."""
    metric = METRIC_BY_KEY.get(key)
    reader = _READERS.get(key)
    if metric is None or reader is None:
        return None
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get((key, arg))
        if hit and now - hit[0] < metric.ttl:
            return hit[1]
    try:
        value = reader(arg)
    except Exception as exc:  # noqa: BLE001 - une mesure en echec ne doit jamais planter la detection
        log.debug("Mesure %s indisponible : %s", key, exc)
        value = None
    with _cache_lock:
        _cache[(key, arg)] = (now, value)
    return value


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


class SystemVars(dict):
    """Variable ``system`` des workflows : ``{{ system.cpu_percent }}`` (mesure a la demande)."""

    def get(self, key, default=None):  # type: ignore[override]
        metric = METRIC_BY_KEY.get(key)
        if metric is None or metric.arg_label:
            return default
        return read_metric(key)

    def __getitem__(self, key):
        return self.get(key)

    def keys(self):
        return [m.key for m in METRICS if not m.arg_label]


# --------------------------------------------------------------- conditions


def _compare(actual: Any, op: str, expected: Any) -> bool:
    if isinstance(actual, bool) or isinstance(expected, bool):
        a, b = bool(actual), expected if isinstance(expected, bool) else str(expected).lower() in ("1", "true", "oui", "yes")
        return a == b if op in ("==", ">=", "<=") else a != b
    a, b = float(actual), float(expected)
    return {">": a > b, ">=": a >= b, "<": a < b, "<=": a <= b, "==": a == b, "!=": a != b}[op]


def evaluate(condition: dict) -> tuple[bool, str]:
    """Evalue une condition -> (remplie, explication lisible)."""
    metric = METRIC_BY_KEY.get(condition.get("metric"))
    if metric is None:
        return False, f"mesure inconnue ({condition.get('metric')!r})"
    arg = str(condition.get("arg") or "")
    op = condition.get("op", "==" if metric.kind == "bool" else ">")
    expected = condition.get("value", True if metric.kind == "bool" else 0)
    actual = read_metric(metric.key, arg)
    unit = f" {metric.unit}" if metric.unit else ""
    name = f"{metric.label}{f' « {arg} »' if arg else ''}"
    if actual is None:
        if condition.get("on_unknown") == "pass":
            return True, f"{name} : indisponible (ignoré)"
        return False, f"{name} : indisponible sur ce système"
    try:
        ok = _compare(actual, op, expected)
    except (TypeError, ValueError):
        return False, f"{name} : valeur de comparaison invalide ({expected!r})"
    if metric.kind == "bool":
        shown = "oui" if actual else "non"
        return ok, f"{name} : {shown}"
    shown_actual = f"{actual:.0f}" if abs(actual) >= 100 else f"{actual:.1f}".rstrip("0").rstrip(".")
    return ok, f"{name} : {shown_actual}{unit} (attendu {op} {expected}{unit})"


def check(conditions: list[dict] | None, mode: str = "all") -> tuple[bool, list[str]]:
    """Evalue la liste -> (autorise, motifs des conditions NON remplies)."""
    if not conditions:
        return True, []
    results = [evaluate(c) for c in conditions if isinstance(c, dict)]
    if not results:
        return True, []
    failed = [reason for ok, reason in results if not ok]
    allowed = any(ok for ok, _ in results) if mode == "any" else not failed
    return allowed, ([] if allowed else failed)


def catalog_for_ui() -> dict:
    return {
        "metrics": [
            {
                "key": m.key, "label": m.label, "unit": m.unit, "kind": m.kind,
                "icon": m.icon, "help": m.help, "arg_label": m.arg_label,
            }
            for m in METRICS
        ],
        "operators": list(OPERATORS),
        "modes": list(CONDITION_MODES),
    }
