# HandShortCut devient PhysicalShortCut

À partir de la **version 2.0.0**, le projet s'appelle **PhysicalShortCut**.

## Pourquoi ce nom ?

HandShortCut déclenchait des actions avec **la main** devant une webcam. Le projet ne se limite
plus à la main : il réagit maintenant à tout ce que **le monde physique** peut signaler à un
ordinateur : un **claquement**, une **phrase**, une **empreinte**, un **branchement USB**, la
fermeture du **capot**, une **secousse**, un niveau de **lumière**, une **température**, un
**capteur de gaz** branché sur un Arduino… « Hand » était devenu trop étroit ; **Physical**
décrit ce que fait l'outil : *transformer un événement physique en action*.

Le fonctionnement reste le même : un **déclencheur** (geste, son, voix…) + des **conditions**
→ un **workflow**. La main n'est plus qu'un déclencheur parmi d'autres.

## Ce qui a changé

| Avant (1.x) | Maintenant (2.0) |
|---|---|
| Dépôt `HandShortCut` | `PhysicalShortCut` (à renommer par toi sur GitHub) |
| Paquet Python `handshortcut` | `physicalshortcut` |
| Commande `handshortcut` / `handshortcut-gui` | `physicalshortcut` / `physicalshortcut-gui` |
| Variables `HANDSHORTCUT_*` | `PHYSICALSHORTCUT_*` (les anciennes **fonctionnent toujours**) |
| En-tête CSRF `X-HandShortCut` | `X-PhysicalShortCut` |
| Dossier de données `handshortcut` | `physicalshortcut` |
| Paquets `.deb` / `.rpm` / `.msi` | `physicalshortcut_…`, `PhysicalShortCut-…` |
| Service systemd, `.desktop`, démarrage auto | `physicalshortcut.*` |

## Tes données sont conservées

Au premier lancement, si le dossier `physicalshortcut` n'existe pas encore, tes fichiers
(`gestures.json`, `actions.json`, réglages, tracés, images) sont **copiés** depuis l'ancien dossier
`handshortcut`. L'ancien dossier n'est **jamais supprimé** : tu peux le garder comme sauvegarde.
Si tu utilises `HANDSHORTCUT_DATA_DIR`, ton dossier personnalisé est respecté tel quel.

Le **démarrage automatique** de l'ancien nom (entrée de registre Windows ou `handshortcut.desktop`
sous Linux) est supprimé quand tu actives ou désactives le démarrage automatique de la nouvelle version.

## Mise à jour depuis la 1.x

1. Désinstalle l'ancien paquet (`handshortcut`), puis installe `physicalshortcut` 2.0.0.
   (Avec `uv` : `uv tool uninstall handshortcut && uv tool install physicalshortcut`.)
2. Mets à jour tes scripts : `handshortcut` → `physicalshortcut`, `HANDSHORTCUT_*` → `PHYSICALSHORTCUT_*`.
3. Si un de tes workflows appelle l'API locale avec l'en-tête `X-HandShortCut`, renomme-le en `X-PhysicalShortCut`.

## Renommer le dépôt GitHub (à faire par toi)

1. GitHub → **Settings** → **General** → *Repository name* → `PhysicalShortCut` → **Rename**.
   GitHub redirige automatiquement les anciennes URL (clone, issues, releases) vers le nouveau nom.
2. Localement : `git remote set-url origin https://github.com/yo-le-zz/PhysicalShortCut.git`.
3. Mets à jour la description du dépôt et ses *topics* si tu veux (`physical-computing`, `sensors`, `voice-control`, `gesture-recognition`).
4. Crée le tag `v2.0.0` : la CI construit les paquets et publie la release (voir `docs/github-setup.md`).

Les anciennes versions (1.0.0, 1.1.0) gardent l'ancien nom dans `CHANGELOG.md` : c'est l'historique.
