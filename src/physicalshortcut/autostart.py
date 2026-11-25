"""Demarrage automatique a l'ouverture de session (Linux et Windows), sans droits admin.

* Linux   : ``~/.config/autostart/physicalshortcut.desktop`` (XDG) ;
* Windows : cle ``HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run``.

Les paquets (.deb, .rpm, MSI, installateur .exe) configurent deja le demarrage
automatique ; cette commande sert pour une installation avec ``uv`` / ``pip``.
"""

from __future__ import annotations

import logging
import os
import shlex
import subprocess
from pathlib import Path

from . import platform_utils as pu

log = logging.getLogger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "PhysicalShortCut"


def _linux_file() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "autostart" / "physicalshortcut.desktop"


def _command_line() -> str:
    command = pu.executable_command()
    if pu.IS_WINDOWS:
        return subprocess.list2cmdline(command)
    return " ".join(shlex.quote(part) for part in command)


def is_enabled() -> bool:
    if pu.IS_WINDOWS:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                winreg.QueryValueEx(key, VALUE_NAME)
            return True
        except OSError:
            return False
    return _linux_file().exists()


def enable() -> str:
    """Active le demarrage automatique ; retourne l'emplacement configure."""
    command = _command_line()
    _remove_legacy()
    if pu.IS_WINDOWS:
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command)
        return f"HKCU\\{RUN_KEY}\\{VALUE_NAME}"
    path = _linux_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=PhysicalShortCut\n"
        "Comment=Gestes de la main vers actions\n"
        f"Exec={command}\n"
        "Icon=physicalshortcut\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n",
        encoding="utf-8",
    )
    return str(path)


def _remove_legacy() -> bool:
    """Retire l'ancien demarrage automatique du projet nomme HandShortCut (avant la 2.0)."""
    if pu.IS_WINDOWS:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, "HandShortCut")
            return True
        except OSError:
            return False
    legacy = _linux_file().with_name("handshortcut.desktop")
    if legacy.exists():
        legacy.unlink()
        return True
    return False


def disable() -> bool:
    """Desactive le demarrage automatique ; ``False`` s'il n'etait pas active."""
    legacy_removed = _remove_legacy()
    if pu.IS_WINDOWS:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, VALUE_NAME)
            return True
        except OSError:
            return legacy_removed
    path = _linux_file()
    if path.exists():
        path.unlink()
        return True
    return legacy_removed
