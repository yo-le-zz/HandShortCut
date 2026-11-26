import time
from types import SimpleNamespace

import pytest

from physicalshortcut.gesture_engine import (
    GestureEngine,
    distance,
    extract_frame_vector,
    normalize_hand,
    resample,
    sequence_window,
)

from .conftest import vec


def hand(scale=1.0, dx=0.0, dy=0.0):
    pts = [
        SimpleNamespace(x=dx + 0.01 * i * scale, y=dy + 0.02 * i * scale, z=0.0) for i in range(21)
    ]
    return SimpleNamespace(landmark=pts)


def test_normalisation_is_invariant_to_position_and_size():
    a = normalize_hand(hand(1.0).landmark)
    b = normalize_hand(hand(3.0, dx=0.4, dy=0.2).landmark)
    assert distance(a, b) < 1e-9
    assert a[:3] == [0.0, 0.0, 0.0]


def test_frame_vector_shape_and_padding():
    assert extract_frame_vector(None) is None
    one = extract_frame_vector([hand()])
    assert len(one) == 126 and one[63:] == [0.0] * 63
    two = extract_frame_vector([hand(dx=0.5), hand(dx=0.0)])
    assert len(two) == 126 and two[63:] != [0.0] * 63


def test_distance_and_resample():
    assert distance([0, 0], [3, 4]) == pytest.approx((25 / 2) ** 0.5)
    assert distance([], [1]) == float("inf")
    assert resample([1, 2, 3, 4, 5], 3) == [1, 3, 5]
    assert resample([1, 2], 4) == [1, 1, 2, 2]
    assert resample([], 3) == []


def test_sequence_window_uses_recorded_duration():
    assert sequence_window({}) == 3.0
    assert sequence_window({"duration": 2.0}) == pytest.approx(2.3)
    assert sequence_window({"duration": 100}) == 6.0
    assert sequence_window({"duration": 0.1}) == 0.5


class StubStore:
    def __init__(self, gestures, actions):
        self._g, self._a = gestures, {a["id"]: a for a in actions}

    def get_gestures(self):
        return self._g

    def get_action(self, action_id):
        return self._a.get(action_id)


def make_engine(gestures, actions=()):
    fired = []
    engine = GestureEngine(
        StubStore(gestures, list(actions)), lambda g, a: fired.append((g["id"], a["id"]))
    )
    return engine, fired


def test_static_gesture_needs_hold_duration_then_cooldown():
    gesture = {
        "id": "g",
        "type": "static",
        "template": vec(0.5),
        "threshold": 0.05,
        "hold_ms": 100,
        "cooldown_seconds": 10,
        "action_id": "a",
    }
    engine, fired = make_engine([gesture], [{"id": "a", "name": "A"}])
    now = time.monotonic()
    for i in range(3):  # 0, 30, 60 ms : tenue trop courte
        engine._process_detection(vec(0.5), now + i * 0.03)
    assert fired == []
    engine._process_detection(vec(0.5), now + 0.11)  # >= 100 ms de tenue : declenche
    assert fired == [("g", "a")]
    for i in range(10):  # cooldown : pas de redeclenchement
        engine._process_detection(vec(0.5), now + 1 + i * 0.03)
    assert len(fired) == 1
    engine._process_detection(vec(0.5), now + 11)  # cooldown ecoule : la tenue repart de 0
    assert len(fired) == 1
    engine._process_detection(vec(0.5), now + 11.12)
    assert len(fired) == 2


def test_legacy_hold_frames_are_converted_to_duration():
    gesture = {
        "id": "g",
        "type": "static",
        "template": vec(0.5),
        "threshold": 0.05,
        "hold_frames": 3,  # ancien format : 3 images a 30 images/s = 100 ms
        "cooldown_seconds": 0,
        "action_id": "a",
    }
    engine, fired = make_engine([gesture], [{"id": "a"}])
    now = time.monotonic()
    engine._process_detection(vec(0.5), now)
    engine._process_detection(vec(0.5), now + 0.09)
    assert fired == []
    engine._process_detection(vec(0.5), now + 0.11)
    assert fired == [("g", "a")]


def test_gap_in_camera_stream_restarts_the_hold():
    gesture = {
        "id": "g",
        "type": "static",
        "template": vec(0.5),
        "threshold": 0.05,
        "hold_ms": 200,
        "cooldown_seconds": 0,
        "action_id": "a",
    }
    engine, fired = make_engine([gesture], [{"id": "a"}])
    now = time.monotonic()
    engine._process_detection(vec(0.5), now)
    engine._process_detection(vec(0.5), now + 2.0)  # 2 s sans image : pas une tenue continue
    assert fired == []
    engine._process_detection(vec(0.5), now + 2.25)
    assert fired == [("g", "a")]


def test_live_scores_and_fps():
    gesture = {
        "id": "g",
        "type": "static",
        "template": vec(0.5),
        "threshold": 0.05,
        "hold_ms": 1000,
        "action_id": None,
    }
    engine, _ = make_engine([gesture])
    now = time.monotonic()
    for i in range(10):
        engine._track_fps(now + i * 0.04)  # 25 images/s
    assert engine.status()["fps"] == pytest.approx(25, abs=0.5)
    engine._process_detection(vec(0.5), now)
    engine._process_detection(vec(0.5), now + 0.4)
    score = engine.live_scores()["g"]
    assert score["distance"] == 0 and score["threshold"] == 0.05
    assert score["held_ms"] == 400 and score["hold_ms"] == 1000


def test_static_hold_resets_when_pose_lost():
    gesture = {
        "id": "g",
        "type": "static",
        "template": vec(0.5),
        "threshold": 0.05,
        "hold_ms": 100,
        "cooldown_seconds": 0,
        "action_id": "a",
    }
    engine, fired = make_engine([gesture], [{"id": "a"}])
    now = time.monotonic()
    engine._process_detection(vec(0.5), now)
    engine._process_detection(vec(0.5), now + 0.05)
    engine._process_detection(None, now + 0.08)
    engine._process_detection(vec(0.5), now + 0.11)  # 110 ms depuis le debut, mais interrompu
    assert fired == []


def test_sequence_gesture_matches_recorded_motion():
    keyframes = [vec(0.1 * i) for i in range(10)]
    gesture = {
        "id": "s",
        "type": "sequence",
        "keyframes": keyframes,
        "threshold": 0.05,
        "duration": 1.0,
        "cooldown_seconds": 5,
        "action_id": "a",
    }
    engine, fired = make_engine([gesture], [{"id": "a"}])
    now = time.monotonic()
    for i in range(30):
        engine._process_detection(vec(0.1 * (i * 9 / 29)), now + i * 0.04)
    assert fired == [("s", "a")]


def test_gesture_without_action_is_harmless_and_cooldown_applies():
    gesture = {
        "id": "g",
        "type": "static",
        "template": vec(0.5),
        "threshold": 0.05,
        "hold_ms": 0,
        "cooldown_seconds": 5,
        "action_id": None,
    }
    engine, fired = make_engine([gesture])
    engine._process_detection(vec(0.5), time.monotonic())
    assert fired == []


def test_recording_static_and_sequence_and_stop_without_start():
    engine, _ = make_engine([])
    assert "error" in engine.stop_recording()

    engine.start_recording("static")
    for _ in range(5):
        engine._handle_vector(vec(1.0))
    result = engine.stop_recording()
    assert result["type"] == "static" and result["template"][0] == pytest.approx(1.0)
    assert result["frames"] == 5 and result["elapsed_ms"] >= 0 and "fps" in result

    engine.start_recording("sequence")
    for i in range(20):
        engine._handle_vector(vec(i / 10))
        time.sleep(0.001)
    seq = engine.stop_recording()
    assert seq["type"] == "sequence" and len(seq["keyframes"]) == 10 and seq["duration"] > 0

    engine.start_recording("static")
    engine._handle_vector(None)
    assert "error" in engine.stop_recording()

    with pytest.raises(ValueError):
        engine.start_recording("weird")


def test_detection_paused_while_recording_and_recording_expires(monkeypatch):
    gesture = {
        "id": "g",
        "type": "static",
        "template": vec(0.5),
        "threshold": 0.05,
        "hold_ms": 0,
        "cooldown_seconds": 0,
        "action_id": "a",
    }
    engine, fired = make_engine([gesture], [{"id": "a"}])
    engine.start_recording("static")
    engine._handle_vector(vec(0.5))
    assert fired == []

    engine._record_started -= 1000  # expire
    engine._handle_vector(vec(0.5))
    assert engine.status()["recording"] is False
    engine._handle_vector(vec(0.5))
    assert fired == []  # toujours suspendu jusqu'au stop...
    assert engine.stop_recording()["type"] == "static"
    engine._handle_vector(vec(0.5))
    assert fired == [("g", "a")]  # ...puis la detection reprend
