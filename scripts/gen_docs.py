#!/usr/bin/env python3
"""Genere le tableau des etapes du README a partir du catalogue ``steps.py``.

    python scripts/gen_docs.py            reecrit le tableau entre les marqueurs
    python scripts/gen_docs.py --check    echoue si le README n'est pas a jour (CI)

Le catalogue est la source unique : ajouter une etape = la declarer dans
``steps.py`` puis relancer ce script (un test verifie que le README est a jour).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from handshortcut.steps import CATEGORIES, STEPS, steps_in_category  # noqa: E402

BEGIN = "<!-- steps:begin (genere par scripts/gen_docs.py, ne pas modifier a la main) -->"
END = "<!-- steps:end -->"
PLATFORM = {"all": "Windows + Linux", "windows": "Windows", "linux": "Linux"}


def render() -> str:
    lines = [f"{len(STEPS)} types d'étapes, regroupés en {len(CATEGORIES)} catégories.", ""]
    for cat in CATEGORIES:
        lines += [f"**{cat.label}** : {cat.description}", ""]
        lines += ["| Type | Rôle | Champs | Plateformes |", "|---|---|---|---|"]
        for spec in steps_in_category(cat.key):
            fields = ", ".join(f"`{k}`" for k in spec.keys) or "_aucun_"
            desc = spec.description.replace("|", "\\|")
            lines.append(f"| `{spec.type}` | {desc} | {fields} | {PLATFORM[spec.platforms]} |")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def apply(text: str) -> str:
    if BEGIN not in text or END not in text:
        raise SystemExit("Marqueurs introuvables dans README.md")
    head, rest = text.split(BEGIN, 1)
    _, tail = rest.split(END, 1)
    return f"{head}{BEGIN}\n\n{render()}\n{END}{tail}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    readme = ROOT / "README.md"
    current = readme.read_text(encoding="utf-8")
    updated = apply(current)
    if args.check:
        if updated != current:
            print("README.md n'est pas a jour : lance `python scripts/gen_docs.py`", file=sys.stderr)
            return 1
        return 0
    readme.write_text(updated, encoding="utf-8")
    print(f"README.md mis a jour ({len(STEPS)} etapes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
