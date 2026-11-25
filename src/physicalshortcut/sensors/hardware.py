"""Capteurs physiques du PC : lumiere ambiante, accelerometre, temperatures, ventilateurs, capot,
inactivite, peripheriques USB / Bluetooth, Wi-Fi.

Chaque lecture renvoie ``None`` quand le capteur n'existe pas sur la machine (ou n'est pas lisible
sur ce systeme) : un PC n'a pas forcement de capteur de lumiere ni d'accelerometre. ``inventory()``
liste ce qui est reellement present, pour l'afficher honnetement dans l'interface.
"""

from __future__ import annotations

import contextlib
import ctypes
import glob
import math
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")
SYS = Path("/sys")


def _read(path: str | Path) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None


def _float(path: str | Path) -> float | None:
    text = _read(path)
    try:
        return float(text) if text not in (None, "") else None
    except ValueError:
        return None


def _run(args: list[str], timeout: float = 4.0) -> str | None:
    if not shutil.which(args[0]):
        return None
    try:
        done = subprocess.run(  # noqa: S603 - arguments fixes, pas de shell
            args, capture_output=True, text=True, timeout=timeout, check=False,
            **({"creationflags": 0x08000000} if IS_WINDOWS else {}),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout if done.returncode == 0 else None


def _powershell(script: str, timeout: float = 8.0) -> str | None:
    return _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], timeout)


# --------------------------------------------------------------------------
# IIO (Linux) : lumiere, accelerometre, temperature ambiante
# --------------------------------------------------------------------------


def _iio_dirs() -> list[Path]:
    return [Path(p) for p in sorted(glob.glob(str(SYS / "bus/iio/devices/iio:device*")))]


def _iio_value(device: Path, name: str) -> float | None:
    """Valeur physique d'un canal IIO : ``(raw + offset) * scale`` ou ``<name>_input``."""
    direct = _float(device / f"{name}_input")
    if direct is not None:
        return direct
    raw = _float(device / f"{name}_raw")
    if raw is None:
        return None
    scale = _float(device / f"{name}_scale")
    offset = _float(device / f"{name}_offset") or 0.0
    return (raw + offset) * (scale if scale is not None else 1.0)


def ambient_light_lux() -> float | None:
    for device in _iio_dirs():
        for channel in ("in_illuminance", "in_intensity_both", "in_illuminance0"):
            value = _iio_value(device, channel)
            if value is not None:
                return value
    for path in glob.glob(str(SYS / "bus/acpi/devices/ACPI0008:*/ali")):
        value = _float(path)
        if value is not None:
            return value
    return None


def accel_vector() -> tuple[float, float, float] | None:
    """Acceleration (x, y, z) en m/s2, ou ``None``."""
    for device in _iio_dirs():
        values = [_iio_value(device, f"in_accel_{axis}") for axis in "xyz"]
        if all(v is not None for v in values):
            return tuple(values)  # type: ignore[return-value]
    text = _read(SYS / "devices/platform/lis3lv02d/position")  # ThinkPad / HP (HDAPS)
    if text:
        found = re.findall(r"-?\d+", text)
        if len(found) >= 3:
            return tuple(float(v) / 1000 * 9.81 for v in found[:3])  # type: ignore[return-value]
    return None


def accel_motion_g() -> float | None:
    """Ecart a la gravite en g (0 = immobile ; > 0,3 = secousse)."""
    vec = accel_vector()
    if vec is None:
        return None
    return abs(math.sqrt(sum(v * v for v in vec)) / 9.80665 - 1.0)


# --------------------------------------------------------------------------
# Temperatures et ventilateurs
# --------------------------------------------------------------------------


def _hwmon() -> list[tuple[str, Path]]:
    out = []
    for path in sorted(glob.glob(str(SYS / "class/hwmon/hwmon*"))):
        out.append(((_read(Path(path) / "name") or "?"), Path(path)))
    return out


def temperatures() -> list[tuple[str, str, float]]:
    """Toutes les sondes lisibles : (source, etiquette, degres C)."""
    found: list[tuple[str, str, float]] = []
    for name, base in _hwmon():
        for temp in sorted(glob.glob(str(base / "temp*_input"))):
            value = _float(temp)
            label = _read(temp.replace("_input", "_label")) or Path(temp).name.replace("_input", "")
            if value is not None:
                found.append((name, label, value / 1000))
    for zone in sorted(glob.glob(str(SYS / "class/thermal/thermal_zone*"))):
        value = _float(Path(zone) / "temp")
        if value is not None:
            found.append(("thermal", _read(Path(zone) / "type") or "zone", value / 1000))
    for device in _iio_dirs():
        value = _iio_value(device, "in_temp")
        if value is not None:
            found.append(("iio", _read(device / "name") or "iio", value / 1000 if abs(value) > 200 else value))
    return found


def _pick(names: tuple[str, ...], labels: tuple[str, ...] = ()) -> float | None:
    best = None
    for source, label, value in temperatures():
        if any(n in source.lower() for n in names) or any(k in label.lower() for k in labels):
            best = value if best is None else max(best, value)
    return best


def ambient_temp_c() -> float | None:
    """Temperature ambiante : seulement si la machine a une vraie sonde (IIO ou etiquette ambient/room).

    Un PC n'a en general PAS de thermometre de piece : les sondes CPU/carte-mere ne comptent pas.
    """
    for device in _iio_dirs():
        value = _iio_value(device, "in_temp")
        if value is not None and "gyro" not in (_read(device / "name") or ""):
            return value / 1000 if abs(value) > 200 else value
    return _pick((), ("ambient", "room", "ambiant"))


def gpu_temp_c() -> float | None:
    value = _pick(("amdgpu", "nouveau", "radeon", "nvidia"))
    if value is not None:
        return value
    out = _run(["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"])
    try:
        return float(out.strip().splitlines()[0]) if out else None
    except ValueError:
        return None


def disk_temp_c() -> float | None:
    return _pick(("nvme", "drivetemp"))


def fan_rpm() -> float | None:
    best = None
    for _, base in _hwmon():
        for fan in glob.glob(str(base / "fan*_input")):
            value = _float(fan)
            if value is not None:
                best = value if best is None else max(best, value)
    return best


# --------------------------------------------------------------------------
# Capot, inactivite, secteur
# --------------------------------------------------------------------------


def lid_closed() -> bool | None:
    for path in glob.glob("/proc/acpi/button/lid/*/state"):
        text = _read(path)
        if text:
            return "closed" in text.lower()
    return None


def idle_minutes() -> float | None:
    """Minutes sans clavier ni souris."""
    if IS_WINDOWS:
        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(info)
        try:
            if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):  # type: ignore[attr-defined]
                return (ctypes.windll.kernel32.GetTickCount() - info.dwTime) / 60000  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            return None
        return None
    out = _run(["xprintidle"])
    if out and out.strip().isdigit():
        return int(out.strip()) / 60000
    session = os.environ.get("XDG_SESSION_ID")
    if session:
        out = _run(["loginctl", "show-session", session, "-p", "IdleHint", "-p", "IdleSinceHintMonotonic"])
        if out:
            props = dict(line.split("=", 1) for line in out.strip().splitlines() if "=" in line)
            since = props.get("IdleSinceHintMonotonic", "0")
            if props.get("IdleHint") == "yes" and since.isdigit() and int(since) > 0:
                return max(0.0, (time.monotonic() - int(since) / 1e6) / 60)
            if props.get("IdleHint") == "no":
                return 0.0
    return None


# --------------------------------------------------------------------------
# Peripheriques
# --------------------------------------------------------------------------


def usb_devices() -> dict[str, str] | None:
    """Peripheriques USB branches : ``{identifiant: nom}`` (``None`` si illisible)."""
    if IS_LINUX:
        found = {}
        for path in glob.glob(str(SYS / "bus/usb/devices/*")):
            vendor, product = _read(Path(path) / "idVendor"), _read(Path(path) / "idProduct")
            if not vendor or not product:
                continue
            if _read(Path(path) / "bDeviceClass") == "09":  # concentrateur (hub) : ignore
                continue
            name = _read(Path(path) / "product") or "Peripherique USB"
            found[f"{vendor}:{product}@{Path(path).name}"] = name
        return found
    if IS_WINDOWS:
        out = _powershell(
            "Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -like 'USB\\VID_*' } | "
            "ForEach-Object { $_.InstanceId + '|' + $_.FriendlyName }"
        )
        if out is None:
            return None
        found = {}
        for line in out.splitlines():
            if "|" in line:
                key, name = line.split("|", 1)
                found[key.strip()] = name.strip() or "Peripherique USB"
        return found
    return None


def bluetooth_connected() -> dict[str, str] | None:
    """Appareils Bluetooth actuellement connectes : ``{adresse: nom}``."""
    if IS_LINUX:
        out = _run(["bluetoothctl", "devices", "Connected"])
        if out is None:
            return None
        found = {}
        for line in out.splitlines():
            parts = line.split(" ", 2)
            if len(parts) == 3 and parts[0] == "Device":
                found[parts[1]] = parts[2]
        return found
    if IS_WINDOWS:
        out = _powershell(
            "Get-PnpDevice -Class Bluetooth -PresentOnly -Status OK | "
            "ForEach-Object { $_.InstanceId + '|' + $_.FriendlyName }"
        )
        if out is None:
            return None
        return {k.strip(): v.strip() for k, _, v in (line.partition("|") for line in out.splitlines()) if v}
    return None


def wifi_ssid() -> str | None:
    if IS_LINUX:
        out = _run(["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"])
        for line in (out or "").splitlines():
            if line.startswith("yes:"):
                return line[4:] or None
        return None
    if IS_WINDOWS:
        out = _run(["netsh", "wlan", "show", "interfaces"])
        match = re.search(r"^\s*SSID\s*:\s*(.+)$", out or "", re.M)
        return match.group(1).strip() if match else None
    return None


# --------------------------------------------------------------------------
# Inventaire (affiche dans l'interface)
# --------------------------------------------------------------------------


def inventory() -> list[dict]:
    """Ce que cette machine possede reellement : [{id, label, present, detail}]."""
    lux, motion = ambient_light_lux(), accel_vector()
    temps = temperatures()
    ambient = ambient_temp_c()
    usb, bt = usb_devices(), bluetooth_connected()
    return [
        {"id": "light", "label": "Capteur de lumière ambiante", "present": lux is not None,
         "detail": f"{lux:.0f} lux" if lux is not None else "Absent (courant sur tablettes et portables 2-en-1)."},
        {"id": "accelerometer", "label": "Accéléromètre", "present": motion is not None,
         "detail": "Présent." if motion is not None else "Absent (surtout sur les portables convertibles)."},
        {"id": "ambient_temp", "label": "Thermomètre de la pièce", "present": ambient is not None,
         "detail": f"{ambient:.1f} °C" if ambient is not None else "Absent : un PC mesure ses composants, pas la pièce. Utilise un capteur externe (DHT22, BME280…) sur Arduino."},
        {"id": "temps", "label": "Sondes de température (CPU, disque, GPU)", "present": bool(temps),
         "detail": f"{len(temps)} sonde(s)" if temps else "Aucune lisible (Linux : installer lm-sensors ; Windows : non exposées)."},
        {"id": "fans", "label": "Ventilateurs", "present": fan_rpm() is not None, "detail": "Vitesse lisible." if fan_rpm() is not None else "Non lisible."},
        {"id": "lid", "label": "Capot de portable", "present": lid_closed() is not None,
         "detail": "Lisible." if lid_closed() is not None else "Non disponible (poste fixe ou non exposé)."},
        {"id": "idle", "label": "Inactivité clavier / souris", "present": idle_minutes() is not None,
         "detail": "Lisible." if idle_minutes() is not None else "Linux : installer `xprintidle` (X11) ; Wayland : selon le bureau."},
        {"id": "usb", "label": "Périphériques USB", "present": usb is not None, "detail": f"{len(usb)} branché(s)" if usb is not None else "Illisible."},
        {"id": "bluetooth", "label": "Bluetooth", "present": bt is not None,
         "detail": f"{len(bt)} connecté(s)" if bt is not None else "Indisponible (Linux : bluez/bluetoothctl requis)."},
    ]


def clear_caches() -> None:
    with contextlib.suppress(Exception):
        temperatures.cache_clear()  # type: ignore[attr-defined]
