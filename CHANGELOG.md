# Changelog

Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) ; versions
[SemVer](https://semver.org/lang/fr/).

## 1.0.0 - 2026-11-23

Première version publique.

### Nouveautés
- **Gestes modifiables** : nom, action liée, seuil, durée de tenue, pause après déclenchement
  et ré-enregistrement du modèle, depuis l'interface (page d'édition dédiée). Duplication d'un geste.
- **Durées en secondes et millisecondes** partout (tenue, pause, enregistrement), avec équivalent
  en images à la cadence mesurée de la caméra ; jauge de détection en direct.
- **45 types d'étapes** en 7 catégories (fenêtres, clavier & souris, média, web, fichiers,
  système, logique), chacun avec icône, description et exemple. Nouveautés : `open_path`,
  `wait_for_window`, `show_desktop`, `switch_desktop`, `mouse_double_click`, `mouse_drag`,
  `play_sound`, `speak`, `set_theme`, `power_action` (verrouiller, veille, déconnexion...), en plus
  des étapes existantes.
- **Éditeur d'actions refondu** : palette par catégorie avec recherche, cartes dépliables,
  **glisser-déposer pour réordonner**, désactivation d'une étape, `only_on` (Windows / Linux), test, duplication.
- **Interface refaite** : vraies icônes (Lucide, sprite auto-généré), menu latéral, cartes colorées
  par catégorie, hors ligne (aucun CDN).
- **Icône de l'application** : `assets/make_icons.py` génère toutes les tailles (hicolor 16-512, `.ico`)
  à partir du logo ; icône dans le menu d'applications Linux et dans l'exécutable / MSI Windows.
- **Compatibilité Linux ↔ Windows** : couche `platform_utils` (alias de touches, chemins `~`/`$VAR`/`%VAR%`,
  `wmctrl` → `xdotool`, Wayland, `pycaw`, PowerShell), export / import portable des gestes,
  `handshortcut doctor`, `handshortcut autostart`.
- **Paquets** : `.deb`, `.rpm`, installateur `.exe` (Inno Setup) et **MSI** (WiX v5).
- **CI / releases** : workflows GitHub `ci.yml` et `release.yml` (tag `v*.*.*` → build et publication).

### Corrections
- Étapes `if_window_exists`, `if_process_running` et `repeat` : elles étaient factices, elles s'exécutent
  désormais (avec garde-fous contre la récursion).
- Page d'édition d'un geste : script inline bloqué par la CSP, classes CSS inexistantes ou purgées.
- Failsafe de pyautogui, saisie de texte non ASCII, intervalle de frappe nul.
- Dépendances manquantes (`websocket-client`, `pycaw` sous Windows).
- Luminosité sous Windows, fonds d'écran (URI), défilement horizontal de l'interface.
- Service systemd : plus de boucle de redémarrage quand HandShortCut tourne déjà.
- Données hors du dossier d'installation ; écritures atomiques ; JSON corrompu mis de côté ;
  contrôle Host/Origin, en-tête anti-CSRF et CSP.
