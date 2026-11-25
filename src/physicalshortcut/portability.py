"""Conversion automatique d'une configuration d'un systeme a l'autre (Windows <-> Linux).

A l'import d'un export, ``detect_os`` determine d'ou il vient (champ ``os`` de l'export, sinon
indices dans les chemins et commandes) et ``convert`` adapte les actions au systeme courant :

* **chemins** : ``C:\\Users\\moi\\Docs`` <-> ``~/Docs``, ``%APPDATA%`` <-> ``~/.config``, ``%VAR%`` <-> ``$VAR``,
  separateurs ``\\`` <-> ``/`` ;
* **programmes** : ``notepad`` <-> ``gnome-text-editor``, ``calc`` <-> ``gnome-calculator``... (table ci-dessous) ;
* **ce qui ne se convertit pas** (commandes shell, programmes inconnus) est reserve a son systeme
  d'origine (``only_on``) au lieu de planter ailleurs ; un rapport detaille chaque changement.

Les gestes sont deja portables (points de la main normalises) : ils ne changent pas.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from . import platform_utils as pu

OS_NAMES = ("windows", "linux")

# (windows, linux) : applications equivalentes courantes
APP_MAP: tuple[tuple[str, str], ...] = (
    ("notepad", "gnome-text-editor"),
    ("calc", "gnome-calculator"),
    ("explorer", "nautilus"),
    ("mspaint", "pinta"),
    ("taskmgr", "gnome-system-monitor"),
    ("wt", "gnome-terminal"),
    ("cmd", "gnome-terminal"),
    ("powershell", "gnome-terminal"),
    ("chrome", "google-chrome"),
    ("msedge", "microsoft-edge"),
    ("winword", "libreoffice --writer"),
    ("excel", "libreoffice --calc"),
    ("powerpnt", "libreoffice --impress"),
)
# memes noms sur les deux systemes : rien a convertir
SAME_APPS = {"firefox", "code", "spotify", "discord", "steam", "vlc", "obs", "slack", "zoom", "telegram", "signal"}

PATH_KEYS = ("path", "source", "destination")
PATH_STEPS = {
    "open_path", "play_sound", "change_wallpaper", "screenshot", "file_write", "file_read", "file_delete",
    "file_copy", "file_move", "directory_create", "launch",
}
WIN_ENV_TO_LINUX = {
    "USERPROFILE": "~", "HOMEPATH": "~", "HOME": "~", "APPDATA": "~/.config", "LOCALAPPDATA": "~/.local/share",
    "TEMP": "/tmp", "TMP": "/tmp", "USERNAME": "$USER", "COMPUTERNAME": "$HOSTNAME",
}
LINUX_ENV_TO_WIN = {
    "HOME": "%USERPROFILE%", "USER": "%USERNAME%", "HOSTNAME": "%COMPUTERNAME%", "TMPDIR": "%TEMP%",
}

_WIN_HINTS = (r"[A-Za-z]:\\", r"%[A-Za-z_]+%", r"\.exe\b", r"\\\\", r"\bpowershell\b", r"\bcmd(\.exe)?\s*/c\b", r"\bexplorer(\.exe)?\b")
_LINUX_HINTS = (r"(^|[\s\"'=])~/", r"/home/", r"\$HOME\b", r"\bxdg-open\b", r"/usr/", r"\bnotify-send\b", r"\.sh\b", r"\bbash\b", r"/tmp/")


# --------------------------------------------------------------------------
# Detection
# --------------------------------------------------------------------------


def _iter_nodes(action: dict) -> list[dict]:
    nodes = action.get("nodes") if isinstance(action.get("nodes"), list) else action.get("steps", [])
    return [n for n in nodes if isinstance(n, dict)]


def _strings(action: dict):
    for node in _iter_nodes(action):
        for key, value in node.items():
            if isinstance(value, str) and key not in ("id", "type"):
                yield value
        if node.get("only_on") in OS_NAMES:
            yield f"only_on:{node['only_on']}"


def detect_os(bundle: dict, actions: list[dict] | None = None) -> str | None:
    declared = bundle.get("os") if isinstance(bundle, dict) else None
    if declared in OS_NAMES:
        return declared
    win = linux = 0
    for action in actions if actions is not None else bundle.get("actions", []):
        if not isinstance(action, dict):
            continue
        for text in _strings(action):
            if text == "only_on:windows":
                win += 3
            elif text == "only_on:linux":
                linux += 3
            win += sum(1 for pattern in _WIN_HINTS if re.search(pattern, text, re.I))
            linux += sum(1 for pattern in _LINUX_HINTS if re.search(pattern, text))
    if win == linux:
        return None
    return "windows" if win > linux else "linux"


# --------------------------------------------------------------------------
# Conversion des chemins et programmes
# --------------------------------------------------------------------------


def path_to_linux(value: str) -> str:
    out = value.strip()
    out = re.sub(r"^[A-Za-z]:\\Users\\[^\\]+\\?", "~/", out)
    out = re.sub(r"%([A-Za-z_]+)%", lambda m: WIN_ENV_TO_LINUX.get(m.group(1).upper(), f"${m.group(1)}"), out)
    out = re.sub(r"^[A-Za-z]:\\", "/mnt/", out)  # autre lecteur : a verifier
    out = out.replace("\\", "/")
    out = re.sub(r"/{2,}", "/", out) if not out.startswith("//") else out
    return out.replace("~//", "~/")


def path_to_windows(value: str) -> str:
    out = value.strip()
    out = re.sub(r"^~/\.config(/|$)", r"%APPDATA%/", out)
    out = re.sub(r"^~/\.local/share(/|$)", r"%LOCALAPPDATA%/", out)
    out = re.sub(r"^~(/|$)", r"%USERPROFILE%/", out)
    out = re.sub(r"^/home/[^/]+(/|$)", r"%USERPROFILE%/", out)
    out = re.sub(r"^/tmp(/|$)", r"%TEMP%/", out)
    out = re.sub(r"\$\{?([A-Za-z_]+)\}?", lambda m: LINUX_ENV_TO_WIN.get(m.group(1), f"%{m.group(1)}%"), out)
    return out.replace("/", "\\")


def _program(value: str, target: str) -> tuple[str, bool]:
    """Nom d'application -> equivalent sur le systeme cible ; (resultat, connu)."""
    command = value.strip()
    head, _, rest = command.partition(" ")
    base = re.sub(r"\.exe$", "", head, flags=re.I)
    low = base.lower()
    if low in SAME_APPS:
        return (f"{base}{' ' + rest if rest else ''}", True)
    for win, lin in APP_MAP:
        if target == "linux" and low == win:
            return (lin + (" " + rest if rest else ""), True)
        if target == "windows" and low == lin.split()[0]:
            extra = lin.split(" ", 1)[1] if " " in lin else ""
            return (win + (" " + rest if rest else "") if not extra else command, not extra)
    return (command, False)


def _looks_like_path(value: str) -> bool:
    return any(c in value for c in ("/", "\\", "~", "%", "$")) or bool(re.match(r"^[A-Za-z]:", value))


def convert_action(action: dict, source: str, target: str) -> tuple[dict, list[str]]:
    """Copie de l'action adaptee a ``target`` + notes lisibles."""
    result = copy.deepcopy(action)
    notes: list[str] = []
    if source == target:
        return result, notes
    to_path = path_to_linux if target == "linux" else path_to_windows
    for node in _iter_nodes(result):
        step_type = node.get("type")
        if node.get("only_on") == source:
            continue  # deja reserve a son systeme d'origine : rien a faire
        changed = False
        if step_type in PATH_STEPS:
            for key in PATH_KEYS:
                value = node.get(key)
                if isinstance(value, str) and value and "{{" not in value:
                    if step_type == "launch" and key == "path" and not _looks_like_path(value):
                        new, known = _program(value, target)
                        if new != value:
                            node[key] = new
                            notes.append(f"Lancer une application : {value} -> {new}")
                            changed = True
                        elif not known and value.lower() not in {a for a, _ in APP_MAP}:
                            notes.append(f"Programme « {value} » : à vérifier sur {target.capitalize()}")
                        continue
                    new = to_path(value)
                    if new != value:
                        node[key] = new
                        notes.append(f"Chemin : {value} -> {new}")
                        changed = True
        elif step_type == "run_shell":
            node["only_on"] = source  # commande non convertible : reste sur son systeme
            notes.append(f"Commande shell réservée à {source.capitalize()} (non convertible)")
            changed = True
        elif step_type in ("if_system", "system_metric") and node.get("metric") == "file_exists" and node.get("arg"):
            node["arg"] = to_path(node["arg"])
            changed = True
        elif step_type == "switch_desktop" and node.get("index") and target == "windows":
            node.pop("index", None)
            notes.append("Bureau virtuel : le numéro précis n'existe que sous Linux")
            changed = True
        if step_type == "launch" and node.get("shell_cmd") and not changed:
            node["only_on"] = source
            notes.append(f"Ligne de commande réservée à {source.capitalize()}")
    return result, notes


def convert(gestures: list[dict], actions: list[dict], source: str | None, target: str | None = None) -> tuple[list[dict], dict]:
    """Convertit toutes les actions ; renvoie (actions, rapport)."""
    target = target or pu.current_os()
    report: dict[str, Any] = {"source_os": source, "target_os": target, "converted": False, "notes": []}
    if source not in OS_NAMES or target not in OS_NAMES or source == target:
        return actions, report
    out = []
    for action in actions:
        new, notes = convert_action(action, source, target)
        out.append(new)
        report["notes"] += [f"« {action.get('name', '?')} » : {n}" for n in notes]
    report["converted"] = True
    return out, report
