"""Boucle reelle du moteur (MediaPipe + OpenCV) avec une camera simulee."""

import http.client
import threading
import time

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("mediapipe")

from physicalshortcut import gesture_engine  # noqa: E402
from physicalshortcut.gesture_engine import GestureEngine  # noqa: E402


class FakeCap:
    def __init__(self, frames_before_loss=None):
        self.reads = 0
        self.released = False
        self.limit = frames_before_loss

    def read(self):
        self.reads += 1
        time.sleep(0.005)
        if self.limit is not None and self.reads > self.limit:
            return False, None
        return True, np.zeros((120, 160, 3), np.uint8)

    def release(self):
        self.released = True


def wait_for(predicate, timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


class StubStore:
    def get_gestures(self):
        return []

    def get_action(self, _):
        return None


def test_engine_runs_streams_only_when_watched_and_stops_cleanly(monkeypatch):
    cap = FakeCap()
    monkeypatch.setattr(GestureEngine, "_open_camera", lambda self: cap)
    engine = GestureEngine(StubStore(), lambda g, a: None)
    engine.start()
    try:
        assert wait_for(lambda: engine.status()["camera"] == "ok")
        time.sleep(0.3)
        assert engine._last_jpeg is None  # personne ne regarde : pas d'encodage
        engine.get_jpeg_frame()  # un spectateur apparait
        assert wait_for(lambda: engine.get_jpeg_frame() is not None)
        assert engine.get_jpeg_frame().startswith(b"\xff\xd8")
    finally:
        engine.stop()
    assert cap.released and engine.status()["camera"] == "stopped"


def test_engine_recovers_from_lost_camera(monkeypatch):
    monkeypatch.setattr(gesture_engine, "CAMERA_MAX_READ_FAILURES", 5)
    monkeypatch.setattr(gesture_engine, "CAMERA_RETRY_SECONDS", 0.1)
    caps = [FakeCap(frames_before_loss=3), FakeCap()]
    opened = []

    def open_camera(self):
        cap = caps[len(opened)] if len(opened) < len(caps) else FakeCap()
        opened.append(cap)
        return cap

    monkeypatch.setattr(GestureEngine, "_open_camera", open_camera)
    engine = GestureEngine(StubStore(), lambda g, a: None)
    engine.start()
    try:
        assert wait_for(lambda: len(opened) >= 2)
        assert wait_for(lambda: engine.status()["camera"] == "ok")
        assert opened[0].released
    finally:
        engine.stop()


def test_engine_without_camera_reports_error_and_retries(monkeypatch):
    monkeypatch.setattr(gesture_engine, "CAMERA_RETRY_SECONDS", 0.05)
    attempts = []
    monkeypatch.setattr(GestureEngine, "_open_camera", lambda self: attempts.append(1))
    engine = GestureEngine(StubStore(), lambda g, a: None)
    engine.start()
    try:
        assert wait_for(lambda: len(attempts) >= 3)
        assert engine.status()["camera"] == "error"
        assert "camera" in engine.status()["error"].lower()
    finally:
        engine.stop()


def test_mjpeg_stream_through_waitress(store, engine):
    """Le flux video doit etre diffuse image par image (pas bufferise)."""
    import waitress.server

    from physicalshortcut.webui.app import create_app

    server = waitress.server.create_server(
        create_app(engine, store), host="127.0.0.1", port=0, threads=4
    )
    port = server.effective_port
    threading.Thread(target=server.run, daemon=True).start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/video_feed")
        response = conn.getresponse()
        assert response.status == 200
        assert response.getheader("Content-Type").startswith("multipart/x-mixed-replace")
        chunk = response.read(40)
        assert b"--frame" in chunk
        conn.close()
        # le serveur reste reactif apres la deconnexion du spectateur
        time.sleep(0.2)
        other = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        other.request("GET", "/api/status")
        assert other.getresponse().status == 200
    finally:
        server.close()
