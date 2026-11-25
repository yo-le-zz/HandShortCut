"""Etapes logiques, garde-fous et champs communs de l'executeur."""

from physicalshortcut import action_executor as ax
from physicalshortcut import platform_utils as pu


def _setup(monkeypatch, actions):
    calls = []
    ax.set_resolver(lambda action_id: actions.get(action_id))
    monkeypatch.setitem(ax._HANDLERS, "wait", lambda step: calls.append(step.get("ms")))
    return calls


def teardown_function():
    ax.set_resolver(None)


def test_if_window_exists_runs_the_right_branch(monkeypatch):
    actions = {
        "yes": {"id": "yes", "steps": [{"type": "wait", "ms": 1}]},
        "no": {"id": "no", "steps": [{"type": "wait", "ms": 2}]},
    }
    calls = _setup(monkeypatch, actions)
    step = {"type": "if_window_exists", "title_contains": "x", "action_id": "yes", "else_action_id": "no"}
    monkeypatch.setattr(pu, "window_exists", lambda title: True)
    ax.run_action_sync({"id": "a", "steps": [step]})
    monkeypatch.setattr(pu, "window_exists", lambda title: False)
    ax.run_action_sync({"id": "a", "steps": [step]})
    assert calls == [1, 2]


def test_if_process_running(monkeypatch):
    actions = {"yes": {"id": "yes", "steps": [{"type": "wait", "ms": 7}]}}
    calls = _setup(monkeypatch, actions)
    monkeypatch.setattr(ax, "_process_running", lambda name: name == "firefox")
    ax.run_action_sync({"steps": [{"type": "if_process_running", "name": "firefox", "action_id": "yes"}]})
    ax.run_action_sync({"steps": [{"type": "if_process_running", "name": "nope", "action_id": "yes"}]})
    assert calls == [7]


def test_repeat_runs_count_times(monkeypatch):
    actions = {"inner": {"id": "inner", "steps": [{"type": "wait", "ms": 3}]}}
    calls = _setup(monkeypatch, actions)
    monkeypatch.setattr(ax.time, "sleep", lambda s: None)
    ax.run_action_sync({"steps": [{"type": "repeat", "count": 3, "action_id": "inner"}]})
    assert calls == [3, 3, 3]


def test_circular_calls_are_stopped(monkeypatch, caplog):
    actions = {"a": {"id": "a", "steps": [{"type": "repeat", "count": 1, "action_id": "a"}]}}
    _setup(monkeypatch, actions)
    ax.run_action_sync(actions["a"])
    assert "appel circulaire" in caplog.text


def test_step_budget_is_enforced(monkeypatch, caplog):
    calls = _setup(monkeypatch, {})
    monkeypatch.setattr(ax, "MAX_TOTAL_STEPS", 3)
    ax.run_action_sync({"steps": [{"type": "wait", "ms": 1}] * 10})
    assert len(calls) == 3 and "plus de" in caplog.text


def test_disabled_and_only_on_steps_are_skipped(monkeypatch):
    calls = _setup(monkeypatch, {})
    monkeypatch.setattr(pu, "current_os", lambda: "linux")
    ax.run_action_sync(
        {
            "steps": [
                {"type": "wait", "ms": 1, "enabled": False},
                {"type": "wait", "ms": 2, "only_on": "windows"},
                {"type": "wait", "ms": 3, "only_on": "linux"},
                {"type": "wait", "ms": 4},
            ]
        }
    )
    assert calls == [3, 4]


def test_missing_nested_action_does_not_crash(monkeypatch, caplog):
    _setup(monkeypatch, {})
    ax.run_action_sync({"steps": [{"type": "repeat", "count": 1, "action_id": "ghost"}]})
    assert "introuvable" in caplog.text


def test_key_aliases_are_normalized():
    assert pu.normalize_keys("Ctrl + Super+D") == ["ctrl", "win", "d"]
    assert pu.normalize_keys("control+Del") == ["ctrl", "delete"]
