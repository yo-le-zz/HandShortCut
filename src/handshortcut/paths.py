"""Emplacements des fichiers de HandShortCut (donnees, journaux, exemples).

Les donnees utilisateur ne sont jamais ecrites dans le dossier d'installation
(il peut etre en lecture seule : /opt, Program Files...). Elles vont dans les
dossiers standards de l'OS via ``platformdirs``. La variable d'environnement
``HANDSHORTCUT_DATA_DIR`` (ou l'option ``--data-dir``) permet de les deplacer.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import platformdirs

APP_DIRNAME = "HandShortCut" if sys.platform == "win32" else "handshortcut"

ENV_DATA_DIR = "HANDSHORTCUT_DATA_DIR"


def data_dir() -> Path:
    """Dossier contenant gestures.json et actions.json."""
    override = os.environ.get(ENV_DATA_DIR)
    if override:
        return Path(override).expanduser().resolve()
    return Path(platformdirs.user_data_dir(APP_DIRNAME, appauthor=False))


def log_dir() -> Path:
    """Dossier du fichier de journal."""
    return Path(platformdirs.user_log_dir(APP_DIRNAME, appauthor=False))


def examples_dir() -> Path:
    """Exemples d'actions/gestes livres avec le paquet."""
    return Path(__file__).resolve().parent / "examples"
