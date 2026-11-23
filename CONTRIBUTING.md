# Contribuer à HandShortCut

```bash
uv sync
uv run pytest
uv run ruff check src tests scripts
uv run python scripts/gen_docs.py --check
```

- **Nouveau type d'étape** : `steps.py` (catalogue) + `_step_<type>` dans `action_executor.py`, puis
  `python scripts/gen_docs.py`. L'interface se construit depuis le catalogue.
- **Interface** : après modification des templates, JS ou icônes, `cd frontend && npm install && npm run build`
  et versionne `webui/static/app.css` et `icons.svg`.
- **Icônes de l'application** : `python assets/make_icons.py` (ne modifie pas les PNG à la main).
- Messages en français, code et commentaires cohérents avec l'existant. Les tests ne doivent
  nécessiter ni caméra ni MediaPipe.
- Version : `pyproject.toml` est la source unique ; la tenir alignée avec `CHANGELOG.md`.
