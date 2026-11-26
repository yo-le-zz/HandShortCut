"""Boucles (tant que, compter, N fois, sortir / suivant), conditions (comparer, switch), infos systeme."""

import pytest

from physicalshortcut import action_executor as ax
from physicalshortcut import draw, system_info
from physicalshortcut.schema import validate_action
from physicalshortcut.steps import STEPS


@pytest.fixture(autouse=True)
def _resolver():
    ax.set_resolver(None)
    yield
    ax.set_resolver(None)


def run(action):
    return ax.run_action_sync(validate_action(action), {"name": "t", "value": None})


def graph(nodes, edges):
    return {"name": "t", "nodes": nodes, "edges": [{"from": a, "port": p, "to": b} for a, p, b in edges]}


def log_into(monkeypatch):
    seen = []
    monkeypatch.setitem(ax._HANDLERS, "log_message", lambda step: seen.append(step["message"]))
    return seen


# ------------------------------------------------------------------ boucles


def test_for_range_counts_with_step_and_runs_done(monkeypatch):
    seen = log_into(monkeypatch)
    result = run(graph(
        [{"id": "r", "type": "for_range", "start": 2, "end": 10, "step": 4},
         {"id": "l", "type": "log_message", "message": "i={{ i }}"},
         {"id": "d", "type": "log_message", "message": "fini"}],
        [("r", "each", "l"), ("r", "done", "d")],
    ))
    assert result["ok"] and seen == ["i=2", "i=6", "i=10", "fini"]


def test_for_range_counts_down_and_empty_range(monkeypatch):
    seen = log_into(monkeypatch)
    run(graph([{"id": "r", "type": "for_range", "start": 3, "end": 1, "step": -1},
               {"id": "l", "type": "log_message", "message": "n{{ i }}"}], [("r", "each", "l")]))
    assert seen == ["n3", "n2", "n1"]
    seen.clear()
    run(graph([{"id": "r", "type": "for_range", "start": 5, "end": 1, "step": 1},
               {"id": "l", "type": "log_message", "message": "x"}], [("r", "each", "l")]))
    assert seen == []


def test_for_range_zero_step_is_an_error():
    result = run(graph([{"id": "r", "type": "for_range", "start": 1, "end": 3, "step": 0}], []))
    assert not result["ok"]


def test_repeat_n_times_exposes_loop_info(monkeypatch):
    seen = log_into(monkeypatch)
    run(graph([{"id": "r", "type": "loop_forever", "count": 3},
               {"id": "l", "type": "log_message", "message": "{{ loop.index }}/{{ loop.count }}"}], [("r", "each", "l")]))
    assert seen == ["1/3", "2/3", "3/3"]


def test_while_loop_reevaluates_the_condition(monkeypatch):
    seen = log_into(monkeypatch)
    run(graph(
        [{"id": "i", "type": "set_variable", "variable": "n", "value": "0"},
         {"id": "w", "type": "while_loop", "condition": "n < 3"},
         {"id": "v", "type": "set_variable", "variable": "n", "value": "{{ n + 1 }}"},
         {"id": "l", "type": "log_message", "message": "n={{ n }}"}],
        [("i", "out", "w"), ("w", "each", "v"), ("v", "out", "l")],
    ))
    assert seen == ["n=1", "n=2", "n=3"]


def test_while_loop_has_a_safety_limit(monkeypatch):
    seen = log_into(monkeypatch)
    result = run(graph([{"id": "w", "type": "while_loop", "condition": "True", "max_iterations": 5},
                        {"id": "l", "type": "log_message", "message": "x"}], [("w", "each", "l")]))
    assert len(seen) == 5 and result["ok"]


def test_do_while_runs_once_and_until_stops_when_true(monkeypatch):
    seen = log_into(monkeypatch)
    run(graph([{"id": "w", "type": "while_loop", "condition": "False", "loop_mode": "do_while"},
               {"id": "l", "type": "log_message", "message": "une fois"}], [("w", "each", "l")]))
    assert seen == ["une fois"]
    seen.clear()
    run(graph([{"id": "w", "type": "while_loop", "condition": "True", "loop_mode": "until"},
               {"id": "l", "type": "log_message", "message": "jamais"}], [("w", "each", "l")]))
    assert seen == []


def test_break_and_continue(monkeypatch):
    seen = log_into(monkeypatch)
    run(graph(
        [{"id": "r", "type": "for_range", "start": 1, "end": 6},
         {"id": "c", "type": "if_value", "condition": "i == 2"},
         {"id": "skip", "type": "continue_loop"},
         {"id": "d", "type": "if_value", "condition": "i == 4"},
         {"id": "stop", "type": "break_loop"},
         {"id": "l", "type": "log_message", "message": "i={{ i }}"},
         {"id": "end", "type": "log_message", "message": "fin"}],
        [("r", "each", "c"), ("c", "true", "skip"), ("c", "out", "d"), ("d", "true", "stop"), ("d", "out", "l"), ("r", "done", "end")],
    ))
    assert seen == ["i=1", "i=3", "fin"]


def test_break_outside_a_loop_is_ignored():
    assert run(graph([{"id": "b", "type": "break_loop"}], []))["ok"]


def test_nested_break_only_leaves_the_inner_loop(monkeypatch):
    seen = log_into(monkeypatch)
    run(graph(
        [{"id": "a", "type": "for_range", "start": 1, "end": 2, "item_var": "a"},
         {"id": "b", "type": "for_range", "start": 1, "end": 3, "item_var": "b"},
         {"id": "x", "type": "break_loop"},
         {"id": "l", "type": "log_message", "message": "{{ a }}{{ b }}"}],
        [("a", "each", "b"), ("b", "each", "l"), ("l", "out", "x")],
    ))
    assert seen == ["11", "21"]


# -------------------------------------------------------------- conditions


@pytest.mark.parametrize(("left", "cmp", "right", "expected"), [
    ("10", "gt", "9", True), ("10", "lt", "9", False), ("abc", "contains", "B", True),
    ("Live", "eq", "live", True), ("a", "ne", "b", True), ("hello", "starts", "he", True),
    ("hello", "ends", "lo", True), ("", "empty", "", True), ("x", "not_empty", "", True),
    ("abc123", "matches", r"\d+", True), ("2,5", "ge", "2.5", True), ("abc", "not_contains", "z", True),
])
def test_compare_values(left, cmp, right, expected):
    assert ax.compare_values(left, cmp, right) is expected


def test_compare_is_case_sensitive_on_request():
    assert not ax.compare_values("Live", "eq", "live", ignore_case=False)


def test_if_compare_branches(monkeypatch):
    seen = log_into(monkeypatch)
    run(graph([{"id": "c", "type": "if_compare", "left": "Musique live", "cmp": "contains", "right": "live"},
               {"id": "y", "type": "log_message", "message": "oui"}, {"id": "n", "type": "log_message", "message": "non"}],
              [("c", "true", "y"), ("c", "false", "n")]))
    assert seen == ["oui"]


def test_switch_picks_the_matching_case_or_default(monkeypatch):
    seen = log_into(monkeypatch)
    nodes = lambda v: [  # noqa: E731
        {"id": "s", "type": "switch", "value": v, "case1": "1", "case2": "2", "case3": "3"},
        {"id": "a", "type": "log_message", "message": "un"}, {"id": "b", "type": "log_message", "message": "deux"},
        {"id": "d", "type": "log_message", "message": "autre"},
    ]
    edges = [("s", "case1", "a"), ("s", "case2", "b"), ("s", "default", "d")]
    run(graph(nodes("2"), edges))
    run(graph(nodes("2.0"), edges))
    run(graph(nodes("9"), edges))
    assert seen == ["deux", "deux", "autre"]


def test_if_random_extremes():
    for percent, port in ((0, "false"), (100, "true")):
        result = run(graph([{"id": "r", "type": "if_random", "percent": percent, "name": "r"}], []))
        assert result["vars"]["r"] is (port == "true")


def test_wait_until_true_and_timeout(monkeypatch):
    result = run(graph([{"id": "w", "type": "wait_until", "condition": "1 == 1", "name": "w"}], []))
    assert result["vars"]["w"] is True
    result = run(graph([{"id": "w", "type": "wait_until", "condition": "1 == 2", "timeout_s": 1, "interval_ms": 100, "name": "w"}], []))
    assert result["vars"]["w"] is False


# --------------------------------------------------------------- infos


def test_info_steps_return_values():
    result = run(graph(
        [{"id": "a", "type": "get_hostname", "name": "h"}, {"id": "b", "type": "get_os_info", "name": "os"},
         {"id": "c", "type": "get_datetime", "name": "t"}, {"id": "d", "type": "get_media_state", "name": "m"},
         {"id": "e", "type": "random_number", "minimum": 5, "maximum": 5, "name": "r"}],
        [("a", "out", "b"), ("b", "out", "c"), ("c", "out", "d"), ("d", "out", "e")],
    ))
    v = result["vars"]
    assert result["ok"] and v["h"] and v["os"]["os"] in ("linux", "windows") and 1 <= v["t"]["weekday"] <= 7
    assert v["m"]["state"] in ("playing", "paused", "stopped", "none") and v["r"] == 5


def test_live_media_variable_is_readable_in_templates():
    result = run(graph([{"id": "a", "type": "set_variable", "variable": "x", "value": "{{ media.state }}-{{ host.name != '' }}"}], []))
    assert result["ok"] and result["vars"]["x"].endswith("-true")


def test_parsers():
    assert system_info.parse_wpctl("Volume: 0.45 [MUTED]") == {"level": 45, "muted": True}
    assert system_info.parse_pactl("Volume: front-left: 30000 /  46% / -20 dB", "Mute: no") == {"level": 46, "muted": False}
    assert system_info.parse_amixer("Mono: Playback 40 [62%] [on]") == {"level": 62, "muted": False}
    media = system_info.parse_windows_media("Playing|Daft Punk|One More Time|Discovery|Spotify.exe")
    assert media["playing"] and media["title"] == "One More Time" and media["artist"] == "Daft Punk"
    assert system_info.parse_windows_media("none")["state"] == "none"
    assert system_info.parse_playerctl("Paused\n", "A\tT\tAl\tvlc\t\t")["paused"]


def test_new_steps_are_declared_with_handlers():
    for key in ("get_hostname", "get_media_state", "while_loop", "for_range", "switch", "if_compare", "wait_until"):
        assert key in STEPS and key in ax._HANDLERS
    assert STEPS["switch"].ports == ("case1", "case2", "case3", "case4", "case5", "default")


# --------------------------------------------------------------------- 5


def test_the_digit_five_is_recognised_with_several_writing_styles():
    bowl = [(0.2, 0.0), (0.15, 0.48), (0.5, 0.4), (0.8, 0.5), (0.88, 0.72), (0.7, 0.95), (0.4, 1.0), (0.1, 0.88)]
    styles = {
        "un trait": [[(0.85, 0.0), *bowl]],
        "barre en dernier": [bowl, [(0.12, 0.0), (0.88, 0.0)]],
        "panse puis barre": [list(reversed([(0.85, 0.0), *bowl]))],
    }
    lib = draw.Library()
    for name, strokes in styles.items():
        best = lib.recognize(strokes, labels=draw.labels_for("digits"), top=1)[0]
        assert best.label == "5", name
