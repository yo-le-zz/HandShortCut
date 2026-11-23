# HandShortCut

<p align="center"><img src="assets/icon.png" alt="HandShortCut" width="96"></p>

Détecte des gestes de la main via ta webcam (en tâche de fond) et déclenche des
actions personnalisées : lancer une application, la placer sur tel écran, envoyer un
raccourci clavier, piloter le volume, ouvrir une URL, appeler une API, exécuter une
commande... Le tout configurable depuis une interface web locale, **sans écrire une
ligne de code**.

**Windows** et **Linux** (X11 et Wayland), Python 3.10 – 3.12 ou exécutable natif sans Python.

```
Webcam --> MediaPipe (points de la main) --> comparaison aux gestes enregistrés
                                                        |
                                                        v
                                          geste reconnu -> action liée
```

- Un **geste** est une **pose statique** (à tenir quelques instants) ou une **séquence** (mouvement).
- Une **action** est une liste d'étapes exécutées dans l'ordre, que tu peux **réordonner par glisser-déposer**.
- Tout se pilote depuis **http://127.0.0.1:5678** (accessible uniquement depuis ta machine).
- `gestures.json` et `actions.json` sont **rechargés à chaud** (via l'interface ou à la main).

---

## Installation

L'application est compilée en **exécutable natif** (Nuitka) : aucun Python à installer.
Les paquets sont dans les [Releases](https://github.com/yo-le-zz/HandShortCut/releases) ;
chaque release fournit un fichier `SHA256SUMS` pour vérifier les téléchargements.

### Fedora / RHEL (.rpm)

```bash
sudo dnf install ./handshortcut-1.0.0-1.x86_64.rpm
```

### Debian / Ubuntu (.deb)

```bash
sudo apt install ./handshortcut_1.0.0_amd64.deb
```

Dans les deux cas : service `systemd --user` activé (démarrage à la connexion), entrée
**HandShortCut** dans le menu d'applications (avec son icône), commande `handshortcut`.

```bash
handshortcut --open        # ou : systemctl --user start handshortcut
handshortcut doctor        # vérifie caméra, outils manquants, session graphique
```

Désinstallation : `sudo dnf remove handshortcut` / `sudo apt remove handshortcut`.

### Windows (.msi ou .exe)

| Fichier | Usage |
|---|---|
| `HandShortCut-1.0.0-x64.msi` | Paquet MSI : double-clic, déploiement en entreprise (GPO, Intune), `msiexec /i HandShortCut-1.0.0-x64.msi /qn` |
| `HandShortCut-Setup-1.0.0.exe` | Installateur classique (Inno Setup), options de démarrage automatique et raccourci bureau |

Avec le MSI, `AUTOSTART=1` active le démarrage avec Windows :
`msiexec /i HandShortCut-1.0.0-x64.msi /qn AUTOSTART=1`. Aucune connexion internet n'est
nécessaire : l'exécutable est embarqué. Désinstallation : Paramètres > Applications.

### Avec uv (toutes plateformes, sans paquet)

```bash
uv tool install --python 3.12 .      # depuis le dossier du projet
handshortcut --open
```

Sous Linux, installe aussi `wmctrl` (ou `xdotool`), `libgl1`, `libglib2.0-0` ; recommandés :
`playerctl`, `xclip`/`wl-clipboard`, `libnotify`, `brightnessctl`. `handshortcut doctor`
indique ce qui manque pour chaque étape.

> **Python ≤ 3.12** : `mediapipe==0.10.14` n'a pas de wheel pour 3.13+ et les versions
> récentes ont supprimé l'API `mp.solutions` utilisée ici. uv télécharge la bonne version.

---

## Utilisation

```text
handshortcut [--port 5678] [--camera 0] [--data-dir DOSSIER] [--open] [-v]
handshortcut stop                 arrête l'instance en cours
handshortcut paths                dossiers de données / journaux / exemples
handshortcut doctor               diagnostic de l'environnement
handshortcut export [fichier]     exporte gestes + actions (JSON portable)
handshortcut import [--replace] fichier
handshortcut autostart on|off|status   démarrage à la connexion (XDG / registre Windows)
```

Variables d'environnement : `HANDSHORTCUT_PORT`, `HANDSHORTCUT_CAMERA`, `HANDSHORTCUT_DATA_DIR`.

| | Linux | Windows |
|---|---|---|
| Données (`gestures.json`, `actions.json`) | `~/.local/share/handshortcut` | `%LOCALAPPDATA%\HandShortCut` |
| Journal | `~/.local/state/handshortcut/log` | `%LOCALAPPDATA%\HandShortCut\Logs` |

Les gestes enregistrés utilisent des coordonnées normalisées : un export fait sous
Windows s'importe tel quel sous Linux (et inversement), via l'interface (**Exporter** /
**Importer**) ou en ligne de commande.

### Créer et modifier un geste

1. **Nouveau geste** : choisis *pose statique* ou *séquence*, **Démarrer**, fais le geste devant la caméra, **Arrêter**.
2. Nomme le geste, règle la **sensibilité**, lie-le à une action, enregistre.
3. Tous les réglages restent **modifiables** ensuite (bouton d'édition de la carte) : nom, action,
   seuil, durée de tenue, pause après déclenchement, et même **ré-enregistrement** du modèle.

**Les durées sont exprimées en secondes et en millisecondes** (avec l'équivalent en images
à la cadence réelle de ta caméra). Exemple : *tenue 0,27 s (270 ms) ≈ 8 images à 29,8 images/s*.
Une jauge **en direct** montre la distance au geste et le seuil, pour régler sans deviner.

### Créer une action

**Nouvelle action** ouvre l'éditeur : une palette par catégorie (recherche + icônes + exemples),
des cartes d'étapes dépliables, **glisser-déposer** (ou flèches) pour changer l'ordre d'exécution,
bouton de test, duplication. Chaque étape accepte aussi :

- `wait_ms` : attente après l'étape ;
- `only_on` : `windows` ou `linux` (une même action peut contenir des variantes par système) ;
- `enabled` : désactiver une étape sans la supprimer.

Les chemins acceptent `~`, `$VAR` et `%VAR%`. Les noms de touches sont normalisés
(`ctrl`, `control`, `win`, `super`, `cmd`... désignent la même touche).

### Étapes disponibles

Générée depuis le catalogue (`src/handshortcut/steps.py`), source unique de l'interface,
de la validation et de cette documentation.

<!-- steps:begin (genere par scripts/gen_docs.py, ne pas modifier a la main) -->

45 types d'étapes, regroupés en 7 catégories.

**Fenêtres & applications** : Lancer, placer et piloter les fenêtres

| Type | Rôle | Champs | Plateformes |
|---|---|---|---|
| `launch` | Démarre un programme, une commande du PATH ou une application installée. | `path`, `args`, `shell_cmd` | Windows + Linux |
| `open_path` | Ouvre un fichier ou un dossier avec l'application par défaut du système. | `path` | Windows + Linux |
| `move_window` | Déplace et redimensionne une fenêtre sur un écran (moitie, tiers, quart, plein écran...). | `title_contains`, `monitor`, `position` | Windows + Linux |
| `close_window` | Demande poliment la fermeture de la fenêtre. | `title_contains` | Windows + Linux |
| `focus_window` | Active la fenêtre et la place devant les autres. | `title_contains` | Windows + Linux |
| `minimize_window` | Réduit la fenêtre dans la barre des taches. | `title_contains` | Windows + Linux |
| `maximize_window` | Agrandit la fenêtre au maximum. | `title_contains` | Windows + Linux |
| `restore_window` | Rend à la fenêtre sa taille normale (annule agrandir / réduire). | `title_contains` | Windows + Linux |
| `wait_for_window` | Attend qu'une fenêtre apparaisse (utile après un lancement) avant de continuer. | `title_contains`, `timeout_ms` | Windows + Linux |
| `show_desktop` | Réduit ou restaure toutes les fenêtres pour montrer le bureau. | `mode` | Windows + Linux |
| `switch_desktop` | Passe au bureau virtuel suivant ou précédent (Linux : ou à un numéro précis). | `target`, `index` | Windows + Linux |

**Clavier & souris** : Simuler des touches, des clics et du texte

| Type | Rôle | Champs | Plateformes |
|---|---|---|---|
| `keypress` | Envoie une touche ou une combinaison. | `keys` | Windows + Linux |
| `type_text` | Tape un texte au clavier dans la fenêtre active (accents et symboles compris). | `text`, `interval_ms` | Windows + Linux |
| `mouse_move` | Place le curseur à une position de l'écran (en pixels). | `x`, `y` | Windows + Linux |
| `mouse_click` | Clique (à la position donnee, ou la ou se trouve le curseur). | `button`, `x`, `y` | Windows + Linux |
| `mouse_double_click` | Double-clique (à la position donnee, ou la ou se trouve le curseur). | `button`, `x`, `y` | Windows + Linux |
| `mouse_drag` | Maintient le bouton enfoncé de la position actuelle (ou de départ) jusqu'à la destination. | `x`, `y`, `from_x`, `from_y`, `button`, `duration_ms` | Windows + Linux |
| `mouse_scroll` | Fait défiler la fenêtre active. | `direction`, `amount` | Windows + Linux |
| `clipboard_set` | Place un texte dans le presse-papiers. | `text` | Windows + Linux |
| `clipboard_get_and_type` | Tape au clavier le contenu actuel du presse-papiers. | _aucun_ | Windows + Linux |

**Média & audio** : Lecture, volume, sons et voix

| Type | Rôle | Champs | Plateformes |
|---|---|---|---|
| `media_control` | Lecture / pause, piste suivante ou précédente, volume, muet. | `action` | Windows + Linux |
| `set_volume` | Définit le volume principal (0 à 100 %). | `level` | Windows + Linux |
| `play_sound` | Joue un fichier audio (WAV sur Windows ; WAV, OGG, MP3... sur Linux selon les lecteurs installés). | `path` | Windows + Linux |
| `speak` | Lit un texte à voix haute. | `text` | Windows + Linux |

**Web & réseau** : Pages web, API et WebSocket

| Type | Rôle | Champs | Plateformes |
|---|---|---|---|
| `open_url` | Ouvre une adresse dans le navigateur par défaut. | `url` | Windows + Linux |
| `http_request` | Envoie une requête HTTP (webhook, domotique, API...). Délai maximum : 5 s. | `method`, `url`, `body` | Windows + Linux |
| `websocket_send` | Ouvre une connexion WebSocket, envoie un message puis la referme. | `url`, `message` | Windows + Linux |

**Fichiers** : Écrire, copier, déplacer, capturer

| Type | Rôle | Champs | Plateformes |
|---|---|---|---|
| `file_write` | Crée ou remplace un fichier texte. | `path`, `content`, `append` | Windows + Linux |
| `file_read` | Lit un fichier texte (le résultat est ecrit dans le journal). | `path` | Windows + Linux |
| `file_delete` | Supprime définitivement un fichier. | `path` | Windows + Linux |
| `file_copy` | Copie un fichier (les métadonnées sont conservées). | `source`, `destination` | Windows + Linux |
| `file_move` | Déplace ou renomme un fichier ou un dossier. | `source`, `destination` | Windows + Linux |
| `directory_create` | Crée un dossier (et ses parents si besoin). | `path` | Windows + Linux |
| `screenshot` | Enregistre une capture de l'écran dans un fichier PNG. | `path` | Windows + Linux |

**Système** : Commandes, processus, affichage, alimentation

| Type | Rôle | Champs | Plateformes |
|---|---|---|---|
| `run_shell` | Exécute une commande dans le shell, sans attendre sa fin. | `cmd` | Windows + Linux |
| `kill_process` | Arrête les processus dont le nom contient le texte donne (jamais HandShortCut lui-même). | `name` | Windows + Linux |
| `notify` | Affiche une notification système. | `title`, `message` | Windows + Linux |
| `change_brightness` | Définit la luminosité de l'écran (0 à 100 %). | `level` | Windows + Linux |
| `change_wallpaper` | Applique une image comme fond d'écran. | `path` | Windows + Linux |
| `set_theme` | Bascule le thème du système entre clair et sombre. | `mode` | Windows + Linux |
| `power_action` | Verrouille, met en veille, ferme la session, redémarre ou éteint l'ordinateur. | `action` | Windows + Linux |

**Logique & contrôle** : Attentes, conditions et répétitions

| Type | Rôle | Champs | Plateformes |
|---|---|---|---|
| `wait` | Attend un certain temps avant l'étape suivante. | `ms` | Windows + Linux |
| `if_window_exists` | Exécute une autre action si une fenêtre est ouverte (sinon l'action alternative, si définie). | `title_contains`, `action_id`, `else_action_id` | Windows + Linux |
| `if_process_running` | Exécute une autre action si un processus est actif (sinon l'action alternative, si définie). | `name`, `action_id`, `else_action_id` | Windows + Linux |
| `repeat` | Exécute une autre action plusieurs fois de suite. | `count`, `action_id`, `delay_ms` | Windows + Linux |

<!-- steps:end -->

Un exemple complet est livré dans `src/handshortcut/examples/` (chemin affiché par
`handshortcut paths`). Le geste d'exemple est un gabarit vide : il faut l'enregistrer.

### Compatibilité Linux / Windows

- **Linux** : X11 complet ; Wayland partiel (fenêtres XWayland via `wmctrl`/`xdotool`, volume
  via `wpctl`/`pactl`, média via `playerctl`). `handshortcut doctor` liste les limites de ta session.
- **Windows** : fenêtres via `pygetwindow`, volume via `pycaw` (repli sur les touches média),
  luminosité, bureaux virtuels, synthèse vocale et thème via PowerShell.
- Les étapes propres à un système sont signalées dans le catalogue ; sur l'autre système elles
  sont ignorées proprement (journal) au lieu de planter l'action.

---

## Développement

```bash
uv sync                    # crée .venv (Python 3.12) avec les dépendances
uv run handshortcut -v     # lance l'application
uv run pytest              # tests
uv run ruff check src tests scripts
uv run python scripts/gen_docs.py   # régénère le tableau des étapes ci-dessus
```

Interface : CSS, icônes et polices sont **versionnés** (`webui/static`) ; Node n'est nécessaire
que pour les régénérer : `cd frontend && npm install && npm run build` (Tailwind CSS, icônes
[Lucide](https://lucide.dev) détectées automatiquement dans les templates, JS et le catalogue ;
le build échoue si une icône n'existe pas). Icônes de l'application : `python assets/make_icons.py`
régénère toutes les tailles à partir de `assets/logo.png`.

### Ajouter un type d'étape

1. `steps.py` : ajoute une `StepSpec` (catégorie, icône, champs, plateformes).
2. `action_executor.py` : écris `_step_<type>(step)` et ajoute-le à `_HANDLERS`.
3. `python scripts/gen_docs.py` pour mettre à jour la documentation.

Aucun JavaScript à modifier : l'éditeur se construit depuis le catalogue. Des tests vérifient
que catalogue, gestionnaires, icônes et README restent synchronisés.

### Construire les paquets

```bash
./build.sh            # Linux : détecte le système et les outils, compile (Nuitka), crée .deb/.rpm -> dist/
./build.sh --list     # montre ce qui est possible sans construire
./build.sh --docker   # compile dans Ubuntu 22.04 (binaire compatible avec davantage de distributions)
powershell -File packaging\windows\build.ps1       # Windows : .exe (Inno Setup 6) + .msi (WiX v5) -> dist\
```

La compilation prend 30 à 60 minutes la première fois. La CI fait tout cela automatiquement.

### Publier une version

1. Mets à jour `version` dans `pyproject.toml` et la section correspondante de `CHANGELOG.md`.
2. Crée et pousse le tag : `git tag v1.0.0 && git push origin v1.0.0`.

Le workflow `.github/workflows/release.yml` vérifie que le tag correspond à `pyproject.toml`,
construit `.deb`, `.rpm`, `.exe` et `.msi`, calcule `SHA256SUMS` et crée la release GitHub avec
les notes extraites du changelog. Détails : [docs/github-setup.md](docs/github-setup.md).

```
src/handshortcut/         cli, gesture_engine, steps (catalogue), action_executor, platform_utils,
                          schema, config_store, bundle, autostart, doctor, paths
src/handshortcut/webui/   Flask (app.py), templates, static (CSS, JS, icônes, polices)
frontend/                 sources Tailwind + génération du sprite d'icônes
assets/                   logo, icônes (make_icons.py)
packaging/                build_exe.py (Nuitka), linux (deb/rpm, systemd), windows (Inno Setup, WiX MSI)
scripts/                  gen_docs.py, release_notes.py
tests/                    pytest
```

## Limites connues

- Reconnaissance de séquence : ré-échantillonnage + distance moyenne (pas de DTW) ; sensible à
  une vitesse très différente de l'enregistrement. En cas de faux négatifs, ré-enregistre 2-3 fois.
- Wayland pur : pas de contrôle des fenêtres natives ni d'injection de clavier sans `ydotool`.
- Une seule caméra à la fois (`--camera`).
- L'interface n'écoute que sur `127.0.0.1` ; ne l'expose jamais sur le réseau : elle peut lancer
  des commandes.

Licence : MIT.
