"""Export / import de la configuration (gestes + actions) dans un seul fichier JSON.

Les gestes sont enregistres sous forme de points de la main normalises (independants
de la camera, de la position et de la taille) : un export fait sous Linux fonctionne
tel quel sous Windows, et inversement. Les chemins d'applications des actions peuvent
se corriger apres import, ou s'ecrire avec ``~``, ``%VAR%`` et le champ « Plateforme ».
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from . import __version__
from .config_store import new_id
from .schema import (
    ValidationError,
    validate_action,
    validate_gesture,
)

BUNDLE_FORMAT = "handshortcut-bundle"
BUNDLE_VERSION = 1


def export_bundle(store) -> dict:
    return {
        "format": BUNDLE_FORMAT,
        "bundle_version": BUNDLE_VERSION,
        "app_version": __version__,
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "gestures": store.get_gestures(),
        "actions": store.get_actions(),
    }


def parse_bundle(data: Any) -> tuple[list[dict], list[dict]]:
    """Valide un export ; leve ``ValidationError`` au moindre element invalide."""
    if not isinstance(data, dict) or data.get("format") != BUNDLE_FORMAT:
        raise ValidationError("Fichier d'export HandShortCut invalide.")
    gestures, actions = data.get("gestures", []), data.get("actions", [])
    if not isinstance(gestures, list) or not isinstance(actions, list):
        raise ValidationError("Export invalide : `gestures` et `actions` doivent etre des listes.")
    return (
        [validate_gesture(g) for g in gestures],
        [validate_action(a) for a in actions],
    )


def import_bundle(store, data: Any, *, replace: bool = False) -> dict:
    """Importe un export. ``replace`` efface d'abord la configuration actuelle ;
    sinon les elements de meme identifiant sont mis a jour et les autres ajoutes."""
    gestures, actions = parse_bundle(data)
    if replace:
        for item in (*gestures, *actions):
            item["id"] = item.get("id") or new_id()
        store.replace_all(gestures, actions)
    else:
        for action in actions:
            store.save_action(action)
        for gesture in gestures:
            store.save_gesture(gesture)
    return {"gestures": len(gestures), "actions": len(actions), "replaced": replace}


def read_bundle_file(path: str | Path) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_bundle_file(store, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        json.dump(export_bundle(store), f, indent=2, ensure_ascii=False)
    return target
