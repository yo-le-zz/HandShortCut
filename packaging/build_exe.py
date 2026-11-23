#!/usr/bin/env python3
"""Compile HandShortCut en executable natif (Nuitka, mode standalone).

    uv run --group build python packaging/build_exe.py [--output build/exe] [--jobs N]

Produit `<output>/handshortcut.dist/` : un dossier autonome (aucun Python requis
sur la machine cible) contenant l'executable `handshortcut` (`handshortcut.exe`
sous Windows) avec toutes ses bibliotheques et donnees (MediaPipe, OpenCV...).
Necessite un compilateur C (gcc/clang, ou MSVC/MinGW sous Windows) ; sous Linux
aussi `patchelf`.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parent.parent
EXE_LINUX = "handshortcut-bin"


def project_version() -> str:
    with open(ROOT / "pyproject.toml", "rb") as f:
        return tomllib.load(f)["project"]["version"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=ROOT / "build" / "exe")
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 2)
    args = parser.parse_args()

    version = project_version()
    is_windows = sys.platform == "win32"
    out = args.output.resolve()
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)

    # Sous Linux le dossier de donnees `handshortcut/` du paquet entrerait en conflit
    # avec un executable du meme nom : on le suffixe (le lien /usr/bin/handshortcut le masque).
    exe_name = "handshortcut" if is_windows else EXE_LINUX

    cmd = [
        sys.executable,
        "-m",
        "nuitka",
        "--mode=standalone",
        f"--output-dir={out}",
        f"--output-filename={exe_name}",
        "--include-package=handshortcut",
        "--include-package-data=handshortcut",
        "--include-distribution-metadata=handshortcut",
        "--include-package-data=mediapipe",  # modeles .tflite / graphes .binarypb
        "--nofollow-import-to=jax,jaxlib,tkinter,pytest,matplotlib.tests,numpy.tests",
        "--assume-yes-for-downloads",
        "--remove-output",
        f"--jobs={args.jobs}",
        "--product-name=HandShortCut",
        f"--product-version={version}",
        "--file-description=HandShortCut",
        "--company-name=yolezz",
    ]
    if is_windows:
        cmd += [
            # console si lance depuis un terminal (stop, paths...), sinon aucune fenetre
            "--windows-console-mode=attach",
            f"--windows-icon-from-ico={ROOT / 'assets' / 'icon.ico'}",
        ]
    cmd.append(str(ROOT / "packaging" / "entry.py"))

    print("==> Compilation Nuitka (plusieurs minutes)...", flush=True)
    subprocess.run(cmd, check=True, cwd=ROOT)

    dist = out / "entry.dist"
    final = out / "handshortcut.dist"
    dist.rename(final)
    exe = final / ("handshortcut.exe" if is_windows else EXE_LINUX)
    if not exe.exists():
        print(f"Erreur : {exe} introuvable apres compilation.", file=sys.stderr)
        return 1
    print(f"==> OK : {final}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
