import json

from physicalshortcut import events, settings
from physicalshortcut import system_metrics as sm


def test_events_ring_buffer_and_since():
    events.clear()
    a = events.emit("gesture", gesture="x")
    b = events.emit("log", message="m")
    assert [e["id"] for e in events.since(0)] == [a["id"], b["id"]]
    assert [e["id"] for e in events.since(a["id"])] == [b["id"]]
    assert events.last_id() == b["id"]
    for _ in range(events.MAX_EVENTS + 20):
        events.emit("log")
    assert len(events.since(0, limit=10_000)) == events.MAX_EVENTS


def test_events_listener_errors_do_not_break_emit():
    events.clear()
    seen = []
    events.subscribe(lambda e: 1 / 0)
    events.subscribe(seen.append)
    events.emit("gesture")
    assert len(seen) == 1
    events.clear()


def test_settings_persist_and_filter(tmp_path):
    path = tmp_path / "s.json"
    cfg = settings.Settings(path)
    assert cfg.get("notify_in_app") is True
    cfg.update({"notify_desktop": 1, "ai_model": "  llava ", "unknown": "x"})
    again = settings.Settings(path)
    assert again.get("notify_desktop") is True and again.get("ai_model") == "llava"
    assert "unknown" not in json.loads(path.read_text())
    path.write_text("{ pas du json")
    assert settings.Settings(path).get("notify_in_app") is True  # fichier illisible : valeurs par defaut


def test_metric_catalog_and_conditions(monkeypatch):
    catalog = sm.catalog_for_ui()
    keys = {m["key"] for m in catalog["metrics"]}
    assert {"uptime_minutes", "cpu_percent", "cpu_temp_c"} <= keys
    monkeypatch.setattr(sm, "read_metric", lambda key, arg="": {"cpu_percent": 40.0, "uptime_minutes": 5.0}.get(key))
    ok, _ = sm.check([{"metric": "cpu_percent", "op": "<", "value": 70}])
    assert ok
    ok, reasons = sm.check([{"metric": "uptime_minutes", "op": ">=", "value": 10}])
    assert not ok and reasons
    # mesure indisponible : echec, sauf on_unknown = pass
    ok, _ = sm.check([{"metric": "cpu_temp_c", "op": "<", "value": 50}])
    assert not ok
    ok, _ = sm.check([{"metric": "cpu_temp_c", "op": "<", "value": 50, "on_unknown": "pass"}])
    assert ok
    # mode any
    ok, _ = sm.check([{"metric": "cpu_percent", "op": ">", "value": 90}, {"metric": "cpu_percent", "op": "<", "value": 50}], "any")
    assert ok
    assert sm.check([], "all")[0] is True
