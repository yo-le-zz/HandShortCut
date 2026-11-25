"""Capteurs v2.0 : son, voix, empreinte, peripheriques, capteurs externes, hub, migration."""

import json
import time

import numpy as np
import pytest

from physicalshortcut import paths, system_metrics, templates_lib
from physicalshortcut.config_store import ConfigStore
from physicalshortcut.gesture_engine import GestureEngine
from physicalshortcut.schema import ValidationError, validate_gesture, validate_gesture_patch
from physicalshortcut.sensors import devices, external, fingerprint, voice_text
from physicalshortcut.sensors.audio import SAMPLE_RATE, ClapDetector, to_db
from physicalshortcut.sensors.hub import SensorHub, clap_matches

# ----------------------------------------------------------------- voix


def test_match_phrase_modes():
    assert voice_text.match_phrase("Ouvre le navigateur s'il te plaît", ["ouvre le navigateur"]) == "ouvre le navigateur"
    assert voice_text.match_phrase("ouvre le navigateur", ["ouvre le navigateur"], "exact")
    assert voice_text.match_phrase("ouvre le navigateurs", ["ouvre le navigateur"], "exact") is None
    assert voice_text.match_phrase("ouvre le navigateure", ["ouvre le navigateur"], "fuzzy")
    assert voice_text.match_phrase("bonjour", ["ouvre"]) is None


def test_extract_number_digits_and_french_words():
    assert voice_text.extract_number("volume 40") == 40
    assert voice_text.extract_number("volume soixante") == 60
    assert voice_text.extract_number("volume quatre-vingt-dix") == 90
    assert voice_text.extract_number("rien") is None


# ----------------------------------------------------------------- son


def clap(rate=SAMPLE_RATE, amp=0.9):
    n = int(0.03 * rate)
    return (amp * np.exp(-np.linspace(0, 8, n)) * np.sign(np.random.default_rng(1).standard_normal(n))).astype(np.float32)


def silence(seconds, rate=SAMPLE_RATE):
    return np.full(int(seconds * rate), 0.001, dtype=np.float32)


def run_detector(parts):
    det = ClapDetector(sensitivity=0.6)
    out = []
    for part in parts:
        out += det.feed(part)
    return out


def test_clap_groups_are_counted():
    single = [silence(0.5), clap(), silence(1.0)]
    double = [silence(0.5), clap(), silence(0.25), clap(), silence(1.0)]
    assert run_detector(single) == [1]
    assert run_detector(double) == [2]
    assert run_detector([silence(2.0)]) == []


def test_sustained_loud_noise_is_not_a_clap():
    noise = (0.8 * np.sin(np.linspace(0, 2000, SAMPLE_RATE))).astype(np.float32)
    assert run_detector([silence(0.5), noise, silence(1.0)]) == []


def test_db_scale_and_clap_matching():
    assert to_db(1.0) == pytest.approx(0, abs=0.1)
    assert to_db(0.1) == pytest.approx(-20, abs=0.5)
    assert clap_matches("double_clap", [2]) and not clap_matches("double_clap", [1])
    assert clap_matches("any_clap", [3]) and not clap_matches("loud", [1])


# ------------------------------------------------------ capteurs externes


def test_parse_line_formats():
    assert external.parse_line("gaz=412") == [("gaz", 412.0)]
    assert external.parse_line("gaz:41,5 temp=20") == [("gaz", 41.5), ("temp", 20.0)]
    assert external.parse_line('{"gaz": 3, "t": 2.5}') == [("gaz", 3.0), ("t", 2.5)]
    assert external.parse_line("17", "pir") == [("pir", 17.0)]
    assert external.parse_line("bonjour") == []


def test_validate_sensors():
    ok = external.validate_sensors([{"name": "gaz", "kind": "serial", "port": "/dev/ttyACM0"}])
    assert ok[0]["baud"] == 9600
    for bad in ([{"name": "1x", "kind": "serial", "port": "p"}], [{"name": "a", "kind": "x"}],
                [{"name": "a", "kind": "command", "command": ""}], "pas une liste"):
        with pytest.raises(ValueError):
            external.validate_sensors(bad)


def test_external_values_expire(tmp_path):
    ext = external.ExternalSensors(tmp_path / "s.json")
    ext.set_value("gaz", 5)
    assert ext.get("gaz") == 5 and ext.get("inconnu") is None
    ext._values["gaz"] = (5.0, time.time() - 999)
    assert ext.get("gaz") is None


# ---------------------------------------------------------- peripheriques


def test_diff_state_events():
    old = {"usb": {"a": "Cle"}, "bluetooth": {}, "ac": True, "lid": False, "wifi": "Maison"}
    new = {"usb": {"b": "Souris"}, "bluetooth": {"x": "Casque"}, "ac": False, "lid": True, "wifi": None}
    got = {e[0] for e in devices.diff_state(old, new)}
    assert got == {"usb_plugged", "usb_unplugged", "bluetooth_connected", "power_unplugged", "lid_closed", "wifi_disconnected"}
    assert devices.diff_state(old, old) == []
    assert devices.diff_state({"usb": None}, {"usb": {"a": "x"}}) == []  # illisible puis lisible : pas d'evenement


def test_families_for():
    assert devices.families_for({"usb_plugged", "lid_opened"}) == {"usb", "lid"}


def test_fingerprint_output_parsing():
    assert fingerprint.parse_verify_output("Verify result: verify-match (done)")[0] == "match"
    assert fingerprint.parse_verify_output("Verify result: verify-no-match (done)")[0] == "no_match"
    assert fingerprint.parse_verify_output("rien")[0] is None


# ------------------------------------------------------------------ schema


def test_new_gesture_types_validate():
    assert validate_gesture({"name": "c", "type": "sound", "sound": "triple_clap"})["sound"] == "triple_clap"
    assert validate_gesture({"name": "v", "type": "voice", "phrases": [" ouvre "], "match": "fuzzy"})["phrases"] == ["ouvre"]
    assert validate_gesture({"name": "f", "type": "fingerprint", "result": "any"})["result"] == "any"
    assert validate_gesture({"name": "d", "type": "device", "event": "usb_plugged"})["event"] == "usb_plugged"
    s = validate_gesture({"name": "s", "type": "sensor", "metric": "external", "arg": "gaz", "op": ">", "value": 400})
    assert s["arg"] == "gaz" and s["value"] == 400
    for bad in ({"type": "voice", "phrases": []}, {"type": "device", "event": "boom"},
                {"type": "sensor", "metric": "nope"}, {"type": "sensor", "metric": "external"},
                {"type": "sensor", "metric": "cpu_percent", "op": "~"}):
        with pytest.raises(ValidationError):
            validate_gesture({"name": "x", **bad})
    assert validate_gesture_patch({"type": "sound", "sound": "loud", "level_db": -15})["level_db"] == -15


def test_changing_type_drops_old_keys(tmp_path):
    store = ConfigStore(tmp_path)
    gid = store.save_gesture(validate_gesture({"name": "c", "type": "sound", "sound": "loud", "level_db": -20, "hold_ms": 300}))
    store.update_gesture(gid, validate_gesture_patch({"type": "device", "event": "lid_closed"}))
    g = store.get_gesture(gid)
    assert "sound" not in g and "level_db" not in g and g["event"] == "lid_closed"


def test_templates_with_sensors_install(tmp_path):
    store = ConfigStore(tmp_path)
    for template in templates_lib.LIBRARY:
        templates_lib.install(store, template["id"])
    kinds = {g["type"] for g in store.get_gestures()}
    assert {"sound", "voice", "fingerprint", "device", "sensor"} <= kinds


# ------------------------------------------------------------------- hub


class FakeStore:
    def __init__(self, gestures):
        self.g = gestures

    def get_gestures(self):
        return self.g


def make_hub(gestures, settings=None, tmp=None):
    fired = []
    hub = SensorHub(FakeStore(gestures), lambda g, c: fired.append((g["id"], c)) or True, tmp, (settings or {}).get)
    return hub, fired


def test_mic_is_not_needed_without_sound_gestures(tmp_path):
    hub, _ = make_hub([{"id": "d", "type": "device", "event": "usb_plugged"}], {"mic_enabled": True}, tmp_path)
    need = hub.needs()
    assert not need["mic"] and need["families"] == {"usb"}


def test_mic_requires_consent(tmp_path):
    gestures = [{"id": "s", "type": "sound", "sound": "clap"}]
    hub, _ = make_hub(gestures, {"mic_enabled": False}, tmp_path)
    need = hub.needs()
    assert not need["mic"] and need["mic_blocked"]
    hub2, _ = make_hub(gestures, {"mic_enabled": True}, tmp_path)
    assert hub2.needs()["mic"] and hub2.needs()["claps"]


def test_voice_trigger_passes_text_and_number(tmp_path):
    hub, fired = make_hub([{"id": "v", "type": "voice", "phrases": ["volume"], "match": "contains"}], tmp=tmp_path)
    hub.handle_speech("volume soixante")
    hub.handle_speech("autre chose")
    assert fired == [("v", {"text": "volume soixante", "phrase": "volume", "value": 60})]


def test_device_and_finger_filters(tmp_path):
    gestures = [
        {"id": "d", "type": "device", "event": "usb_plugged", "match": "souris"},
        {"id": "f", "type": "fingerprint", "result": "match", "finger": "index"},
    ]
    hub, fired = make_hub(gestures, tmp=tmp_path)
    hub._on_device("usb_plugged", "1:2", "Clé USB")
    hub._on_device("usb_plugged", "1:3", "Souris Logitech")
    hub._on_finger("match", "left-thumb")
    hub._on_finger("match", "right-index-finger")
    assert [f[0] for f in fired] == ["d", "f"]


def test_sensor_threshold_edge_and_hold(tmp_path, monkeypatch):
    gesture = {"id": "s", "type": "sensor", "metric": "external", "arg": "gaz", "op": ">", "value": 10, "edge": "rising", "hold_ms": 0}
    hub, fired = make_hub([gesture], tmp=tmp_path)
    hub.external.set_value("gaz", 50)
    system_metrics.clear_cache()
    hub._poll_thresholds(1.0)
    hub._poll_thresholds(1.5)  # toujours au-dessus : pas de nouveau declenchement
    assert len(fired) == 1
    hub.external.set_value("gaz", 1)
    system_metrics.clear_cache()
    hub._poll_thresholds(2.0)
    hub.external.set_value("gaz", 99)
    system_metrics.clear_cache()
    hub._poll_thresholds(3.0)
    assert len(fired) == 2


def test_fire_external_respects_cooldown_and_conditions(tmp_path):
    class Store2(FakeStore):
        def get_action(self, _id):
            return {"id": "a", "name": "A"}

    fired = []
    engine = GestureEngine(Store2([]), lambda g, a, ctx: fired.append(ctx))
    gesture = {"id": "g", "name": "G", "type": "sound", "action_id": "a", "cooldown_seconds": 30}
    assert engine.fire_external(gesture, {"value": 2})
    assert not engine.fire_external(gesture, {"value": 2})  # cooldown
    assert fired[0]["value"] == 2 and fired[0]["type"] == "sound"
    blocked = {**gesture, "id": "h", "conditions": [{"metric": "hour", "op": ">", "value": 99}]}
    assert not engine.fire_external(blocked, {})


# ------------------------------------------------------------- migration


def test_legacy_env_and_data_migration(tmp_path, monkeypatch):
    monkeypatch.delenv(paths.ENV_DATA_DIR, raising=False)
    monkeypatch.setenv(paths.LEGACY_ENV_DATA_DIR, str(tmp_path / "ancien"))
    assert paths.data_dir() == tmp_path / "ancien"

    monkeypatch.delenv(paths.LEGACY_ENV_DATA_DIR)
    monkeypatch.setattr(paths, "legacy_data_dir", lambda: tmp_path / "old")
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path / "new")
    (tmp_path / "old").mkdir()
    (tmp_path / "old" / "gestures.json").write_text(json.dumps([{"id": "x"}]))
    assert paths.migrate_legacy_data() == tmp_path / "old"
    assert (tmp_path / "new" / "gestures.json").exists()
    assert (tmp_path / "old" / "gestures.json").exists()  # non destructif


# ------------------------------------------------------------------ routes


def test_sensor_routes(tmp_path):
    from physicalshortcut.webui.app import create_app

    store = ConfigStore(tmp_path)
    hub = SensorHub(store, lambda g, c: True, tmp_path, lambda _k: False)
    client = create_app(GestureEngine(store, lambda g, a, c: None), store, hub=hub).test_client()
    headers = {"X-PhysicalShortCut": "1"}
    assert client.get("/api/sensors/status").json["mic"]["open"] is False
    assert {i["id"] for i in client.get("/api/sensors/report").json["items"]} >= {"sound", "voice", "fingerprint", "external"}
    body = {"sensors": [{"name": "gaz", "kind": "serial", "port": "/dev/null"}]}
    ok = client.put("/api/sensors/external", json=body, headers=headers)
    assert ok.status_code == 200 and ok.json["sensors"][0]["name"] == "gaz"
    hub.external.stop()
    bad = client.put("/api/sensors/external", json={"sensors": [{"name": "1"}]}, headers=headers)
    assert bad.status_code == 400
    r = client.post("/api/gestures", json={"name": "Clap", "type": "sound", "sound": "double_clap"}, headers=headers)
    assert r.status_code in (200, 201)
    assert client.get("/").status_code == 200
