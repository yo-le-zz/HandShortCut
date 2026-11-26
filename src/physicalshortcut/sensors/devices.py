"""Surveillance des branchements : USB, Bluetooth, secteur, capot, Wi-Fi.

``diff_state`` est une fonction pure (testable) ; ``DeviceWatcher`` l'appelle a intervalle regulier.
La premiere lecture sert de reference : aucun evenement n'est emis pour ce qui etait deja branche.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from . import hardware

log = logging.getLogger("physicalshortcut.sensors.devices")

DEVICE_EVENTS = (
    "usb_plugged", "usb_unplugged", "bluetooth_connected", "bluetooth_disconnected",
    "power_plugged", "power_unplugged", "lid_closed", "lid_opened", "wifi_connected", "wifi_disconnected",
)


def diff_state(old: dict, new: dict) -> list[tuple[str, str, str]]:
    """Compare deux etats ; renvoie [(evenement, identifiant, nom)]."""
    events: list[tuple[str, str, str]] = []
    for family, on, off in (("usb", "usb_plugged", "usb_unplugged"), ("bluetooth", "bluetooth_connected", "bluetooth_disconnected")):
        before, after = old.get(family), new.get(family)
        if before is None or after is None:
            continue
        events += [(on, key, after[key]) for key in after.keys() - before.keys()]
        events += [(off, key, before[key]) for key in before.keys() - after.keys()]
    if old.get("ac") is not None and new.get("ac") is not None and old["ac"] != new["ac"]:
        events.append(("power_plugged" if new["ac"] else "power_unplugged", "ac", "Secteur"))
    if old.get("lid") is not None and new.get("lid") is not None and old["lid"] != new["lid"]:
        events.append(("lid_closed" if new["lid"] else "lid_opened", "lid", "Capot"))
    if "wifi" in old and "wifi" in new and old["wifi"] != new["wifi"]:
        if new["wifi"]:
            events.append(("wifi_connected", new["wifi"], new["wifi"]))
        if old["wifi"]:
            events.append(("wifi_disconnected", old["wifi"], old["wifi"]))
    return events


def read_state(families: set[str]) -> dict:
    state: dict = {}
    if "usb" in families:
        state["usb"] = hardware.usb_devices()
    if "bluetooth" in families:
        state["bluetooth"] = hardware.bluetooth_connected()
    if "power" in families:
        try:
            import psutil

            battery = psutil.sensors_battery()
            state["ac"] = None if battery is None else bool(battery.power_plugged)
        except Exception:  # noqa: BLE001
            state["ac"] = None
    if "lid" in families:
        state["lid"] = hardware.lid_closed()
    if "wifi" in families:
        state["wifi"] = hardware.wifi_ssid()
    return state


def families_for(events: set[str]) -> set[str]:
    out = set()
    for event in events:
        out.add({"usb": "usb", "bluetooth": "bluetooth", "power": "power", "lid": "lid", "wifi": "wifi"}[event.split("_")[0]])
    return out


class DeviceWatcher:
    def __init__(self, emit: Callable[[str, str, str], None], interval: float = 2.5) -> None:
        self.emit = emit
        self.interval = interval
        self.families: set[str] = set()
        self._state: dict | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def set_families(self, families: set[str]) -> None:
        if families != self.families:
            self.families = set(families)
            self._state = None  # nouvelle reference

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="device-watcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            families = set(self.families)
            if not families:
                continue
            try:
                new = read_state(families)
                if self._state is not None:
                    for event in diff_state(self._state, new):
                        self.emit(*event)
                self._state = new
            except Exception:  # noqa: BLE001
                log.exception("Lecture des peripheriques")
