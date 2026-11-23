"""Interprete et execute une "action" : une liste d'etapes JSON.

Chaque etape a un `type` et ses parametres (voir ``steps.py``, le catalogue unique).
Champs communs a toutes les etapes :

* ``wait_ms``  : delai APRES l'etape ;
* ``only_on``  : ``windows`` ou ``linux`` -> l'etape est ignoree sur l'autre systeme
                 (une meme action sert sur les deux) ;
* ``enabled``  : ``false`` -> l'etape est ignoree (desactivee sans la supprimer).

Les etapes de logique (``if_*``, ``repeat``) lancent d'autres actions par leur
identifiant ; la profondeur et le nombre total d'etapes sont bornes (pas de boucle infinie).

Pour ajouter un type d'etape : le declarer dans ``steps.py``, ecrire un
`_step_<type>(step)` ici et l'ajouter a ``_HANDLERS`` (un test verifie la synchro).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from . import platform_utils as pu
from .steps import STEPS

log = logging.getLogger(__name__)

MAX_DEPTH = 5  # actions imbriquees (if_* / repeat)
MAX_TOTAL_STEPS = 5000  # etapes executees par declenchement, toutes actions confondues

Resolver = Callable[[str], dict | None]
_resolver: Resolver | None = None
_context = threading.local()


def set_resolver(resolver: Resolver | None) -> None:
    """Fonction qui retrouve une action par son identifiant (pour if_* et repeat)."""
    global _resolver
    _resolver = resolver


class _Run:
    """Etat d'un declenchement : pile d'actions et compteur d'etapes."""

    def __init__(self) -> None:
        self.stack: list[str] = []
        self.steps = 0


def run_action(action: dict) -> threading.Thread:
    """Execute l'action dans un thread : ne bloque jamais la detection."""
    thread = threading.Thread(target=run_action_sync, args=(action,), name="action", daemon=True)
    thread.start()
    return thread


def run_action_sync(action: dict) -> None:
    run = getattr(_context, "run", None)
    owner = run is None
    if owner:
        run = _context.run = _Run()
    try:
        _run_action(action, run)
    finally:
        if owner:
            _context.run = None


def _run_action(action: dict, run: _Run) -> None:
    name = action.get("name") or action.get("id") or "?"
    marker = str(action.get("id") or name)
    if len(run.stack) >= MAX_DEPTH:
        log.error("Action %r ignoree : %d actions imbriquees au maximum", name, MAX_DEPTH)
        return
    if marker in run.stack:
        log.error("Action %r ignoree : appel circulaire (%s)", name, " > ".join([*run.stack, marker]))
        return
    run.stack.append(marker)
    log.info("Execution de l'action %r", name)
    try:
        for index, step in enumerate(action.get("steps", []), start=1):
            if run.steps >= MAX_TOTAL_STEPS:
                log.error("Action %r interrompue : plus de %d etapes executees", name, MAX_TOTAL_STEPS)
                return
            if not isinstance(step, dict):
                log.error("Action %r, etape %d ignoree : objet attendu", name, index)
                continue
            if not _should_run(step, index):
                continue
            run.steps += 1
            _run_step(step, index)
            _sleep_ms(step.get("wait_ms"), f"etape {index} : wait_ms")
    finally:
        run.stack.pop()


def _should_run(step: dict, index: int) -> bool:
    if step.get("enabled") is False:
        log.debug("Etape %d desactivee : ignoree", index)
        return False
    only_on = step.get("only_on")
    if only_on in ("windows", "linux") and only_on != pu.current_os():
        log.debug("Etape %d reservee a %s : ignoree", index, only_on)
        return False
    return True


def _sleep_ms(value, what: str) -> None:
    if not value:
        return
    try:
        time.sleep(max(0.0, float(value)) / 1000.0)
    except (TypeError, ValueError):
        log.error("%s invalide (%r)", what, value)


def _run_step(step: dict, index: int = 0) -> None:
    step_type = step.get("type")
    handler = _HANDLERS.get(step_type)
    if handler is None:
        log.error("Etape %d : type inconnu %r", index, step_type)
        return
    try:
        handler(step)
    except Exception:
        log.exception("Etape %d (%s) en erreur", index, step_type)


# --------------------------------------------------------------- parametres


def _param(step: dict, key: str):
    """Valeur d'un parametre, avec la valeur par defaut du catalogue."""
    value = step.get(key)
    if value is not None and value != "":
        return value
    spec = STEPS.get(step.get("type"))
    if spec is not None:
        for field in spec.fields:
            if field.key == key:
                return field.default
    return None


def _int(step: dict, key: str, fallback: int = 0) -> int:
    try:
        return int(float(_param(step, key)))
    except (TypeError, ValueError):
        return fallback


def _text(step: dict, key: str) -> str:
    value = _param(step, key)
    return "" if value is None else str(value)


def _path(step: dict, key: str = "path") -> str:
    return pu.expand_path(_text(step, key)) if _text(step, key) else ""


# ------------------------------------------------- fenetres & applications


def _step_launch(step: dict) -> None:
    args = step.get("args")
    if isinstance(args, str):
        args = [a.strip() for a in args.split(",") if a.strip()]
    pu.launch_app(step.get("path"), args, step.get("shell_cmd"))


def _step_open_path(step: dict) -> None:
    pu.open_path(_text(step, "path"))


def _step_move_window(step: dict) -> None:
    pu.move_window(
        title_contains=_text(step, "title_contains"),
        monitor_index=_int(step, "monitor", 1) or 1,
        position=_text(step, "position") or "fullscreen",
    )


def _step_close_window(step: dict) -> None:
    pu.close_window(_text(step, "title_contains"))


def _step_focus_window(step: dict) -> None:
    pu.focus_window(_text(step, "title_contains"))


def _step_minimize_window(step: dict) -> None:
    pu.minimize_window(_text(step, "title_contains"))


def _step_maximize_window(step: dict) -> None:
    pu.maximize_window(_text(step, "title_contains"))


def _step_restore_window(step: dict) -> None:
    pu.restore_window(_text(step, "title_contains"))


def _step_wait_for_window(step: dict) -> None:
    pu.wait_for_window(_text(step, "title_contains"), _int(step, "timeout_ms", 10000) / 1000.0)


def _step_show_desktop(step: dict) -> None:
    pu.show_desktop(_text(step, "mode") or "toggle")


def _step_switch_desktop(step: dict) -> None:
    index = _int(step, "index", 0) or None
    pu.switch_desktop(_text(step, "target") or "next", index)


# --------------------------------------------------------- clavier & souris


def _step_keypress(step: dict) -> None:
    pu.send_keypress(_text(step, "keys"))


def _step_type_text(step: dict) -> None:
    pu.type_text(_text(step, "text"), _int(step, "interval_ms", 0) / 1000.0)


def _step_mouse_move(step: dict) -> None:
    gui = pu.pyautogui_module()
    if gui is not None:
        gui.moveTo(_int(step, "x"), _int(step, "y"))


def _click(step: dict, clicks: int) -> None:
    gui = pu.pyautogui_module()
    if gui is None:
        return
    button = _text(step, "button") or "left"
    if step.get("x") is not None and step.get("y") is not None:
        gui.click(_int(step, "x"), _int(step, "y"), clicks=clicks, button=button)
    else:
        gui.click(clicks=clicks, button=button)


def _step_mouse_click(step: dict) -> None:
    _click(step, 1)


def _step_mouse_double_click(step: dict) -> None:
    _click(step, 2)


def _step_mouse_drag(step: dict) -> None:
    gui = pu.pyautogui_module()
    if gui is None:
        return
    if step.get("from_x") is not None and step.get("from_y") is not None:
        gui.moveTo(_int(step, "from_x"), _int(step, "from_y"))
    gui.dragTo(
        _int(step, "x"),
        _int(step, "y"),
        duration=_int(step, "duration_ms", 300) / 1000.0,
        button=_text(step, "button") or "left",
    )


def _step_mouse_scroll(step: dict) -> None:
    gui = pu.pyautogui_module()
    if gui is None:
        return
    direction = _text(step, "direction") or "up"
    amount = max(1, _int(step, "amount", 3)) * 100
    if direction in ("up", "down"):
        gui.scroll(amount if direction == "up" else -amount)
    else:
        try:
            gui.hscroll(amount if direction == "right" else -amount)
        except (AttributeError, NotImplementedError):
            log.warning("Defilement horizontal non gere par ce systeme")


def _step_clipboard_set(step: dict) -> None:
    import pyperclip

    pyperclip.copy(_text(step, "text"))


def _step_clipboard_get_and_type(step: dict) -> None:
    import pyperclip

    pu.type_text(pyperclip.paste())


# ------------------------------------------------------------- media & voix


def _step_media_control(step: dict) -> None:
    pu.media_control(_text(step, "action"))


def _step_set_volume(step: dict) -> None:
    pu.set_volume(_int(step, "level", 50))


def _step_play_sound(step: dict) -> None:
    pu.play_sound(_text(step, "path"))


def _step_speak(step: dict) -> None:
    pu.speak(_text(step, "text"))


# -------------------------------------------------------------------- web


def _step_open_url(step: dict) -> None:
    pu.open_url(_text(step, "url"))


def _step_http_request(step: dict) -> None:
    url = _text(step, "url")
    if not url.lower().startswith(("http://", "https://")):
        log.error("http_request : l'URL doit commencer par http:// ou https:// (%r)", url)
        return
    method = (_text(step, "method") or "GET").upper()
    body = step.get("body")

    data = None
    headers = {"User-Agent": "HandShortCut"}
    if body:
        data = str(body).encode("utf-8")
        try:
            json.loads(body)
            headers["Content-Type"] = "application/json"
        except (TypeError, ValueError):
            headers["Content-Type"] = "text/plain; charset=utf-8"

    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310 (http/https verifie)
            log.info("%s %s -> %s", method, url, response.status)
    except urllib.error.HTTPError as exc:
        log.warning("%s %s -> HTTP %s", method, url, exc.code)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        log.error("%s %s a echoue : %s", method, url, exc)


def _step_websocket_send(step: dict) -> None:
    url = _text(step, "url")
    if not url.lower().startswith(("ws://", "wss://")):
        log.error("websocket_send : l'URL doit commencer par ws:// ou wss://")
        return
    try:
        import websocket
    except ImportError:
        log.error("websocket-client n'est pas installe (pip install websocket-client)")
        return
    try:
        ws = websocket.create_connection(url, timeout=5)
        try:
            ws.send(_text(step, "message"))
        finally:
            ws.close()
        log.info("Message WebSocket envoye a %s", url)
    except Exception as exc:  # noqa: BLE001 - erreurs reseau variees
        log.error("Erreur WebSocket : %s", exc)


# --------------------------------------------------------------- fichiers


def _step_file_write(step: dict) -> None:
    path = _path(step)
    if not path:
        return
    mode = "a" if step.get("append") else "w"
    try:
        with open(path, mode, encoding="utf-8") as f:
            f.write(_text(step, "content"))
        log.info("Fichier ecrit : %s", path)
    except OSError as exc:
        log.error("Erreur ecriture fichier %s : %s", path, exc)


def _step_file_read(step: dict) -> None:
    path = _path(step)
    if not path:
        return
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
        log.info("Fichier lu : %s (%d caracteres)", path, len(content))
        log.debug("Contenu de %s : %.500s", path, content)
    except OSError as exc:
        log.error("Erreur lecture fichier %s : %s", path, exc)


def _step_file_delete(step: dict) -> None:
    path = _path(step)
    if not path:
        return
    try:
        os.remove(path)
        log.info("Fichier supprime : %s", path)
    except OSError as exc:
        log.error("Erreur suppression fichier %s : %s", path, exc)


def _step_file_copy(step: dict) -> None:
    source, destination = _path(step, "source"), _path(step, "destination")
    if not source or not destination:
        return
    try:
        Path(destination).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        log.info("Fichier copie : %s -> %s", source, destination)
    except OSError as exc:
        log.error("Erreur copie %s -> %s : %s", source, destination, exc)


def _step_file_move(step: dict) -> None:
    source, destination = _path(step, "source"), _path(step, "destination")
    if not source or not destination:
        return
    try:
        Path(destination).parent.mkdir(parents=True, exist_ok=True)
        shutil.move(source, destination)
        log.info("Fichier deplace : %s -> %s", source, destination)
    except OSError as exc:
        log.error("Erreur deplacement %s -> %s : %s", source, destination, exc)


def _step_directory_create(step: dict) -> None:
    path = _path(step)
    if not path:
        return
    try:
        os.makedirs(path, exist_ok=True)
        log.info("Dossier cree : %s", path)
    except OSError as exc:
        log.error("Erreur creation dossier %s : %s", path, exc)


def _step_screenshot(step: dict) -> None:
    path = _path(step)
    if path and pu.screenshot(path):
        log.info("Capture d'ecran enregistree : %s", path)


# ---------------------------------------------------------------- systeme


def _step_run_shell(step: dict) -> None:
    cmd = _text(step, "cmd")
    if cmd:
        pu.spawn(cmd, shell=True)


def _step_kill_process(step: dict) -> None:
    name = _text(step, "name").strip().lower()
    if not name:
        return
    import psutil

    own_pid = os.getpid()
    killed = 0
    for proc in psutil.process_iter(["name", "pid"]):
        try:
            if proc.info["pid"] != own_pid and name in (proc.info.get("name") or "").lower():
                proc.terminate()
                killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if not killed:
        log.info("kill_process : aucun processus ne correspond a %r", name)


def _step_notify(step: dict) -> None:
    pu.notify(_text(step, "title") or "HandShortCut", _text(step, "message"))


def _step_change_brightness(step: dict) -> None:
    pu.set_brightness(_int(step, "level", 50))


def _step_change_wallpaper(step: dict) -> None:
    pu.set_wallpaper(_text(step, "path"))


def _step_set_theme(step: dict) -> None:
    pu.set_theme(_text(step, "mode") or "toggle")


def _step_power_action(step: dict) -> None:
    action = _text(step, "action") or "lock"
    log.warning("Action d'alimentation : %s", action)
    pu.power_action(action)


# ---------------------------------------------------------------- logique


def _step_wait(step: dict) -> None:
    time.sleep(max(0, _int(step, "ms", 0)) / 1000.0)


def _nested(action_id: str | None, what: str) -> None:
    """Execute une autre action (dans le meme thread, avec les garde-fous du declenchement)."""
    if not action_id:
        return
    action = _resolver(action_id) if _resolver else None
    if action is None:
        log.error("%s : action %r introuvable", what, action_id)
        return
    run = getattr(_context, "run", None)
    if run is None:  # appel direct hors declenchement (tests)
        run_action_sync(action)
    else:
        _run_action(action, run)


def _branch(step: dict, condition: bool, what: str) -> None:
    chosen = step.get("action_id") if condition else step.get("else_action_id")
    log.info("%s : condition %s", what, "vraie" if condition else "fausse")
    _nested(chosen, what)


def _step_if_window_exists(step: dict) -> None:
    _branch(step, pu.window_exists(_text(step, "title_contains")), "if_window_exists")


def _process_running(name: str) -> bool:
    import psutil

    name = name.strip().lower()
    if not name:
        return False
    for proc in psutil.process_iter(["name"]):
        try:
            if name in (proc.info.get("name") or "").lower():
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False


def _step_if_process_running(step: dict) -> None:
    _branch(step, _process_running(_text(step, "name")), "if_process_running")


def _step_repeat(step: dict) -> None:
    count = max(1, _int(step, "count", 1))
    for i in range(count):
        _nested(step.get("action_id"), "repeat")
        if i < count - 1:
            _sleep_ms(_param(step, "delay_ms"), "repeat : delay_ms")


_HANDLERS: dict[str, Callable[[dict], None]] = {
    "launch": _step_launch,
    "open_path": _step_open_path,
    "move_window": _step_move_window,
    "close_window": _step_close_window,
    "focus_window": _step_focus_window,
    "minimize_window": _step_minimize_window,
    "maximize_window": _step_maximize_window,
    "restore_window": _step_restore_window,
    "wait_for_window": _step_wait_for_window,
    "show_desktop": _step_show_desktop,
    "switch_desktop": _step_switch_desktop,
    "keypress": _step_keypress,
    "type_text": _step_type_text,
    "mouse_move": _step_mouse_move,
    "mouse_click": _step_mouse_click,
    "mouse_double_click": _step_mouse_double_click,
    "mouse_drag": _step_mouse_drag,
    "mouse_scroll": _step_mouse_scroll,
    "clipboard_set": _step_clipboard_set,
    "clipboard_get_and_type": _step_clipboard_get_and_type,
    "media_control": _step_media_control,
    "set_volume": _step_set_volume,
    "play_sound": _step_play_sound,
    "speak": _step_speak,
    "open_url": _step_open_url,
    "http_request": _step_http_request,
    "websocket_send": _step_websocket_send,
    "file_write": _step_file_write,
    "file_read": _step_file_read,
    "file_delete": _step_file_delete,
    "file_copy": _step_file_copy,
    "file_move": _step_file_move,
    "directory_create": _step_directory_create,
    "screenshot": _step_screenshot,
    "run_shell": _step_run_shell,
    "kill_process": _step_kill_process,
    "notify": _step_notify,
    "change_brightness": _step_change_brightness,
    "change_wallpaper": _step_change_wallpaper,
    "set_theme": _step_set_theme,
    "power_action": _step_power_action,
    "wait": _step_wait,
    "if_window_exists": _step_if_window_exists,
    "if_process_running": _step_if_process_running,
    "repeat": _step_repeat,
}
