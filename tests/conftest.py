import pytest

from handshortcut.config_store import ConfigStore


class FakeEngine:
    """Moteur factice : l'interface web n'a besoin ni de camera ni de MediaPipe."""

    def __init__(self):
        self.recording = None
        self.frame = b"\xff\xd8fake-jpeg\xff\xd9"

    def status(self):
        return {"camera": "ok", "error": None, "recording": self.recording is not None}

    def get_jpeg_frame(self):
        return self.frame

    def start_recording(self, kind):
        self.recording = kind

    def cancel_recording(self):
        self.recording = None

    def stop_recording(self):
        kind, self.recording = self.recording, None
        if kind is None:
            return {"error": "Aucun enregistrement en cours."}
        return {"type": kind}


@pytest.fixture
def store(tmp_path):
    return ConfigStore(tmp_path / "data")


@pytest.fixture
def engine():
    return FakeEngine()


@pytest.fixture
def stopped():
    from threading import Event

    return Event()


@pytest.fixture
def client(store, engine, stopped):
    from handshortcut.webui.app import create_app

    app = create_app(engine, store, on_shutdown=stopped.set)
    app.testing = True
    return app.test_client()


@pytest.fixture
def api():
    """En-tetes exiges par la protection CSRF pour les ecritures."""
    return {"X-HandShortCut": "1"}


def vec(value=0.1, length=126):
    return [value] * length
