"""Export / import et nouvelles routes de l'interface web."""

import json

from handshortcut import bundle
from handshortcut.cli import main
from tests.conftest import vec


def _seed(store):
    aid = store.save_action({"name": "Ouvrir", "steps": [{"type": "open_url", "url": "https://example.org"}]})
    gid = store.save_gesture(
        {"name": "Poing", "type": "static", "template": vec(), "threshold": 0.2, "hold_ms": 300, "action_id": aid}
    )
    return gid, aid


def test_export_import_roundtrip(store, tmp_path):
    _seed(store)
    data = bundle.export_bundle(store)
    other = type(store)(tmp_path / "other")
    result = bundle.import_bundle(other, data)
    assert result["gestures"] == 1 and result["actions"] == 1
    assert other.get_gestures()[0]["hold_ms"] == 300


def test_import_rejects_invalid_bundle(store):
    import pytest

    from handshortcut.schema import ValidationError

    with pytest.raises(ValidationError):
        bundle.import_bundle(store, {"format": "autre"})


def test_cli_export_then_import(store, tmp_path, capsys):
    _seed(store)
    out = tmp_path / "x.json"
    assert main(["--data-dir", str(store.data_dir), "export", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["format"] == "handshortcut-bundle"
    target = tmp_path / "t"
    assert main(["--data-dir", str(target), "import", str(out)]) == 0


def test_api_export_import(client, api, store):
    _seed(store)
    res = client.get("/api/export")
    assert res.status_code == 200 and "attachment" in res.headers["Content-Disposition"]
    payload = res.get_json()
    res = client.post("/api/import", json={"bundle": payload, "replace": True}, headers=api)
    assert res.status_code == 200 and res.get_json()["gestures"] == 1
    assert client.post("/api/import", json={"bundle": {}}, headers=api).status_code == 400


def test_api_live_and_duplicate(client, api, store):
    gid, aid = _seed(store)
    assert "engine" in client.get("/api/live").get_json()
    assert client.post(f"/api/gestures/{gid}/duplicate", headers=api).status_code == 200
    assert client.post(f"/api/actions/{aid}/duplicate", headers=api).status_code == 200
    assert len(store.get_gestures()) == 2 and len(store.get_actions()) == 2
    assert client.post("/api/gestures/nope/duplicate", headers=api).status_code == 404


def test_api_actions_test_validates(client, api, monkeypatch):
    from handshortcut import action_executor

    ran = []
    monkeypatch.setattr(action_executor, "run_action", ran.append)
    ok = client.post("/api/actions/test", json={"name": "t", "steps": [{"type": "wait", "ms": 5}]}, headers=api)
    assert ok.status_code == 200 and len(ran) == 1
    bad = client.post("/api/actions/test", json={"name": "t", "steps": [{"type": "zzz"}]}, headers=api)
    assert bad.status_code == 400


def test_pages_render(client, store):
    gid, aid = _seed(store)
    for url in ("/", "/gestures/new", f"/gestures/{gid}/edit", "/actions/new", f"/actions/{aid}/edit"):
        assert client.get(url).status_code == 200, url
