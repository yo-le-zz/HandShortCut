"""Interface web locale de HandShortCut (Flask).

Accessible sur http://127.0.0.1:5678. Permet de creer des gestes (enregistres
via la webcam), de composer des actions, de les lier, et de tout tester.
Chaque modification est ecrite dans gestures.json / actions.json, relus a chaud
par le daemon.

Securite : le serveur n'ecoute que sur la boucle locale, mais une page web
quelconque peut tenter de lui parler (CSRF, DNS rebinding) et cette API sait
lancer des commandes. Chaque requete est donc filtree : nom d'hote local,
`Origin` local, et en-tete personnalise `X-HandShortCut` sur les ecritures.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from urllib.parse import urlsplit

from flask import Flask, Response, abort, jsonify, render_template, request

from .. import __version__, action_executor, bundle
from .. import platform_utils as pu
from ..schema import (
    LEGACY_FPS,
    ValidationError,
    hold_ms_of,
    validate_action,
    validate_gesture,
    validate_gesture_patch,
)
from ..steps import STEPS, catalog_for_ui

log = logging.getLogger(__name__)

LOCAL_HOSTNAMES = {"127.0.0.1", "localhost", "::1"}
CSRF_HEADER = "X-HandShortCut"
MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; "
    "script-src 'self'; font-src 'self'; connect-src 'self'; "
    "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
)


def _hostname(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return urlsplit(value if "//" in value else f"//{value}").hostname
    except ValueError:
        return None


def format_ms(value) -> str:
    """Duree lisible, en secondes ET en millisecondes : ``0,27 s (270 ms)``."""
    try:
        ms = round(float(value))
    except (TypeError, ValueError):
        return "-"
    seconds = f"{ms / 1000:.2f}".rstrip("0").rstrip(".").replace(".", ",")
    grouped = f"{ms:,}".replace(",", "\u202f")  # espace fine insecable : 1 250 ms
    return f"{seconds} s ({grouped} ms)"


def format_seconds(value) -> str:
    try:
        return format_ms(float(value) * 1000)
    except (TypeError, ValueError):
        return "-"


def create_app(engine, store, on_shutdown: Callable[[], None] | None = None) -> Flask:
    app = Flask(__name__)
    app.json.ensure_ascii = False
    app.json.sort_keys = False
    app.jinja_env.filters["ms"] = format_ms
    app.jinja_env.filters["seconds"] = format_seconds
    app.jinja_env.globals["hold_ms_of"] = hold_ms_of
    app.jinja_env.globals["version"] = __version__
    app.jinja_env.globals["steps"] = {
        t: {"label": spec.label, "icon": spec.icon, "category": spec.category} for t, spec in STEPS.items()
    }

    # ------------------------------------------------------------ securite
    @app.before_request
    def guard():
        if _hostname(request.host) not in LOCAL_HOSTNAMES:
            abort(403, "Hote non autorise.")
        origin = request.headers.get("Origin")
        if origin and origin != "null" and _hostname(origin) not in LOCAL_HOSTNAMES:
            abort(403, "Origine non autorisee.")
        if origin == "null":
            abort(403, "Origine non autorisee.")
        if request.method in MUTATING_METHODS and CSRF_HEADER not in request.headers:
            abort(403, "En-tete de securite manquant.")

    @app.after_request
    def add_headers(response):
        response.headers.setdefault("Content-Security-Policy", CSP)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(ValidationError)
    def on_validation_error(exc):
        return jsonify(ok=False, error=str(exc)), 400

    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(405)
    @app.errorhandler(415)
    @app.errorhandler(503)
    def on_http_error(exc):
        if request.path.startswith("/api/"):
            return jsonify(ok=False, error=exc.description), exc.code
        return exc

    # --------------------------------------------------------------- pages
    @app.route("/")
    def index():
        return render_template(
            "index.html",
            gestures=store.get_gestures(),
            actions=store.get_actions(),
            active="dashboard",
        )

    @app.route("/gestures/new")
    def gesture_new():
        return render_template(
            "gesture_form.html",
            gesture=None,
            actions=store.get_actions(),
            legacy_fps=LEGACY_FPS,
            active="gesture",
        )

    @app.route("/gestures/<gesture_id>/edit")
    def gesture_edit(gesture_id):
        gesture = store.get_gesture(gesture_id)
        if gesture is None:
            abort(404)
        return render_template(
            "gesture_form.html",
            gesture=gesture,
            actions=store.get_actions(),
            legacy_fps=LEGACY_FPS,
            active="dashboard",
        )

    @app.route("/actions/new")
    def action_new():
        return render_template("action_form.html", action=None, active="action", **_form_context())

    @app.route("/actions/<action_id>/edit")
    def action_edit(action_id):
        action = store.get_action(action_id)
        if action is None:
            abort(404)
        return render_template("action_form.html", action=action, active="action", **_form_context())

    def _form_context() -> dict:
        form = {
            **catalog_for_ui(),
            "monitors": pu.list_monitors(),
            "actions": [{"id": a["id"], "name": a.get("name", "?")} for a in store.get_actions()],
            "os": pu.current_os(),
        }
        return {"form_json": json.dumps(form, ensure_ascii=False).replace("</", "<\\/")}

    # ---------------------------------------------------------- flux video
    @app.route("/video_feed")
    def video_feed():
        # Sans camera il n'y aurait jamais d'image : une reponse 503 evite une
        # page qui charge indefiniment (record.js recharge le flux au retour de la camera).
        if engine.status()["camera"] != "ok":
            abort(503, "Camera indisponible.")

        def generate():
            last = None
            while True:
                frame = engine.get_jpeg_frame()
                if frame and frame is not last:
                    last = frame
                    yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n")
                time.sleep(0.03)

        response = Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")
        response.headers["Cache-Control"] = "no-store"
        return response

    # ----------------------------------------------------------------- API
    @app.route("/api/status")
    def api_status():
        return jsonify(
            version=__version__,
            engine=engine.status(),
            gestures=len(store.get_gestures()),
            actions=len(store.get_actions()),
        )

    @app.route("/api/live")
    def api_live():
        """Cadence de la camera et distance de chaque geste a sa cible (reglage du seuil)."""
        live = engine.live_scores() if hasattr(engine, "live_scores") else {}
        return jsonify(engine=engine.status(), scores=live)

    @app.route("/api/export")
    def api_export():
        payload = json.dumps(bundle.export_bundle(store), indent=2, ensure_ascii=False)
        name = f"handshortcut-{time.strftime('%Y%m%d-%H%M%S')}.json"
        return Response(
            payload,
            mimetype="application/json",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )

    @app.route("/api/import", methods=["POST"])
    def api_import():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise ValidationError("Import : objet JSON attendu.")
        result = bundle.import_bundle(store, body.get("bundle"), replace=bool(body.get("replace")))
        return jsonify(ok=True, **result)

    @app.route("/api/monitors")
    def api_monitors():
        return jsonify(pu.list_monitors())

    @app.route("/api/record/start", methods=["POST"])
    def api_record_start():
        kind = (request.get_json(silent=True) or {}).get("kind", "static")
        if kind not in ("static", "sequence"):
            raise ValidationError("Type d'enregistrement invalide.")
        engine.start_recording(kind)
        return jsonify(ok=True)

    @app.route("/api/record/stop", methods=["POST"])
    def api_record_stop():
        return jsonify(engine.stop_recording())

    @app.route("/api/record/cancel", methods=["POST"])
    def api_record_cancel():
        engine.cancel_recording()
        return jsonify(ok=True)

    @app.route("/api/gestures", methods=["GET"])
    def api_gestures_list():
        return jsonify(store.get_gestures())

    @app.route("/api/gestures", methods=["POST"])
    def api_gestures_save():
        gesture = validate_gesture(request.get_json(silent=True))
        return jsonify(ok=True, id=store.save_gesture(gesture))

    @app.route("/api/gestures/<gesture_id>", methods=["PATCH"])
    def api_gestures_patch(gesture_id):
        patch = validate_gesture_patch(request.get_json(silent=True))
        if patch.get("action_id") and store.get_action(patch["action_id"]) is None:
            raise ValidationError("Action introuvable.")
        updated = store.update_gesture(gesture_id, patch)
        if updated is None:
            abort(404, "Geste introuvable.")
        return jsonify(ok=True, id=gesture_id)

    @app.route("/api/gestures/<gesture_id>/duplicate", methods=["POST"])
    def api_gestures_duplicate(gesture_id):
        new_id = store.duplicate_gesture(gesture_id)
        if new_id is None:
            abort(404, "Geste introuvable.")
        return jsonify(ok=True, id=new_id)

    @app.route("/api/gestures/<gesture_id>", methods=["DELETE"])
    def api_gestures_delete(gesture_id):
        if not store.delete_gesture(gesture_id):
            abort(404, "Geste introuvable.")
        return jsonify(ok=True)

    @app.route("/api/actions", methods=["GET"])
    def api_actions_list():
        return jsonify(store.get_actions())

    @app.route("/api/actions", methods=["POST"])
    def api_actions_save():
        action = validate_action(request.get_json(silent=True))
        if action["id"] and store.get_action(action["id"]) is None:
            action["id"] = None  # identifiant inconnu : nouvelle action
        return jsonify(ok=True, id=store.save_action(action))

    @app.route("/api/actions/test", methods=["POST"])
    def api_actions_test():
        """Teste une action en cours d'edition, sans l'enregistrer."""
        action_executor.run_action(validate_action(request.get_json(silent=True)))
        return jsonify(ok=True)

    @app.route("/api/actions/<action_id>/duplicate", methods=["POST"])
    def api_actions_duplicate(action_id):
        new_id = store.duplicate_action(action_id)
        if new_id is None:
            abort(404, "Action introuvable.")
        return jsonify(ok=True, id=new_id)

    @app.route("/api/actions/<action_id>", methods=["DELETE"])
    def api_actions_delete(action_id):
        if not store.delete_action(action_id):
            abort(404, "Action introuvable.")
        return jsonify(ok=True)

    @app.route("/api/actions/<action_id>/run", methods=["POST"])
    def api_actions_run(action_id):
        action = store.get_action(action_id)
        if action is None:
            abort(404, "Action introuvable.")
        action_executor.run_action(action)
        return jsonify(ok=True)

    @app.route("/api/shutdown", methods=["POST"])
    def api_shutdown():
        if on_shutdown is None:
            abort(404)
        log.info("Arret demande via l'API")
        on_shutdown()
        return jsonify(ok=True)

    return app
