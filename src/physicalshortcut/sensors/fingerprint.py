"""Empreinte digitale.

* **Linux** : ``fprintd`` (le service standard des lecteurs d'empreintes). Le declencheur lance
  ``fprintd-verify`` en boucle : chaque pose d'un doigt **enregistre** (``fprintd-enroll``) donne
  « reconnu » (avec le nom du doigt), un autre doigt donne « inconnu ».
* **Windows** : Windows Hello ne laisse pas une application ecouter le lecteur en continu. On peut
  seulement **demander une verification** (etape de workflow « Verifier mon identite ») : Windows
  affiche sa fenetre Hello (empreinte, visage ou code PIN) et renvoie oui/non.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import threading
from collections.abc import Callable

from . import hardware

log = logging.getLogger("physicalshortcut.sensors.fingerprint")


def parse_verify_output(text: str) -> tuple[str | None, str | None]:
    """Sortie de ``fprintd-verify`` -> (resultat, doigt) ; resultat : match | no_match | error | None."""
    finger = None
    result = None
    for line in text.splitlines():
        m = re.search(r"Verify started!|Verifying:\s*([a-z0-9-]+)", line)
        if m and m.group(1):
            finger = m.group(1)
        if "verify-match" in line:
            result = "match"
        elif "verify-no-match" in line:
            result = "no_match"
        elif "verify-unknown-error" in line or "verify-disconnected" in line:
            result = "error"
    return result, finger


def availability() -> tuple[bool, str]:
    if hardware.IS_LINUX:
        if not shutil.which("fprintd-verify"):
            return False, "fprintd absent : sudo dnf install fprintd / sudo apt install fprintd, puis `fprintd-enroll` pour enregistrer un doigt."
        out = hardware._run(["fprintd-list", hardware._read("/etc/hostname") and __import__("getpass").getuser()])
        if out is None or "no devices" in (out or "").lower():
            return False, "Aucun lecteur d'empreintes détecté par fprintd."
        if "no fingerprints enrolled" in out.lower():
            return False, "Aucune empreinte enregistrée : lance `fprintd-enroll`."
        return True, "Lecteur détecté et empreinte(s) enregistrée(s)."
    if hardware.IS_WINDOWS:
        return True, "Windows Hello : vérification à la demande uniquement (pas d'écoute continue)."
    return False, "Non pris en charge sur ce système."


def verify_once(timeout: float = 20.0) -> tuple[bool, str]:
    """Demande une verification maintenant ; renvoie (accepte, detail)."""
    if hardware.IS_LINUX and shutil.which("fprintd-verify"):
        try:
            done = subprocess.run(["fprintd-verify"], capture_output=True, text=True, timeout=timeout, check=False)  # noqa: S603, S607
        except (OSError, subprocess.TimeoutExpired):
            return False, "délai dépassé"
        result, finger = parse_verify_output(done.stdout + done.stderr)
        return result == "match", finger or result or "inconnu"
    if hardware.IS_WINDOWS:
        script = (
            "Add-Type -AssemblyName System.Runtime.WindowsRuntime;"
            "$null=[Windows.Security.Credentials.UI.UserConsentVerifier,Windows.Security.Credentials.UI,ContentType=WindowsRuntime];"
            "$op=[Windows.Security.Credentials.UI.UserConsentVerifier]::RequestVerificationAsync('PhysicalShortCut');"
            "$m=[System.WindowsRuntimeSystemExtensions].GetMethods()|?{$_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'}|select -first 1;"
            "$t=$m.MakeGenericMethod([Windows.Security.Credentials.UI.UserConsentVerificationResult]).Invoke($null,@($op));"
            "$t.Wait();$t.Result"
        )
        out = hardware._powershell(script, timeout=timeout)
        return (out or "").strip() == "Verified", (out or "indisponible").strip()
    return False, "non pris en charge"


class FingerprintListener:
    """Boucle ``fprintd-verify`` (Linux) : appelle ``emit(resultat, doigt)`` a chaque pose de doigt."""

    def __init__(self, emit: Callable[[str, str], None]) -> None:
        self.emit = emit
        self.error: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._proc: subprocess.Popen | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="fingerprint", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()

    def _loop(self) -> None:
        if not (hardware.IS_LINUX and shutil.which("fprintd-verify")):
            self.error = "L'écoute continue du lecteur n'est disponible que sous Linux avec fprintd."
            return
        while not self._stop.is_set():
            try:
                self._proc = subprocess.Popen(["fprintd-verify"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)  # noqa: S603, S607
                output, _ = self._proc.communicate(timeout=3600)
            except (OSError, subprocess.TimeoutExpired):
                self._stop.wait(5)
                continue
            result, finger = parse_verify_output(output or "")
            if result in ("match", "no_match"):
                self.error = None
                self.emit(result, finger or "inconnu")
                self._stop.wait(1.0)
            else:
                self.error = (output or "fprintd indisponible").strip().splitlines()[-1][:160] if output else "fprintd indisponible"
                self._stop.wait(8)  # lecteur occupe (ecran de verrouillage...) : on reessaie plus tard
