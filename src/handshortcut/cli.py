"""Point d'entree : ``handshortcut`` (ou ``python -m handshortcut``).

Demarre dans UN SEUL process :
  1. le moteur de detection (camera + MediaPipe) dans un thread ;
  2. le serveur web de configuration (waitress) sur http://127.0.0.1:5678.

Sous-commandes :
  handshortcut [run]              lance le daemon (defaut)
  handshortcut stop               arrete le daemon deja lance
  handshortcut paths              affiche les dossiers utilises
  handshortcut doctor             diagnostique l'environnement (outils manquants...)
  handshortcut export [FICHIER]   exporte gestes + actions (JSON portable Linux <-> Windows)
  handshortcut import FICHIER     importe un export (--replace pour tout remplacer)
  handshortcut autostart on|off|status   demarrage automatique a la connexion
"""

from __future__ import annotations

import argparse
import contextlib
import errno
import logging
import os
import signal
import sys
import threading
import urllib.error
import urllib.request
import webbrowser

from . import __version__
from .paths import ENV_DATA_DIR, data_dir, examples_dir, log_dir

DEFAULT_PORT = 5678
HOST = "127.0.0.1"  # ne jamais exposer l'interface sur le reseau : elle lance des commandes

log = logging.getLogger("handshortcut")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="handshortcut",
        description="Gestes de la main -> actions (apps, fenetres, URL, commandes).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--port",
        type=int,
        default=_env_int("HANDSHORTCUT_PORT", DEFAULT_PORT),
        help=f"port de l'interface web (defaut {DEFAULT_PORT}, env HANDSHORTCUT_PORT)",
    )
    parser.add_argument(
        "--camera",
        type=int,
        default=_env_int("HANDSHORTCUT_CAMERA", 0),
        help="index de la camera (defaut 0, env HANDSHORTCUT_CAMERA)",
    )
    parser.add_argument("--data-dir", help=f"dossier des donnees (env {ENV_DATA_DIR})")
    parser.add_argument("--open", action="store_true", help="ouvre l'interface dans le navigateur")
    parser.add_argument("-v", "--verbose", action="store_true", help="journaux detailles")

    sub = parser.add_subparsers(dest="command")
    sub.add_parser("run", help="lance le daemon (commande par defaut)")
    sub.add_parser("stop", help="arrete le daemon en cours d'execution")
    sub.add_parser("paths", help="affiche les dossiers de donnees, journaux et exemples")
    sub.add_parser("doctor", help="diagnostique l'environnement et les outils manquants")
    export = sub.add_parser("export", help="exporte gestes et actions dans un fichier JSON")
    export.add_argument("file", nargs="?", default="handshortcut-export.json", help="fichier de sortie")
    imp = sub.add_parser("import", help="importe un fichier exporte")
    imp.add_argument("file", help="fichier a importer")
    imp.add_argument("--replace", action="store_true", help="remplace la configuration actuelle")
    auto = sub.add_parser("autostart", help="demarrage automatique a la connexion")
    auto.add_argument("state", choices=("on", "off", "status"))
    return parser


def say(message: str, *, error: bool = False) -> None:
    """print() sur la console, sans planter quand il n'y en a pas (Windows, mode fenetre)."""
    stream = sys.stderr if error else sys.stdout
    if stream is not None:
        print(message, file=stream)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.data_dir:
        os.environ[ENV_DATA_DIR] = args.data_dir

    if args.command == "paths":
        say(f"donnees  : {data_dir()}")
        say(f"journaux : {log_dir()}")
        say(f"exemples : {examples_dir()}")
        return 0
    if args.command == "stop":
        return _stop(args.port)
    if args.command == "doctor":
        from . import doctor

        say(doctor.render(doctor.collect()))
        return 0
    if args.command in ("export", "import"):
        return _bundle(args)
    if args.command == "autostart":
        return _autostart(args.state)
    return _run(args)


# ---------------------------------------------------------- export / import


def _bundle(args: argparse.Namespace) -> int:
    from . import bundle
    from .config_store import ConfigStore
    from .schema import ValidationError

    store = ConfigStore(data_dir())
    if args.command == "export":
        target = bundle.write_bundle_file(store, args.file)
        say(f"Exporte : {target} ({len(store.get_gestures())} geste(s), {len(store.get_actions())} action(s))")
        return 0
    try:
        result = bundle.import_bundle(store, bundle.read_bundle_file(args.file), replace=args.replace)
    except (OSError, ValueError, ValidationError) as exc:
        say(f"Import impossible : {exc}", error=True)
        return 1
    say(f"Importe : {result['gestures']} geste(s), {result['actions']} action(s).")
    return 0


# --------------------------------------------------------------- autostart


def _autostart(state: str) -> int:
    from . import autostart

    if state == "status":
        say("active" if autostart.is_enabled() else "desactive")
    elif state == "on":
        say(f"Demarrage automatique active : {autostart.enable()}")
    else:
        say("Demarrage automatique desactive." if autostart.disable() else "Il n'etait pas active.")
    return 0


# ------------------------------------------------------------------ stop


def _stop(port: int) -> int:
    request = urllib.request.Request(
        f"http://{HOST}:{port}/api/shutdown",
        data=b"{}",
        method="POST",
        headers={"Content-Type": "application/json", "X-HandShortCut": "1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5):
            say("HandShortCut arrete.")
    except urllib.error.URLError:
        say("HandShortCut n'est pas lance.")
    return 0


def _is_handshortcut(port: int) -> bool:
    """Le port est-il tenu par une instance de HandShortCut (et pas un autre programme) ?"""
    try:
        with urllib.request.urlopen(f"http://{HOST}:{port}/api/status", timeout=2) as response:
            return b'"engine"' in response.read(4096)
    except (urllib.error.URLError, OSError, ValueError):
        return False


# ------------------------------------------------------------------- run


def _run(args: argparse.Namespace) -> int:
    # Reduit le bruit des bibliotheques C++ de MediaPipe (avant son import).
    os.environ.setdefault("GLOG_minloglevel", "2")
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

    from .logging_setup import setup_logging

    setup_logging(args.verbose)
    url = f"http://{HOST}:{args.port}"

    import waitress.server

    from . import action_executor
    from .config_store import ConfigStore
    from .gesture_engine import GestureEngine
    from .webui.app import create_app

    stop_event = threading.Event()
    store = ConfigStore(data_dir())
    engine = GestureEngine(
        store,
        on_trigger=lambda gesture, action: action_executor.run_action(action),
        camera_index=args.camera,
    )
    action_executor.set_resolver(store.get_action)  # pour les etapes if_* et repeat
    app = create_app(engine, store, on_shutdown=stop_event.set)

    try:
        server = waitress.server.create_server(
            app, host=HOST, port=args.port, threads=16, ident="HandShortCut"
        )
    except OSError as exc:
        if exc.errno in (errno.EADDRINUSE, getattr(errno, "WSAEADDRINUSE", -1), 10048):
            if _is_handshortcut(args.port):
                # Deja lance : ce n'est pas une erreur (evite qu'un service systemd boucle).
                say(f"HandShortCut est deja lance : {url}")
                if args.open:
                    webbrowser.open(url)
                return 0
            msg = f"Le port {args.port} est deja utilise par un autre programme (--port pour en changer)."
            log.error(msg)
            say(msg, error=True)
            return 1
        raise

    log.info("HandShortCut %s - donnees : %s", __version__, store.data_dir)
    log.info("Interface de configuration : %s", url)

    for sig_name in ("SIGINT", "SIGTERM", "SIGBREAK"):  # SIGBREAK : Windows
        sig = getattr(signal, sig_name, None)
        if sig is not None:
            with contextlib.suppress(ValueError, OSError):
                signal.signal(sig, lambda *_: stop_event.set())

    def watch_config() -> None:
        while not stop_event.wait(2):
            try:
                store.reload_if_changed()
            except Exception:
                log.exception("Echec du rechargement de la configuration")

    threading.Thread(target=watch_config, name="config-watcher", daemon=True).start()
    threading.Thread(target=server.run, name="web", daemon=True).start()
    engine.start()

    if args.open:
        webbrowser.open(url)

    try:
        while not stop_event.wait(0.5):
            pass
    finally:
        log.info("Arret en cours...")
        engine.stop()
        server.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
