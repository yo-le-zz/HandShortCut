"""Diagnostic de l'environnement (``handshortcut doctor``).

Indique ce qui fonctionne et quoi installer, sous Linux comme sous Windows.
"""

from __future__ import annotations

import importlib.util
import os
import platform
import sys

from . import __version__
from . import platform_utils as pu

# (outil, utilite, paquet a installer)
LINUX_TOOLS = (
    ("wmctrl", "fenetres : deplacer, fermer, focus", "wmctrl"),
    ("xdotool", "fenetres / medias (alternative a wmctrl)", "xdotool"),
    ("playerctl", "lecture / pause / piste suivante", "playerctl"),
    ("wpctl", "volume (PipeWire)", "wireplumber"),
    ("pactl", "volume (PulseAudio)", "pulseaudio-utils"),
    ("xclip", "presse-papiers (X11)", "xclip"),
    ("wl-copy", "presse-papiers (Wayland)", "wl-clipboard"),
    ("notify-send", "notifications", "libnotify-bin"),
    ("brightnessctl", "luminosite", "brightnessctl"),
    ("xdg-open", "ouvrir fichiers / dossiers / URL", "xdg-utils"),
    ("gsettings", "theme et fond d'ecran (GNOME)", "libglib2.0-bin"),
    ("spd-say", "synthese vocale", "speech-dispatcher"),
    ("paplay", "jouer des sons", "pulseaudio-utils"),
)
PYTHON_MODULES = (
    ("cv2", "camera (OpenCV)"),
    ("mediapipe", "detection des mains"),
    ("flask", "interface web"),
    ("waitress", "serveur web"),
    ("pyautogui", "clavier et souris"),
    ("pyperclip", "presse-papiers"),
    ("psutil", "processus"),
    ("screeninfo", "ecrans"),
    ("websocket", "etape WebSocket"),
)


def collect() -> list[tuple[str, bool | None, str]]:
    """Liste de (libelle, etat, detail) ; etat ``None`` = information seulement."""
    rows: list[tuple[str, bool | None, str]] = [
        ("Version", None, __version__),
        ("Systeme", None, f"{platform.platform()} - Python {platform.python_version()}"),
    ]
    if pu.IS_LINUX:
        session = "Wayland" if pu.IS_WAYLAND else "X11" if os.environ.get("DISPLAY") else "aucune session graphique"
        rows.append(("Session", None, f"{session} ({os.environ.get('XDG_CURRENT_DESKTOP', 'bureau inconnu')})"))
        if pu.IS_WAYLAND:
            rows.append(
                (
                    "Wayland",
                    None,
                    "clavier, souris et fenetres ne pilotent que les applications XWayland",
                )
            )
    monitors = pu.list_monitors()
    rows.append(("Ecrans", bool(monitors), f"{len(monitors)} detecte(s)" if monitors else "aucun ecran detecte"))

    for module, role in PYTHON_MODULES:
        if getattr(sys, "frozen", False) or "__compiled__" in globals():
            break  # executable compile : les modules sont embarques
        found = importlib.util.find_spec(module) is not None
        rows.append((f"Module {module}", found, role if found else f"{role} - manquant"))

    if pu.IS_LINUX:
        for tool, role, package in LINUX_TOOLS:
            found = pu.have(tool)
            rows.append((tool, found, role if found else f"{role} - paquet : {package}"))
    elif pu.IS_WINDOWS:
        rows.append(("PowerShell", pu.have("powershell") or pu.have("pwsh"), "luminosite, voix, bureau"))
    return rows


def render(rows) -> str:
    width = max(len(label) for label, _, _ in rows)
    lines = []
    for label, state, detail in rows:
        mark = "    " if state is None else "[OK]" if state else "[--]"
        lines.append(f"{mark} {label.ljust(width)}  {detail}")
    return "\n".join(lines)
