"""PhysicalShortCut : gestes de la main -> actions."""

from importlib import metadata

__author__ = "yolezz"
CREDITS = "Créé par yolezz"

try:
    __version__ = metadata.version("physicalshortcut")  # source unique : pyproject.toml
except metadata.PackageNotFoundError:  # execution depuis un dossier sans installation
    __version__ = "0.0.0+unknown"
