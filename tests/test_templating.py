import pytest

from physicalshortcut import templating as t


def test_plain_text_and_types_are_preserved():
    assert t.render("bonjour", {}) == "bonjour"
    assert t.render("{{ n }}", {"n": 3}) == 3  # un seul jeton garde son type
    assert t.render("a {{ n }} b", {"n": 3}) == "a 3 b"
    assert t.render({"k": ["{{ x }}", 1]}, {"x": "v"}) == {"k": ["v", 1]}


def test_arithmetic_comparisons_and_filters():
    assert t.render("{{ gesture.value * 10 }}", {"gesture": {"value": 7}}) == 70
    assert t.render("{{ name | upper }}", {"name": "abc"}) == "ABC"
    assert t.render("{{ missing | default('x') }}", {}) == "x"
    assert t.render("{{ 3 == '3' }}", {}) is True
    assert t.render("{{ items | length }}", {"items": [1, 2, 3]}) == 3
    assert t.render("{{ text | truncate(3) }}", {"text": "abcdef"}).startswith("abc")
    assert t.eval_expression("a > 1 and b", {"a": 2, "b": True}) is True


def test_missing_variable_is_none_not_an_error():
    assert t.render("{{ nothing.here }}", {}) in (None, "")


def test_unsafe_expressions_are_rejected():
    for bad in ("{{ __import__('os').system('x') }}", "{{ 9 ** 99999999 }}", "{{ open('/etc/passwd') }}"):
        with pytest.raises(t.TemplateError):
            t.render(bad, {})


def test_references_and_preview():
    assert {"contenu", "gesture"} <= t.find_references("{{ contenu | upper }} {{ gesture.value }}")
    assert len(t.preview("x" * 1000, 50)) <= 60


def test_dunder_attributes_leak_nothing():
    assert t.render("{{ x.__class__ }}", {"x": "abc"}) in ("", None)
    assert t.render("{{ x.__dict__ }}", {"x": {"a": 1}}) in ("", None)
