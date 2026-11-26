"""Gestes v1.1 (pose, comptage, deux mains, dessin, conditions), portabilite, modeles, routes."""

import time

import pytest

from physicalshortcut import draw, events, hands, portability, system_metrics, templates_lib
from physicalshortcut.config_store import ConfigStore
from physicalshortcut.gesture_engine import GestureEngine
from physicalshortcut.schema import ValidationError, validate_gesture


class Store:
    def __init__(self, gestures, actions):
        self._g, self._a = gestures, {a["id"]: a for a in actions}

    def get_gestures(self):
        return self._g

    def get_action(self, action_id):
        return self._a.get(action_id)


def engine_for(gesture):
    fired = []
    engine = GestureEngine(Store([gesture], [{"id": "a", "name": "A"}]), lambda g, a, ctx: fired.append(ctx))
    return engine, fired


def feed(engine, frame, seconds=1.0, step=0.05, start=None):
    start = start if start is not None else time.monotonic()
    t = start
    while t < start + seconds:
        engine._process_detection(frame, t)
        t += step
    return t


BASE = {"id": "g", "name": "G", "action_id": "a", "cooldown_seconds": 0}


def test_pose_gesture_fires_only_for_the_right_fingers():
    engine, fired = engine_for({**BASE, "type": "pose", "fingers": [0, 1, 1, 0, 0], "hands": 1, "hold_ms": 200})
    feed(engine, hands.synth_frame([1, 1, 1, 1, 1]))
    assert fired == []
    feed(engine, hands.synth_frame([0, 1, 1, 0, 0]))
    assert fired and fired[0]["name"] == "G"


def test_count_gesture_passes_the_value():
    engine, fired = engine_for({**BASE, "type": "count", "min_value": 1, "max_value": 5, "hands": 1, "hold_ms": 200})
    feed(engine, hands.synth_frame([0, 1, 1, 1, 0]))
    assert fired and fired[0]["value"] == 3


def test_two_hand_pose_needs_both_hands():
    gesture = {**BASE, "type": "pose", "hands": 2, "fingers": [1, 1, 1, 1, 1], "fingers_second": [0, 0, 0, 0, 0], "hold_ms": 200}
    engine, fired = engine_for(gesture)
    feed(engine, hands.synth_frame([1, 1, 1, 1, 1]))  # une seule main
    assert fired == []
    feed(engine, hands.synth_frame([1, 1, 1, 1, 1], [0, 0, 0, 0, 0]))
    assert fired


def test_conditions_block_the_gesture_and_report_why(monkeypatch):
    events.clear()
    monkeypatch.setattr(system_metrics, "read_metric", lambda key, arg="": 95.0)
    gesture = {**BASE, "type": "pose", "fingers": [0, 0, 0, 0, 0], "hands": 1, "hold_ms": 100,
               "conditions": [{"metric": "cpu_percent", "op": "<", "value": 70}]}
    engine, fired = engine_for(gesture)
    feed(engine, hands.synth_frame([0, 0, 0, 0, 0]))
    assert fired == []
    assert any(e["kind"] == "gesture_blocked" for e in events.since(0))
    monkeypatch.setattr(system_metrics, "read_metric", lambda key, arg="": 10.0)
    feed(engine, hands.synth_frame([0, 0, 0, 0, 0]))
    assert fired


def test_drawing_gesture_recognises_a_circle():
    gesture = {**BASE, "type": "draw", "charset": "shapes", "labels": ["cercle"], "recognizer": "local", "pen": "index",
               "idle_ms": 400, "min_confidence": 0.6}
    engine, fired = engine_for(gesture)
    frame = hands.synth_frame([0, 1, 0, 0, 0])
    t = time.monotonic()
    for x, y in draw.TEMPLATES["cercle"][0][0]:
        engine._process_detection(frame, t, pointers=[{"x": 0.3 + x * 0.4, "y": 0.3 + y * 0.4, "pinch": 1.0}])
        t += 0.03
    for _ in range(40):
        engine._process_detection(frame, t, pointers=[])
        t += 0.05
        time.sleep(0.01)
        if fired:
            break
    deadline = time.time() + 3
    while not fired and time.time() < deadline:
        time.sleep(0.05)
    assert fired and fired[0]["label"] == "cercle"


def test_gesture_validation_for_new_types():
    ok = validate_gesture({"name": "p", "type": "pose", "fingers": [1, 0, 0, 0, 0], "hands": 1})
    assert ok["type"] == "pose"
    with pytest.raises(ValidationError):
        validate_gesture({"name": "p", "type": "pose", "fingers": [1, 0, 0]})
    with pytest.raises(ValidationError):
        validate_gesture({"name": "c", "type": "count", "min_value": 5, "max_value": 2})
    with pytest.raises(ValidationError):
        validate_gesture({"name": "d", "type": "draw", "recognizer": "magie"})
    with pytest.raises(ValidationError):
        validate_gesture({"name": "x", "type": "pose", "fingers": [1] * 5, "conditions": [{"metric": "inconnue", "op": "<", "value": 1}]})


# ------------------------------------------------------------ portabilite
def test_windows_bundle_is_converted_to_linux():
    actions = [{"name": "A", "steps": [
        {"type": "launch", "path": "notepad.exe"},
        {"type": "open_path", "path": "C:\\Users\\yo\\Documents\\x.txt"},
        {"type": "run_shell", "cmd": "dir"}]}]
    assert portability.detect_os({"actions": actions}) == "windows"
    out, report = portability.convert([], actions, "windows", "linux")
    steps = out[0]["steps"]
    assert steps[0]["path"].startswith("gnome-text-editor")
    assert steps[1]["path"] == "~/Documents/x.txt"
    assert steps[2]["only_on"] == "windows"
    assert report["converted"] and report["notes"]


def test_linux_paths_to_windows_and_declared_os_wins():
    assert portability.path_to_windows("~/Documents/a") == "%USERPROFILE%\\Documents\\a"
    assert portability.path_to_linux("%APPDATA%\\x\\y") == "~/.config/x/y"
    assert portability.detect_os({"os": "linux", "actions": []}) == "linux"
    out, report = portability.convert([], [{"name": "n", "steps": []}], "linux", "linux")
    assert not report["converted"]


def test_import_reports_conversion(tmp_path, monkeypatch):
    from physicalshortcut import bundle
    from physicalshortcut import platform_utils as pu

    monkeypatch.setattr(pu, "current_os", lambda: "linux")
    store = ConfigStore(tmp_path)
    data = {"format": bundle.BUNDLE_FORMAT, "version": 1, "os": "windows",
            "gestures": [], "actions": [{"id": "a1", "name": "W", "steps": [{"type": "open_path", "path": "C:\\Users\\yo\\Docs"}]}]}
    result = bundle.import_bundle(store, data)
    assert result["conversion"]["converted"]
    assert store.get_actions()[0]["steps"][0]["path"] == "~/Docs"


# ---------------------------------------------------------------- modeles
def test_every_template_installs_and_links_gestures(tmp_path):
    store = ConfigStore(tmp_path)
    for template in templates_lib.LIBRARY:
        result = templates_lib.install(store, template["id"])
        assert store.get_action(result["action_id"])
        for gid in result["gesture_ids"]:
            assert store.get_gesture(gid)["action_id"] == result["action_id"]
    assert len(templates_lib.LIBRARY) >= 15
    assert len({t["id"] for t in templates_lib.LIBRARY}) == len(templates_lib.LIBRARY)


# ------------------------------------------------------------------ routes
@pytest.fixture
def client(tmp_path):
    from physicalshortcut.webui.app import create_app

    class FakeEngine:
        def status(self):
            return {"camera": "ok", "fps": 30}

        def live_scores(self):
            return {}

        def live_hands(self):
            return []

        def draw_state(self):
            return {"trail": []}

    app = create_app(FakeEngine(), ConfigStore(tmp_path), drawings_file=tmp_path / "d.json")
    c = app.test_client()
    c.environ_base["HTTP_X_PHYSICALSHORTCUT"] = "1"
    return c


def test_new_pages_render(client):
    for path in ("/", "/activity", "/templates", "/actions/new", "/gestures/new"):
        response = client.get(path)
        assert response.status_code == 200, path
    assert "yolezz" in client.get("/").get_data(as_text=True)


def test_api_events_settings_templates_metrics(client):
    assert client.get("/api/events?since=0").json["events"] is not None
    patched = client.patch("/api/settings", json={"notify_desktop": True})
    assert patched.json["settings"]["notify_desktop"] is True
    assert client.get("/api/templates").json["templates"]
    installed = client.post("/api/templates/mute-toggle/install", json={})
    assert installed.json["ok"] and installed.json["gesture_ids"]
    assert client.post("/api/templates/nope/install", json={}).status_code == 404
    assert "values" in client.get("/api/system/metrics").json
    assert client.get("/api/live").json["hands"] == []


def test_api_test_runs_a_graph_and_returns_variables(client, tmp_path):
    f = tmp_path / "in.txt"
    f.write_text("abc", encoding="utf-8")
    body = {"name": "t", "nodes": [{"id": "n1", "type": "file_read", "path": str(f), "name": "contenu"}], "edges": []}
    reply = client.post("/api/actions/test", json=body).json
    assert reply["success"] and reply["vars"]["contenu"] == "abc"


def test_custom_drawings_api(client, tmp_path):
    strokes = [[[0.0, 0.0], [0.1, 0.2], [0.2, 0.1], [0.3, 0.4], [0.4, 0.2], [0.5, 0.5], [0.6, 0.3], [0.7, 0.7], [0.8, 0.1]]]
    assert client.post("/api/drawings", json={"label": "mien", "strokes": strokes}).json["ok"]
    assert (tmp_path / "d.json").exists()
    assert client.post("/api/drawings", json={"label": "", "strokes": strokes}).status_code == 400
    assert client.delete("/api/drawings/mien").json["ok"]
    draw.library().custom.clear()
