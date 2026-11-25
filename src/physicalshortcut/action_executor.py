"""Interprete et execute un « workflow » : un graphe de noeuds relies entre eux.

Format d'une action (``actions.json``) :

* **graphe** : ``{"nodes": [...], "edges": [{"from": id, "port": "out", "to": id}]}`` ;
* **liste** (ancien format) : ``{"steps": [...]}`` -> convertie a la volee en chaine de noeuds.

Execution : on part du noeud ``trigger`` (ou des noeuds sans entree), on execute le noeud,
puis on suit les liaisons du port choisi par le noeud :

* ``out``                        suite normale ;
* ``true`` / ``false``           noeuds conditionnels (``if_*``) ; ``out`` est suivi apres, dans tous les cas ;
* ``each`` / ``done``            boucle ``for_each`` : ``each`` pour chaque element, puis ``done`` ;
* ``error``                      suivi si le noeud a echoue ; sans liaison ``error``, on continue sur ``out``
                                 (sauf ``on_error = "stop"``).

**Donnees** : chaque noeud range sa sortie dans une variable portant son ``name`` ; les champs
des noeuds suivants la lisent avec ``{{ name }}`` (voir ``templating.py``). Variables
predefinies : ``gesture`` (geste declencheur : ``gesture.value``...), ``system`` (mesures),
``args`` (arguments d'un sous-workflow), ``last`` (derniere sortie), ``now``, ``env``, ``loop``.

Champs communs a tous les noeuds : ``wait_ms`` (pause apres), ``only_on`` (windows / linux),
``enabled`` (false = noeud traverse sans rien faire), ``name``, ``on_error``.

Pour ajouter un type de noeud : le declarer dans ``steps.py``, ecrire ``_step_<type>(step)``
ici (il peut renvoyer une valeur = sa sortie) et l'ajouter a ``_HANDLERS``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import ai, events, system_metrics, templating
from . import hands as handlib
from . import platform_utils as pu
from .steps import STEPS

log = logging.getLogger(__name__)

MAX_DEPTH = 5  # workflows imbriques (sous-workflows, if_*, repeat, for_each)
MAX_TOTAL_STEPS = 5000  # noeuds executes par declenchement, tous workflows confondus
MAX_LOOP_ITEMS = 1000
MAX_FILE_BYTES = 5_000_000
MAX_HTTP_BYTES = 2_000_000

# champs jamais traites comme modele {{ }} avant l'appel du noeud
NO_RENDER = {
    "type", "id", "name", "save_as", "x", "y", "enabled", "only_on", "on_error", "label",
    "action_id", "else_action_id", "condition", "variable", "item_var",
}

Resolver = Callable[[str], dict | None]
_resolver: Resolver | None = None
_context = threading.local()
_providers: dict[str, Callable[[], Any] | None] = {"frame": None, "vector": None}


def set_resolver(resolver: Resolver | None) -> None:
    """Fonction qui retrouve une action par son identifiant (sous-workflows)."""
    global _resolver
    _resolver = resolver


def set_providers(frame: Callable[[], bytes | None] | None = None, vector: Callable[[], list[float] | None] | None = None) -> None:
    """Acces a la camera : derniere image (JPEG) et derniere main analysee."""
    _providers["frame"] = frame
    _providers["vector"] = vector


@dataclass
class Branch:
    """Resultat d'un noeud conditionnel : le port a suivre et la valeur de sortie."""

    port: str
    value: Any = None


@dataclass
class _Run:
    """Etat d'un declenchement."""

    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    stack: list[str] = field(default_factory=list)
    steps: int = 0
    vars: dict[str, Any] = field(default_factory=dict)
    stopped: bool = False
    errors: int = 0


# --------------------------------------------------------------------------
# Capture des erreurs journalisees pendant un noeud
# --------------------------------------------------------------------------


class _Capture(logging.Handler):
    """Releve les avertissements / erreurs emis (par n'importe quel module) pendant un noeud."""

    def emit(self, record: logging.LogRecord) -> None:
        bucket = getattr(_context, "capture", None)
        if bucket is not None and record.levelno >= logging.WARNING:
            bucket.append((record.levelno, record.getMessage()))


_capture_installed = False


def _ensure_capture() -> None:
    global _capture_installed
    if not _capture_installed:
        logging.getLogger("physicalshortcut").addHandler(_Capture(level=logging.WARNING))
        _capture_installed = True


# --------------------------------------------------------------------------
# Modele de graphe
# --------------------------------------------------------------------------

TRIGGER = "trigger"


def to_graph(action: dict) -> tuple[list[dict], list[dict]]:
    """Action -> (noeuds, liaisons), quel que soit son format (graphe ou liste d'etapes)."""
    if isinstance(action.get("nodes"), list):
        return action["nodes"], [e for e in action.get("edges", []) if isinstance(e, dict)]
    nodes = [{"id": "n0", "type": TRIGGER}]
    edges = []
    for i, step in enumerate(action.get("steps", []), start=1):
        if not isinstance(step, dict):
            continue
        nodes.append({**step, "id": f"n{i}"})
        edges.append({"from": f"n{i - 1}", "port": "out", "to": f"n{i}"})
    return nodes, edges


class _Graph:
    def __init__(self, action: dict):
        nodes, edges = to_graph(action)
        self.nodes: dict[str, dict] = {str(n.get("id")): n for n in nodes if isinstance(n, dict) and n.get("id") is not None}
        self.order = list(self.nodes)
        self.out: dict[tuple[str, str], list[str]] = {}
        incoming: set[str] = set()
        for edge in edges:
            src, dst = str(edge.get("from")), str(edge.get("to"))
            if src in self.nodes and dst in self.nodes:
                self.out.setdefault((src, edge.get("port") or "out"), []).append(dst)
                incoming.add(dst)
        entries = [nid for nid, n in self.nodes.items() if n.get("type") == TRIGGER]
        self.entries = entries or [nid for nid in self.order if nid not in incoming][:1] or self.order[:1]

    def targets(self, node_id: str, port: str) -> list[str]:
        found = list(self.out.get((node_id, port), []))
        if port not in ("out", "error"):  # « out » = suite commune apres vrai/faux/termine ; jamais apres une erreur
            found += self.out.get((node_id, "out"), [])
        return found

    def has_edges(self, node_id: str, port: str) -> bool:
        return bool(self.out.get((node_id, port)))


# --------------------------------------------------------------------------
# Lancement
# --------------------------------------------------------------------------


def run_action(action: dict, context: dict | None = None) -> threading.Thread:
    """Execute le workflow dans un thread : ne bloque jamais la detection."""
    thread = threading.Thread(target=run_action_sync, args=(action, context), name="action", daemon=True)
    thread.start()
    return thread


def run_action_sync(action: dict, context: dict | None = None) -> dict:
    """Execute le workflow ; renvoie ``{"ok", "vars", "ms"}`` (utile aux tests et au bouton « Tester »)."""
    _ensure_capture()
    run = getattr(_context, "run", None)
    owner = run is None
    started = time.perf_counter()
    if owner:
        run = _context.run = _Run(vars=_initial_vars(context))
        events.emit(
            "action_start", run_id=run.run_id, action_id=action.get("id"),
            action=action.get("name") or "?", trigger=(context or {}).get("name"),
        )
    try:
        _run_action(action, run)
    finally:
        if owner:
            _context.run = None
    ms = round((time.perf_counter() - started) * 1000)
    if owner:
        events.emit(
            "action_end", run_id=run.run_id, action_id=action.get("id"), action=action.get("name") or "?",
            ok=run.errors == 0, errors=run.errors, steps=run.steps, ms=ms,
        )
    return {"ok": run.errors == 0, "vars": run.vars, "ms": ms}


def _initial_vars(context: dict | None) -> dict[str, Any]:
    now = time.localtime()
    gesture = dict(context or {})
    return {
        "gesture": gesture,
        "trigger": gesture,
        "system": system_metrics.SystemVars(),
        "args": {},
        "last": None,
        "loop": {},
        "env": dict(os.environ),
        "now": {
            "iso": time.strftime("%Y-%m-%dT%H:%M:%S", now), "date": time.strftime("%Y-%m-%d", now),
            "time": time.strftime("%H:%M:%S", now), "hour": now.tm_hour, "minute": now.tm_min,
            "weekday": now.tm_wday + 1, "timestamp": int(time.time()),
        },
    }


def _run_action(action: dict, run: _Run, args: dict | None = None) -> Any:
    name = action.get("name") or action.get("id") or "?"
    marker = str(action.get("id") or name)
    if len(run.stack) >= MAX_DEPTH:
        log.error("Workflow %r ignore : %d workflows imbriques au maximum", name, MAX_DEPTH)
        run.errors += 1
        return None
    if marker in run.stack:
        log.error("Workflow %r ignore : appel circulaire (%s)", name, " > ".join([*run.stack, marker]))
        run.errors += 1
        return None
    run.stack.append(marker)
    saved_args = run.vars.get("args")
    saved_result = run.vars.get("result")
    if args is not None:
        run.vars["args"] = args
        run.vars["result"] = None
    log.info("Execution du workflow %r", name)
    try:
        graph = _Graph(action)
        _walk(graph, graph.entries, run, name)
        result = run.vars.get("result") if args is not None else None
        return result if result is not None else run.vars.get("last")
    finally:
        run.stack.pop()
        if args is not None:
            run.vars["args"] = saved_args
            run.vars["result"] = saved_result


def _walk(graph: _Graph, start: list[str], run: _Run, action_name: str) -> None:
    """Parcours iteratif : pas de recursion, donc pas de limite de profondeur sur de longues chaines."""
    stack = list(reversed(start))
    while stack:
        if run.stopped:
            return
        if run.steps >= MAX_TOTAL_STEPS:
            log.error("Workflow %r interrompu : plus de %d noeuds executes", action_name, MAX_TOTAL_STEPS)
            run.errors += 1
            run.stopped = True
            return
        node = graph.nodes[stack.pop()]
        port = _exec_node(node, graph, run)
        if port:
            stack.extend(reversed(graph.targets(str(node["id"]), port)))


def _should_run(step: dict) -> bool:
    if step.get("enabled") is False:
        return False
    only_on = step.get("only_on")
    return not (only_on in ("windows", "linux") and only_on != pu.current_os())


def _node_label(node: dict) -> str:
    spec = STEPS.get(node.get("type"))
    return str(node.get("label") or (spec.label if spec else node.get("type")) or "?")


def _exec_node(node: dict, graph: _Graph, run: _Run) -> str | None:
    """Execute un noeud ; renvoie le port a suivre (``None`` = arret de cette branche)."""
    step_type = node.get("type")
    node_id = str(node.get("id"))
    base_event = {"run_id": run.run_id, "node_id": node_id, "step": step_type, "label": _node_label(node)}

    if step_type == TRIGGER:
        return "out"
    if not _should_run(node):
        events.emit("step", status="skipped", ms=0, **base_event)
        return "out"
    handler = _HANDLERS.get(step_type)
    if handler is None:
        log.error("Noeud %s : type inconnu %r", node_id, step_type)
        run.errors += 1
        events.emit("step", status="error", ms=0, errors=[f"type inconnu {step_type!r}"], **base_event)
        return "error" if graph.has_edges(node_id, "error") else "out"

    run.steps += 1
    started = time.perf_counter()
    bucket: list[tuple[int, str]] = []
    _context.capture = bucket
    output: Any = None
    port = "out"
    failed = False
    try:
        rendered = _render_step(node, run.vars)
        if step_type == "for_each":
            output, port = _for_each(rendered, graph, run, node)
        else:
            result = handler(rendered)
            if isinstance(result, Branch):
                output, port = result.value, result.port
            else:
                output = result
    except Exception as exc:  # noqa: BLE001 - un noeud en echec ne doit jamais arreter l'application
        log.exception("Noeud %s (%s) en erreur", node_id, step_type) if not isinstance(exc, templating.TemplateError) else log.error(
            "Noeud %s (%s) : %s", node_id, step_type, exc
        )
        failed = True
    finally:
        _context.capture = None

    errors = [m for level, m in bucket if level >= logging.ERROR]
    failed = failed or bool(errors)
    if failed:
        run.errors += 1
    ms = round((time.perf_counter() - started) * 1000)

    name = node.get("name") or node.get("save_as")
    if not failed or output is not None:
        if name:
            run.vars[str(name)] = output
        if output is not None:
            run.vars["last"] = output
    events.emit(
        "step", status="error" if failed else "ok", ms=ms, errors=errors[-3:],
        output=templating.preview(output) if output is not None else None, **base_event,
    )
    _sleep_ms(node.get("wait_ms"), f"noeud {node_id} : wait_ms")

    if failed:
        if graph.has_edges(node_id, "error"):
            return "error"
        return None if node.get("on_error") == "stop" else port
    return port


def _render_step(node: dict, variables: dict[str, Any]) -> dict:
    rendered: dict[str, Any] = {}
    for key, value in node.items():
        rendered[key] = value if key in NO_RENDER else templating.render(value, variables)
    return rendered


def _sleep_ms(value, what: str) -> None:
    if not value:
        return
    try:
        time.sleep(max(0.0, float(value)) / 1000.0)
    except (TypeError, ValueError):
        log.error("%s invalide (%r)", what, value)


def _current_run() -> _Run:
    run = getattr(_context, "run", None)
    if run is None:  # appel direct d'un handler hors declenchement (tests)
        run = _context.run = _Run(vars=_initial_vars(None))
    return run


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


def _step_clipboard_get(step: dict) -> str:
    import pyperclip

    return pyperclip.paste()


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


def _step_http_request(step: dict) -> dict | None:
    url = _text(step, "url")
    if not url.lower().startswith(("http://", "https://")):
        log.error("http_request : l'URL doit commencer par http:// ou https:// (%r)", url)
        return None
    method = (_text(step, "method") or "GET").upper()
    body = step.get("body")

    data = None
    headers = {"User-Agent": "PhysicalShortCut"}
    if body:
        data = str(body).encode("utf-8")
        try:
            json.loads(body)
            headers["Content-Type"] = "application/json"
        except (TypeError, ValueError):
            headers["Content-Type"] = "text/plain; charset=utf-8"

    extra = step.get("headers")
    if isinstance(extra, str) and extra.strip():
        for line in extra.splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                headers[key.strip()] = value.strip()

    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=_int(step, "timeout_s", 10)) as response:  # noqa: S310 (http/https verifie)
            log.info("%s %s -> %s", method, url, response.status)
            return _http_result(response.status, response.read(MAX_HTTP_BYTES))
    except urllib.error.HTTPError as exc:
        log.warning("%s %s -> HTTP %s", method, url, exc.code)
        return _http_result(exc.code, exc.read(MAX_HTTP_BYTES))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        log.error("%s %s a echoue : %s", method, url, exc)
    return None


def _http_result(status: int, raw: bytes) -> dict:
    body = raw.decode("utf-8", errors="replace")
    try:
        parsed = json.loads(body)
    except ValueError:
        parsed = None
    return {"status": status, "ok": 200 <= status < 300, "body": body, "json": parsed}


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


def _step_file_write(step: dict) -> str | None:
    path = _path(step)
    if not path:
        return None
    mode = "a" if step.get("append") else "w"
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, mode, encoding="utf-8") as f:
            f.write(_text(step, "content"))
        log.info("Fichier ecrit : %s", path)
        return path
    except OSError as exc:
        log.error("Erreur ecriture fichier %s : %s", path, exc)
    return None


def _step_file_read(step: dict) -> str | None:
    path = _path(step)
    if not path:
        return None
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            content = f.read(MAX_FILE_BYTES)
        log.info("Fichier lu : %s (%d caracteres)", path, len(content))
        return content
    except OSError as exc:
        log.error("Erreur lecture fichier %s : %s", path, exc)
    return None


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


def _step_screenshot(step: dict) -> str | None:
    path = _path(step)
    if path and pu.screenshot(path):
        log.info("Capture d'ecran enregistree : %s", path)
        return path
    return None


# ---------------------------------------------------------------- systeme


def _step_run_shell(step: dict) -> dict | None:
    cmd = _text(step, "cmd")
    if not cmd:
        return None
    if not step.get("capture"):
        pu.spawn(cmd, shell=True)
        return None
    try:
        done = subprocess.run(  # noqa: S602 (commande ecrite par l'utilisateur, comme le champ « shell »)
            cmd, shell=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=max(1, _int(step, "timeout_s", 30)), check=False,
        )
    except subprocess.TimeoutExpired:
        log.error("run_shell : delai depasse (%s s)", _int(step, "timeout_s", 30))
        return None
    except OSError as exc:
        log.error("run_shell : %s", exc)
        return None
    if done.returncode != 0:
        log.warning("run_shell : code de sortie %s", done.returncode)
    return {"stdout": done.stdout.strip(), "stderr": done.stderr.strip(), "code": done.returncode, "ok": done.returncode == 0}


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
    pu.notify(_text(step, "title") or "PhysicalShortCut", _text(step, "message"))


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


def _nested(action_id: str | None, what: str, args: dict | None = None) -> Any:
    """Execute un autre workflow (meme thread, memes garde-fous et memes variables)."""
    if not action_id:
        return None
    action = _resolver(action_id) if _resolver else None
    if action is None:
        log.error("%s : workflow %r introuvable", what, action_id)
        return None
    run = getattr(_context, "run", None)
    if run is None:  # appel direct hors declenchement (tests)
        return run_action_sync(action)["vars"].get("last")
    return _run_action(action, run, args)


def _branch(step: dict, condition: bool, what: str, value: Any = None) -> Branch:
    chosen = step.get("action_id") if condition else step.get("else_action_id")
    log.info("%s : condition %s", what, "vraie" if condition else "fausse")
    _nested(chosen, what)
    return Branch("true" if condition else "false", condition if value is None else value)


def _step_if_window_exists(step: dict) -> Branch:
    return _branch(step, pu.window_exists(_text(step, "title_contains")), "if_window_exists")


def _process_running(name: str) -> bool:
    return bool(system_metrics.read_metric("process_running", name.strip()))


def _step_if_process_running(step: dict) -> Branch:
    return _branch(step, _process_running(_text(step, "name")), "if_process_running")


def _step_require_auth(step: dict) -> Branch:
    from .sensors import fingerprint

    ok, detail = fingerprint.verify_once(float(step.get("timeout") or 20))
    return _branch(step, ok, "require_auth", detail if ok else False)


def _step_if_value(step: dict) -> Branch:
    expression = _text(step, "condition").strip()
    if expression.startswith("{{") and expression.endswith("}}"):
        expression = expression[2:-2]
    result = templating.truthy(templating.eval_expression(expression, _current_run().vars)) if expression else False
    return _branch(step, result, "if_value")


def _step_if_system(step: dict) -> Branch:
    condition = {
        "metric": _text(step, "metric"),
        "arg": _text(step, "arg"),
        "op": _text(step, "op") or ">",
        "value": step.get("value") if step.get("value") not in (None, "") else 0,
        "on_unknown": _text(step, "on_unknown") or "fail",
    }
    ok, why = system_metrics.evaluate(condition)
    log.info("if_system : %s -> %s", why, "vrai" if ok else "faux")
    return _branch(step, ok, "if_system", system_metrics.read_metric(condition["metric"], condition["arg"]))


def _step_repeat(step: dict) -> None:
    count = max(1, _int(step, "count", 1))
    run = _current_run()
    for i in range(count):
        run.vars["loop"] = {"index": i + 1, "count": count, "first": i == 0, "last": i == count - 1}
        _nested(step.get("action_id"), "repeat")
        if i < count - 1:
            _sleep_ms(_param(step, "delay_ms"), "repeat : delay_ms")


def _as_items(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [{"key": k, "value": v} for k, v in value.items()]
    if value is None or value == "":
        return []
    text = str(value).strip()
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return parsed
        except ValueError:
            pass
    return [line for line in text.splitlines() if line.strip()]


def _for_each(step: dict, graph: _Graph, run: _Run, node: dict) -> tuple[Any, str]:
    """Boucle : le sous-graphe relie au port ``each`` est execute pour chaque element."""
    items = _as_items(step.get("items"))[: max(1, min(MAX_LOOP_ITEMS, _int(step, "limit", 100)))]
    item_var = str(step.get("item_var") or "item")
    each = graph.out.get((str(node["id"]), "each"), [])
    total = len(items)
    for index, item in enumerate(items, start=1):
        if run.stopped:
            break
        run.vars[item_var] = item
        run.vars["loop"] = {"index": index, "count": total, "first": index == 1, "last": index == total}
        _nested(step.get("action_id"), "for_each")
        if each:
            _walk(graph, each, run, "for_each")
    log.info("for_each : %d element(s)", total)
    return total, "done"


def _coerce(text: str) -> Any:
    """``"21"`` -> 21, ``"1.5"`` -> 1.5 : les arguments chiffres restent utilisables dans un calcul."""
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if re.fullmatch(r"-?\d+\.\d+", text):
        return float(text)
    return text


def _step_run_action(step: dict) -> Any:
    args: dict[str, Any] = {}
    raw = step.get("args")
    if isinstance(raw, dict):
        args = dict(raw)
    elif isinstance(raw, str):
        for line in raw.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                if key.strip():
                    args[key.strip()] = _coerce(value.strip())
    return _nested(step.get("action_id"), "run_action", args)


def _step_stop_workflow(step: dict) -> None:
    reason = _text(step, "reason")
    log.info("Workflow arrete%s", f" : {reason}" if reason else "")
    _current_run().stopped = True


def _step_set_variable(step: dict) -> Any:
    value = step.get("value")
    name = _text(step, "variable").strip()
    if name:
        _current_run().vars[name] = value
    return value


def _step_log_message(step: dict) -> str:
    message, level = _text(step, "message"), _text(step, "level") or "info"
    getattr(log, {"warning": "warning", "error": "error"}.get(level, "info"))("%s", message)
    events.emit("log", level=level, message=templating.preview(message, 300))
    return message


def _walk_path(data: Any, path: str) -> Any:
    for part in re.findall(r"[^.\[\]]+", path):
        if isinstance(data, list):
            try:
                data = data[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(data, dict):
            data = data.get(part)
        else:
            return None
    return data


def _step_parse_json(step: dict) -> Any:
    source = step.get("source")
    if isinstance(source, str):
        try:
            source = json.loads(source)
        except ValueError:
            log.error("parse_json : texte JSON invalide")
            return None
    return _walk_path(source, _text(step, "path")) if _text(step, "path") else source


def _step_regex_extract(step: dict) -> str:
    try:
        match = re.search(_text(step, "pattern"), _text(step, "source"))
    except re.error as exc:
        log.error("regex_extract : expression invalide (%s)", exc)
        return ""
    if not match:
        return ""
    try:
        return match.group(_int(step, "group", 0)) or ""
    except IndexError:
        return ""


def _step_system_metric(step: dict) -> Any:
    return system_metrics.read_metric(_text(step, "metric"), _text(step, "arg"))


def _step_hand_info(step: dict) -> dict:
    provider = _providers["vector"]
    infos = handlib.analyze(provider() if provider else None)
    return {
        "hands": len(infos),
        "count": sum(h["count"] for h in infos),
        "fingers": [h["fingers"] for h in infos],
    }


def _step_ai_ask(step: dict) -> str | None:
    image = None
    if step.get("with_image"):
        provider = _providers["frame"]
        image = provider() if provider else None
        if image is None:
            log.warning("ai_ask : aucune image de camera disponible, la question est envoyee sans image")
    try:
        return ai.ask(
            _text(step, "prompt"), system=_text(step, "system"), image=image,
            base_url=_text(step, "base_url"), model=_text(step, "model"),
            timeout=max(1, _int(step, "timeout_s", 60)),
        )
    except ai.AIError as exc:
        log.error("ai_ask : %s", exc)
        return None


def _step_trigger(step: dict) -> Any:
    return _current_run().vars.get("gesture")


_HANDLERS: dict[str, Callable[[dict], Any]] = {
    "trigger": _step_trigger,
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
    "clipboard_get": _step_clipboard_get,
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
    "system_metric": _step_system_metric,
    "hand_info": _step_hand_info,
    "ai_ask": _step_ai_ask,
    "wait": _step_wait,
    "if_window_exists": _step_if_window_exists,
    "if_process_running": _step_if_process_running,
    "require_auth": _step_require_auth,
    "if_value": _step_if_value,
    "if_system": _step_if_system,
    "repeat": _step_repeat,
    "for_each": lambda step: None,  # execute par le moteur (_for_each) : il pilote le sous-graphe
    "run_action": _step_run_action,
    "stop_workflow": _step_stop_workflow,
    "set_variable": _step_set_variable,
    "log_message": _step_log_message,
    "parse_json": _step_parse_json,
    "regex_extract": _step_regex_extract,
}
