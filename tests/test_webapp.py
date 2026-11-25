import json

from .conftest import vec


def post(client, url, payload, headers):
    return client.post(
        url, data=json.dumps(payload), content_type="application/json", headers=headers
    )


def test_pages_render(client, store):
    store.save_action({"name": "Mon action", "steps": [{"type": "wait", "ms": 5}]})
    for url in ("/", "/gestures/new", "/actions/new"):
        response = client.get(url)
        assert response.status_code == 200, url
        assert b"/static/app.css" in response.data
    action_id = store.get_actions()[0]["id"]
    page = client.get(f"/actions/{action_id}/edit")
    assert page.status_code == 200 and b"Mon action" in page.data
    assert client.get("/actions/inconnue/edit").status_code == 404


def test_pages_have_no_cdn_or_emoji(client):
    for url in ("/", "/gestures/new", "/actions/new"):
        html = client.get(url).get_data(as_text=True)
        assert "googleapis" not in html and "cdn." not in html
        assert not any(ord(c) > 0x1F000 for c in html)


def test_static_assets_served(client):
    for path in (
        "app.css",
        "icons.svg",
        "icon.png",
        "js/main.js",
        "js/index.js",
        "js/gesture_form.js",
        "js/action_form.js",
        "fonts/geist-latin-wght-normal.woff2",
    ):
        assert client.get(f"/static/{path}").status_code == 200, path


def test_security_headers_and_csp(client):
    response = client.get("/")
    assert "script-src 'self'" in response.headers["Content-Security-Policy"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_dns_rebinding_and_foreign_origin_blocked(client, api):
    assert client.get("/api/status", headers={"Host": "evil.example.com"}).status_code == 403
    assert client.get("/api/status", headers={"Host": "localhost:5678"}).status_code == 200
    assert client.get("/api/status", headers={"Host": "127.0.0.1:5678"}).status_code == 200
    assert (
        client.get("/api/status", headers={"Origin": "https://evil.example.com"}).status_code == 403
    )
    assert client.get("/api/status", headers={"Origin": "null"}).status_code == 403
    ok = client.get("/api/status", headers={"Origin": "http://127.0.0.1:5678"})
    assert ok.status_code == 200


def test_writes_require_custom_header(client):
    response = client.post("/api/actions", json={"name": "x", "steps": []})
    assert response.status_code == 403 and response.get_json()["ok"] is False
    assert client.delete("/api/actions/abc").status_code == 403
    assert client.post("/api/shutdown").status_code == 403


def test_action_crud_and_validation(client, store, api):
    bad = post(client, "/api/actions", {"name": "", "steps": []}, api)
    assert bad.status_code == 400 and bad.get_json()["ok"] is False

    created = post(client, "/api/actions", {"name": "A", "steps": [{"type": "wait", "ms": 1}]}, api)
    action_id = created.get_json()["id"]
    assert store.get_action(action_id)["name"] == "A"

    updated = post(client, "/api/actions", {"id": action_id, "name": "B", "steps": []}, api)
    assert updated.get_json()["id"] == action_id and len(store.get_actions()) == 1

    assert client.delete(f"/api/actions/{action_id}", headers=api).status_code == 200
    assert client.delete(f"/api/actions/{action_id}", headers=api).status_code == 404


def test_action_run_endpoint(client, store, api, monkeypatch):
    ran = []
    monkeypatch.setattr(
        "physicalshortcut.webui.app.action_executor.run_action_sync", lambda a, c=None: ran.append(a) or {"ok": True, "ms": 1, "vars": {}}
    )
    action_id = store.save_action({"name": "A", "steps": []})
    assert client.post(f"/api/actions/{action_id}/run", headers=api).status_code == 200
    assert ran and ran[0]["id"] == action_id
    assert client.post("/api/actions/zzz/run", headers=api).status_code == 404


def test_gesture_save_patch_delete(client, store, api):
    action_id = store.save_action({"name": "A", "steps": []})
    assert (
        post(
            client, "/api/gestures", {"name": "g", "type": "static", "template": [1]}, api
        ).status_code
        == 400
    )

    saved = post(
        client,
        "/api/gestures",
        {"name": "g", "type": "static", "template": vec(), "action_id": None},
        api,
    )
    gid = saved.get_json()["id"]

    patched = client.patch(f"/api/gestures/{gid}", json={"action_id": action_id}, headers=api)
    assert patched.status_code == 200 and store.get_gesture(gid)["action_id"] == action_id
    unknown = client.patch(f"/api/gestures/{gid}", json={"action_id": "nope"}, headers=api)
    assert unknown.status_code == 400
    assert client.patch("/api/gestures/zzz", json={"name": "x"}, headers=api).status_code == 404

    assert client.delete(f"/api/gestures/{gid}", headers=api).status_code == 200
    assert client.delete(f"/api/gestures/{gid}", headers=api).status_code == 404


def test_record_endpoints(client, engine, api):
    assert post(client, "/api/record/start", {"kind": "weird"}, api).status_code == 400
    assert post(client, "/api/record/start", {"kind": "sequence"}, api).status_code == 200
    assert engine.recording == "sequence"
    assert client.post("/api/record/cancel", headers=api).status_code == 200
    assert engine.recording is None
    assert "error" in client.post("/api/record/stop", headers=api).get_json()


def test_status_and_shutdown(client, stopped, api):
    status = client.get("/api/status").get_json()
    assert status["engine"]["camera"] == "ok" and status["gestures"] == 0
    assert client.post("/api/shutdown", headers=api).status_code == 200
    assert stopped.is_set()


def test_video_feed_streams_multipart(client):
    response = client.get("/video_feed", buffered=False)
    assert response.mimetype == "multipart/x-mixed-replace"
    first = next(iter(response.response))
    assert first.startswith(b"--frame") and b"fake-jpeg" in first
    response.close()


def test_video_feed_unavailable_without_camera(client, engine):
    engine.status = lambda: {"camera": "error", "error": "x", "recording": False}
    assert client.get("/video_feed").status_code == 503
