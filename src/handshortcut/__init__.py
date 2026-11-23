"""HandShortCut : gestes de la main -> actions."""

from importlib import metadata

try:
    __version__ = metadata.version("handshortcut")  # source unique : pyproject.toml
except metadata.PackageNotFoundError:  # execution depuis un dossier sans installation
    __version__ = "0.0.0+unknown"
