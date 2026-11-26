"""Lecture/ecriture/rechargement a chaud de gestures.json et actions.json.

- thread-safe (verrou re-entrant) ;
- ecritures atomiques (fichier temporaire + ``os.replace``) ;
- detecte les modifications faites a la main (mtime) ;
- un JSON invalide ne fait jamais planter le daemon : la derniere
  configuration valide reste en memoire.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


# reglages propres a chaque type de geste (retires quand le geste change de type)
KIND_KEYS: dict[str, set[str]] = {
    "static": {"template", "hold_ms", "hands", "threshold"},
    "sequence": {"keyframes", "duration", "threshold", "hands"},
    "pose": {"fingers", "fingers_second", "hands", "hold_ms"},
    "count": {"hands", "min_value", "max_value", "hold_ms"},
    "draw": {"charset", "labels", "recognizer", "min_confidence", "pen", "idle_ms"},
    "sound": {"sound", "sensitivity", "level_db", "hold_ms"},
    "voice": {"phrases", "match"},
    "fingerprint": {"finger", "result"},
    "device": {"event", "match"},
    "sensor": {"metric", "arg", "op", "value", "edge", "hold_ms"},
}


def new_id() -> str:
    return uuid.uuid4().hex[:8]


_new_id = new_id


class ConfigStore:
    def __init__(self, data_dir: Path | str):
        self.data_dir = Path(data_dir)
        self.gestures_path = self.data_dir / "gestures.json"
        self.actions_path = self.data_dir / "actions.json"

        self._lock = threading.RLock()
        self._gestures: list[dict] = []
        self._actions: list[dict] = []
        self._mtimes = {"gestures": 0.0, "actions": 0.0}

        self.data_dir.mkdir(parents=True, exist_ok=True)
        for path in (self.gestures_path, self.actions_path):
            if not path.exists():
                self._atomic_write(path, [])
        self._load_initial()

    # ----------------------------------------------------------- fichiers
    @staticmethod
    def _atomic_write(path: Path, data: Any) -> None:
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)

    @staticmethod
    def _mtime(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    @staticmethod
    def _read_list(path: Path) -> list[dict]:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValueError("la racine du fichier doit etre une liste JSON")
        items = [item for item in data if isinstance(item, dict)]
        for item in items:
            item.setdefault("id", _new_id())
        return items

    def _load_initial(self) -> None:
        """Premier chargement : un fichier corrompu est mis de cote."""
        for kind, path in (("gestures", self.gestures_path), ("actions", self.actions_path)):
            try:
                items = self._read_list(path)
            except (OSError, ValueError) as exc:
                backup = path.with_name(f"{path.name}.corrupt-{time.strftime('%Y%m%d-%H%M%S')}")
                log.error(
                    "%s illisible (%s) : sauvegarde dans %s, demarrage a vide", path, exc, backup
                )
                with contextlib.suppress(OSError):
                    os.replace(path, backup)
                self._atomic_write(path, [])
                items = []
            setattr(self, f"_{kind}", items)
            self._mtimes[kind] = self._mtime(path)

    def reload_if_changed(self) -> bool:
        """Recharge si un fichier a change sur le disque. Retourne True si recharge."""
        changed = False
        with self._lock:
            for kind, path in (("gestures", self.gestures_path), ("actions", self.actions_path)):
                mtime = self._mtime(path)
                if mtime == self._mtimes[kind]:
                    continue
                self._mtimes[kind] = mtime  # evite de re-logger l'erreur a chaque tour
                try:
                    items = self._read_list(path)
                except (OSError, ValueError) as exc:
                    log.error(
                        "Rechargement de %s ignore (%s) : configuration precedente conservee",
                        path,
                        exc,
                    )
                    continue
                setattr(self, f"_{kind}", items)
                changed = True
                log.info("%s recharge (%d element(s))", path.name, len(items))
        return changed

    def _write(self, kind: str) -> None:
        path = self.gestures_path if kind == "gestures" else self.actions_path
        self._atomic_write(path, getattr(self, f"_{kind}"))
        self._mtimes[kind] = self._mtime(path)

    # ------------------------------------------------------------- gestes
    def get_gestures(self) -> list[dict]:
        with self._lock:
            return list(self._gestures)

    def get_gesture(self, gesture_id: str) -> dict | None:
        with self._lock:
            return next((g for g in self._gestures if g.get("id") == gesture_id), None)

    def save_gesture(self, gesture: dict) -> str:
        with self._lock:
            gesture = dict(gesture)
            gesture["id"] = gesture.get("id") or _new_id()
            for i, existing in enumerate(self._gestures):
                if existing.get("id") == gesture["id"]:
                    self._gestures[i] = gesture
                    break
            else:
                self._gestures.append(gesture)
            self._write("gestures")
            return gesture["id"]

    def update_gesture(self, gesture_id: str, patch: dict) -> dict | None:
        """Fusionne ``patch`` dans le geste. Un nouvel enregistrement (``type`` change)
        remplace l'ancien modele ; l'ancien format ``hold_frames`` est retire."""
        with self._lock:
            current = self.get_gesture(gesture_id)
            if current is None:
                return None
            updated = {**current, **patch}
            if "hold_ms" in patch:
                updated.pop("hold_frames", None)
            new_type = patch.get("type")
            if new_type in KIND_KEYS:
                # un changement de type retire les reglages propres aux autres types
                keep = KIND_KEYS[new_type] | set(patch)
                for kind, keys in KIND_KEYS.items():
                    if kind != new_type:
                        for key in keys - keep:
                            updated.pop(key, None)
                if new_type in ("sequence", "draw", "voice", "fingerprint", "device"):
                    updated.pop("hold_ms", None)
                    updated.pop("hold_frames", None)
            self.save_gesture(updated)
            return updated

    def duplicate_gesture(self, gesture_id: str) -> str | None:
        with self._lock:
            current = self.get_gesture(gesture_id)
            if current is None:
                return None
            copy = {**current, "id": None, "name": f"{current.get('name', 'Geste')} (copie)"}
            return self.save_gesture(copy)

    def delete_gesture(self, gesture_id: str) -> bool:
        with self._lock:
            before = len(self._gestures)
            self._gestures = [g for g in self._gestures if g.get("id") != gesture_id]
            if len(self._gestures) == before:
                return False
            self._write("gestures")
            return True

    # ------------------------------------------------------------ actions
    def get_actions(self) -> list[dict]:
        with self._lock:
            return list(self._actions)

    def get_action(self, action_id: str | None) -> dict | None:
        if not action_id:
            return None
        with self._lock:
            return next((a for a in self._actions if a.get("id") == action_id), None)

    def save_action(self, action: dict) -> str:
        with self._lock:
            action = dict(action)
            action["id"] = action.get("id") or _new_id()
            for i, existing in enumerate(self._actions):
                if existing.get("id") == action["id"]:
                    self._actions[i] = action
                    break
            else:
                self._actions.append(action)
            self._write("actions")
            return action["id"]

    def duplicate_action(self, action_id: str) -> str | None:
        with self._lock:
            current = self.get_action(action_id)
            if current is None:
                return None
            copy = json.loads(json.dumps(current))
            copy["id"] = None
            copy["name"] = f"{current.get('name', 'Action')} (copie)"
            return self.save_action(copy)

    def replace_all(self, gestures: list[dict], actions: list[dict]) -> None:
        """Remplace toute la configuration (import en mode « remplacer »)."""
        with self._lock:
            self._gestures = [dict(g) for g in gestures]
            self._actions = [dict(a) for a in actions]
            self._write("gestures")
            self._write("actions")

    def delete_action(self, action_id: str) -> bool:
        """Supprime l'action et delie les gestes qui la referencaient."""
        with self._lock:
            before = len(self._actions)
            self._actions = [a for a in self._actions if a.get("id") != action_id]
            if len(self._actions) == before:
                return False
            self._write("actions")
            relinked = False
            for gesture in self._gestures:
                if gesture.get("action_id") == action_id:
                    gesture["action_id"] = None
                    relinked = True
            if relinked:
                self._write("gestures")
            return True
