# Publier HandShortCut sur GitHub

## Description du dépôt (About)

> Gestes de la main via webcam (MediaPipe) → actions : apps, fenêtres, raccourcis, volume, URL, API, commandes. Interface web locale, Windows & Linux, .deb / .rpm / .msi.

Site web : laisser vide (ou l'URL des releases).

## Topics (tags)

`hand-gesture` `gesture-recognition` `gesture-control` `mediapipe` `opencv` `webcam`
`computer-vision` `automation` `shortcuts` `flask` `linux` `windows` `wayland` `python` `nuitka` `msi`

## Appliquer en une commande (GitHub CLI)

```bash
gh repo edit yo-le-zz/HandShortCut \
  --description "Gestes de la main via webcam (MediaPipe) → actions : apps, fenêtres, raccourcis, volume, URL, API, commandes. Interface web locale, Windows & Linux, .deb / .rpm / .msi." \
  --add-topic hand-gesture,gesture-recognition,gesture-control,mediapipe,opencv,webcam,computer-vision,automation,shortcuts,flask,linux,windows,wayland,python,nuitka,msi
```

## Réglages recommandés
- *Settings → Actions → General → Workflow permissions* : **Read and write** (nécessaire pour créer la release).
- *Settings → Code and automation → Tags* : protéger le motif `v*` si tu veux.
- Activer *Issues* et *Discussions* ; ajouter `docs/releases/v1.0.0.md` comme texte de la première release si tu préfères le saisir à la main.

## Publier une version
1. `version` dans `pyproject.toml` + section dans `CHANGELOG.md`.
2. `git tag v1.0.0 && git push origin v1.0.0`.
3. Le workflow `release.yml` construit et publie `.deb`, `.rpm`, `.exe`, `.msi` et `SHA256SUMS`.

Test à blanc : *Actions → Release → Run workflow* construit tout sans publier (artefacts téléchargeables).
