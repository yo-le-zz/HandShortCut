"""Genere toutes les icones de PhysicalShortCut a partir de ``assets/logo.png``.

Le logo source est un visuel 512x512 : bandes blanches en haut et en bas, bande noire
au milieu, logo cyan au centre. Le script :

1. isole le logo (bande noire, puis boite englobante des pixels clairs) ;
2. remplace le fond noir par de la transparence (alpha d'apres la luminance, couleur
   unie du logo : les bords restent lisses) ;
3. le centre dans un carre avec une marge, puis le redimensionne (LANCZOS) ;
4. ecrit :
     assets/icons/physicalshortcut-<taille>.png   16 ... 512  (menu d'applications Linux, hicolor)
     assets/icon.png                          256x256 RGBA (reference, dans les paquets)
     assets/icon.ico                          16/24/32/48/64/128/256 (Windows : exe, MSI, installateur)
     src/physicalshortcut/webui/static/icon.png   favicon de l'interface (64x64)
     src/physicalshortcut/webui/static/logo.png   logo de la barre laterale (128x128)

Usage : python assets/make_icons.py          (necessite Pillow et numpy)
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

ASSETS = Path(__file__).resolve().parent
ROOT = ASSETS.parent
STATIC = ROOT / "src" / "physicalshortcut" / "webui" / "static"

SOURCE = ASSETS / "logo.png"
LINUX_SIZES = (16, 22, 24, 32, 48, 64, 96, 128, 256, 512)
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
MARGIN = 0.08  # marge autour du logo (part du cote)


def extract_logo(source: Path) -> Image.Image:
    """Logo cyan sur fond transparent, rogne a sa boite englobante."""
    rgb = np.asarray(Image.open(source).convert("RGB")).astype(float)
    lum = rgb.max(axis=2)

    # Bande noire centrale : lignes majoritairement sombres.
    dark_rows = np.where((lum < 25).mean(axis=1) > 0.6)[0]
    top, bottom = int(dark_rows.min()), int(dark_rows.max()) + 1
    band = rgb[top:bottom]
    band_lum = lum[top:bottom]

    peak = band_lum.max()
    solid = np.median(band[band_lum > 0.85 * peak], axis=0)  # couleur pleine du logo
    alpha = np.clip(band_lum / solid.max(), 0.0, 1.0)
    alpha[alpha < 0.04] = 0.0  # supprime le bruit de compression du fond

    ys, xs = np.where(alpha > 0.1)
    box = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)

    out = np.zeros((*alpha.shape, 4), dtype=np.uint8)
    out[..., :3] = solid.astype(np.uint8)
    out[..., 3] = (alpha * 255).round().astype(np.uint8)
    return Image.fromarray(out, "RGBA").crop(box)


def square(logo: Image.Image, side: int = 1024) -> Image.Image:
    """Centre le logo dans un carre transparent, avec marge."""
    inner = int(side * (1 - 2 * MARGIN))
    scale = inner / max(logo.size)
    resized = logo.resize(
        (max(1, round(logo.width * scale)), max(1, round(logo.height * scale))), Image.LANCZOS
    )
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(resized, ((side - resized.width) // 2, (side - resized.height) // 2), resized)
    return canvas


def main() -> None:
    master = square(extract_logo(SOURCE))

    def at(size: int) -> Image.Image:
        return master.resize((size, size), Image.LANCZOS)

    icons_dir = ASSETS / "icons"
    icons_dir.mkdir(exist_ok=True)
    for size in LINUX_SIZES:
        at(size).save(icons_dir / f"physicalshortcut-{size}.png", optimize=True)

    at(256).save(ASSETS / "icon.png", optimize=True)
    master.save(
        ASSETS / "icon.ico",
        format="ICO",
        sizes=[(s, s) for s in ICO_SIZES],
    )
    at(64).save(STATIC / "icon.png", optimize=True)
    at(128).save(STATIC / "logo.png", optimize=True)
    print(f"Icones ecrites : {len(LINUX_SIZES)} PNG, icon.png, icon.ico, favicon et logo web")


if __name__ == "__main__":
    main()
