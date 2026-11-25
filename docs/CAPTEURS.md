# Capteurs : ce qui est possible, et ce qui ne l'est pas

PhysicalShortCut ne **fabrique** pas de capteurs : il lit ceux que l'ordinateur possède et propose
un pont pour ceux qu'il n'a pas. Cette page dit honnêtement ce qui marche où.
La page **Activité → Capteurs de cette machine** affiche la même chose pour ta machine précise.

## Règles de confidentialité

- Le **micro est désactivé par défaut** et ne s'ouvre que si **tu l'autorises** (Activité → Micro)
  **et** qu'un geste *Son* ou *Voix* existe. Sans déclencheur, rien ne s'ouvre.
- Rien n'est enregistré ni envoyé : le son est analysé en mémoire (niveau, claquements) ; la voix est
  reconnue **hors ligne**.
- Chaque capteur n'est lu que si un déclencheur l'utilise.

## Matrice de faisabilité

| Capteur | Linux | Windows | Remarques |
|---|---|---|---|
| **Son** : claquement simple/double/triple, bruit fort, silence | ✅ micro | ✅ micro | Extra `audio` ; Linux : paquet **PortAudio** (`dnf install portaudio` / `apt install libportaudio2`). |
| **Voix** : commandes parlées, nombres | ✅ | ✅ | Extra `audio` + modèle **Vosk** français à déposer dans `<données>/models/` (~40 Mo, `vosk-model-small-fr-0.22`). |
| **Empreinte digitale** | ✅ via **fprintd** (écoute continue, nom du doigt) | ⚠️ **à la demande seulement** | Windows Hello n'autorise pas une appli à écouter le lecteur : on ne peut que *demander une vérification* (étape « Vérifier mon identité »). |
| **USB** branché / débranché | ✅ | ✅ | |
| **Bluetooth** connecté / déconnecté | ✅ `bluetoothctl` (bluez) | ✅ | |
| **Secteur** branché / débranché | ✅ | ✅ | Portables ; via psutil. |
| **Capot** fermé / ouvert | ✅ si exposé par ACPI | ❌ | Portables Linux uniquement. |
| **Wi-Fi** connecté / déconnecté (SSID) | ✅ `nmcli` | ✅ `netsh` | |
| **Inactivité** clavier/souris | ✅ `xprintidle` (X11) ou logind | ✅ | Wayland : dépend du bureau. |
| **Lumière ambiante** | ⚠️ si capteur IIO / ACPI | ❌ | Tablettes, 2-en-1. Absent sur la plupart des PC. |
| **Accéléromètre** (secousse) | ⚠️ si IIO / HDAPS | ❌ | Portables convertibles, anciens ThinkPad. |
| **Températures** CPU, disque NVMe, GPU | ✅ (`lm-sensors`/hwmon) | ⚠️ selon la machine ; GPU NVIDIA via `nvidia-smi` | |
| **Ventilateurs** (tr/min) | ✅ hwmon | ❌ | |
| **Température de la pièce** | ❌ sur un PC | ❌ | **Un PC mesure ses composants, pas la pièce.** Utilise un capteur externe (DHT22, BME280…). |
| **Gaz, humidité, mouvement PIR, distance…** | ❌ sur un PC | ❌ | **Aucun PC n'en a.** Utilise un capteur externe. |

Un capteur absent n'est **jamais** déclenché et n'est jamais deviné : sa mesure est « indisponible ».

## Capteurs externes (Arduino, ESP32, micro:bit, scripts)

Pour tout ce qu'un PC n'a pas (gaz MQ-2, humidité, PIR, ultrason, thermomètre de pièce…), branche une carte :

1. Programme la carte pour afficher **une ligne par mesure** sur le port série : `gaz=412`
   (ou `{"gaz": 412}`, ou un nombre seul).
2. Installe l'extra : `pip install "physicalshortcut[serial]"`.
3. **Activité → Capteurs externes** : déclare le capteur, par exemple
   `[{"name":"gaz","kind":"serial","port":"/dev/ttyACM0","baud":9600}]` (Windows : `COM3`).
4. Crée un geste de type **Capteur (seuil)** : mesure *Capteur externe*, nom `gaz`, `> 400`.

Variante **commande** : `{"name":"temp","kind":"command","command":"python lire.py","interval_s":5}` ;
le programme affiche un nombre. ⚠️ La commande est exécutée telle quelle : n'y mets que du code de confiance.
Sous Linux, ajoute ton utilisateur au groupe `dialout` pour accéder au port série.

Dans un workflow, lis la valeur avec l'étape **Lire une mesure système** (mesure *Capteur externe* + nom du capteur).

## Variables transmises au workflow

| Déclencheur | Variables |
|---|---|
| Son (claquement) | `{{ gesture.value }}` = nombre de claquements |
| Capteur (seuil) | `{{ gesture.value }}` = valeur mesurée, `{{ gesture.metric }}` |
| Voix | `{{ gesture.text }}` (phrase entendue), `{{ gesture.phrase }}`, `{{ gesture.value }}` (nombre dit) |
| Empreinte | `{{ gesture.finger }}`, `{{ gesture.result }}` |
| Branchement | `{{ gesture.device }}`, `{{ gesture.device_id }}`, `{{ gesture.event }}` |

## Non testé sur du vrai matériel

Cette version a été écrite et testée avec des données simulées (sons de synthèse, sorties de commandes
d'exemple). Les lectures de vrais capteurs (micro, fprintd, IIO, port série, Windows Hello) dépendent de
ta machine : signale les écarts dans une issue avec la sortie de **Activité → Capteurs de cette machine**.
