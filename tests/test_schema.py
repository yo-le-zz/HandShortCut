import pytest

from handshortcut.action_executor import _HANDLERS
from handshortcut.schema import (
    FRAME_VEC_LEN,
    STEP_FIELDS,
    ValidationError,
    validate_action,
    validate_gesture,
    validate_gesture_patch,
)

from .conftest import vec


def test_every_step_type_has_a_handler():
    assert set(STEP_FIELDS) == set(_HANDLERS)


def test_action_ok_and_cleaned():
    action = validate_action(
        {
            "name": "  Musique ",
            "steps": [
                {"type": "launch", "path": "spotify", "args": ["a", 1], "junk": "x"},
                {"type": "move_window", "title_contains": "spot", "monitor": "2"},
                {"type": "wait", "ms": 500, "wait_ms": 10},
            ],
        }
    )
    assert action["name"] == "Musique"
    assert action["steps"][0] == {"type": "launch", "path": "spotify", "args": ["a", "1"]}
    assert action["steps"][1]["monitor"] == 2 and action["steps"][1]["position"] == "fullscreen"
    assert action["steps"][2]["wait_ms"] == 10


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {"name": "", "steps": []},
        {"name": "x", "steps": "nope"},
        {"name": "x", "steps": [{"type": "rm_rf"}]},
        {"name": "x", "steps": [{"type": "launch"}]},
        {"name": "x", "steps": [{"type": "wait", "ms": -5}]},
        {"name": "x", "steps": [{"type": "http_request", "url": "file:///etc/passwd"}]},
        {"name": "x", "steps": [{"type": "media_control", "action": "explode"}]},
        {
            "name": "x",
            "steps": [{"type": "move_window", "title_contains": "a", "position": "nowhere"}],
        },
    ],
)
def test_action_rejected(payload):
    with pytest.raises(ValidationError):
        validate_action(payload)


def test_gesture_static_and_sequence():
    g = validate_gesture({"name": "a", "type": "static", "template": vec(), "threshold": 0.2})
    assert g["type"] == "static" and len(g["template"]) == 126
    s = validate_gesture(
        {"name": "b", "type": "sequence", "keyframes": [vec(), vec(0.2)], "duration": 1.5}
    )
    assert s["duration"] == 1.5


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "a", "type": "static", "template": [1, 2, 3]},
        {"name": "a", "type": "static", "template": vec(float("nan"))},
        {"name": "a", "type": "sequence", "keyframes": [vec()]},
        {"name": "a", "type": "other"},
        {"name": "a", "type": "static", "template": vec(), "threshold": 99},
    ],
)
def test_gesture_rejected(payload):
    with pytest.raises(ValidationError):
        validate_gesture(payload)


def test_gesture_patch_only_known_fields():
    assert validate_gesture_patch({"action_id": "abc", "junk": "ignored"}) == {"action_id": "abc"}
    assert validate_gesture_patch({"action_id": None}) == {"action_id": None}
    assert validate_gesture_patch({"hold_frames": 6}) == {"hold_ms": 200}  # ancien format converti
    assert validate_gesture_patch({"hold_ms": 450})["hold_ms"] == 450


def test_gesture_patch_can_rerecord():
    patch = validate_gesture_patch({"type": "static", "template": vec(0.3)})
    assert patch["type"] == "static" and len(patch["template"]) == FRAME_VEC_LEN
    with pytest.raises(ValidationError):  # un modele sans type est ambigu
        validate_gesture_patch({"template": vec()})
    with pytest.raises(ValidationError):
        validate_gesture_patch({"type": "sequence", "keyframes": [vec()]})
