import json

from handshortcut.config_store import ConfigStore


def test_creates_empty_files(store):
    assert store.get_gestures() == [] and store.get_actions() == []
    assert (store.data_dir / "gestures.json").exists()


def test_save_update_delete(store):
    aid = store.save_action({"name": "A", "steps": []})
    gid = store.save_gesture({"name": "G", "type": "static", "action_id": aid})
    assert store.get_action(aid)["name"] == "A"
    assert store.update_gesture(gid, {"name": "G2"})["name"] == "G2"
    assert store.update_gesture("nope", {}) is None

    # supprimer l'action delie le geste
    assert store.delete_action(aid) is True
    assert store.get_gesture(gid)["action_id"] is None
    assert store.delete_action(aid) is False
    assert store.delete_gesture(gid) is True


def test_persistence_roundtrip(tmp_path):
    first = ConfigStore(tmp_path)
    first.save_action({"name": "Cafe", "steps": [{"type": "wait", "ms": 1}]})
    second = ConfigStore(tmp_path)
    assert second.get_actions()[0]["name"] == "Cafe"
    assert not list(tmp_path.glob("*.tmp"))


def test_hot_reload_and_corrupt_json_does_not_crash(store):
    path = store.actions_path
    path.write_text(json.dumps([{"id": "x", "name": "Edite a la main", "steps": []}]))
    # force un mtime different
    import os

    os.utime(path, (path.stat().st_atime, path.stat().st_mtime + 5))
    assert store.reload_if_changed() is True
    assert store.get_action("x")["name"] == "Edite a la main"

    path.write_text("{ pas du json")
    os.utime(path, (path.stat().st_atime, path.stat().st_mtime + 5))
    assert store.reload_if_changed() is False  # config precedente conservee
    assert store.get_action("x") is not None


def test_corrupt_file_at_startup_is_backed_up(tmp_path):
    (tmp_path / "gestures.json").write_text("garbage")
    store = ConfigStore(tmp_path)
    assert store.get_gestures() == []
    assert list(tmp_path.glob("gestures.json.corrupt-*"))


def test_entries_without_id_get_one(tmp_path):
    (tmp_path / "actions.json").write_text(json.dumps([{"name": "sans id", "steps": []}, 42]))
    store = ConfigStore(tmp_path)
    assert len(store.get_actions()) == 1 and store.get_actions()[0]["id"]
