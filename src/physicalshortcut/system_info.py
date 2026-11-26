"""Lectures d'informations sur l'ordinateur (etapes « Obtenir ... » des workflows).

Tout est en lecture seule. Les analyseurs de sortie (``parse_*``) sont des fonctions pures, testees ;
les lectures renvoient ``None`` / un dictionnaire ``available: False`` quand l'information n'existe pas
sur la machine (aucun lecteur de musique, pas d'outil audio...).
"""

from __future__ import annotations

import getpass
import logging
import os
import platform
import re
import socket
from datetime import datetime
from typing import Any

from . import platform_utils as pu

log = logging.getLogger("physicalshortcut.system_info")

IS_WINDOWS = pu.IS_WINDOWS
IS_LINUX = pu.IS_LINUX


# --------------------------------------------------------------------------
# Identite de la machine
# --------------------------------------------------------------------------


def hostname() -> str:
    return socket.gethostname()


def username() -> str:
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001
        return os.environ.get("USER") or os.environ.get("USERNAME") or ""


def os_info() -> dict[str, Any]:
    return {
        "os": pu.current_os(),
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "hostname": hostname(),
        "user": username(),
        "home": os.path.expanduser("~"),
    }


def ip_address() -> str:
    """Adresse IP locale (aucun paquet n'est envoye : on interroge seulement la table de routage)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.0.2.1", 9))  # adresse de documentation, jamais routee
        return sock.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(hostname())
        except OSError:
            return ""
    finally:
        sock.close()


def datetime_info(now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now()
    return {
        "iso": now.isoformat(timespec="seconds"),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "year": now.year, "month": now.month, "day": now.day,
        "hour": now.hour, "minute": now.minute, "second": now.second,
        "weekday": now.isoweekday(),  # 1 = lundi
        "timestamp": int(now.timestamp()),
    }


def screen_info() -> dict[str, Any]:
    monitors = pu.list_monitors()
    primary = next((m for m in monitors if m.get("primary")), monitors[0] if monitors else None)
    return {
        "count": len(monitors),
        "width": primary.get("width") if primary else None,
        "height": primary.get("height") if primary else None,
        "monitors": monitors,
    }


def cursor_position() -> dict[str, int] | None:
    try:
        gui = pu.pyautogui_module()
        if gui is None:
            return None
        pos = gui.position()
        return {"x": int(pos[0]), "y": int(pos[1])}
    except Exception as exc:  # noqa: BLE001
        log.debug("Position de la souris : %s", exc)
        return None


def active_window_title() -> str | None:
    if IS_WINDOWS:
        try:
            import ctypes

            user32 = ctypes.windll.user32  # type: ignore[attr-defined]
            handle = user32.GetForegroundWindow()
            length = user32.GetWindowTextLengthW(handle)
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(handle, buffer, length + 1)
            return buffer.value
        except Exception:  # noqa: BLE001
            return None
    if IS_LINUX and pu.have("xdotool"):
        result = pu.run(["xdotool", "getactivewindow", "getwindowname"], timeout=2)
        if pu._ok(result):
            return result.stdout.strip()
    return None


# --------------------------------------------------------------------------
# Volume
# --------------------------------------------------------------------------


def parse_wpctl(text: str) -> dict[str, Any] | None:
    """``Volume: 0.45 [MUTED]`` -> {level: 45, muted: True}."""
    match = re.search(r"Volume:\s*([0-9.]+)", text)
    if not match:
        return None
    return {"level": round(float(match.group(1)) * 100), "muted": "MUTED" in text.upper()}


def parse_pactl(volume_text: str, mute_text: str = "") -> dict[str, Any] | None:
    match = re.search(r"(\d+)%", volume_text)
    if not match:
        return None
    return {"level": int(match.group(1)), "muted": bool(re.search(r"(yes|oui)", mute_text, re.I))}


def parse_amixer(text: str) -> dict[str, Any] | None:
    match = re.search(r"\[(\d+)%\]", text)
    if not match:
        return None
    return {"level": int(match.group(1)), "muted": "[off]" in text}


def volume() -> dict[str, Any]:
    """{available, level (0-100), muted}."""
    found: dict[str, Any] | None = None
    if IS_LINUX:
        if pu.have("wpctl"):
            result = pu.run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"], timeout=3)
            if pu._ok(result):
                found = parse_wpctl(result.stdout)
        if found is None and pu.have("pactl"):
            vol = pu.run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"], timeout=3)
            mute = pu.run(["pactl", "get-sink-mute", "@DEFAULT_SINK@"], timeout=3)
            if pu._ok(vol):
                found = parse_pactl(vol.stdout, mute.stdout if pu._ok(mute) else "")
        if found is None and pu.have("amixer"):
            result = pu.run(["amixer", "sget", "Master"], timeout=3)
            if pu._ok(result):
                found = parse_amixer(result.stdout)
    elif IS_WINDOWS:
        try:
            from pycaw.pycaw import AudioUtilities

            endpoint = AudioUtilities.GetSpeakers().EndpointVolume
            found = {"level": round(endpoint.GetMasterVolumeLevelScalar() * 100), "muted": bool(endpoint.GetMute())}
        except Exception as exc:  # noqa: BLE001
            log.debug("Lecture du volume (pycaw) : %s", exc)
    if found is None:
        return {"available": False, "level": None, "muted": None}
    return {"available": True, **found}


# --------------------------------------------------------------------------
# Etat de la musique / des medias
# --------------------------------------------------------------------------

STATES = ("playing", "paused", "stopped", "none")


def _state_of(raw: str) -> str:
    raw = (raw or "").strip().lower()
    if raw == "playing":
        return "playing"
    if raw == "paused":
        return "paused"
    if raw in ("stopped", "closed", "opened", "changing"):
        return "stopped"
    return "none"


def media_dict(state: str, title: str = "", artist: str = "", album: str = "", player: str = "",
               position: float | None = None, length: float | None = None, available: bool = True) -> dict[str, Any]:
    state = _state_of(state)
    return {
        "available": available, "state": state, "playing": state == "playing", "paused": state == "paused",
        "title": title, "artist": artist, "album": album, "player": player,
        "position": position, "length": length,
    }


def parse_playerctl(status: str, metadata: str) -> dict[str, Any]:
    """Sorties de ``playerctl status`` et de ``playerctl metadata --format '...|...'`` (champs separes par \\t)."""
    parts = (metadata.rstrip("\n").split("\t") + [""] * 6)[:6]
    artist, title, album, player, position, length = parts

    def seconds(value: str, divisor: float) -> float | None:
        try:
            return round(float(value) / divisor, 1)
        except ValueError:
            return None

    return media_dict(status, title, artist, album, player, seconds(position, 1_000_000), seconds(length, 1_000_000))


def parse_windows_media(text: str) -> dict[str, Any]:
    """``Playing|Artiste|Titre|Album|Application`` (script PowerShell ci-dessous) ou ``none``."""
    text = text.strip()
    if not text or text == "none":
        return media_dict("none")
    artist_title = (text.split("|") + [""] * 5)[:5]
    state, artist, title, album, player = artist_title
    return media_dict(state, title, artist, album, player)


_WINDOWS_MEDIA_SCRIPT = r"""
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
Function Await($task, $type) { $m = $asTask.MakeGenericMethod($type); $n = $m.Invoke($null, @($task)); $n.Wait(-1) | Out-Null; $n.Result }
[Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager, Windows.Media.Control, ContentType=WindowsRuntime] | Out-Null
$mgr = Await ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager]::RequestAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager])
$s = $mgr.GetCurrentSession()
if (-not $s) { 'none'; exit }
$p = Await ($s.TryGetMediaPropertiesAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionMediaProperties])
$st = $s.GetPlaybackInfo().PlaybackStatus
"$st|$($p.Artist)|$($p.Title)|$($p.AlbumTitle)|$($s.SourceAppUserModelId)"
"""


def media_state() -> dict[str, Any]:
    """Etat du lecteur de musique / video actif : lecture, pause, titre, artiste..."""
    if IS_LINUX and pu.have("playerctl"):
        status = pu.run(["playerctl", "status"], timeout=3)
        if not pu._ok(status):  # aucun lecteur ouvert
            return media_dict("none")
        meta = pu.run(
            ["playerctl", "metadata", "--format",
             "{{artist}}\t{{title}}\t{{album}}\t{{playerName}}\t{{position}}\t{{mpris:length}}"],
            timeout=3,
        )
        return parse_playerctl(status.stdout, meta.stdout if pu._ok(meta) else "")
    if IS_WINDOWS:
        result = pu.powershell(_WINDOWS_MEDIA_SCRIPT, timeout=12)
        if pu._ok(result):
            return parse_windows_media(result.stdout)
    return media_dict("none", available=False)


class LiveInfo(dict):
    """Variable de workflow relue a la demande (``{{ media.title }}``, ``{{ volume.level }}``).

    Les valeurs sont rafraichies au plus une fois par ``ttl`` secondes : une condition « attendre que
    la musique joue » voit donc l'etat reel et pas celui du debut du workflow.
    """

    def __init__(self, fetch, ttl: float = 1.0) -> None:
        super().__init__()
        self._fetch, self._ttl = fetch, ttl
        self._at = 0.0
        self._data: dict[str, Any] = {}

    def _fresh(self) -> dict[str, Any]:
        import time

        now = time.monotonic()
        if now - self._at >= self._ttl or not self._data:
            self._data, self._at = dict(self._fetch()), now
        return self._data

    def get(self, key, default=None):  # type: ignore[override]
        return self._fresh().get(key, default)

    def __getitem__(self, key):
        return self._fresh()[key]

    def __contains__(self, key):
        return key in self._fresh()

    def keys(self):
        return self._fresh().keys()

    def items(self):
        return self._fresh().items()

    def __iter__(self):
        return iter(self._fresh())

    def __len__(self):
        return len(self._fresh())
