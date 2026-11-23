"""Validation des actions et des gestes recus par l'API web.

Les fichiers JSON edites a la main restent acceptes tels quels par le
``ConfigStore`` ; cette validation ne protege que les ecritures via l'interface
(et l'import d'un export). Les regles des etapes viennent du catalogue
``steps.py`` : une seule definition par type d'etape.
"""

from __future__ import annotations

import math
from typing import Any

from .steps import (
    HTTP_METHODS,
    MEDIA_ACTIONS,
    MOUSE_BUTTONS,
    PLATFORMS,
    POSITIONS,
    SCROLL_DIRECTIONS,
    STEP_TYPES,
    STEPS,
    Field,
)

__all__ = [
    "FRAME_VEC_LEN",
    "HTTP_METHODS",
    "MEDIA_ACTIONS",
    "MOUSE_BUTTONS",
    "POSITIONS",
    "SCROLL_DIRECTIONS",
    "SEQUENCE_KEYFRAMES",
    "STEP_FIELDS",
    "STEP_TYPES",
    "ValidationError",
    "hold_ms_of",
    "validate_action",
    "validate_gesture",
    "validate_gesture_patch",
    "validate_step",
]

# Taille d'un vecteur de frame : 2 mains x 21 points x 3 coordonnees.
FRAME_VEC_LEN = 2 * 21 * 3
SEQUENCE_KEYFRAMES = 10

GESTURE_TYPES = ("static", "sequence")

# Les anciennes versions comptaient la tenue d'une pose en images ; on la convertit
# en duree avec cette cadence de reference (la camera type tourne a ~30 images/s).
LEGACY_FPS = 30
DEFAULT_HOLD_MS = 270  # = 8 images a 30 images/s (ancien defaut)
MAX_HOLD_MS = 10_000

# type d'etape -> champs acceptes (hors champs communs) ; derive du catalogue
STEP_FIELDS: dict[str, tuple[str, ...]] = {t: spec.keys for t, spec in STEPS.items()}

MAX_NAME_LEN = 100
MAX_STEPS = 100
MAX_WAIT_MS = 3_600_000


class ValidationError(ValueError):
    """Donnee invalide ; le message est affichable a l'utilisateur."""


def hold_ms_of(gesture: dict) -> int:
    """Duree de tenue (ms) d'une pose statique, avec repli sur l'ancien format en images."""
    value = gesture.get("hold_ms")
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
        return int(value)
    frames = gesture.get("hold_frames")
    if isinstance(frames, (int, float)) and not isinstance(frames, bool) and frames >= 0:
        return round(frames * 1000 / LEGACY_FPS)
    return DEFAULT_HOLD_MS


def _as_dict(value: Any, what: str) -> dict:
    if not isinstance(value, dict):
        raise ValidationError(f"{what} : objet JSON attendu.")
    return value


def _clean_name(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{what} : le nom est obligatoire.")
    name = value.strip()
    if len(name) > MAX_NAME_LEN:
        raise ValidationError(f"{what} : nom trop long (max {MAX_NAME_LEN} caracteres).")
    return name


def _number(value: Any, what: str, *, minimum: float, maximum: float) -> float:
    if isinstance(value, str):  # tolere "2" dans un JSON edite a la main
        try:
            value = float(value)
        except ValueError:
            raise ValidationError(f"{what} : nombre attendu.") from None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{what} : nombre attendu.")
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValidationError(f"{what} : valeur entre {minimum:g} et {maximum:g} attendue.")
    return float(value)


def _vector(value: Any, what: str) -> list[float]:
    if not isinstance(value, list) or len(value) != FRAME_VEC_LEN:
        raise ValidationError(f"{what} : {FRAME_VEC_LEN} valeurs attendues.")
    out = []
    for v in value:
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise ValidationError(f"{what} : valeurs numeriques attendues.")
        out.append(float(v))
    return out


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip()) or value == []


# --------------------------------------------------------------------------
# Etapes
# --------------------------------------------------------------------------


def _clean_field(spec: Field, value: Any, label: str) -> Any:
    """Convertit et controle la valeur d'un champ selon son type."""
    what = f"{label} : {spec.label.lower()}"
    kind = spec.kind
    if kind in ("number", "monitor"):
        low = spec.minimum if spec.minimum is not None else -math.inf
        high = spec.maximum if spec.maximum is not None else math.inf
        return int(_number(value, what, minimum=low, maximum=high))
    if kind == "select":
        text = str(value)
        if spec.key == "method":
            text = text.upper()
        if text not in spec.options:
            raise ValidationError(f"{what} : valeur inconnue ({value!r}).")
        return text
    if kind == "list":
        if isinstance(value, str):
            value = [part.strip() for part in value.split(",") if part.strip()]
        if not isinstance(value, list) or not all(isinstance(a, (str, int, float)) for a in value):
            raise ValidationError(f"{what} : liste attendue.")
        return [str(a) for a in value]
    if kind == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in ("true", "false", "1", "0"):
            return value.lower() in ("true", "1")
        raise ValidationError(f"{what} : vrai ou faux attendu.")
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise ValidationError(f"{what} : texte attendu.")
    return str(value)


def validate_step(step: Any, index: int) -> dict:
    label = f"Etape {index + 1}"
    step = _as_dict(step, label)
    step_type = step.get("type")
    spec = STEPS.get(step_type)
    if spec is None:
        raise ValidationError(f"{label} : type d'etape inconnu ({step_type!r}).")

    clean: dict[str, Any] = {"type": step_type}
    for field in spec.fields:
        value = step.get(field.key)
        if _is_blank(value):
            if field.default is not None and field.kind not in ("bool",):
                clean[field.key] = field.default
            continue
        clean[field.key] = _clean_field(field, value, f"{label} ({step_type})")

    missing = [k for k in spec.required if _is_blank(clean.get(k))]
    if missing or (spec.any_of and not any(not _is_blank(clean.get(k)) for k in spec.any_of)):
        raise ValidationError(f"{label} ({step_type}) : champ obligatoire manquant.")

    if step_type == "http_request" and not str(clean["url"]).lower().startswith(("http://", "https://")):
        raise ValidationError(f"{label} : l'URL doit commencer par http:// ou https://.")
    if step_type == "websocket_send" and not str(clean["url"]).lower().startswith(("ws://", "wss://")):
        raise ValidationError(f"{label} : l'URL doit commencer par ws:// ou wss://.")

    # champs communs
    if step.get("wait_ms") not in (None, "", 0):
        clean["wait_ms"] = int(
            _number(step["wait_ms"], f"{label} : attente", minimum=0, maximum=MAX_WAIT_MS)
        )
    only_on = step.get("only_on")
    if only_on not in (None, "", "all"):
        if only_on not in PLATFORMS:
            raise ValidationError(f"{label} : plateforme inconnue ({only_on!r}).")
        clean["only_on"] = only_on
    if step.get("enabled") is False:
        clean["enabled"] = False
    return clean


def validate_action(data: Any) -> dict:
    data = _as_dict(data, "Action")
    steps = data.get("steps", [])
    if not isinstance(steps, list):
        raise ValidationError("Action : `steps` doit etre une liste.")
    if len(steps) > MAX_STEPS:
        raise ValidationError(f"Action : {MAX_STEPS} etapes maximum.")
    action = {
        "id": data.get("id") or None,
        "name": _clean_name(data.get("name"), "Action"),
        "steps": [validate_step(s, i) for i, s in enumerate(steps)],
    }
    if action["id"] is not None and not isinstance(action["id"], str):
        raise ValidationError("Action : identifiant invalide.")
    return action


# --------------------------------------------------------------------------
# Gestes
# --------------------------------------------------------------------------


def _validate_common(data: dict, clean: dict) -> None:
    if "threshold" in data:
        clean["threshold"] = _number(data["threshold"], "Seuil", minimum=0.01, maximum=2.0)
    if data.get("hold_ms") is not None:
        clean["hold_ms"] = int(
            _number(data["hold_ms"], "Duree de tenue (ms)", minimum=0, maximum=MAX_HOLD_MS)
        )
    elif data.get("hold_frames") is not None:  # ancien format : converti en duree
        frames = _number(data["hold_frames"], "Images de tenue", minimum=0, maximum=300)
        clean["hold_ms"] = round(frames * 1000 / LEGACY_FPS)
    if "cooldown_seconds" in data:
        clean["cooldown_seconds"] = _number(
            data["cooldown_seconds"], "Cooldown", minimum=0, maximum=86400
        )
    if "action_id" in data:
        action_id = data["action_id"]
        if action_id is not None and not isinstance(action_id, str):
            raise ValidationError("Geste : identifiant d'action invalide.")
        clean["action_id"] = action_id or None


def _validate_recording(data: dict, clean: dict, gesture_type: str) -> None:
    if gesture_type == "static":
        clean["template"] = _vector(data.get("template"), "Geste statique : modele")
    else:
        frames = data.get("keyframes")
        if not isinstance(frames, list) or not 2 <= len(frames) <= 64:
            raise ValidationError("Geste sequence : images-cles invalides.")
        clean["keyframes"] = [_vector(f, "Geste sequence : image-cle") for f in frames]
        if data.get("duration") is not None:
            clean["duration"] = _number(data["duration"], "Duree", minimum=0.1, maximum=60)


def validate_gesture(data: Any) -> dict:
    data = _as_dict(data, "Geste")
    gesture_type = data.get("type")
    if gesture_type not in GESTURE_TYPES:
        raise ValidationError("Geste : type invalide (static ou sequence).")

    clean: dict[str, Any] = {
        "id": data.get("id") or None,
        "name": _clean_name(data.get("name"), "Geste"),
        "type": gesture_type,
    }
    _validate_common(data, clean)
    _validate_recording(data, clean, gesture_type)
    return clean


def validate_gesture_patch(data: Any) -> dict:
    """Mise a jour partielle : reglages, nom, action liee et, optionnellement,
    un nouvel enregistrement (``type`` + ``template`` ou ``keyframes``)."""
    data = _as_dict(data, "Geste")
    clean: dict[str, Any] = {}
    if "name" in data:
        clean["name"] = _clean_name(data["name"], "Geste")
    _validate_common(data, clean)
    if "template" in data or "keyframes" in data:
        gesture_type = data.get("type")
        if gesture_type not in GESTURE_TYPES:
            raise ValidationError("Geste : type invalide (static ou sequence).")
        clean["type"] = gesture_type
        _validate_recording(data, clean, gesture_type)
    return clean
