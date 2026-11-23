#!/usr/bin/env python3
"""Extrait les notes d'une version depuis CHANGELOG.md (utilise par la CI).

    python scripts/release_notes.py 1.0.0 > notes.md
    python scripts/release_notes.py --check-tag v1.0.0     verifie tag == version de pyproject.toml
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parent.parent


def project_version() -> str:
    with open(ROOT / "pyproject.toml", "rb") as f:
        return tomllib.load(f)["project"]["version"]


def notes_for(version: str) -> str:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(rf"^## \[?{re.escape(version)}\]?[^\n]*\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    if not match:
        raise SystemExit(f"Version {version} absente de CHANGELOG.md")
    return match.group(1).strip() + "\n"


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "--check-tag":
        tag = argv[1].removeprefix("refs/tags/")
        expected = f"v{project_version()}"
        if tag != expected:
            print(f"Le tag {tag} ne correspond pas a pyproject.toml ({expected}).", file=sys.stderr)
            return 1
        return 0
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    # octets UTF-8 : la console Windows (cp1252) ne sait pas encoder tous les caracteres
    sys.stdout.buffer.write(notes_for(argv[0].removeprefix("v")).encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
