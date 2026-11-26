"""Emplacements des fichiers de PhysicalShortCut (donnees, journaux, exemples).

Les donnees utilisateur ne sont jamais ecrites dans le dossier d'installation
(il peut etre en lecture seule : /opt, Program Files...). Elles vont dans les
dossiers standards de l'OS via ``platformdirs``. La variable d'environnement
``PHYSICALSHORTCUT_DATA_DIR`` (ou l'option ``--data-dir``) permet de les deplacer.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import platformdirs

APP_DIRNAME = "PhysicalShortCut" if sys.platform == "win32" else "physicalshortcut"

ENV_DATA_DIR = "PHYSICALSHORTCUT_DATA_DIR"
LEGACY_ENV_DATA_DIR = "HANDSHORTCUT_DATA_DIR"  # ancien nom du projet (avant la 2.0)
LEGACY_APP_DIRNAME = "HandShortCut" if sys.platform == "win32" else "handshortcut"


def data_dir() -> Path:
    """Dossier contenant gestures.json et actions.json."""
    override = os.environ.get(ENV_DATA_DIR) or os.environ.get(LEGACY_ENV_DATA_DIR)
    if override:
        return Path(override).expanduser().resolve()
    return Path(platformdirs.user_data_dir(APP_DIRNAME, appauthor=False))


def log_dir() -> Path:
    """Dossier du fichier de journal."""
    return Path(platformdirs.user_log_dir(APP_DIRNAME, appauthor=False))


def examples_dir() -> Path:
    """Exemples d'actions/gestes livres avec le paquet."""
    return Path(__file__).resolve().parent / "examples"


def legacy_data_dir() -> Path:
    """Ancien dossier de donnees (projet nomme HandShortCut jusqu'a la 1.x)."""
    return Path(platformdirs.user_data_dir(LEGACY_APP_DIRNAME, appauthor=False))


def migrate_legacy_data() -> Path | None:
    """Copie (sans rien supprimer) les donnees de l'ancien dossier HandShortCut au premier lancement.

    Ne fait rien si un dossier de donnees personnalise est utilise, si le nouveau dossier contient deja
    des donnees ou si l'ancien n'existe pas. Renvoie l'ancien dossier quand une copie a eu lieu.
    """
    if os.environ.get(ENV_DATA_DIR) or os.environ.get(LEGACY_ENV_DATA_DIR):
        return None
    new, old = data_dir(), legacy_data_dir()
    if not old.is_dir() or old == new:
        return None
    if new.exists() and any(new.iterdir()):
        return None
    new.mkdir(parents=True, exist_ok=True)
    copied = False
    for item in old.iterdir():
        if item.is_file() and item.suffix in (".json", ".png", ".wav"):
            try:
                (new / item.name).write_bytes(item.read_bytes())
                copied = True
            except OSError:
                continue
    return old if copied else None
