# Changelog

Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) ; versions
[SemVer](https://semver.org/lang/fr/).

## 2.1.0 - 2026-11-25

Créé par **yolezz**.

### Éditeur de workflows
- **Grand canvas** (80 % de la hauteur de l'écran, page élargie jusqu'à 1800 px).
- **Zoom** de 25 % à 200 % : molette (centré sur le curseur), boutons, touches `+` `-` `0`, bouton « tout voir » ; le niveau de zoom est mémorisé.
- **Déplacement** : clic dans le vide puis déplacement de la souris. Un simple clic dans le vide désélectionne toujours.
- Le canvas déborde du contenu d'un demi-écran : on peut toujours se déplacer dans le vide.

### Nouvelles étapes (60 → 81)
- **Obtenir** : nom de l'ordinateur (hostname), utilisateur, système d'exploitation, adresse IP locale, date et heure, écrans, position de la souris, fenêtre active, volume, **état de la musique** (lecture / pause, titre, artiste, album, lecteur), variable d'environnement, nombre aléatoire.
- **Conditions** : comparer deux valeurs (égal, différent, supérieur, contient, commence / finit par, expression, vide…), **selon la valeur** (switch à 5 cas + « Autre cas »), au hasard, **attendre jusqu'à ce que** (avec délai).
- **Boucles** : tant que / faire-tant-que / jusqu'à, compter de A à B (pas négatif possible), répéter N fois, **sortir de la boucle**, **passer au tour suivant**. « Pour chaque » gère aussi sortir / suivant. Garde-fous : 1000 tours maximum.
- Variables vivantes dans tous les champs : `{{ media.title }}`, `{{ media.playing }}`, `{{ volume.level }}`, `{{ host.name }}`.
- « Définir une valeur » transforme un nombre écrit en vrai nombre (`0` + 1 = 1 et plus « 01 »).

### Dessin dans l'air
- Le **5** est reconnu avec 7 façons de l'écrire (un trait, deux traits, barre tracée en dernier, penché, arrondi, retour sans lever le doigt) : environ 90 % sur des tracés simulés (contre 70 %).

### Non testé ici
- Lecture de l'état de la musique sous Windows (script PowerShell) et sous Linux avec un vrai lecteur (playerctl) : seuls les analyseurs de sortie sont testés.

## 2.0.0 - 2026-11-25

Créé par **yolezz**. **HandShortCut devient PhysicalShortCut** (explication : [RENAMING.md](RENAMING.md)).

### Nouveautés
- **Nouveau nom** : PhysicalShortCut. Paquet `physicalshortcut`, commande `physicalshortcut`, variables
  `PHYSICALSHORTCUT_*`, paquets, service, icônes, documentation : tout est renommé. Les anciennes variables
  `HANDSHORTCUT_*` fonctionnent encore, les données de l'ancien dossier sont **copiées** au premier lancement
  (sans rien supprimer) et l'ancien démarrage automatique est nettoyé.
- **Son** : claquement simple, double, triple, bruit fort, silence (micro, analyse en mémoire).
- **Voix** : commandes parlées **hors ligne** (Vosk), phrases exactes, contenues ou approximatives ;
  le texte et un nombre dit (« volume soixante ») sont transmis au workflow.
- **Empreinte digitale** : Linux via fprintd (reconnu / inconnu, doigt précis). Windows : étape de workflow
  **Vérifier mon identité** (Windows Hello / fprintd) avec branches vrai / faux.
- **Branchements** : USB, Bluetooth, secteur, capot, Wi-Fi.
- **Capteur à seuil** : lumière ambiante, accéléromètre (secousse), températures (CPU, GPU, disque, pièce),
  ventilateur, inactivité, niveau sonore, capteur externe. Déclenchement une fois ou en continu, durée de tenue.
- **Capteurs externes** (Arduino, ESP32, micro:bit par port série, ou commande) pour ce qu'un PC n'a pas :
  gaz, humidité, mouvement PIR…
- **Faisabilité honnête** : la page Activité liste ce que *ta* machine possède ; [docs/CAPTEURS.md](docs/CAPTEURS.md)
  détaille chaque capteur par système.
- **Vie privée** : le micro est désactivé par défaut, et n'est ouvert que si tu l'autorises et qu'un
  déclencheur Son ou Voix existe. Chaque capteur n'est lu que si un déclencheur l'utilise.
- 10 nouvelles mesures utilisables aussi dans les conditions des gestes ; 9 nouveaux modèles
  (clap → pause, commande vocale, USB, gaz, secousse, empreinte…) ; 1 nouvelle étape (60 au total).
- Extras d'installation : `physicalshortcut[audio]`, `[serial]`, `[sensors]`.

### Changements
- `sounddevice` n'est plus exclu de l'installation (il sert au micro).
- Les anciens gestes (statique, mouvement, doigts, comptage, dessin) et les workflows existants fonctionnent sans changement.

### Non testé ici
- Matériel réel (micro, lecteur d'empreintes, capteurs IIO, port série), Windows Hello, paquets MSI / Nuitka avec les extras.

## 1.1.0 - 2026-11-24

Créé par **yolezz**.

### Nouveautés
- **Workflows en graphe** : les actions deviennent de vrais workflows de noeuds reliés par des ports
  (`suite`, `vrai`, `faux`, `pour chaque`, `terminé`, `erreur`). Éditeur visuel : glisser les noeuds,
  tirer un lien depuis un port, liens de données en pointillés, inspecteur, test avec trace par noeud.
  Les anciennes actions (liste d'étapes) continuent de fonctionner et s'ouvrent en graphe.
- **Données partagées entre noeuds** : la sortie d'un noeud nommé est une variable, utilisable partout
  avec `{{ nom }}` (filtres `upper`, `int`, `json`, `regex`…, calculs, conditions). Exemple :
  *lire un fichier → l'écrire ailleurs*. Moteur d'expressions sécurisé (pas d'`eval`).
- **15 nouveaux types d'étapes** : presse-papiers (lecture), variable, message de journal, JSON, regex,
  mesure système, info mains, question à l'IA, Si (valeur), Si (système), Pour chaque, lancer un workflow
  avec arguments, arrêter le workflow… (59 au total). Les lectures de fichier, requêtes HTTP, commandes
  (`capture`) et captures renvoient désormais leur résultat.
- **Dessiner dans l'air** : trace un chiffre (0-9) ou une forme (cercle, carré, triangle, coche, étoile,
  cœur…) avec l'index ; reconnaissance locale hors ligne (nuage de points), IA de vision optionnelle
  (Ollama ou tout service compatible OpenAI), tracés personnalisés à apprendre. Le résultat est passé au
  workflow (`{{ gesture.value }}`, `{{ gesture.label }}`).
- **Nouveaux gestes** : *doigts levés* (sans enregistrement), *compter les doigts* (valeur transmise),
  **deux mains** pour les poses et les comptages.
- **Conditions en plus du geste** : allumé depuis X minutes, CPU < 70 %, température < 50 °C, RAM,
  disque, batterie, heure, jour, processus lancé, fenêtre ouverte, fichier présent… (mode *toutes* / *une*).
  Les gestes bloqués expliquent pourquoi dans l'activité.
- **Retour visuel** : bulles à l'écran quand un geste est reconnu, bloqué ou qu'un workflow échoue,
  notification du bureau (réglable), page **Activité** avec le détail de chaque noeud exécuté.
- **Import intelligent** : l'export mémorise le système d'origine (ou le détecte) ; à l'import, chemins,
  variables d'environnement et programmes courants sont convertis Windows ↔ Linux, le non-convertible est
  réservé à son système, et un rapport est affiché.
- **20 modèles** de workflows et de gestes prêts à installer (page *Modèles*).
- Crédits « Créé par yolezz » (interface, `--version`, paquets).

### Corrections
- Les workflows ne s'arrêtent plus à la première erreur masquée : chaque noeud reçoit ses erreurs.

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
