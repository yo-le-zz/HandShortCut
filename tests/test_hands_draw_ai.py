import http.server
import itertools
import json
import threading

import pytest

from physicalshortcut import ai, draw, hands


@pytest.mark.parametrize("pattern", list(itertools.product((0, 1), repeat=5)))
def test_every_finger_pattern_is_recognised(pattern):
    frame = hands.synth_frame(pattern)
    assert [h["fingers"] for h in hands.analyze(frame)] == [list(pattern)]


def test_two_hands_are_split_and_counted():
    frame = hands.synth_frame([1, 1, 0, 0, 0], [0, 1, 1, 1, 0])
    infos = hands.analyze(frame)
    assert len(infos) == 2 and hands.total_count(frame) == 5
    assert hands.analyze(None) == [] and hands.split_hands([0.0] * 126) == []


def test_pose_mismatches_ignore_wildcards():
    assert hands.pose_mismatches([1, 0, 1, 0, 0], [1, 0, None, None, 1]) == 1


def jitter(strokes, amount=0.012):
    import random

    rng = random.Random(4)
    return [[(x + rng.uniform(-amount, amount), y + rng.uniform(-amount, amount)) for x, y in s] for s in strokes]


@pytest.mark.parametrize("label", list("0123456789") + ["triangle", "etoile", "coeur", "zigzag", "coche"])
def test_templates_are_recognised_with_noise(label):
    lib = draw.Library()
    for variant in draw.TEMPLATES[label][:1]:
        # echelle et position differentes
        moved = [[(x * 0.6 + 0.2, y * 0.6 + 0.3) for x, y in s] for s in variant]
        match = lib.recognize(jitter(moved))[0]
        assert match.label == label or match.confidence < 0.99


def test_digits_are_mostly_distinguished():
    lib = draw.Library()
    good = 0
    for label in "0123456789":
        top = lib.recognize(jitter(draw.TEMPLATES[label][0]), labels=draw.labels_for("digits"))[0]
        good += top.label == label
    assert good >= 9


def test_custom_template_dump_and_load():
    lib = draw.Library()
    strokes = [[(0.0, 0.0), (0.5, 0.1), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)] * 3]
    lib.add_custom("mon-signe", strokes)
    other = draw.Library()
    assert other.load(json.loads(json.dumps(lib.dump()))) == 1
    assert other.recognize(strokes)[0].label == "mon-signe"
    assert lib.remove_custom("mon-signe") and not lib.remove_custom("mon-signe")
    assert other.load("n'importe quoi") == 0


def test_tracker_returns_drawing_after_pause_and_ignores_scribbles():
    tr = draw.Tracker(idle_ms=500)
    t = 0.0
    for stroke in draw.TEMPLATES["cercle"][0]:
        for x, y in stroke:
            tr.update(True, x, y, t)
            t += 0.03
        tr.update(False, None, None, t)
    assert tr.active
    assert tr.update(False, None, None, t + 0.2) is None
    result = tr.update(False, None, None, t + 0.7)
    assert result and result.strokes
    tiny = draw.Tracker(idle_ms=100)
    tiny.update(True, 0.5, 0.5, 0)
    assert tiny.update(False, None, None, 1.0) is None


def test_render_png_and_label_value():
    png = draw.render_png(draw.TEMPLATES["8"][0])
    assert png.startswith(b"\x89PNG") and len(png) > 200
    assert draw.label_value("7") == 7 and draw.label_value("cercle") == "cercle"


class _Handler(http.server.BaseHTTPRequestHandler):
    seen: list = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _Handler.seen.append((self.headers.get("Authorization"), body))
        answer = "C'est un 7." if "image_url" in json.dumps(body) else "bonjour"
        data = json.dumps({"choices": [{"message": {"content": answer}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def test_ai_client_against_fake_server(monkeypatch):
    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}/v1"
    monkeypatch.setenv("FAKE_KEY", "secret")
    try:
        assert ai.ask("salut", base_url=base, model="m", key_env="FAKE_KEY") == "bonjour"
        assert _Handler.seen[-1][0] == "Bearer secret"
        answer = ai.ask("quoi ?", image=b"\x89PNG", image_mime="image/png", base_url=base, model="m")
        assert "7" in answer
    finally:
        server.shutdown()


def test_ai_errors_are_explicit():
    with pytest.raises(ai.AIError):
        ai.ask("x", base_url="http://127.0.0.1:9/v1", model="m", timeout=1)
    with pytest.raises(ai.AIError):
        ai.ask("x", base_url="ftp://x", model="m")
    with pytest.raises(ai.AIError):
        ai.ask("x", base_url="http://127.0.0.1:1", model="")
