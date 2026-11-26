"""Notifications du bureau : un abonne du journal d'activite (``events``).

Affiche une notification systeme quand un geste declenche une action (ou quand une action echoue),
selon les reglages (``notify_desktop`` / ``notify_errors``). L'envoi se fait dans un thread
pour ne jamais ralentir la detection.
"""

from __future__ import annotations

import threading

from . import events
from . import platform_utils as pu
from . import settings as settings_mod


def _send(title: str, message: str) -> None:
    threading.Thread(target=pu.notify, args=(title, message), name="notify", daemon=True).start()


def on_event(event: dict) -> None:
    cfg = settings_mod.current()
    kind = event.get("kind")
    if kind == "gesture" and cfg.get("notify_desktop"):
        action = event.get("action")
        value = event.get("value")
        extra = f" (valeur : {value})" if value not in (None, "") else ""
        _send(f"PhysicalShortCut : {event.get('gesture') or 'Geste'}{extra}", f"Action : {action}" if action else "Aucune action liée")
    elif kind == "action_end" and not event.get("ok", True) and cfg.get("notify_errors"):
        _send("PhysicalShortCut : erreur", f"L'action « {event.get('action') or '?'} » a rencontré {event.get('errors') or 1} erreur(s)")


def install() -> None:
    events.subscribe(on_event)
