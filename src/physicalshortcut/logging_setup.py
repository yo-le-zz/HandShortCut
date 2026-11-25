"""Configuration des journaux : fichier tournant + console si disponible."""

from __future__ import annotations

import logging
import logging.handlers
import sys

from .paths import log_dir

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup_logging(verbose: bool = False) -> None:
    handlers: list[logging.Handler] = []

    # Sous Windows (pythonw.exe / physicalshortcut-gui.exe) il n'y a pas de console :
    # sys.stderr vaut None, le fichier de journal est alors la seule trace.
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler(sys.stderr))
    try:
        directory = log_dir()
        directory.mkdir(parents=True, exist_ok=True)
        handlers.append(
            logging.handlers.RotatingFileHandler(
                directory / "physicalshortcut.log",
                maxBytes=1_000_000,
                backupCount=3,
                encoding="utf-8",
            )
        )
    except OSError:
        pass

    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format=LOG_FORMAT,
        handlers=handlers,
        force=True,
    )
    for noisy in ("waitress", "werkzeug"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
