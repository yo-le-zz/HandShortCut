"""Workflows en graphe : liens, ports, partage de donnees, boucles, erreurs, limites."""

import pytest

from physicalshortcut import action_executor as ax
from physicalshortcut.schema import ValidationError, validate_action


@pytest.fixture(autouse=True)
def _resolver():
    ax.set_resolver(None)
    yield
    ax.set_resolver(None)


def run(action, context=None):
    return ax.run_action_sync(validate_action(action), context or {"name": "t", "value": None})


def chain_of(*nodes):
    nodes = [{"id": f"n{i}", **n} for i, n in enumerate(nodes, 1)]
    return {"name": "t", "nodes": nodes, "edges": [{"from": f"n{i}", "port": "out", "to": f"n{i + 1}"} for i in range(1, len(nodes))]}


def test_read_file_output_feeds_write_file(tmp_path):
    source, target = tmp_path / "a.txt", tmp_path / "b.txt"
    source.write_text("salut", encoding="utf-8")
    result = run(chain_of(
        {"type": "file_read", "path": str(source), "name": "contenu"},
        {"type": "file_write", "path": str(target), "content": "{{ contenu | upper }}!"},
    ))
    assert result["ok"] and target.read_text(encoding="utf-8") == "SALUT!"
    assert result["vars"]["contenu"] == "salut"


def test_gesture_value_is_available_and_keeps_its_type(monkeypatch):
    seen = []
    monkeypatch.setitem(ax._HANDLERS, "set_volume", lambda step: seen.append(step["level"]))
    run(chain_of({"type": "set_volume", "level": "{{ gesture.value * 10 }}"}), {"name": "g", "value": 7})
    assert seen == [70]


def test_branches_follow_true_or_false(monkeypatch):
    hit = []
    monkeypatch.setitem(ax._HANDLERS, "log_message", lambda step: hit.append(step["message"]))
    action = {
        "name": "b",
        "nodes": [
            {"id": "c", "type": "if_value", "condition": "{{ gesture.value == 2 }}"},
            {"id": "y", "type": "log_message", "message": "oui"},
            {"id": "n", "type": "log_message", "message": "non"},
        ],
        "edges": [{"from": "c", "port": "true", "to": "y"}, {"from": "c", "port": "false", "to": "n"}],
    }
    run(action, {"name": "g", "value": 2})
    run(action, {"name": "g", "value": 5})
    assert hit == ["oui", "non"]


def test_for_each_runs_each_branch_then_done(monkeypatch):
    seen = []
    monkeypatch.setitem(ax._HANDLERS, "log_message", lambda step: seen.append(step["message"]))
    action = {
        "name": "loop",
        "nodes": [
            {"id": "l", "type": "for_each", "items": "{{ [1, 2, 3] }}"},
            {"id": "a", "type": "log_message", "message": "item {{ item }}"},
            {"id": "z", "type": "log_message", "message": "fini"},
        ],
        "edges": [{"from": "l", "port": "each", "to": "a"}, {"from": "l", "port": "done", "to": "z"}],
    }
    assert run(action)["ok"]
    assert seen == ["item 1", "item 2", "item 3", "fini"]


def test_error_port_takes_over_and_stop_policy(monkeypatch):
    seen = []
    monkeypatch.setitem(ax._HANDLERS, "open_url", lambda step: 1 / 0)
    monkeypatch.setitem(ax._HANDLERS, "log_message", lambda step: seen.append(step["message"]))
    with_error_edge = {
        "name": "e",
        "nodes": [{"id": "a", "type": "open_url", "url": "https://x.y"}, {"id": "ok", "type": "log_message", "message": "suite"},
                  {"id": "ko", "type": "log_message", "message": "erreur geree"}],
        "edges": [{"from": "a", "port": "out", "to": "ok"}, {"from": "a", "port": "error", "to": "ko"}],
    }
    result = run(with_error_edge)
    assert seen == ["erreur geree"] and not result["ok"]
    seen.clear()
    stop = chain_of({"type": "open_url", "url": "https://x.y", "on_error": "stop"}, {"type": "log_message", "message": "jamais"})
    run(stop)
    assert seen == []
    cont = chain_of({"type": "open_url", "url": "https://x.y"}, {"type": "log_message", "message": "continue"})
    run(cont)
    assert seen == ["continue"]


def test_legacy_steps_still_work(monkeypatch):
    calls = []
    monkeypatch.setitem(ax._HANDLERS, "wait", lambda step: calls.append(step["ms"]))
    assert ax.run_action_sync({"name": "old", "steps": [{"type": "wait", "ms": 1}, {"type": "wait", "ms": 2}]})["ok"]
    assert calls == [1, 2]


def test_run_action_passes_args_and_result(monkeypatch):
    sub = {"id": "sub", "name": "sub", "nodes": [{"id": "s", "type": "set_variable", "variable": "result", "value": "{{ args.n * 2 }}"}], "edges": []}
    ax.set_resolver(lambda action_id: sub if action_id == "sub" else None)
    result = run(chain_of({"type": "run_action", "action_id": "sub", "args": "n=21", "name": "r"}))
    assert result["vars"]["r"] in (42, "42")


def test_recursive_workflow_is_stopped():
    loop = {"id": "me", "name": "me", "nodes": [{"id": "a", "type": "run_action", "action_id": "me"}], "edges": []}
    ax.set_resolver(lambda action_id: loop)
    assert ax.run_action_sync(loop)["ok"] is False


def test_stop_workflow_halts_everything(monkeypatch):
    seen = []
    monkeypatch.setitem(ax._HANDLERS, "log_message", lambda step: seen.append(1))
    action = {
        "name": "s",
        "nodes": [{"id": "a", "type": "log_message", "message": "debut"}, {"id": "b", "type": "stop_workflow"},
                  {"id": "c", "type": "log_message", "message": "x"}],
        "edges": [{"from": "a", "port": "out", "to": "b"}, {"from": "a", "port": "out", "to": "c"}],
    }
    run(action)
    assert seen == [1]  # « debut » seulement : le noeud c n'est jamais atteint


def test_system_condition_node(monkeypatch):
    from physicalshortcut import system_metrics as sm

    monkeypatch.setattr(sm, "read_metric", lambda key, arg="": 80.0)
    seen = []
    monkeypatch.setitem(ax._HANDLERS, "log_message", lambda step: seen.append(step["message"]))
    action = {
        "name": "s",
        "nodes": [{"id": "c", "type": "if_system", "metric": "cpu_percent", "op": ">", "value": 70},
                  {"id": "t", "type": "log_message", "message": "charge"}, {"id": "f", "type": "log_message", "message": "calme"}],
        "edges": [{"from": "c", "port": "true", "to": "t"}, {"from": "c", "port": "false", "to": "f"}],
    }
    run(action)
    assert seen == ["charge"]


def test_step_events_carry_node_ids_and_outputs(tmp_path):
    from physicalshortcut import events

    events.clear()
    f = tmp_path / "x.txt"
    f.write_text("hello", encoding="utf-8")
    run(chain_of({"type": "file_read", "path": str(f), "name": "t"}))
    kinds = [e["kind"] for e in events.since(0)]
    assert kinds[0] == "action_start" and kinds[-1] == "action_end"
    step = next(e for e in events.since(0) if e["kind"] == "step")
    assert step["node_id"] == "n1" and step["status"] == "ok" and "hello" in step["output"]


def test_graph_validation_rejects_bad_graphs():
    base = chain_of({"type": "wait", "ms": 1}, {"type": "wait", "ms": 1})
    bad_port = {**base, "edges": [{"from": "n1", "port": "true", "to": "n2"}]}
    with pytest.raises(ValidationError):
        validate_action(bad_port)
    with pytest.raises(ValidationError):
        validate_action({**base, "edges": [{"from": "n1", "port": "out", "to": "zzz"}]})
    with pytest.raises(ValidationError):
        validate_action({**base, "edges": [{"from": "n1", "port": "out", "to": "n1"}]})
    dup = {"name": "d", "nodes": [{"id": "a", "type": "wait", "ms": 1}, {"id": "a", "type": "wait", "ms": 1}], "edges": []}
    with pytest.raises(ValidationError):
        validate_action(dup)
    with pytest.raises(ValidationError):
        validate_action({"name": "x", "nodes": [{"id": "a", "type": "nope"}], "edges": []})
