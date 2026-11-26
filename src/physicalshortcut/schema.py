"""Validation des actions et des gestes recus par l'API web.

Les fichiers JSON edites a la main restent acceptes tels quels par le
``ConfigStore`` ; cette validation ne protege que les ecritures via l'interface
(et l'import d'un export). Les regles des etapes viennent du catalogue
``steps.py`` : une seule definition par type d'etape.
"""

from __future__ import annotations

import math
import re
from typing import Any

from . import system_metrics
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
    ports_of,
)

__all__ = [
    "FRAME_VEC_LEN",
    "GESTURE_TYPES",
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

GESTURE_TYPES = ("static", "sequence", "pose", "count", "draw", "sound", "voice", "fingerprint", "device", "sensor")
SOUND_KINDS = ("clap", "double_clap", "triple_clap", "any_clap", "loud", "silence")
VOICE_MATCHES = ("contains", "exact", "fuzzy")
FINGER_RESULTS = ("match", "no_match", "any")
DEVICE_EVENTS = (
    "usb_plugged", "usb_unplugged", "bluetooth_connected", "bluetooth_disconnected",
    "power_plugged", "power_unplugged", "lid_closed", "lid_opened", "wifi_connected", "wifi_disconnected",
)
SENSOR_EDGES = ("rising", "level")
PHYSICAL_TYPES = ("sound", "voice", "fingerprint", "device", "sensor")
RECORDED_TYPES = ("static", "sequence")
HANDS_VALUES = (1, 2, "any")
DRAW_CHARSETS = ("digits", "shapes", "all")
DRAW_RECOGNIZERS = ("local", "ai", "auto")
DRAW_PENS = ("index", "pinch", "any")

# Les anciennes versions comptaient la tenue d'une pose en images ; on la convertit
# en duree avec cette cadence de reference (la camera type tourne a ~30 images/s).
LEGACY_FPS = 30
DEFAULT_HOLD_MS = 270  # = 8 images a 30 images/s (ancien defaut)
MAX_HOLD_MS = 10_000

# type d'etape -> champs acceptes (hors champs communs) ; derive du catalogue
STEP_FIELDS: dict[str, tuple[str, ...]] = {t: spec.keys for t, spec in STEPS.items()}

MAX_NAME_LEN = 100
MAX_STEPS = 100
MAX_NODES = 100
MAX_EDGES = 400
MAX_WAIT_MS = 3_600_000
NODE_ID = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
NODE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,31}$")
RESERVED_NAMES = {
    "gesture", "trigger", "system", "args", "last", "loop", "env", "now", "result", "true", "false", "null",
    "none", "and", "or", "not", "in", "is", "if", "else", "item",
}
TEMPLATE = "{{"


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
        if isinstance(value, str) and TEMPLATE in value:
            return value  # formule {{ ... }} : evaluee a l'execution
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

    if step_type == "http_request" and TEMPLATE not in clean["url"] and not clean["url"].lower().startswith(("http://", "https://")):
        raise ValidationError(f"{label} : l'URL doit commencer par http:// ou https://.")
    if step_type == "websocket_send" and TEMPLATE not in clean["url"] and not clean["url"].lower().startswith(("ws://", "wss://")):
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
    for key in ("name", "save_as"):
        if step.get(key) not in (None, ""):
            clean[key] = _clean_node_name(step[key], label)
    if step.get("on_error") not in (None, "", "continue"):
        if step["on_error"] not in ("continue", "stop"):
            raise ValidationError(f"{label} : mode d'erreur inconnu ({step['on_error']!r}).")
        clean["on_error"] = step["on_error"]
    if step.get("label") not in (None, ""):
        clean["label"] = str(step["label"]).strip()[:60]
    return clean


def _clean_node_name(value: Any, label: str) -> str:
    name = str(value).strip()
    if not NODE_NAME.match(name):
        raise ValidationError(f"{label} : nom invalide « {name} » (lettres, chiffres et _, sans espace, 32 max).")
    if name.lower() in RESERVED_NAMES:
        raise ValidationError(f"{label} : le nom « {name} » est reserve.")
    return name


def validate_node(node: Any, index: int) -> dict:
    """Noeud de graphe : une etape + son identifiant et sa position dans l'editeur."""
    node = _as_dict(node, f"Noeud {index + 1}")
    clean = validate_step(node, index)
    node_id = node.get("id")
    if not isinstance(node_id, str) or not NODE_ID.match(node_id):
        raise ValidationError(f"Noeud {index + 1} : identifiant invalide.")
    clean["id"] = node_id
    for axis in ("x", "y"):
        if node.get(axis) is not None:
            clean[axis] = int(_number(node[axis], f"Noeud {index + 1} : position", minimum=-50000, maximum=50000))
    return clean


def validate_graph(data: dict) -> tuple[list[dict], list[dict]]:
    nodes_raw, edges_raw = data.get("nodes", []), data.get("edges", [])
    if not isinstance(nodes_raw, list) or not isinstance(edges_raw, list):
        raise ValidationError("Workflow : `nodes` et `edges` doivent etre des listes.")
    if len(nodes_raw) > MAX_NODES:
        raise ValidationError(f"Workflow : {MAX_NODES} noeuds maximum.")
    if len(edges_raw) > MAX_EDGES:
        raise ValidationError(f"Workflow : {MAX_EDGES} liaisons maximum.")
    nodes = [validate_node(n, i) for i, n in enumerate(nodes_raw)]
    by_id: dict[str, dict] = {}
    names: set[str] = set()
    for node in nodes:
        if node["id"] in by_id:
            raise ValidationError(f"Workflow : identifiant de noeud en double ({node['id']}).")
        by_id[node["id"]] = node
        name = node.get("name")
        if name:
            if name in names:
                raise ValidationError(f"Workflow : le nom « {name} » est utilise par deux noeuds.")
            names.add(name)
    edges: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for i, raw in enumerate(edges_raw):
        raw = _as_dict(raw, f"Liaison {i + 1}")
        src, dst, port = raw.get("from"), raw.get("to"), raw.get("port") or "out"
        if src not in by_id or dst not in by_id:
            raise ValidationError(f"Liaison {i + 1} : noeud introuvable.")
        if src == dst:
            raise ValidationError(f"Liaison {i + 1} : un noeud ne peut pas etre relie a lui-meme.")
        if port not in ports_of(by_id[src]["type"]):
            raise ValidationError(f"Liaison {i + 1} : le noeud « {by_id[src]['type']} » n'a pas de port « {port} ».")
        if (src, port, dst) not in seen:
            seen.add((src, port, dst))
            edges.append({"from": src, "port": port, "to": dst})
    return nodes, edges


def validate_action(data: Any) -> dict:
    """Valide un workflow : graphe (``nodes`` / ``edges``) ou ancienne liste d'etapes (``steps``)."""
    data = _as_dict(data, "Action")
    action: dict[str, Any] = {"id": data.get("id") or None, "name": _clean_name(data.get("name"), "Action")}
    if data.get("description"):
        action["description"] = str(data["description"]).strip()[:300]
    if "nodes" in data:
        action["nodes"], action["edges"] = validate_graph(data)
    else:
        steps = data.get("steps", [])
        if not isinstance(steps, list):
            raise ValidationError("Action : `steps` doit etre une liste.")
        if len(steps) > MAX_STEPS:
            raise ValidationError(f"Action : {MAX_STEPS} etapes maximum.")
        action["steps"] = [validate_step(s, i) for i, s in enumerate(steps)]
    if action["id"] is not None and not isinstance(action["id"], str):
        raise ValidationError("Action : identifiant invalide.")
    return action


# --------------------------------------------------------------------------
# Gestes
# --------------------------------------------------------------------------


def _validate_conditions(data: dict, clean: dict) -> None:
    if "conditions" in data:
        raw = data["conditions"] or []
        if not isinstance(raw, list) or len(raw) > system_metrics.MAX_CONDITIONS:
            raise ValidationError(f"Conditions : liste de {system_metrics.MAX_CONDITIONS} maximum attendue.")
        out = []
        for i, item in enumerate(raw):
            item = _as_dict(item, f"Condition {i + 1}")
            metric = system_metrics.METRIC_BY_KEY.get(item.get("metric"))
            if metric is None:
                raise ValidationError(f"Condition {i + 1} : mesure inconnue ({item.get('metric')!r}).")
            op = item.get("op", "==" if metric.kind == "bool" else ">")
            if op not in system_metrics.OPERATORS:
                raise ValidationError(f"Condition {i + 1} : operateur inconnu ({op!r}).")
            cond: dict[str, Any] = {"metric": metric.key, "op": op}
            if metric.kind == "bool":
                value = item.get("value", True)
                cond["value"] = value if isinstance(value, bool) else str(value).lower() in ("1", "true", "oui", "yes")
            else:
                cond["value"] = _number(item.get("value", 0), f"Condition {i + 1} : valeur", minimum=-1e9, maximum=1e9)
            if metric.arg_label:
                arg = str(item.get("arg") or "").strip()
                if not arg:
                    raise ValidationError(f"Condition {i + 1} : {metric.arg_label.lower()} obligatoire.")
                cond["arg"] = arg[:300]
            if item.get("on_unknown") == "pass":
                cond["on_unknown"] = "pass"
            out.append(cond)
        clean["conditions"] = out
    if "conditions_mode" in data:
        if data["conditions_mode"] not in system_metrics.CONDITION_MODES:
            raise ValidationError("Conditions : mode invalide (all ou any).")
        clean["conditions_mode"] = data["conditions_mode"]


def _choice(data: dict, key: str, allowed: tuple, label: str, clean: dict) -> None:
    if key in data and data[key] is not None:
        if data[key] not in allowed:
            raise ValidationError(f"Geste : {label} invalide ({data[key]!r}).")
        clean[key] = data[key]


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
    _validate_conditions(data, clean)


def _validate_pattern(value: Any, what: str) -> list[int | None]:
    if not isinstance(value, list) or len(value) != 5 or not all(v in (0, 1, None, True, False) for v in value):
        raise ValidationError(f"{what} : 5 valeurs (pouce, index, majeur, annulaire, auriculaire) 0, 1 ou vide attendues.")
    return [None if v is None else int(v) for v in value]


def _validate_kind_options(data: dict, clean: dict, gesture_type: str) -> None:
    """Reglages propres a chaque type de geste (mains, doigts, dessin)."""
    if gesture_type in ("static", "sequence"):
        _choice(data, "hands", (1, 2), "nombre de mains", clean)
    elif gesture_type == "pose":
        _choice(data, "hands", (1, 2), "nombre de mains", clean)
        if "fingers" in data or "fingers_second" in data or "template" not in data:
            clean["fingers"] = _validate_pattern(data.get("fingers"), "Pose : doigts")
        if data.get("fingers_second") is not None:
            clean["fingers_second"] = _validate_pattern(data["fingers_second"], "Pose : doigts de la seconde main")
    elif gesture_type == "count":
        _choice(data, "hands", HANDS_VALUES, "nombre de mains", clean)
        low = int(_number(data.get("min_value", 1), "Nombre minimum", minimum=0, maximum=10))
        high = int(_number(data.get("max_value", 10), "Nombre maximum", minimum=0, maximum=10))
        if low > high:
            raise ValidationError("Geste : le nombre minimum depasse le maximum.")
        clean["min_value"], clean["max_value"] = low, high
    elif gesture_type == "draw":
        _choice(data, "charset", DRAW_CHARSETS, "jeu de symboles", clean)
        _choice(data, "recognizer", DRAW_RECOGNIZERS, "reconnaissance", clean)
        _choice(data, "pen", DRAW_PENS, "mode du stylo", clean)
        if data.get("labels") is not None:
            labels = data["labels"]
            if not isinstance(labels, list) or len(labels) > 60 or not all(isinstance(x, str) and 0 < len(x) <= 30 for x in labels):
                raise ValidationError("Geste : liste de symboles invalide.")
            clean["labels"] = labels
        if data.get("min_confidence") is not None:
            clean["min_confidence"] = _number(data["min_confidence"], "Confiance minimale", minimum=0.3, maximum=0.99)
        if data.get("idle_ms") is not None:
            clean["idle_ms"] = int(_number(data["idle_ms"], "Pause de fin de dessin (ms)", minimum=300, maximum=5000))


def _validate_physical(data: dict, clean: dict, gesture_type: str) -> None:
    """Declencheurs issus de capteurs : son, voix, empreinte, peripherique, capteur a seuil."""
    if gesture_type == "sound":
        clean["sound"] = data.get("sound") if data.get("sound") in SOUND_KINDS else "double_clap"
        if data.get("sensitivity") is not None:
            clean["sensitivity"] = _number(data["sensitivity"], "Sensibilite", minimum=0.05, maximum=1.0)
        if data.get("level_db") is not None:
            clean["level_db"] = _number(data["level_db"], "Niveau (dB)", minimum=-90, maximum=0)
    elif gesture_type == "voice":
        phrases = data.get("phrases")
        if not isinstance(phrases, list) or not 1 <= len(phrases) <= 20:
            raise ValidationError("Voix : 1 a 20 phrases attendues.")
        cleaned = [p.strip() for p in phrases if isinstance(p, str) and p.strip()]
        if not cleaned or any(len(p) > 80 for p in cleaned):
            raise ValidationError("Voix : phrases vides ou trop longues (80 caracteres max).")
        clean["phrases"] = cleaned
        _choice(data, "match", VOICE_MATCHES, "mode de comparaison", clean)
    elif gesture_type == "fingerprint":
        _choice(data, "result", FINGER_RESULTS, "resultat", clean)
        if data.get("finger") is not None:
            clean["finger"] = str(data["finger"]).strip()[:40]
    elif gesture_type == "device":
        if data.get("event") not in DEVICE_EVENTS:
            raise ValidationError("Peripherique : evenement invalide.")
        clean["event"] = data["event"]
        if data.get("match") is not None:
            clean["match"] = str(data["match"]).strip()[:80]
    elif gesture_type == "sensor":
        metric = data.get("metric")
        if metric not in system_metrics.METRIC_BY_KEY:
            raise ValidationError("Capteur : mesure inconnue.")
        spec = system_metrics.METRIC_BY_KEY[metric]
        clean["metric"] = metric
        if spec.arg_label:
            arg = str(data.get("arg") or "").strip()
            if not arg:
                raise ValidationError(f"Capteur : {spec.arg_label} requis.")
            clean["arg"] = arg[:200]
        op = data.get("op", ">" if spec.kind == "number" else "==")
        if op not in system_metrics.OPERATORS:
            raise ValidationError("Capteur : operateur invalide.")
        clean["op"] = op
        if spec.kind == "bool":
            clean["value"] = bool(data.get("value", True))
        else:
            clean["value"] = _number(data.get("value", 0), "Valeur", minimum=-1e9, maximum=1e9)
        _choice(data, "edge", SENSOR_EDGES, "declenchement", clean)


def _validate_recording(data: dict, clean: dict, gesture_type: str) -> None:
    if gesture_type == "static":
        clean["template"] = _vector(data.get("template"), "Geste statique : modele")
    elif gesture_type == "sequence":
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
        raise ValidationError(f"Geste : type invalide ({', '.join(GESTURE_TYPES)}).")

    clean: dict[str, Any] = {
        "id": data.get("id") or None,
        "name": _clean_name(data.get("name"), "Geste"),
        "type": gesture_type,
    }
    _validate_common(data, clean)
    _validate_kind_options(data, clean, gesture_type)
    _validate_physical(data, clean, gesture_type)
    _validate_recording(data, clean, gesture_type)
    return clean


def validate_gesture_patch(data: Any) -> dict:
    """Mise a jour partielle : reglages, nom, action liee, conditions et, optionnellement,
    un nouvel enregistrement (``type`` + ``template`` ou ``keyframes``)."""
    data = _as_dict(data, "Geste")
    clean: dict[str, Any] = {}
    if "name" in data:
        clean["name"] = _clean_name(data["name"], "Geste")
    _validate_common(data, clean)
    gesture_type = data.get("type")
    if gesture_type is not None and gesture_type not in GESTURE_TYPES:
        raise ValidationError(f"Geste : type invalide ({', '.join(GESTURE_TYPES)}).")
    if gesture_type is not None:
        clean["type"] = gesture_type
        _validate_kind_options(data, clean, gesture_type)
        _validate_physical(data, clean, gesture_type)
    if "template" in data or "keyframes" in data:
        if gesture_type not in RECORDED_TYPES:
            raise ValidationError("Geste : type invalide (static ou sequence) pour un enregistrement.")
        _validate_recording(data, clean, gesture_type)
    return clean
