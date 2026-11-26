"""Catalogue des types d'étapes : SOURCE UNIQUE de verite.

Ce module decrit chaque type d'étape (categorie, icone, libelle, description,
champs). Il alimente :

* la validation des ecritures de l'interface (``schema.py``) ;
* l'editeur d'actions de l'interface web (le catalogue est injecte en JSON dans la page) ;
* la table des étapes du README (``scripts/gen_docs.py``) ;
* les tests d'alignement (catalogue <-> exécuteur <-> icones <-> README).

Chaque type est un **noeud** de workflow : il a des ports de sortie (``out``, ``true`` /
``false``, ``each`` / ``done``...) et peut produire une valeur (sa « sortie »), que les
noeuds suivants lisent avec ``{{ nom_du_noeud }}``.

Pour ajouter un type d'étape : le declarer ici, ecrire ``_step_<type>`` dans
``action_executor.py`` puis regenerer la doc (``python scripts/gen_docs.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .system_metrics import METRICS, OPERATORS

# --------------------------------------------------------------------------
# Constantes partagees
# --------------------------------------------------------------------------

POSITIONS = (
    "fullscreen",
    "left_half",
    "right_half",
    "top_half",
    "bottom_half",
    "center",
    "top_left",
    "top_right",
    "bottom_left",
    "bottom_right",
    "left_third",
    "center_third",
    "right_third",
)
MEDIA_ACTIONS = ("play_pause", "next", "prev", "volume_up", "volume_down", "mute")
HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
MOUSE_BUTTONS = ("left", "right", "middle")
SCROLL_DIRECTIONS = ("up", "down", "left", "right")
DESKTOP_MODES = ("show", "hide", "toggle")
DESKTOP_TARGETS = ("next", "prev")
POWER_ACTIONS = ("lock", "sleep", "logout", "restart", "shutdown")
THEME_MODES = ("dark", "light", "toggle")
PLATFORMS = ("all", "windows", "linux")

PLATFORM_LABELS = {"all": "Toutes les plateformes", "windows": "Windows seulement", "linux": "Linux seulement"}

# Ports de sortie des noeuds (``error`` existe sur tous les noeuds, il n'est pas liste dans les specs).
PORT_LABELS = {
    "out": "Suite",
    "true": "Vrai",
    "false": "Faux",
    "each": "Pour chaque",
    "done": "Terminé",
    "error": "Erreur",
    "case1": "Cas 1",
    "case2": "Cas 2",
    "case3": "Cas 3",
    "case4": "Cas 4",
    "case5": "Cas 5",
    "default": "Autre cas",
}
BRANCH_PORTS = ("true", "false", "out")
LOOP_PORTS = ("each", "done")
SWITCH_PORTS = ("case1", "case2", "case3", "case4", "case5", "default")
COMPARISONS = (
    "eq", "ne", "gt", "ge", "lt", "le", "contains", "not_contains", "starts", "ends", "matches", "empty", "not_empty",
)
LOOP_MODES = ("while", "do_while", "until")
INFO_KINDS = ("hostname", "username", "os", "ip", "datetime", "screen", "cursor", "active_window", "volume", "media")
ON_ERROR_MODES = ("continue", "stop")
LOG_LEVELS = ("info", "warning", "error")
AI_PROVIDERS = ()


# Libelles francais des valeurs de listes deroulantes ; cle "<type>.<champ>" ou "<champ>".
OPTION_LABELS: dict[str, dict[str, str]] = {
    "position": {
        "fullscreen": "Plein écran",
        "left_half": "Moitié gauche",
        "right_half": "Moitié droite",
        "top_half": "Moitié haute",
        "bottom_half": "Moitié basse",
        "center": "Centré",
        "top_left": "Quart haut-gauche",
        "top_right": "Quart haut-droit",
        "bottom_left": "Quart bas-gauche",
        "bottom_right": "Quart bas-droit",
        "left_third": "Tiers gauche",
        "center_third": "Tiers central",
        "right_third": "Tiers droit",
    },
    "media_control.action": {
        "play_pause": "Lecture / pause",
        "next": "Piste suivante",
        "prev": "Piste précédente",
        "volume_up": "Volume +",
        "volume_down": "Volume -",
        "mute": "Muet",
    },
    "power_action.action": {
        "lock": "Verrouiller l'écran",
        "sleep": "Mettre en veille",
        "logout": "Fermer la session",
        "restart": "Redémarrer",
        "shutdown": "Éteindre",
    },
    "button": {"left": "Gauche", "right": "Droit", "middle": "Milieu"},
    "direction": {"up": "Haut", "down": "Bas", "left": "Gauche", "right": "Droite"},
    "mode": {"show": "Afficher", "hide": "Masquer", "toggle": "Basculer", "dark": "Sombre", "light": "Clair"},
    "target": {"next": "Suivant", "prev": "Précédent"},
}


_METRIC_KEYS = tuple(m.key for m in METRICS)
OPTION_LABELS["metric"] = {m.key: f"{m.label}{f' ({m.unit})' if m.unit else ''}" for m in METRICS}
OPTION_LABELS["level"] = {"info": "Information", "warning": "Avertissement", "error": "Erreur"}
OPTION_LABELS["cmp"] = {
    "eq": "est égal à", "ne": "est différent de", "gt": "est supérieur à", "ge": "est supérieur ou égal à",
    "lt": "est inférieur à", "le": "est inférieur ou égal à", "contains": "contient", "not_contains": "ne contient pas",
    "starts": "commence par", "ends": "finit par", "matches": "correspond à l'expression", "empty": "est vide",
    "not_empty": "n'est pas vide",
}
OPTION_LABELS["loop_mode"] = {
    "while": "Tant que la condition est vraie", "do_while": "Faire, puis répéter tant que vrai",
    "until": "Répéter jusqu'à ce que la condition soit vraie",
}
OPTION_LABELS["wait_until.metric"] = {"": "(aucune : utiliser la condition)", **OPTION_LABELS["metric"]}
OPTION_LABELS["on_error"] = {"continue": "Continuer", "stop": "Arrêter le workflow"}
OPTION_LABELS["on_unknown"] = {"fail": "Condition non remplie", "pass": "Ignorer la condition"}


def option_labels(step_type: str, key: str) -> dict[str, str]:
    return OPTION_LABELS.get(f"{step_type}.{key}") or OPTION_LABELS.get(key, {})


@dataclass(frozen=True)
class Field:
    """Un parametre d'étape.

    kind : ``text`` | ``textarea`` | ``path`` | ``number`` | ``select`` | ``list`` |
           ``bool`` | ``monitor`` | ``action`` (identifiant d'une autre action).
    """

    key: str
    label: str
    kind: str = "text"
    default: Any = None
    placeholder: str = ""
    options: tuple[str, ...] = ()
    minimum: int | None = None
    maximum: int | None = None
    icon: str = ""
    help: str = ""

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "kind": self.kind,
            "default": self.default,
            "placeholder": self.placeholder,
            "options": list(self.options),
            "min": self.minimum,
            "max": self.maximum,
            "icon": self.icon,
            "help": self.help,
        }


@dataclass(frozen=True)
class StepSpec:
    type: str
    category: str
    label: str
    icon: str
    description: str
    example: str = ""
    fields: tuple[Field, ...] = ()
    # au moins un de ces champs doit etre renseigné
    any_of: tuple[str, ...] = ()
    # champs qui doivent tous etre renseignés
    required: tuple[str, ...] = ()
    platforms: str = "all"  # "all" | "windows" | "linux" : ou l'étape fonctionne
    note: str = ""
    keywords: tuple[str, ...] = field(default_factory=tuple)
    ports: tuple[str, ...] = ("out",)  # ports de sortie (le port ``error`` s'ajoute toujours)
    output: str = ""  # ce que le noeud produit (lisible par les noeuds suivants)
    output_keys: tuple[str, ...] = ()  # sous-champs de la sortie : {{ nom.cle }}
    hidden: bool = False  # absent de la palette et de la doc (ex. noeud de declenchement)

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(f.key for f in self.fields)

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "category": self.category,
            "label": self.label,
            "icon": self.icon,
            "description": self.description,
            "example": self.example,
            "fields": [{**f.to_dict(), "option_labels": option_labels(self.type, f.key)} for f in self.fields],
            "required": list(self.required),
            "any_of": list(self.any_of),
            "platforms": self.platforms,
            "note": self.note,
            "keywords": list(self.keywords),
            "ports": [{"key": k, "label": PORT_LABELS[k]} for k in self.ports],
            "output": self.output,
            "output_keys": list(self.output_keys),
            "hidden": self.hidden,
        }


@dataclass(frozen=True)
class Category:
    key: str
    label: str
    icon: str
    description: str


CATEGORIES: tuple[Category, ...] = (
    Category("windows", "Fenêtres & applications", "app-window", "Lancer, placer et piloter les fenêtres"),
    Category("input", "Clavier & souris", "keyboard", "Simuler des touches, des clics et du texte"),
    Category("media", "Média & audio", "music", "Lecture, volume, sons et voix"),
    Category("web", "Web & réseau", "globe", "Pages web, API et WebSocket"),
    Category("files", "Fichiers", "folder", "Écrire, copier, déplacer, capturer"),
    Category("system", "Système", "cpu", "Commandes, processus, affichage, alimentation"),
    Category("data", "Données & variables", "database", "Variables, extraction, journal : relier les noeuds entre eux"),
    Category("ai", "IA & analyse", "sparkles", "Questions à une IA, analyse des mains"),
    Category("logic", "Logique & contrôle", "git-branch", "Attentes, conditions, boucles et sous-workflows"),
)

_F = Field

# --------------------------------------------------------------------------
# Catalogue
# --------------------------------------------------------------------------

_SPECS: tuple[StepSpec, ...] = (
    # ------------------------------------------------------------ fenêtres
    StepSpec(
        "launch", "windows", "Lancer une application", "rocket",
        "Démarre un programme, une commande du PATH ou une application installée.",
        "spotify, firefox, /usr/bin/code, C:\\Apps\\app.exe",
        (
            _F("path", "Application / commande", "path", placeholder="spotify, firefox, C:\\Apps\\app.exe", icon="terminal"),
            _F("args", "Arguments (séparés par des virgules)", "list", placeholder="--new-window, https://example.com", icon="list"),
            _F("shell_cmd", "Ligne de commande complete (avance)", "text", placeholder="firefox --private-window", icon="code",
               help="Si renseignée, remplace chemin + arguments (exécutee par le shell)."),
        ),
        any_of=("path", "shell_cmd"),
        keywords=("démarrer", "ouvrir", "programme", "app", "start"),
    ),
    StepSpec(
        "open_path", "windows", "Ouvrir un fichier ou un dossier", "folder-open",
        "Ouvre un fichier ou un dossier avec l'application par défaut du système.",
        "~/Documents, C:\\Users\\moi\\notes.txt",
        (_F("path", "Chemin", "path", placeholder="~/Documents ou C:\\Users\\moi\\Documents", icon="folder"),),
        required=("path",),
        keywords=("explorateur", "dossier", "xdg-open", "default"),
    ),
    StepSpec(
        "move_window", "windows", "Placer une fenêtre", "layout-panel-left",
        "Déplace et redimensionne une fenêtre sur un écran (moitie, tiers, quart, plein écran...).",
        "Spotify -> écran 2, moitie gauche",
        (
            _F("title_contains", "Le titre contient", "text", placeholder="Spotify, Firefox", icon="search"),
            _F("monitor", "Écran cible", "monitor", default=1, minimum=1, maximum=64, icon="monitor"),
            _F("position", "Position", "select", default="fullscreen", options=POSITIONS, icon="maximize"),
        ),
        required=("title_contains",),
        keywords=("déplacer", "redimensionner", "écran", "snap", "moitie"),
    ),
    StepSpec(
        "close_window", "windows", "Fermer une fenêtre", "square-x",
        "Demande poliment la fermeture de la fenêtre.",
        "Discord, Slack",
        (_F("title_contains", "Le titre contient", "text", placeholder="Discord", icon="search"),),
        required=("title_contains",),
        keywords=("quitter",),
    ),
    StepSpec(
        "focus_window", "windows", "Mettre au premier plan", "focus",
        "Active la fenêtre et la place devant les autres.",
        "Terminal, VSCode",
        (_F("title_contains", "Le titre contient", "text", placeholder="Firefox", icon="search"),),
        required=("title_contains",),
        keywords=("activer", "focus", "devant"),
    ),
    StepSpec(
        "minimize_window", "windows", "Réduire une fenêtre", "minimize-2",
        "Réduit la fenêtre dans la barre des taches.",
        "Spotify",
        (_F("title_contains", "Le titre contient", "text", placeholder="Spotify", icon="search"),),
        required=("title_contains",),
        keywords=("minimiser", "cacher"),
    ),
    StepSpec(
        "maximize_window", "windows", "Agrandir une fenêtre", "maximize-2",
        "Agrandit la fenêtre au maximum.",
        "Terminal",
        (_F("title_contains", "Le titre contient", "text", placeholder="Terminal", icon="search"),),
        required=("title_contains",),
        keywords=("maximiser", "plein écran"),
    ),
    StepSpec(
        "restore_window", "windows", "Restaurer une fenêtre", "undo-2",
        "Rend à la fenêtre sa taille normale (annule agrandir / réduire).",
        "VSCode",
        (_F("title_contains", "Le titre contient", "text", placeholder="VSCode", icon="search"),),
        required=("title_contains",),
        keywords=("rétablir",),
    ),
    StepSpec(
        "wait_for_window", "windows", "Attendre une fenêtre", "hourglass",
        "Attend qu'une fenêtre apparaisse (utile après un lancement) avant de continuer.",
        "Spotify, 15000 ms",
        (
            _F("title_contains", "Le titre contient", "text", placeholder="Spotify", icon="search"),
            _F("timeout_ms", "Délai maximum (ms)", "number", default=10000, minimum=100, maximum=300000, icon="clock"),
        ),
        required=("title_contains",),
        keywords=("patienter", "apparaître"),
    ),
    StepSpec(
        "show_desktop", "windows", "Afficher le bureau", "monitor-down",
        "Réduit ou restaure toutes les fenêtres pour montrer le bureau.",
        "Afficher / masquer le bureau",
        (_F("mode", "Mode", "select", default="toggle", options=DESKTOP_MODES, icon="eye"),),
        keywords=("bureau", "desktop", "win+d"),
    ),
    StepSpec(
        "switch_desktop", "windows", "Changer de bureau virtuel", "arrow-left-right",
        "Passe au bureau virtuel suivant ou précédent (Linux : ou à un numéro précis).",
        "Bureau suivant",
        (
            _F("target", "Direction", "select", default="next", options=DESKTOP_TARGETS, icon="arrow-left-right"),
            _F("index", "Numéro du bureau (Linux, optionnel)", "number", minimum=1, maximum=64, icon="hash",
               help="Si renseigné, ignore la direction (Linux uniquement)."),
        ),
        keywords=("espace de travail", "workspace", "virtual desktop"),
    ),
    # ------------------------------------------------------------- entrees
    StepSpec(
        "keypress", "input", "Raccourci clavier", "keyboard",
        "Envoie une touche ou une combinaison.",
        "ctrl+shift+m, alt+tab, win+d",
        (_F("keys", "Touches (séparées par +)", "text", placeholder="ctrl+shift+m", icon="keyboard",
            help="Noms pyautogui. Alias acceptés : super, meta, cmd -> win ; control -> ctrl ; esc ; return."),),
        required=("keys",),
        note="Linux : nécessite X11 / XWayland.",
        keywords=("touche", "hotkey", "raccourci"),
    ),
    StepSpec(
        "type_text", "input", "Taper du texte", "type",
        "Tape un texte au clavier dans la fenêtre active (accents et symboles compris).",
        "Bonjour le monde !",
        (
            _F("text", "Texte à taper", "textarea", placeholder="Bonjour le monde !", icon="type"),
            _F("interval_ms", "Délai entre deux touches (ms)", "number", default=0, minimum=0, maximum=1000, icon="clock"),
        ),
        required=("text",),
        note="Linux : nécessite X11 / XWayland.",
        keywords=("ecrire", "saisir"),
    ),
    StepSpec(
        "mouse_move", "input", "Déplacer la souris", "move",
        "Place le curseur à une position de l'écran (en pixels).",
        "x=500, y=300",
        (
            _F("x", "Position X", "number", placeholder="500", minimum=0, maximum=20000, icon="move"),
            _F("y", "Position Y", "number", placeholder="300", minimum=0, maximum=20000, icon="move"),
        ),
        required=("x", "y"),
        note="Linux : nécessite X11 / XWayland.",
        keywords=("curseur", "pointeur"),
    ),
    StepSpec(
        "mouse_click", "input", "Clic de souris", "mouse-pointer-click",
        "Clique (à la position donnee, ou la ou se trouve le curseur).",
        "clic gauche",
        (
            _F("button", "Bouton", "select", default="left", options=MOUSE_BUTTONS, icon="mouse-pointer"),
            _F("x", "Position X (optionnel)", "number", minimum=0, maximum=20000, icon="move"),
            _F("y", "Position Y (optionnel)", "number", minimum=0, maximum=20000, icon="move"),
        ),
        note="Linux : nécessite X11 / XWayland.",
        keywords=("cliquer",),
    ),
    StepSpec(
        "mouse_double_click", "input", "Double-clic", "pointer",
        "Double-clique (à la position donnee, ou la ou se trouve le curseur).",
        "double-clic gauche",
        (
            _F("button", "Bouton", "select", default="left", options=MOUSE_BUTTONS, icon="mouse-pointer"),
            _F("x", "Position X (optionnel)", "number", minimum=0, maximum=20000, icon="move"),
            _F("y", "Position Y (optionnel)", "number", minimum=0, maximum=20000, icon="move"),
        ),
        note="Linux : nécessite X11 / XWayland.",
        keywords=("double clic",),
    ),
    StepSpec(
        "mouse_drag", "input", "Glisser-déposer", "move-diagonal",
        "Maintient le bouton enfoncé de la position actuelle (ou de départ) jusqu'à la destination.",
        "de (100,100) vers (600,400)",
        (
            _F("x", "Destination X", "number", placeholder="600", minimum=0, maximum=20000, icon="move"),
            _F("y", "Destination Y", "number", placeholder="400", minimum=0, maximum=20000, icon="move"),
            _F("from_x", "Départ X (optionnel)", "number", minimum=0, maximum=20000, icon="move"),
            _F("from_y", "Départ Y (optionnel)", "number", minimum=0, maximum=20000, icon="move"),
            _F("button", "Bouton", "select", default="left", options=MOUSE_BUTTONS, icon="mouse-pointer"),
            _F("duration_ms", "Durée du geste (ms)", "number", default=300, minimum=0, maximum=10000, icon="clock"),
        ),
        required=("x", "y"),
        note="Linux : nécessite X11 / XWayland.",
        keywords=("drag", "glisser", "déposer"),
    ),
    StepSpec(
        "mouse_scroll", "input", "Défiler (scroll)", "mouse",
        "Fait défiler la fenêtre active.",
        "vers le bas, 3 crans",
        (
            _F("direction", "Direction", "select", default="up", options=SCROLL_DIRECTIONS, icon="arrow-up"),
            _F("amount", "Quantite (crans)", "number", default=3, minimum=1, maximum=100, icon="hash"),
        ),
        note="Linux : nécessite X11 / XWayland.",
        keywords=("molette", "scroll"),
    ),
    StepSpec(
        "clipboard_set", "input", "Copier dans le presse-papiers", "clipboard-copy",
        "Place un texte dans le presse-papiers.",
        "un lien, une adresse e-mail...",
        (_F("text", "Texte à copier", "textarea", placeholder="Texte dans le presse-papiers", icon="clipboard"),),
        note="Linux : xclip, xsel ou wl-clipboard requis.",
        keywords=("copier",),
    ),
    StepSpec(
        "clipboard_get_and_type", "input", "Coller le presse-papiers (en tapant)", "clipboard-paste",
        "Tape au clavier le contenu actuel du presse-papiers.",
        "colle sans raccourci",
        (),
        note="Linux : nécessite X11 / XWayland.",
        keywords=("coller", "paste"),
    ),
    # --------------------------------------------------------------- media
    StepSpec(
        "media_control", "media", "Contrôle média", "circle-play",
        "Lecture / pause, piste suivante ou précédente, volume, muet.",
        "play_pause, next, mute",
        (_F("action", "Action", "select", default="play_pause", options=MEDIA_ACTIONS, icon="play"),),
        keywords=("musique", "lecture", "spotify", "pause"),
    ),
    StepSpec(
        "set_volume", "media", "Régler le volume", "volume-2",
        "Définit le volume principal (0 à 100 %).",
        "30 %",
        (_F("level", "Niveau (0-100)", "number", default=50, minimum=0, maximum=100, icon="volume-2"),),
        keywords=("son", "audio"),
    ),
    StepSpec(
        "play_sound", "media", "Jouer un son", "audio-lines",
        "Joue un fichier audio (WAV sur Windows ; WAV, OGG, MP3... sur Linux selon les lecteurs installés).",
        "~/Music/ding.wav",
        (_F("path", "Fichier audio", "path", placeholder="~/Music/ding.wav", icon="file"),),
        required=("path",),
        note="Linux : paplay, pw-play, aplay, ffplay ou mpv.",
        keywords=("son", "bip", "alerte"),
    ),
    StepSpec(
        "speak", "media", "Dire un texte (synthèse vocale)", "speech",
        "Lit un texte à voix haute.",
        "Geste reconnu !",
        (_F("text", "Texte à dire", "textarea", placeholder="Geste reconnu !", icon="message-circle"),),
        required=("text",),
        note="Linux : spd-say, espeak-ng ou espeak.",
        keywords=("voix", "tts", "parler"),
    ),
    # ----------------------------------------------------------------- web
    StepSpec(
        "open_url", "web", "Ouvrir une URL", "external-link",
        "Ouvre une adresse dans le navigateur par défaut.",
        "https://github.com",
        (_F("url", "URL", "text", placeholder="https://example.com", icon="link"),),
        required=("url",),
        keywords=("site", "navigateur", "lien"),
    ),
    StepSpec(
        "http_request", "web", "Requête HTTP / API", "send",
        "Envoie une requête HTTP (webhook, domotique, API...) et renvoie la réponse aux noeuds suivants.",
        "POST vers un webhook",
        (
            _F("method", "Méthode", "select", default="GET", options=HTTP_METHODS, icon="send"),
            _F("url", "URL", "text", placeholder="https://api.example.com/webhook", icon="link"),
            _F("body", "Corps (JSON ou texte, optionnel)", "textarea", placeholder='{"key": "value"}', icon="code"),
            _F("headers", "En-têtes (un par ligne, « Nom: valeur »)", "textarea", placeholder="Authorization: Bearer ...", icon="list"),
            _F("timeout_s", "Délai maximum (s)", "number", default=10, minimum=1, maximum=300, icon="timer"),
        ),
        required=("url",),
        output="Réponse : status, ok, body (texte), json (si JSON)",
        output_keys=("status", "ok", "body", "json"),
        keywords=("webhook", "api", "rest", "domotique"),
    ),
    StepSpec(
        "websocket_send", "web", "Envoyer un message WebSocket", "radio",
        "Ouvre une connexion WebSocket, envoie un message puis la referme.",
        "ws://localhost:8080",
        (
            _F("url", "URL WebSocket", "text", placeholder="ws://localhost:8080", icon="radio"),
            _F("message", "Message", "textarea", placeholder="Hello", icon="message-circle"),
        ),
        required=("url", "message"),
        keywords=("ws", "temps réel"),
    ),
    # -------------------------------------------------------------- fichiers
    StepSpec(
        "file_write", "files", "Écrire un fichier", "file-pen",
        "Crée ou remplace un fichier texte.",
        "~/notes.txt",
        (
            _F("path", "Chemin du fichier", "path", placeholder="~/notes.txt", icon="file-text"),
            _F("content", "Contenu", "textarea", placeholder="Texte à écrire...", icon="pencil"),
            _F("append", "Ajouter à la fin au lieu de remplacer", "bool", default=False, icon="plus"),
        ),
        required=("path",),
        keywords=("créer", "sauvegarder", "journal"),
    ),
    StepSpec(
        "file_read", "files", "Lire un fichier", "file-text",
        "Lit un fichier texte et donne son contenu aux noeuds suivants (ex. Lire un fichier -> Écrire un fichier).",
        "~/notes.txt",
        (_F("path", "Chemin du fichier", "path", placeholder="~/notes.txt", icon="file"),),
        required=("path",),
        output="Contenu du fichier (texte)",
        keywords=("ouvrir",),
    ),
    StepSpec(
        "file_delete", "files", "Supprimer un fichier", "file-x",
        "Supprime définitivement un fichier.",
        "/tmp/ancien.txt",
        (_F("path", "Chemin du fichier", "path", placeholder="/tmp/ancien.txt", icon="trash-2"),),
        required=("path",),
        keywords=("effacer", "rm"),
    ),
    StepSpec(
        "file_copy", "files", "Copier un fichier", "copy",
        "Copie un fichier (les métadonnées sont conservées).",
        "~/a.txt -> ~/sauvegarde/a.txt",
        (
            _F("source", "Fichier source", "path", placeholder="~/a.txt", icon="file"),
            _F("destination", "Destination", "path", placeholder="~/sauvegarde/a.txt", icon="copy"),
        ),
        required=("source", "destination"),
        keywords=("dupliquer", "cp"),
    ),
    StepSpec(
        "file_move", "files", "Déplacer un fichier", "folder-output",
        "Déplace ou renomme un fichier ou un dossier.",
        "~/a.txt -> ~/archive/a.txt",
        (
            _F("source", "Source", "path", placeholder="~/a.txt", icon="file"),
            _F("destination", "Destination", "path", placeholder="~/archive/a.txt", icon="move"),
        ),
        required=("source", "destination"),
        keywords=("renommer", "mv"),
    ),
    StepSpec(
        "directory_create", "files", "Créer un dossier", "folder-plus",
        "Crée un dossier (et ses parents si besoin).",
        "~/Projets/nouveau",
        (_F("path", "Chemin du dossier", "path", placeholder="~/Projets/nouveau", icon="folder-plus"),),
        required=("path",),
        keywords=("mkdir", "répertoire"),
    ),
    StepSpec(
        "screenshot", "files", "Capture d'écran", "camera",
        "Enregistre une capture de l'écran dans un fichier PNG.",
        "~/Images/capture.png",
        (_F("path", "Fichier de destination", "path", placeholder="~/Images/capture.png", icon="image"),),
        required=("path",),
        note="Linux : nécessite X11 / XWayland.",
        keywords=("screenshot", "image"),
    ),
    # --------------------------------------------------------------- système
    StepSpec(
        "run_shell", "system", "Commande shell", "terminal",
        "Exécute une commande dans le shell (en arrière-plan, ou en attendant sa fin pour récupérer sa sortie).",
        "notify-send 'Bonjour'",
        (
            _F("cmd", "Commande", "textarea", placeholder="notify-send 'Bonjour'", icon="terminal"),
            _F("capture", "Attendre la fin et récupérer la sortie", "bool", icon="download"),
            _F("timeout_s", "Délai maximum si on attend (s)", "number", default=30, minimum=1, maximum=3600, icon="timer"),
        ),
        required=("cmd",),
        output="Avec « récupérer la sortie » : stdout, stderr, code, ok",
        output_keys=("stdout", "stderr", "code", "ok"),
        keywords=("script", "bash", "powershell", "cmd"),
    ),
    StepSpec(
        "kill_process", "system", "Arrêter un processus", "circle-x",
        "Arrête les processus dont le nom contient le texte donne (jamais PhysicalShortCut lui-même).",
        "discord, chrome",
        (_F("name", "Nom du processus", "text", placeholder="discord", icon="search"),),
        required=("name",),
        keywords=("tuer", "kill", "terminer"),
    ),
    StepSpec(
        "notify", "system", "Notification", "bell",
        "Affiche une notification système.",
        "Geste détecté !",
        (
            _F("title", "Titre", "text", default="PhysicalShortCut", placeholder="PhysicalShortCut", icon="bell"),
            _F("message", "Message", "text", placeholder="Geste détecté !", icon="message-square"),
        ),
        note="Linux : notify-send (libnotify).",
        keywords=("alerte", "toast"),
    ),
    StepSpec(
        "change_brightness", "system", "Régler la luminosité", "sun",
        "Définit la luminosité de l'écran (0 à 100 %).",
        "40 %",
        (_F("level", "Niveau (0-100)", "number", default=50, minimum=0, maximum=100, icon="sun"),),
        note="Linux : brightnessctl ou xbacklight. Windows : écrans internes (portables).",
        keywords=("écran", "eclairage"),
    ),
    StepSpec(
        "change_wallpaper", "system", "Changer le fond d'écran", "image",
        "Applique une image comme fond d'écran.",
        "~/Images/fond.jpg",
        (_F("path", "Chemin de l'image", "path", placeholder="~/Images/fond.jpg", icon="image"),),
        required=("path",),
        note="Linux : GNOME, KDE Plasma, XFCE ou feh.",
        keywords=("arriere-plan", "wallpaper"),
    ),
    StepSpec(
        "set_theme", "system", "Thème clair / sombre", "sun-moon",
        "Bascule le thème du système entre clair et sombre.",
        "basculer",
        (_F("mode", "Mode", "select", default="toggle", options=THEME_MODES, icon="sun-moon"),),
        note="Linux : GNOME ou KDE Plasma.",
        keywords=("dark mode", "mode sombre"),
    ),
    StepSpec(
        "power_action", "system", "Alimentation / session", "power",
        "Verrouille, met en veille, ferme la session, redémarre ou éteint l'ordinateur.",
        "verrouiller l'écran",
        (_F("action", "Action", "select", default="lock", options=POWER_ACTIONS, icon="power"),),
        note="Attention : redémarrer et éteindre sont immédiats.",
        keywords=("verrouiller", "veille", "éteindre", "redémarrer", "deconnexion"),
    ),
    # --------------------------------------------------------------- logique
    StepSpec(
        "wait", "logic", "Pause", "timer",
        "Attend un certain temps avant l'étape suivante.",
        "1500 ms",
        (_F("ms", "Durée (millisecondes)", "number", default=1000, minimum=0, maximum=3_600_000, icon="clock"),),
        keywords=("attendre", "délai", "sleep"),
    ),
    StepSpec(
        "if_window_exists", "logic", "Si une fenêtre existe", "split",
        "Branche « Vrai » si une fenêtre est ouverte, « Faux » sinon (ou exécute un sous-workflow).",
        "Si Spotify est ouvert : pause",
        (
            _F("title_contains", "Le titre contient", "text", placeholder="Firefox", icon="search"),
            _F("action_id", "Alors exécuter le workflow (optionnel)", "action", icon="zap"),
            _F("else_action_id", "Sinon exécuter le workflow (optionnel)", "action", icon="zap"),
        ),
        required=("title_contains",),
        ports=BRANCH_PORTS,
        output="Vrai ou faux",
        keywords=("condition", "si", "if"),
    ),
    StepSpec(
        "if_process_running", "logic", "Si un processus tourne", "activity",
        "Branche « Vrai » si un processus est actif, « Faux » sinon (ou exécute un sous-workflow).",
        "Si discord tourne : notification",
        (
            _F("name", "Nom du processus", "text", placeholder="spotify", icon="search"),
            _F("action_id", "Alors exécuter le workflow (optionnel)", "action", icon="zap"),
            _F("else_action_id", "Sinon exécuter le workflow (optionnel)", "action", icon="zap"),
        ),
        required=("name",),
        ports=BRANCH_PORTS,
        output="Vrai ou faux",
        keywords=("condition", "si", "if"),
    ),
    StepSpec(
        "require_auth", "logic", "Vérifier mon identité", "fingerprint",
        "Demande l'empreinte (Linux : fprintd) ou Windows Hello, puis branche « Vrai » si c'est accepté, « Faux » sinon.",
        "Empreinte avant de verrouiller le coffre",
        (
            _F("timeout", "Délai (secondes)", "number", default=20, minimum=5, maximum=120, icon="clock"),
            _F("action_id", "Si accepté, exécuter le workflow (optionnel)", "action", icon="zap"),
            _F("else_action_id", "Sinon exécuter le workflow (optionnel)", "action", icon="zap"),
        ),
        ports=BRANCH_PORTS,
        output="Vrai ou faux",
        keywords=("empreinte", "fingerprint", "hello", "authentification", "identité", "sécurité"),
    ),
    StepSpec(
        "repeat", "logic", "Répéter une action", "repeat",
        "Exécute un autre workflow plusieurs fois de suite (variable loop.index).",
        "3 fois",
        (
            _F("count", "Nombre de répétitions", "number", default=2, minimum=1, maximum=1000, icon="repeat"),
            _F("action_id", "Workflow à répéter", "action", icon="zap"),
            _F("delay_ms", "Pause entre deux répétitions (ms)", "number", default=0, minimum=0, maximum=600000, icon="clock"),
        ),
        required=("action_id",),
        output="",
        keywords=("boucle", "loop", "fois"),
    ),

    # ---------------------------------------------------- entrees (suite)
    StepSpec(
        "clipboard_get", "input", "Lire le presse-papiers", "clipboard-list",
        "Récupère le texte du presse-papiers et le donne aux noeuds suivants.",
        "copier un lien, puis l'utiliser",
        (),
        output="Texte du presse-papiers",
        note="Linux : xclip, xsel ou wl-clipboard requis.",
        keywords=("copier", "paste", "coller"),
    ),
    # ------------------------------------------------------ données
    StepSpec(
        "set_variable", "data", "Définir une valeur", "variable",
        "Calcule une valeur (texte, nombre, formule) et la range sous le nom du noeud.",
        "{{ gesture.value * 10 }}",
        (
            _F("value", "Valeur ou formule", "textarea", placeholder="{{ gesture.value * 10 }}", icon="variable",
               help="Utilise {{ ... }} pour lire des variables, faire des calculs ou des filtres (| upper, | lines...)."),
            _F("variable", "Nom d'une variable supplémentaire (optionnel)", "text", placeholder="total", icon="tag",
               help="Pour la réutiliser plus loin ou la modifier dans une boucle."),
        ),
        required=("value",),
        output="La valeur calculée",
        keywords=("variable", "calcul", "formule", "set"),
    ),
    StepSpec(
        "log_message", "data", "Écrire dans le journal", "scroll-text",
        "Écrit un message dans le journal et dans l'activité (utile pour vérifier ce que transporte un lien).",
        "Contenu lu : {{ lecture }}",
        (
            _F("message", "Message", "textarea", placeholder="Contenu lu : {{ lecture }}", icon="scroll-text"),
            _F("level", "Niveau", "select", default="info", options=("info", "warning", "error"), icon="flag"),
        ),
        required=("message",),
        output="Le message",
        keywords=("log", "debug", "journal"),
    ),
    StepSpec(
        "parse_json", "data", "Extraire d'un JSON", "braces",
        "Lit un texte JSON (ex. réponse d'une API) et extrait une valeur par son chemin.",
        "reponse.body, chemin items[0].name",
        (
            _F("source", "Source (texte JSON)", "textarea", placeholder="{{ reponse.body }}", icon="braces"),
            _F("path", "Chemin (optionnel)", "text", placeholder="items[0].name", icon="route"),
        ),
        required=("source",),
        output="La valeur trouvée",
        keywords=("json", "api", "extraire"),
    ),
    StepSpec(
        "regex_extract", "data", "Extraire avec une expression", "regex",
        "Cherche un motif (expression régulière) dans un texte et renvoie la correspondance.",
        "un nombre : \\d+",
        (
            _F("source", "Texte", "textarea", placeholder="{{ lecture }}", icon="file-text"),
            _F("pattern", "Expression régulière", "text", placeholder="(\\d+) fois", icon="regex"),
            _F("group", "Groupe à renvoyer", "number", default=0, minimum=0, maximum=20, icon="hash"),
        ),
        required=("source", "pattern"),
        output="Le texte trouvé (vide sinon)",
        keywords=("regex", "motif", "chercher"),
    ),
    # --------------------------------------------------------- IA & analyse
    StepSpec(
        "ai_ask", "ai", "Demander à une IA", "sparkles",
        "Pose une question à une IA (Ollama, OpenAI, LM Studio...) avec, si tu veux, l'image de la caméra.",
        "« Combien de doigts vois-tu ? » + image caméra",
        (
            _F("prompt", "Question", "textarea", placeholder="Combien de doigts levés vois-tu ? Réponds par un nombre.", icon="message-square"),
            _F("with_image", "Joindre l'image de la caméra", "bool", icon="camera"),
            _F("system", "Consigne système (optionnel)", "text", placeholder="Réponds en un mot.", icon="settings"),
            _F("model", "Modèle (optionnel)", "text", placeholder="llava, gpt-4o-mini...", icon="cpu",
               help="Sinon : le modèle des réglages IA."),
            _F("base_url", "URL de l'API (optionnel)", "text", placeholder="http://127.0.0.1:11434/v1", icon="link"),
            _F("timeout_s", "Délai maximum (s)", "number", default=60, minimum=1, maximum=600, icon="timer"),
        ),
        required=("prompt",),
        output="La réponse de l'IA (texte)",
        note="Nécessite une IA configurée (Activité > Réglages IA). Rien n'est envoyé sans configuration.",
        keywords=("ia", "ai", "llm", "gpt", "ollama", "vision", "chatgpt"),
    ),
    StepSpec(
        "hand_info", "ai", "Analyser les mains", "hand",
        "Compte les doigts levés des mains visibles à cet instant.",
        "nombre de doigts = {{ mains.count }}",
        (),
        output="Mains visibles : hands, count (doigts levés au total), fingers",
        output_keys=("hands", "count", "fingers"),
        keywords=("doigts", "compter", "mains", "main"),
    ),
    StepSpec(
        "system_metric", "system", "Lire une mesure système", "gauge",
        "Lit l'uptime, l'usage ou la température du CPU, la RAM, la batterie... et la donne aux noeuds suivants.",
        "température du CPU",
        (
            _F("metric", "Mesure", "select", default="cpu_percent", options=_METRIC_KEYS, icon="gauge"),
            _F("arg", "Argument (processus, fenêtre, chemin)", "text", placeholder="spotify", icon="search",
               help="Seulement pour les mesures « Un processus tourne », « Une fenêtre est ouverte », « Un fichier existe »."),
        ),
        required=("metric",),
        output="La valeur mesurée (nombre ou vrai/faux)",
        keywords=("cpu", "température", "ram", "uptime", "batterie", "charge"),
    ),
    # --------------------------------------------------------------- logique (suite)
    StepSpec(
        "if_value", "logic", "Si (condition sur une valeur)", "split",
        "Branche « Vrai » ou « Faux » selon une formule : comparaison, et/ou, valeurs des noeuds précédents.",
        "gesture.value > 3 and system.cpu_percent < 70",
        (
            _F("condition", "Condition", "text", placeholder="gesture.value > 3", icon="split",
               help="Variables : gesture, system, args, last, et le nom de chaque noeud. Opérateurs : > < == != and or not in."),
            _F("action_id", "Si vrai : exécuter le workflow (optionnel)", "action", icon="zap"),
            _F("else_action_id", "Si faux : exécuter le workflow (optionnel)", "action", icon="zap"),
        ),
        required=("condition",),
        ports=BRANCH_PORTS,
        output="Vrai ou faux",
        keywords=("condition", "si", "if", "comparer", "test"),
    ),
    StepSpec(
        "if_system", "logic", "Si (condition système)", "activity",
        "Branche « Vrai » ou « Faux » selon l'état de l'ordinateur : uptime, CPU, température, RAM, batterie, heure...",
        "température CPU < 50 °C",
        (
            _F("metric", "Mesure", "select", default="cpu_percent", options=_METRIC_KEYS, icon="gauge"),
            _F("arg", "Argument (processus, fenêtre, chemin)", "text", placeholder="spotify", icon="search"),
            _F("op", "Opérateur", "select", default=">", options=OPERATORS, icon="equal"),
            _F("value", "Valeur", "number", default=50, minimum=-1000000, maximum=1000000, icon="hash"),
            _F("on_unknown", "Si la mesure est indisponible", "select", default="fail", options=("fail", "pass"), icon="circle-help"),
            _F("action_id", "Si vrai : exécuter le workflow (optionnel)", "action", icon="zap"),
            _F("else_action_id", "Si faux : exécuter le workflow (optionnel)", "action", icon="zap"),
        ),
        required=("metric",),
        ports=BRANCH_PORTS,
        output="La valeur mesurée",
        keywords=("cpu", "température", "uptime", "ram", "batterie", "condition"),
    ),
    StepSpec(
        "for_each", "logic", "Pour chaque élément", "list-ordered",
        "Répète les noeuds reliés au port « Pour chaque » pour chaque ligne ou élément d'une liste, puis continue sur « Terminé ».",
        "chaque ligne d'un fichier",
        (
            _F("items", "Éléments (liste, texte multi-lignes ou JSON)", "textarea", placeholder="{{ lecture }}", icon="list"),
            _F("item_var", "Nom de la variable de l'élément", "text", default="item", placeholder="item", icon="tag"),
            _F("limit", "Nombre maximum d'éléments", "number", default=100, minimum=1, maximum=1000, icon="hash"),
            _F("action_id", "Workflow à lancer pour chaque élément (optionnel)", "action", icon="zap"),
        ),
        required=("items",),
        ports=LOOP_PORTS,
        output="Nombre d'éléments parcourus",
        keywords=("boucle", "chaque", "liste", "foreach", "loop"),
    ),
    StepSpec(
        "run_action", "logic", "Lancer un workflow", "workflow",
        "Exécute un autre workflow en lui passant des arguments (args.nom) et récupère son résultat.",
        "envoyer(message = {{ lecture }})",
        (
            _F("action_id", "Workflow", "action", icon="zap"),
            _F("args", "Arguments (un par ligne : nom = valeur)", "textarea", placeholder="message = {{ lecture }}", icon="list"),
        ),
        required=("action_id",),
        output="Le résultat du workflow (variable « result », sinon sa dernière sortie)",
        keywords=("sous-workflow", "appeler", "fonction", "arguments"),
    ),
    StepSpec(
        "stop_workflow", "logic", "Arrêter le workflow", "octagon-x",
        "Termine immédiatement le workflow (toutes les branches).",
        "si la température est trop haute",
        (_F("reason", "Raison (journal)", "text", placeholder="CPU trop chaud", icon="info"),),
        ports=(),
        keywords=("stop", "fin", "terminer", "arrêter"),
    ),
    # --------------------------------------------------------------- obtenir (infos)
    StepSpec(
        "get_hostname", "system", "Obtenir le nom de l'ordinateur", "monitor",
        "Donne le hostname (nom réseau) de l'ordinateur aux noeuds suivants.",
        "{{ nom_pc }} dans une notification",
        (),
        output="Le nom de l'ordinateur (texte)",
        keywords=("hostname", "nom", "machine", "pc", "ordinateur"),
    ),
    StepSpec(
        "get_username", "system", "Obtenir l'utilisateur connecté", "user",
        "Donne le nom de la session en cours.",
        "Bonjour {{ utilisateur }}",
        (),
        output="Le nom d'utilisateur (texte)",
        keywords=("utilisateur", "user", "session", "login", "nom"),
    ),
    StepSpec(
        "get_os_info", "system", "Obtenir le système d'exploitation", "server",
        "Système, version, architecture, nom de la machine et dossier personnel.",
        "linux ou windows ?",
        (),
        output="Infos : os, system, release, version, machine, hostname, user, home, python",
        output_keys=("os", "system", "release", "version", "machine", "hostname", "user", "home", "python"),
        keywords=("os", "windows", "linux", "version", "architecture", "système"),
    ),
    StepSpec(
        "get_ip_address", "system", "Obtenir l'adresse IP locale", "network",
        "Adresse IP de l'ordinateur sur le réseau local (aucune requête n'est envoyée).",
        "afficher mon IP",
        (),
        output="L'adresse IP (texte)",
        keywords=("ip", "réseau", "adresse", "network"),
    ),
    StepSpec(
        "get_datetime", "system", "Obtenir la date et l'heure", "calendar-clock",
        "Date, heure, jour de la semaine (1 = lundi) et horodatage, utilisables dans une condition ou un message.",
        "si l'heure est > 22",
        (),
        output="Date : iso, date, time, year, month, day, hour, minute, second, weekday, timestamp",
        output_keys=("iso", "date", "time", "year", "month", "day", "hour", "minute", "second", "weekday", "timestamp"),
        keywords=("date", "heure", "temps", "jour", "horloge", "time"),
    ),
    StepSpec(
        "get_screen_info", "system", "Obtenir les écrans", "monitor-smartphone",
        "Nombre d'écrans et résolution de l'écran principal.",
        "déplacer selon la largeur",
        (),
        output="Écrans : count, width, height, monitors",
        output_keys=("count", "width", "height", "monitors"),
        keywords=("écran", "résolution", "moniteur", "screen", "display"),
    ),
    StepSpec(
        "get_cursor_position", "input", "Obtenir la position de la souris", "mouse-pointer",
        "Coordonnées actuelles du curseur.",
        "cliquer là où je suis",
        (),
        output="Position : x, y",
        output_keys=("x", "y"),
        keywords=("souris", "curseur", "position", "mouse"),
    ),
    StepSpec(
        "get_active_window", "windows", "Obtenir la fenêtre active", "app-window",
        "Titre de la fenêtre au premier plan.",
        "si c'est le navigateur",
        (),
        output="Le titre de la fenêtre (texte)",
        note="Linux : nécessite xdotool (X11).",
        keywords=("fenêtre", "active", "titre", "premier plan", "window"),
    ),
    StepSpec(
        "get_volume", "media", "Obtenir le volume", "volume-2",
        "Niveau du volume principal (0-100) et état muet.",
        "si le volume > 80",
        (),
        output="Volume : level (0-100), muted, available",
        output_keys=("level", "muted", "available"),
        note="Linux : wpctl, pactl ou amixer ; Windows : pycaw.",
        keywords=("volume", "son", "muet", "audio"),
    ),
    StepSpec(
        "get_media_state", "media", "Obtenir l'état de la musique", "music",
        "Lecture / pause / arrêt du lecteur actif, avec le titre, l'artiste et l'album.",
        "si la musique joue, la mettre en pause",
        (),
        output="Média : state (playing/paused/stopped/none), playing, paused, title, artist, album, player, position, length, available",
        output_keys=("state", "playing", "paused", "title", "artist", "album", "player", "position", "length", "available"),
        note="Linux : playerctl (Spotify, VLC, navigateurs…) ; Windows : session multimédia du système.",
        keywords=("musique", "lecture", "pause", "titre", "artiste", "spotify", "média", "joue", "player"),
    ),
    StepSpec(
        "get_env_var", "system", "Obtenir une variable d'environnement", "terminal",
        "Valeur d'une variable d'environnement (vide si elle n'existe pas).",
        "HOME, USER, PATH…",
        (_F("name", "Nom de la variable", "text", placeholder="HOME", icon="tag"),),
        required=("name",),
        output="La valeur (texte)",
        keywords=("environnement", "env", "variable", "path"),
    ),
    StepSpec(
        "random_number", "data", "Nombre aléatoire", "dices",
        "Tire un entier au hasard entre deux bornes (incluses).",
        "tirer un nombre de 1 à 6",
        (
            _F("minimum", "Minimum", "number", default=1, minimum=-1000000, maximum=1000000, icon="arrow-down"),
            _F("maximum", "Maximum", "number", default=6, minimum=-1000000, maximum=1000000, icon="arrow-up"),
        ),
        output="Le nombre tiré",
        keywords=("hasard", "aléatoire", "random", "dé", "tirage"),
    ),
    # --------------------------------------------------------------- conditions
    StepSpec(
        "if_compare", "logic", "Si (comparer deux valeurs)", "scale",
        "Branche « Vrai » ou « Faux » : égal, différent, plus grand, contient, commence par, vide…",
        "{{ titre }} contient « live »",
        (
            _F("left", "Valeur", "text", placeholder="{{ titre }}", icon="text-cursor"),
            _F("cmp", "Comparaison", "select", default="eq", options=COMPARISONS, icon="equal"),
            _F("right", "Avec", "text", placeholder="live", icon="text-cursor-input",
               help="Inutile pour « est vide » / « n'est pas vide »."),
            _F("ignore_case", "Ignorer majuscules / minuscules", "bool", default=True, icon="case-sensitive"),
            _F("action_id", "Si vrai : exécuter le workflow (optionnel)", "action", icon="zap"),
            _F("else_action_id", "Si faux : exécuter le workflow (optionnel)", "action", icon="zap"),
        ),
        required=("cmp",),
        ports=BRANCH_PORTS,
        output="Vrai ou faux",
        keywords=("condition", "si", "comparer", "égal", "contient", "vide", "plus grand", "if", "compare"),
    ),
    StepSpec(
        "switch", "logic", "Selon la valeur (switch)", "git-fork",
        "Compare une valeur à jusqu'à 5 cas et suit la sortie correspondante ; « Autre cas » sinon.",
        "selon le nombre de doigts : 1, 2, 3…",
        (
            _F("value", "Valeur", "text", placeholder="{{ gesture.value }}", icon="text-cursor"),
            _F("case1", "Cas 1", "text", placeholder="1", icon="hash"),
            _F("case2", "Cas 2", "text", placeholder="2", icon="hash"),
            _F("case3", "Cas 3", "text", icon="hash"),
            _F("case4", "Cas 4", "text", icon="hash"),
            _F("case5", "Cas 5", "text", icon="hash"),
            _F("ignore_case", "Ignorer majuscules / minuscules", "bool", default=True, icon="case-sensitive"),
        ),
        required=("value",),
        ports=SWITCH_PORTS,
        output="Le numéro du cas retenu (1 à 5) ou 0",
        note="Les cas laissés vides sont ignorés. Un cas peut aussi être une valeur numérique : 3 = 3.0.",
        keywords=("switch", "selon", "cas", "choix", "case", "multi"),
    ),
    StepSpec(
        "if_random", "logic", "Si (au hasard)", "dices",
        "Branche « Vrai » avec une probabilité donnée (pile ou face, effet surprise…).",
        "1 chance sur 4",
        (_F("percent", "Probabilité de « Vrai » (%)", "number", default=50, minimum=0, maximum=100, icon="percent"),),
        ports=BRANCH_PORTS,
        output="Vrai ou faux",
        keywords=("hasard", "random", "probabilité", "pile", "face"),
    ),
    # --------------------------------------------------------------- boucles
    StepSpec(
        "while_loop", "logic", "Boucle : tant que / jusqu'à", "repeat-2",
        "Répète les noeuds reliés à « Pour chaque » selon une condition réévaluée à chaque tour, puis continue sur « Terminé ».",
        "tant que n < 5 (avec un noeud « Définir une valeur » n = {{ n + 1 }})",
        (
            _F("loop_mode", "Type de boucle", "select", default="while", options=LOOP_MODES, icon="repeat-2"),
            _F("condition", "Condition", "text", placeholder="n < 5", icon="split",
               help="Mêmes variables que « Si (condition sur une valeur) ». Modifie-les dans la boucle avec « Définir une valeur »."),
            _F("max_iterations", "Nombre maximum de tours", "number", default=100, minimum=1, maximum=1000, icon="hash",
               help="Garde-fou contre les boucles infinies."),
            _F("delay_ms", "Pause entre deux tours (ms)", "number", default=0, minimum=0, maximum=60000, icon="timer"),
        ),
        required=("condition",),
        ports=LOOP_PORTS,
        output="Nombre de tours effectués",
        keywords=("while", "tant que", "jusqu'à", "until", "boucle", "répéter", "do while"),
    ),
    StepSpec(
        "for_range", "logic", "Boucle : compter de A à B", "list-ordered",
        "Répète les noeuds reliés à « Pour chaque » en comptant (variable i par défaut), puis continue sur « Terminé ».",
        "de 1 à 10, de 2 en 2",
        (
            _F("start", "Début", "number", default=1, minimum=-1000000, maximum=1000000, icon="arrow-right-from-line"),
            _F("end", "Fin (incluse)", "number", default=5, minimum=-1000000, maximum=1000000, icon="arrow-right-to-line"),
            _F("step", "Pas", "number", default=1, minimum=-1000000, maximum=1000000, icon="footprints",
               help="Négatif pour compter à l'envers. Jamais 0."),
            _F("item_var", "Nom de la variable", "text", default="i", placeholder="i", icon="tag"),
            _F("delay_ms", "Pause entre deux tours (ms)", "number", default=0, minimum=0, maximum=60000, icon="timer"),
        ),
        ports=LOOP_PORTS,
        output="Nombre de tours effectués",
        keywords=("for", "compter", "range", "boucle", "répéter", "de à", "itération"),
    ),
    StepSpec(
        "loop_forever", "logic", "Boucle : répéter N fois", "rotate-cw",
        "Répète les noeuds reliés à « Pour chaque » N fois (variables loop.index, loop.last), puis continue sur « Terminé ».",
        "faire 3 fois",
        (
            _F("count", "Nombre de répétitions", "number", default=3, minimum=1, maximum=1000, icon="hash"),
            _F("delay_ms", "Pause entre deux tours (ms)", "number", default=0, minimum=0, maximum=60000, icon="timer"),
        ),
        ports=LOOP_PORTS,
        output="Nombre de tours effectués",
        keywords=("répéter", "fois", "repeat", "boucle", "n fois"),
    ),
    StepSpec(
        "break_loop", "logic", "Sortir de la boucle", "log-out",
        "Interrompt la boucle en cours : on passe directement à « Terminé ».",
        "dès qu'on trouve ce qu'on cherche",
        (),
        ports=(),
        keywords=("break", "sortir", "arrêter la boucle", "quitter"),
    ),
    StepSpec(
        "continue_loop", "logic", "Passer au tour suivant", "skip-forward",
        "Abandonne le reste du tour en cours et passe au tour suivant de la boucle.",
        "ignorer les lignes vides",
        (),
        ports=(),
        keywords=("continue", "suivant", "passer", "ignorer", "next"),
    ),
    StepSpec(
        "wait_until", "logic", "Attendre jusqu'à ce que…", "hourglass",
        "Attend qu'une condition devienne vraie (sortie « Vrai ») ou que le délai expire (sortie « Faux »).",
        "attendre que la musique joue",
        (
            _F("condition", "Condition", "text", placeholder="musique.playing", icon="split",
               help="Réévaluée à chaque contrôle. Pour relire une mesure à chaque fois, utilise la condition système ci-dessous."),
            _F("metric", "ou mesure système (optionnel)", "select", default="", options=("", *_METRIC_KEYS), icon="gauge"),
            _F("arg", "Argument de la mesure", "text", placeholder="spotify", icon="search"),
            _F("op", "Opérateur", "select", default=">", options=OPERATORS, icon="equal"),
            _F("value", "Valeur", "number", default=0, minimum=-1000000, maximum=1000000, icon="hash"),
            _F("timeout_s", "Délai maximum (s)", "number", default=30, minimum=1, maximum=3600, icon="timer"),
            _F("interval_ms", "Contrôle toutes les (ms)", "number", default=500, minimum=100, maximum=60000, icon="clock"),
        ),
        ports=BRANCH_PORTS,
        output="Vrai si la condition a été remplie, faux si le délai a expiré",
        keywords=("attendre", "until", "jusqu'à", "wait", "condition", "délai", "timeout"),
    ),
    StepSpec(
        "trigger", "logic", "Déclencheur", "play",
        "Point de départ du workflow : expose le geste (gesture.name, gesture.value...).",
        "",
        (),
        output="Le geste déclencheur",
        hidden=True,
    ),
)

STEPS: dict[str, StepSpec] = {spec.type: spec for spec in _SPECS}
STEP_TYPES: tuple[str, ...] = tuple(STEPS)
CATEGORY_BY_KEY: dict[str, Category] = {c.key: c for c in CATEGORIES}

# Champs communs à toutes les étapes (hors catalogue).
COMMON_KEYS = ("wait_ms", "only_on", "enabled", "name", "save_as", "on_error", "label")


def steps_in_category(category: str) -> list[StepSpec]:
    return [s for s in _SPECS if s.category == category and not s.hidden]


def ports_of(step_type: str) -> tuple[str, ...]:
    """Ports de sortie valides d'un type de noeud (``error`` toujours accepte)."""
    spec = STEPS.get(step_type)
    return (*(spec.ports if spec else ("out",)), "error")


def catalog_for_ui() -> dict:
    """Catalogue serialisable, injecte dans la page de l'editeur d'actions."""
    return {
        "categories": [
            {"key": c.key, "label": c.label, "icon": c.icon, "description": c.description}
            for c in CATEGORIES
        ],
        "steps": [s.to_dict() for s in _SPECS],
        "platforms": [{"key": k, "label": v} for k, v in PLATFORM_LABELS.items()],
    }


def icons_used() -> set[str]:
    """Toutes les icones referencees par le catalogue (vérifiées par un test)."""
    names = {c.icon for c in CATEGORIES}
    for spec in _SPECS:
        names.add(spec.icon)
        names.update(f.icon for f in spec.fields if f.icon)
    return names
