"""Le catalogue des etapes (steps.py) reste la source unique : tout doit rester synchronise."""

import re
import subprocess
import sys
from pathlib import Path

from handshortcut import action_executor as ax
from handshortcut import steps
from handshortcut.schema import STEP_FIELDS, validate_step

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "src" / "handshortcut" / "webui" / "static"


def test_every_step_has_a_handler_and_vice_versa():
    assert set(steps.STEPS) == set(ax._HANDLERS)
    assert set(STEP_FIELDS) == set(steps.STEPS)


def test_catalogue_is_complete():
    assert len(steps.STEPS) == 45
    for spec in steps.STEPS.values():
        assert spec.category in steps.CATEGORY_BY_KEY
        assert spec.label and spec.description and spec.icon


def test_all_icons_exist_in_sprite():
    sprite = (STATIC / "icons.svg").read_text(encoding="utf-8")
    ids = set(re.findall(r'id="([^"]+)"', sprite))
    missing = {i for i in steps.icons_used() if i not in ids and f"i-{i}" not in ids}
    assert not missing, f"icones absentes du sprite : {sorted(missing)}"


def test_readme_steps_table_is_up_to_date():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "gen_docs.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_changelog_has_notes_for_current_version():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "release_notes.py"), "1.0.0"],
        capture_output=True,
        encoding="utf-8",
    )
    assert result.returncode == 0 and result.stdout.strip()


def test_each_step_type_validates_with_minimal_fields():
    for spec in steps.STEPS.values():
        step = {"type": spec.type}
        for key in spec.required:
            field = next(f for f in spec.fields if f.key == key)
            step[key] = {"number": 1, "select": field.options[0] if field.options else "x"}.get(
                field.kind, "http://x" if key == "url" else "x"
            )
        if spec.any_of:
            step[spec.any_of[0]] = "x"
        if spec.type == "websocket_send":
            step["url"] = "ws://localhost:1"
        assert validate_step(step, 0)["type"] == spec.type
