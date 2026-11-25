import http.server
import json
import threading
import time

from physicalshortcut import action_executor as ax
from physicalshortcut import platform_utils as pu


def test_unknown_and_failing_steps_do_not_stop_the_action(monkeypatch, caplog):
    calls = []
    monkeypatch.setitem(ax._HANDLERS, "wait", lambda step: calls.append(step))
    monkeypatch.setitem(ax._HANDLERS, "open_url", lambda step: 1 / 0)
    ax.run_action_sync(
        {
            "name": "t",
            "steps": [{"type": "nope"}, {"type": "open_url"}, {"type": "wait", "ms": 1}, 7],
        }
    )
    assert [(c["type"], c["ms"]) for c in calls] == [("wait", 1)]
    assert "type inconnu" in caplog.text and "en erreur" in caplog.text


def test_wait_ms_delays_after_step(monkeypatch):
    slept = []
    monkeypatch.setattr(ax.time, "sleep", slept.append)
    monkeypatch.setitem(ax._HANDLERS, "wait", lambda step: None)
    ax.run_action_sync({"steps": [{"type": "wait", "wait_ms": 250}]})
    assert slept == [0.25]


def test_http_request_posts_json():
    received = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            received["body"] = self.rfile.read(int(self.headers["Content-Length"]))
            received["type"] = self.headers["Content-Type"]
            self.send_response(204)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        ax._step_http_request(
            {"method": "post", "url": f"http://127.0.0.1:{server.server_port}/", "body": '{"a": 1}'}
        )
    finally:
        server.shutdown()
    assert json.loads(received["body"]) == {"a": 1}
    assert received["type"] == "application/json"


def test_http_request_refuses_non_http(caplog):
    ax._step_http_request({"url": "file:///etc/passwd"})
    assert "http://" in caplog.text


def test_kill_process_never_targets_itself(monkeypatch):
    import os

    import psutil

    terminated = []

    class Proc:
        def __init__(self, pid, name):
            self.info = {"pid": pid, "name": name}

        def terminate(self):
            terminated.append(self.info["pid"])

    monkeypatch.setattr(
        psutil,
        "process_iter",
        lambda attrs: [Proc(os.getpid(), "python"), Proc(999999, "python3")],
    )
    ax._step_kill_process({"name": "python"})
    assert terminated == [999999]


def test_spawn_runs_and_reaps_children():
    assert pu.spawn(["python3", "-c", "pass"]) is True
    assert pu.spawn(["definitely-not-a-command-xyz"]) is False


def test_rect_for_position():
    mon = {"x": 100, "y": 50, "width": 1920, "height": 1080}
    assert pu.rect_for_position(mon, "fullscreen") == (100, 50, 1920, 1080)
    assert pu.rect_for_position(mon, "left_half") == (100, 50, 960, 1080)
    assert pu.rect_for_position(mon, "right_half") == (1060, 50, 960, 1080)
    assert pu.rect_for_position(mon, "top_half") == (100, 50, 1920, 540)
    assert pu.rect_for_position(mon, "bottom_half") == (100, 590, 1920, 540)
    assert pu.rect_for_position(mon, "center") == (580, 320, 960, 540)
    assert pu.rect_for_position(mon, "???") == (100, 50, 1920, 1080)


def test_list_monitors_never_raises_without_display(monkeypatch):
    import screeninfo

    def boom():
        raise screeninfo.ScreenInfoError("no display")

    monkeypatch.setattr(screeninfo, "get_monitors", boom)
    assert pu.list_monitors() == []
    assert pu.get_monitor(1) is None


def test_media_control_rejects_unknown_action():
    assert pu.media_control("explode") is False


def test_launch_without_path():
    assert pu.launch_app(None) is False
    assert time  # (import utilise)
