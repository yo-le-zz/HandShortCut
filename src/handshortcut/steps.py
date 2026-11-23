"""Catalogue des types d'étapes : SOURCE UNIQUE de verite.

Ce module decrit chaque type d'étape (categorie, icone, libelle, description,
champs). Il alimente :

* la validation des ecritures de l'interface (``schema.py``) ;
* l'editeur d'actions de l'interface web (le catalogue est injecte en JSON dans la page) ;
* la table des étapes du README (``scripts/gen_docs.py``) ;
* les tests d'alignement (catalogue <-> exécuteur <-> icones <-> README).

Pour ajouter un type d'étape : le declarer ici, ecrire ``_step_<type>`` dans
``action_executor.py`` puis regenerer la doc (``python scripts/gen_docs.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

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
    Category("logic", "Logique & contrôle", "git-branch", "Attentes, conditions et répétitions"),
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
        "Envoie une requête HTTP (webhook, domotique, API...). Délai maximum : 5 s.",
        "POST vers un webhook",
        (
            _F("method", "Méthode", "select", default="GET", options=HTTP_METHODS, icon="send"),
            _F("url", "URL", "text", placeholder="https://api.example.com/webhook", icon="link"),
            _F("body", "Corps (JSON ou texte, optionnel)", "textarea", placeholder='{"key": "value"}', icon="code"),
        ),
        required=("url",),
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
        "Lit un fichier texte (le résultat est ecrit dans le journal).",
        "~/notes.txt",
        (_F("path", "Chemin du fichier", "path", placeholder="~/notes.txt", icon="file"),),
        required=("path",),
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
        "Exécute une commande dans le shell, sans attendre sa fin.",
        "notify-send 'Bonjour'",
        (_F("cmd", "Commande", "textarea", placeholder="notify-send 'Bonjour'", icon="terminal"),),
        required=("cmd",),
        keywords=("script", "bash", "powershell", "cmd"),
    ),
    StepSpec(
        "kill_process", "system", "Arrêter un processus", "circle-x",
        "Arrête les processus dont le nom contient le texte donne (jamais HandShortCut lui-même).",
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
            _F("title", "Titre", "text", default="HandShortCut", placeholder="HandShortCut", icon="bell"),
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
        "Exécute une autre action si une fenêtre est ouverte (sinon l'action alternative, si définie).",
        "Si Spotify est ouvert : pause",
        (
            _F("title_contains", "Le titre contient", "text", placeholder="Firefox", icon="search"),
            _F("action_id", "Alors exécuter l'action", "action", icon="zap"),
            _F("else_action_id", "Sinon exécuter l'action (optionnel)", "action", icon="zap"),
        ),
        required=("title_contains", "action_id"),
        keywords=("condition", "si", "if"),
    ),
    StepSpec(
        "if_process_running", "logic", "Si un processus tourne", "activity",
        "Exécute une autre action si un processus est actif (sinon l'action alternative, si définie).",
        "Si discord tourne : notification",
        (
            _F("name", "Nom du processus", "text", placeholder="spotify", icon="search"),
            _F("action_id", "Alors exécuter l'action", "action", icon="zap"),
            _F("else_action_id", "Sinon exécuter l'action (optionnel)", "action", icon="zap"),
        ),
        required=("name", "action_id"),
        keywords=("condition", "si", "if"),
    ),
    StepSpec(
        "repeat", "logic", "Répéter une action", "repeat",
        "Exécute une autre action plusieurs fois de suite.",
        "3 fois",
        (
            _F("count", "Nombre de répétitions", "number", default=2, minimum=1, maximum=1000, icon="repeat"),
            _F("action_id", "Action à répéter", "action", icon="zap"),
            _F("delay_ms", "Pause entre deux répétitions (ms)", "number", default=0, minimum=0, maximum=600000, icon="clock"),
        ),
        required=("action_id",),
        keywords=("boucle", "loop", "fois"),
    ),
)

STEPS: dict[str, StepSpec] = {spec.type: spec for spec in _SPECS}
STEP_TYPES: tuple[str, ...] = tuple(STEPS)
CATEGORY_BY_KEY: dict[str, Category] = {c.key: c for c in CATEGORIES}

# Champs communs à toutes les étapes (hors catalogue).
COMMON_KEYS = ("wait_ms", "only_on", "enabled")


def steps_in_category(category: str) -> list[StepSpec]:
    return [s for s in _SPECS if s.category == category]


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
