"""Bibliotheque de modeles : workflows et gestes prets a installer.

Chaque modele est un dictionnaire serialisable :

* ``action``  : un workflow complet (``nodes`` + ``edges``), valide comme n'importe quelle action ;
* ``gestures``: des gestes proposes pour le declencher (pose, nombre de doigts, dessin, deux mains...).
  Les gestes enregistres a la camera (statique / sequence) ne peuvent pas etre fournis d'avance :
  les modeles utilisent donc les types qui se decrivent sans camera (``pose``, ``count``, ``draw``).

``install`` cree l'action puis les gestes lies a cette action.
"""

from __future__ import annotations

import copy
from typing import Any

from .schema import validate_action, validate_gesture


def chain(*steps: dict) -> dict:
    """Enchaine des etapes : ``nodes`` numerotes et ``edges`` du port ``out``."""
    nodes = []
    for i, step in enumerate(steps, 1):
        nodes.append({"id": f"n{i}", **step})
    edges = [{"from": f"n{i}", "port": "out", "to": f"n{i + 1}"} for i in range(1, len(nodes))]
    return {"nodes": nodes, "edges": edges}


def graph(nodes: list[dict], edges: list[tuple]) -> dict:
    """``edges`` : (source, destination) ou (source, port, destination)."""
    out = []
    for edge in edges:
        src, port, dst = edge if len(edge) == 3 else (edge[0], "out", edge[1])
        out.append({"from": src, "port": port, "to": dst})
    return {"nodes": nodes, "edges": out}


def _pose(name: str, fingers: list, **extra: Any) -> dict:
    return {"name": name, "type": "pose", "fingers": fingers, "hold_ms": 400, "cooldown_seconds": 2, **extra}


def _count(name: str, low: int, high: int, **extra: Any) -> dict:
    return {"name": name, "type": "count", "min_value": low, "max_value": high, "hold_ms": 700, "cooldown_seconds": 2, **extra}


def _draw(name: str, labels: list[str], **extra: Any) -> dict:
    return {"name": name, "type": "draw", "charset": "all", "labels": labels, "recognizer": "local", "pen": "index", "cooldown_seconds": 2, **extra}


OPEN = [1, 1, 1, 1, 1]
FIST = [0, 0, 0, 0, 0]
THUMB = [1, 0, 0, 0, 0]
POINT = [0, 1, 0, 0, 0]
PEACE = [0, 1, 1, 0, 0]
ROCK = [0, 1, 0, 0, 1]
PHONE = [1, 0, 0, 0, 1]

LIBRARY: list[dict] = [
    # ---------------------------------------------------------------- systeme / media
    {
        "id": "mute-toggle", "category": "media", "icon": "volume-x", "title": "Couper / rétablir le son",
        "description": "Bascule le son avec la touche muet du clavier.",
        "action": {"name": "Couper le son", **chain({"type": "media_control", "action": "mute"})},
        "gestures": [_pose("Poing fermé → muet", FIST)],
    },
    {
        "id": "play-pause", "category": "media", "icon": "play", "title": "Lecture / pause",
        "description": "Met en pause ou relance la musique ou la vidéo en cours.",
        "action": {"name": "Lecture / pause", **chain({"type": "media_control", "action": "play_pause"})},
        "gestures": [_pose("Main ouverte → lecture/pause", OPEN, hands=2)],
    },
    {
        "id": "next-track", "category": "media", "icon": "skip-forward", "title": "Piste suivante",
        "description": "Passe à la piste suivante.",
        "action": {"name": "Piste suivante", **chain({"type": "media_control", "action": "next"})},
        "gestures": [_pose("Index levé → suivant", POINT)],
    },
    {
        "id": "volume-by-fingers", "category": "media", "icon": "volume-2", "title": "Volume selon les doigts levés",
        "description": "Le nombre de doigts levés règle le volume (1 doigt = 20 %, 5 doigts = 100 %).",
        "action": {
            "name": "Volume = doigts × 20 %",
            **chain({"type": "set_volume", "level": "{{ gesture.value * 20 }}"}),
        },
        "gestures": [_count("Compter les doigts → volume", 1, 5)],
    },
    {
        "id": "volume-draw-digit", "category": "media", "icon": "pencil", "title": "Volume en dessinant un chiffre",
        "description": "Dessinez un chiffre dans l'air (de 0 à 9) : le volume est réglé à ce chiffre × 10 %.",
        "action": {
            "name": "Volume = chiffre dessiné × 10",
            **chain(
                {"type": "set_volume", "level": "{{ gesture.value * 10 }}"},
                {"type": "notify", "title": "Volume", "message": "Volume réglé à {{ gesture.value * 10 }} %"},
            ),
        },
        "gestures": [_draw("Dessiner un chiffre → volume", list("0123456789"), charset="digits")],
    },
    {
        "id": "screenshot-to-folder", "category": "files", "icon": "camera", "title": "Capture d'écran datée",
        "description": "Enregistre une capture dans Images avec la date et l'heure, puis notifie.",
        "action": {
            "name": "Capture d'écran datée",
            **chain(
                {"type": "screenshot", "path": "~/Pictures/capture-{{ now.date }}_{{ now.time | replace(':', '-') }}.png", "name": "capture"},
                {"type": "notify", "title": "Capture enregistrée", "message": "{{ capture }}"},
            ),
        },
        "gestures": [_pose("Rock → capture", ROCK)],
    },
    {
        "id": "show-desktop", "category": "windows", "icon": "monitor", "title": "Afficher le bureau",
        "description": "Réduit toutes les fenêtres pour montrer le bureau.",
        "action": {"name": "Afficher le bureau", **chain({"type": "show_desktop", "mode": "show"})},
        "gestures": [_pose("Deux mains ouvertes → bureau", OPEN, hands=2, fingers_second=OPEN)],
    },
    {
        "id": "lock-screen", "category": "system", "icon": "lock", "title": "Verrouiller la session",
        "description": "Verrouille l'écran (si l'ordinateur ne tourne pas sur batterie faible).",
        "action": {"name": "Verrouiller", **chain({"type": "power_action", "action": "lock"})},
        "gestures": [_pose("Poing + main ouverte → verrouiller", FIST, hands=2, fingers_second=OPEN)],
    },
    {
        "id": "dark-mode", "category": "system", "icon": "moon", "title": "Thème sombre / clair selon l'heure",
        "description": "Après 19 h ou avant 7 h : thème sombre ; sinon thème clair.",
        "action": {
            "name": "Thème selon l'heure",
            **graph(
                [
                    {"id": "n1", "type": "if_value", "condition": "{{ system.hour >= 19 or system.hour < 7 }}", "name": "nuit"},
                    {"id": "n2", "type": "set_theme", "mode": "dark"},
                    {"id": "n3", "type": "set_theme", "mode": "light"},
                ],
                [("n1", "true", "n2"), ("n1", "false", "n3")],
            ),
        },
        "gestures": [_pose("Pouce levé → thème", THUMB)],
    },
    {
        "id": "brightness-by-fingers", "category": "system", "icon": "sun", "title": "Luminosité selon les doigts",
        "description": "1 à 5 doigts : de 20 % à 100 % de luminosité.",
        "action": {"name": "Luminosité = doigts × 20 %", **chain({"type": "change_brightness", "level": "{{ gesture.value * 20 }}"})},
        "gestures": [_count("Compter les doigts (main gauche et droite) → luminosité", 1, 5, hands="any")],
    },
    {
        "id": "notify-when-hot", "category": "system", "icon": "thermometer", "title": "Alerte si le processeur chauffe",
        "description": "Ne s'exécute que si le CPU dépasse 70 % d'utilisation ; sinon dit que tout va bien.",
        "action": {
            "name": "Vérifier le processeur",
            **graph(
                [
                    {"id": "n1", "type": "if_system", "metric": "cpu_percent", "op": ">", "value": 70},
                    {"id": "n2", "type": "notify", "title": "Processeur chargé", "message": "CPU : {{ system.cpu_percent }} %"},
                    {"id": "n3", "type": "notify", "title": "Tout va bien", "message": "CPU : {{ system.cpu_percent }} %"},
                ],
                [("n1", "true", "n2"), ("n1", "false", "n3")],
            ),
        },
        "gestures": [_pose("Victoire → état du CPU", PEACE)],
    },
    # ---------------------------------------------------------------- donnees / workflows
    {
        "id": "copy-file-content", "category": "data", "icon": "files", "title": "Lire un fichier → l'écrire ailleurs",
        "description": "Exemple de liaison : le contenu lu par le premier nœud est passé au second (variable « contenu »).",
        "action": {
            "name": "Copier le contenu d'un fichier",
            **chain(
                {"type": "file_read", "path": "~/Documents/source.txt", "name": "contenu"},
                {"type": "file_write", "path": "~/Documents/copie.txt", "content": "{{ contenu | upper }}"},
                {"type": "notify", "title": "Fichier copié", "message": "{{ contenu | length }} caractères"},
            ),
        },
        "gestures": [_pose("Téléphone → copier", PHONE)],
    },
    {
        "id": "type-clipboard-upper", "category": "data", "icon": "clipboard-list", "title": "Presse-papiers en majuscules",
        "description": "Lit le presse-papiers, le met en majuscules et le copie de nouveau.",
        "action": {
            "name": "Presse-papiers en majuscules",
            **chain(
                {"type": "clipboard_get", "name": "texte"},
                {"type": "clipboard_set", "text": "{{ texte | upper }}"},
            ),
        },
        "gestures": [_pose("Index + auriculaire (deux mains) → majuscules", ROCK, hands=2, fingers_second=ROCK)],
    },
    {
        "id": "fetch-json-notify", "category": "web", "icon": "globe", "title": "Appel d'API → notification",
        "description": "Interroge une API JSON, extrait un champ et l'affiche (à adapter : URL et chemin).",
        "action": {
            "name": "API → notification",
            **chain(
                {"type": "http_request", "method": "GET", "url": "https://api.github.com/repos/yo-le-zz/PhysicalShortCut", "name": "rep"},
                {"type": "parse_json", "source": "{{ rep.body }}", "path": "stargazers_count", "name": "etoiles"},
                {"type": "notify", "title": "Étoiles GitHub", "message": "{{ etoiles }} ★"},
            ),
        },
        "gestures": [_draw("Dessiner une étoile → API", ["etoile"], charset="shapes")],
    },
    {
        "id": "ask-ai-clipboard", "category": "ai", "icon": "sparkles", "title": "Résumer le presse-papiers avec l'IA",
        "description": "Envoie le texte copié à votre IA (Ollama ou compatible OpenAI) et copie la réponse. Configurez l'IA dans Réglages.",
        "action": {
            "name": "Résumer avec l'IA",
            **chain(
                {"type": "clipboard_get", "name": "texte"},
                {"type": "ai_ask", "prompt": "Résume en deux phrases :\n{{ texte }}", "name": "resume", "on_error": "stop"},
                {"type": "clipboard_set", "text": "{{ resume }}"},
                {"type": "notify", "title": "Résumé copié", "message": "{{ resume | truncate(120) }}"},
            ),
        },
        "gestures": [_draw("Dessiner une coche → résumé", ["coche"], charset="shapes")],
    },
    {
        "id": "ai-read-drawing", "category": "ai", "icon": "sparkles", "title": "Dessin libre compris par l'IA",
        "description": "Dessinez n'importe quoi : l'IA de vision (si configurée) dit ce que c'est et vous le notifie.",
        "action": {
            "name": "Que dessinez-vous ?",
            **chain({"type": "notify", "title": "Dessin reconnu", "message": "{{ gesture.value }} ({{ gesture.confidence }})"}),
        },
        "gestures": [_draw("Dessin libre (IA)", [], recognizer="ai", charset="all")],
    },
    {
        "id": "open-app-by-digit", "category": "windows", "icon": "layout-grid", "title": "Ouvrir une application selon le chiffre dessiné",
        "description": "1 = navigateur, 2 = éditeur de texte, 3 = calculatrice (dessinez le chiffre dans l'air).",
        "action": {
            "name": "Ouvrir selon le chiffre",
            **graph(
                [
                    {"id": "n1", "type": "if_value", "condition": "{{ gesture.value == 1 }}"},
                    {"id": "n2", "type": "open_url", "url": "https://duckduckgo.com"},
                    {"id": "n3", "type": "if_value", "condition": "{{ gesture.value == 2 }}"},
                    {"id": "n4", "type": "launch", "path": "notepad", "only_on": "windows"},
                    {"id": "n5", "type": "launch", "path": "gnome-text-editor", "only_on": "linux"},
                    {"id": "n6", "type": "launch", "path": "calc", "only_on": "windows"},
                    {"id": "n7", "type": "launch", "path": "gnome-calculator", "only_on": "linux"},
                ],
                [("n1", "true", "n2"), ("n1", "false", "n3"), ("n3", "true", "n4"), ("n3", "true", "n5"),
                 ("n3", "false", "n6"), ("n3", "false", "n7")],
            ),
        },
        "gestures": [_draw("Chiffre 1, 2 ou 3 → application", ["1", "2", "3"], charset="digits")],
    },
    {
        "id": "uptime-guard", "category": "logic", "icon": "timer", "title": "Action protégée par l'uptime",
        "description": "Exemple de condition : ne notifie que si l'ordinateur est allumé depuis plus de 30 minutes.",
        "action": {"name": "Rappel de pause", **chain({"type": "notify", "title": "Pause", "message": "Allumé depuis {{ system.uptime_minutes | round(0) }} min : levez-vous !"})},
        "gestures": [
            _pose("Pouce levé → rappel de pause", THUMB,
                  conditions=[{"metric": "uptime_minutes", "op": ">=", "value": 30}]),
        ],
    },
    {
        "id": "safe-heavy-task", "category": "logic", "icon": "gauge", "title": "Tâche lourde seulement si le PC est calme",
        "description": "Conditions du geste : CPU < 70 %, température < 50 °C (ignorée si le capteur manque), pas sur batterie.",
        "action": {"name": "Lancer la sauvegarde", **chain({"type": "run_shell", "cmd": "echo sauvegarde", "capture": True, "name": "sortie"}, {"type": "notify", "title": "Sauvegarde", "message": "{{ sortie.stdout }}"})},
        "gestures": [
            _pose("Poing → sauvegarde (PC calme)", FIST,
                  conditions=[
                      {"metric": "cpu_percent", "op": "<", "value": 70},
                      {"metric": "cpu_temp_c", "op": "<", "value": 50, "on_unknown": "pass"},
                      {"metric": "on_battery", "op": "==", "value": False},
                  ]),
        ],
    },
    {
        "id": "repeat-keys", "category": "input", "icon": "repeat", "title": "Défiler une page vers le bas (5 fois)",
        "description": "Envoie cinq fois la touche Page suivante avec une courte pause.",
        "action": {
            "name": "Défiler vers le bas",
            **graph(
                [
                    {"id": "n1", "type": "for_each", "items": "{{ [1, 2, 3, 4, 5] }}", "name": "boucle"},
                    {"id": "n2", "type": "keypress", "keys": "pagedown"},
                    {"id": "n3", "type": "wait", "ms": 150},
                ],
                [("n1", "each", "n2"), ("n2", "n3")],
            ),
        },
        "gestures": [_pose("Index + majeur vers le bas → défiler", PEACE, hands=2, fingers_second=PEACE)],
    },
    # ---------------------------------------------------------------- capteurs physiques
    {
        "id": "clap-play-pause", "category": "media", "icon": "volume-2", "title": "Double claquement → lecture / pause",
        "description": "Tape deux fois dans tes mains : la musique se met en pause ou repart. Demande d'autoriser le micro.",
        "action": {"name": "Lecture / pause (clap)", **chain({"type": "media_control", "action": "play_pause"})},
        "gestures": [{"name": "Double claquement", "type": "sound", "sound": "double_clap", "sensitivity": 0.5, "cooldown_seconds": 2}],
    },
    {
        "id": "voice-open-browser", "category": "web", "icon": "mic", "title": "Commande vocale : ouvrir le navigateur",
        "description": "Dis « ouvre internet » ou « ouvre le navigateur ». Reconnaissance hors ligne (modèle Vosk requis).",
        "action": {"name": "Ouvrir le navigateur (voix)", **chain({"type": "open_url", "url": "https://duckduckgo.com"})},
        "gestures": [{"name": "Voix : ouvre le navigateur", "type": "voice", "phrases": ["ouvre internet", "ouvre le navigateur"], "match": "fuzzy", "cooldown_seconds": 3}],
    },
    {
        "id": "voice-volume-number", "category": "media", "icon": "mic", "title": "Voix : « volume soixante »",
        "description": "Dis « volume » suivi d'un nombre (en chiffres ou en mots français) : le volume est réglé à ce nombre.",
        "action": {"name": "Volume dit à voix haute", **chain({"type": "set_volume", "level": "{{ gesture.value }}"})},
        "gestures": [{"name": "Voix : volume N", "type": "voice", "phrases": ["volume"], "match": "contains", "cooldown_seconds": 2}],
    },
    {
        "id": "usb-notify", "category": "system", "icon": "usb", "title": "Notifier quand un périphérique USB est branché",
        "description": "Affiche le nom du périphérique branché.",
        "action": {"name": "USB branché", **chain({"type": "notify", "title": "USB", "message": "Branché : {{ gesture.device }}"})},
        "gestures": [{"name": "USB branché", "type": "device", "event": "usb_plugged", "cooldown_seconds": 1}],
    },
    {
        "id": "lid-closed-pause", "category": "system", "icon": "laptop", "title": "Capot fermé → mettre la musique en pause",
        "description": "Met en pause dès que tu fermes le capot du portable.",
        "action": {"name": "Pause (capot fermé)", **chain({"type": "media_control", "action": "play_pause"})},
        "gestures": [{"name": "Capot fermé", "type": "device", "event": "lid_closed", "cooldown_seconds": 5}],
    },
    {
        "id": "fingerprint-unlock-note", "category": "system", "icon": "fingerprint", "title": "Empreinte reconnue → notification",
        "description": "Linux (fprintd) : une notification indique quel doigt a été reconnu.",
        "action": {"name": "Empreinte reconnue", **chain({"type": "notify", "title": "Empreinte", "message": "Doigt reconnu : {{ gesture.finger }}"})},
        "gestures": [{"name": "Empreinte reconnue", "type": "fingerprint", "result": "match", "cooldown_seconds": 2}],
    },
    {
        "id": "gas-alert", "category": "system", "icon": "thermometer", "title": "Alerte gaz (capteur externe)",
        "description": "Avec un capteur de gaz sur Arduino/ESP32 (déclaré sous le nom « gaz »), notifie quand la valeur dépasse 400.",
        "action": {"name": "Alerte gaz", **chain({"type": "notify", "title": "Gaz", "message": "Niveau de gaz élevé : {{ gesture.value }}"})},
        "gestures": [{"name": "Gaz élevé", "type": "sensor", "metric": "external", "arg": "gaz", "op": ">", "value": 400, "edge": "rising", "cooldown_seconds": 60}],
    },
    {
        "id": "shake-lock", "category": "system", "icon": "move", "title": "Secouer le portable → verrouiller",
        "description": "Accéléromètre (portables convertibles) : une secousse verrouille la session.",
        "action": {"name": "Verrouiller (secousse)", **chain({"type": "power_action", "action": "lock"})},
        "gestures": [{"name": "Secousse", "type": "sensor", "metric": "accel_motion_g", "op": ">", "value": 0.6, "edge": "rising", "cooldown_seconds": 10}],
    },
    {
        "id": "secure-with-auth", "category": "logic", "icon": "fingerprint", "title": "Action protégée par l'empreinte / Windows Hello",
        "description": "Demande une vérification d'identité avant de mettre l'ordinateur en veille (exemple à adapter).",
        "action": {
            "name": "Éteindre après vérification",
            **graph(
                [
                    {"id": "n1", "type": "require_auth", "timeout": 20},
                    {"id": "n2", "type": "power_action", "action": "sleep"},
                    {"id": "n3", "type": "notify", "title": "Refusé", "message": "Identité non vérifiée."},
                ],
                [("n1", "true", "n2"), ("n1", "false", "n3")],
            ),
        },
        "gestures": [_pose("Rock → action protégée", ROCK)],
    },
]


def _by_id() -> dict[str, dict]:
    return {t["id"]: t for t in LIBRARY}


def categories() -> list[str]:
    return list(dict.fromkeys(t["category"] for t in LIBRARY))


def listing() -> list[dict]:
    """Version allegee pour l'interface (sans le graphe complet)."""
    out = []
    for t in LIBRARY:
        out.append({
            "id": t["id"], "title": t["title"], "description": t["description"], "category": t["category"],
            "icon": t["icon"], "nodes": len(t["action"]["nodes"]),
            "gestures": [{"name": g["name"], "type": g["type"], "hands": g.get("hands", 1)} for g in t["gestures"]],
        })
    return out


def get(template_id: str) -> dict | None:
    return _by_id().get(template_id)


def install(store, template_id: str, *, with_gestures: bool = True) -> dict:
    """Cree l'action du modele (et ses gestes lies). Renvoie ``{"action_id", "gesture_ids"}``."""
    template = get(template_id)
    if template is None:
        raise KeyError(template_id)
    action = validate_action(copy.deepcopy({**template["action"], "id": None}))
    action_id = store.save_action(action)
    gesture_ids = []
    if with_gestures:
        for raw in template["gestures"]:
            gesture = validate_gesture({**copy.deepcopy(raw), "id": None, "action_id": action_id})
            gesture["action_id"] = action_id
            gesture_ids.append(store.save_gesture(gesture))
    return {"action_id": action_id, "gesture_ids": gesture_ids}
