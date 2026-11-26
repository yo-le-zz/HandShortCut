"""Journal d'activite en direct : gestes reconnus, actions lancees, etapes executees.

Un petit tampon circulaire en memoire, alimente par le moteur de gestes et l'executeur,
lu par l'interface web (``/api/events``) pour afficher des notifications et l'historique.
Rien n'est ecrit sur le disque.
"""

from __future__ import annotations

import collections
import contextlib
import itertools
import threading
import time
from typing import Any

MAX_EVENTS = 500

_lock = threading.Lock()
_events: collections.deque[dict] = collections.deque(maxlen=MAX_EVENTS)
_counter = itertools.count(1)
_listeners: list = []


def emit(kind: str, **data: Any) -> dict:
    """Ajoute un evenement ``{id, ts, kind, ...}`` et previent les ecouteurs."""
    event = {"id": next(_counter), "ts": round(time.time(), 3), "kind": kind, **data}
    with _lock:
        _events.append(event)
        listeners = list(_listeners)
    for listener in listeners:
        with contextlib.suppress(Exception):  # un ecouteur ne doit jamais casser l'emetteur
            listener(event)
    return event


def since(last_id: int = 0, limit: int = 200) -> list[dict]:
    with _lock:
        return [e for e in _events if e["id"] > last_id][-limit:]


def last_id() -> int:
    with _lock:
        return _events[-1]["id"] if _events else 0


def subscribe(listener) -> None:
    with _lock:
        _listeners.append(listener)


def clear() -> None:
    """Vide le tampon et les ecouteurs (tests)."""
    with _lock:
        _events.clear()
        _listeners.clear()
