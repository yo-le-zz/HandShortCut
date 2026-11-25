"""Dessin en l'air : suivi du bout du doigt et reconnaissance du trace (chiffres, formes).

* ``Tracker``    : machine a etats qui transforme les positions du doigt en traits
  (stylo leve / baisse) et rend la liste des traits quand le dessin est termine ;
* ``recognize``  : reconnaisseur « $P » (nuage de points, Vatavu et al.) : independant de
  l'ordre des traits, de la vitesse, de la taille et du point de depart, compare a une
  bibliotheque de modeles (chiffres 0-9, formes) et aux traces que l'utilisateur a appris ;
* ``render_png`` : dessin -> image PNG (pour l'envoyer a une IA vision).

Aucune dependance externe : fonctionne sans camera ni MediaPipe (donc testable).
"""

from __future__ import annotations

import math
import struct
import threading
import zlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

Stroke = list[tuple[float, float]]

CLOUD_POINTS = 32
CONFIDENCE_SCALE = 0.16  # distance moyenne par point correspondant a une confiance nulle

# --------------------------------------------------------------------------
# Modeles
# --------------------------------------------------------------------------


def _arc(cx: float, cy: float, rx: float, ry: float, a0: float, a1: float, n: int = 28) -> Stroke:
    return [
        (cx + rx * math.cos(math.radians(a0 + (a1 - a0) * i / n)), cy + ry * math.sin(math.radians(a0 + (a1 - a0) * i / n)))
        for i in range(n + 1)
    ]


def _rot180(strokes: list[Stroke]) -> list[Stroke]:
    return [[(1 - x, 1 - y) for x, y in s] for s in strokes]


_SIX: list[Stroke] = [[(0.7, 0.0), (0.4, 0.2), (0.2, 0.5), (0.15, 0.78), (0.3, 0.98), (0.6, 1.0), (0.82, 0.82), (0.78, 0.6), (0.55, 0.5), (0.3, 0.58), (0.18, 0.7)]]
_HEART: Stroke = [
    (0.5 + 0.031 * 16 * math.sin(t) ** 3, 0.5 - 0.031 * (13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)))
    for t in [i * 2 * math.pi / 40 for i in range(41)]
]
_STAR: Stroke = [
    (0.5 + 0.5 * math.sin(math.radians(144 * i)), 0.52 - 0.5 * math.cos(math.radians(144 * i))) for i in range(6)
]
_EIGHT: Stroke = [
    (0.5 + 0.32 * math.sin(2 * t), 0.5 - 0.5 * math.cos(t)) for t in [i * 2 * math.pi / 40 for i in range(41)]
]

# etiquette -> variantes (chaque variante = liste de traits ; image : x vers la droite, y vers le bas)
TEMPLATES: dict[str, list[list[Stroke]]] = {
    "0": [[_arc(0.5, 0.5, 0.36, 0.5, -90, 270)]],
    "1": [[[(0.5, 0.0), (0.5, 1.0)]], [[(0.28, 0.2), (0.55, 0.0), (0.55, 1.0)]]],
    "2": [[[(0.12, 0.28), (0.22, 0.1), (0.45, 0.0), (0.7, 0.05), (0.85, 0.22), (0.8, 0.42), (0.55, 0.62), (0.12, 1.0), (0.9, 1.0)]]],
    "3": [[[(0.12, 0.1), (0.4, 0.0), (0.75, 0.05), (0.85, 0.25), (0.65, 0.45), (0.4, 0.5), (0.7, 0.55), (0.88, 0.75), (0.75, 0.95), (0.4, 1.0), (0.1, 0.9)]]],
    "4": [
        [[(0.75, 1.0), (0.75, 0.0), (0.05, 0.68), (0.95, 0.68)]],
        [[(0.6, 0.0), (0.05, 0.65), (0.95, 0.65)], [(0.7, 0.2), (0.7, 1.0)]],
    ],
    "5": [[[(0.85, 0.0), (0.2, 0.0), (0.15, 0.48), (0.5, 0.4), (0.8, 0.5), (0.88, 0.72), (0.7, 0.95), (0.4, 1.0), (0.1, 0.88)]]],
    "6": [_SIX],
    "7": [[[(0.1, 0.0), (0.9, 0.0), (0.4, 1.0)]]],
    "8": [[_EIGHT]],
    "9": [_rot180(_SIX)],
    "cercle": [[_arc(0.5, 0.5, 0.5, 0.5, -90, 270)]],
    "carre": [[[(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]]],
    "triangle": [[[(0.5, 0.0), (1.0, 1.0), (0.0, 1.0), (0.5, 0.0)]]],
    "coche": [[[(0.0, 0.55), (0.35, 1.0), (1.0, 0.0)]]],
    "croix": [[[(0, 0), (1, 1)], [(1, 0), (0, 1)]]],
    "plus": [[[(0.5, 0), (0.5, 1)], [(0, 0.5), (1, 0.5)]]],
    "etoile": [[_STAR]],
    "fleche": [[[(0.0, 0.5), (1.0, 0.5)], [(0.7, 0.2), (1.0, 0.5), (0.7, 0.8)]]],
    "ligne": [[[(0.0, 0.5), (1.0, 0.5)]]],
    "zigzag": [[[(0.0, 0.8), (0.25, 0.2), (0.5, 0.8), (0.75, 0.2), (1.0, 0.8)]]],
    "coeur": [[_HEART]],
}
DIGITS = tuple(str(d) for d in range(10))
SHAPES = tuple(k for k in TEMPLATES if k not in DIGITS)
CHARSETS: dict[str, tuple[str, ...]] = {
    "digits": DIGITS,
    "shapes": SHAPES,
    "all": DIGITS + SHAPES,
}
def labels_for(charset: str) -> list[str]:
    return list(CHARSETS.get(charset, CHARSETS["all"]))


SHAPE_LABELS = {
    "cercle": "Cercle", "carre": "Carré", "triangle": "Triangle", "coche": "Coche ✓", "croix": "Croix ✗",
    "plus": "Plus +", "etoile": "Étoile", "fleche": "Flèche →", "ligne": "Ligne —", "zigzag": "Zigzag", "coeur": "Cœur",
}


# --------------------------------------------------------------------------
# $P : nuage de points
# --------------------------------------------------------------------------

Cloud = list[tuple[float, float]]


def _path_length(strokes: Sequence[Stroke]) -> float:
    return sum(math.dist(s[i - 1], s[i]) for s in strokes for i in range(1, len(s)))


def _resample(strokes: Sequence[Stroke], n: int) -> Cloud:
    """n points repartis regulierement sur l'ensemble des traits (les sauts entre traits ne comptent pas)."""
    total = _path_length(strokes)
    if total <= 1e-9:
        base = strokes[0][0] if strokes and strokes[0] else (0.0, 0.0)
        return [base] * n
    interval = total / (n - 1)
    out: Cloud = []
    carried = 0.0
    for stroke in strokes:
        if not stroke:
            continue
        if not out:
            out.append(stroke[0])
        else:
            out.append(stroke[0]) if len(out) < n else None
            carried = 0.0
        pts = list(stroke)
        i = 1
        prev = pts[0]
        while i < len(pts):
            d = math.dist(prev, pts[i])
            if carried + d >= interval and d > 0:
                t = (interval - carried) / d
                new = (prev[0] + t * (pts[i][0] - prev[0]), prev[1] + t * (pts[i][1] - prev[1]))
                if len(out) < n:
                    out.append(new)
                prev = new
                carried = 0.0
            else:
                carried += d
                prev = pts[i]
                i += 1
    while len(out) < n:
        out.append(out[-1])
    return out[:n]


def normalize(strokes: Sequence[Stroke], n: int = CLOUD_POINTS) -> Cloud:
    """Nuage normalise : n points, echelle unitaire (aspect conserve), centre sur l'origine."""
    cloud = _resample([s for s in strokes if len(s) >= 1], n)
    xs, ys = [p[0] for p in cloud], [p[1] for p in cloud]
    size = max(max(xs) - min(xs), max(ys) - min(ys)) or 1.0
    scaled = [((x - min(xs)) / size, (y - min(ys)) / size) for x, y in cloud]
    cx = sum(p[0] for p in scaled) / n
    cy = sum(p[1] for p in scaled) / n
    return [(x - cx, y - cy) for x, y in scaled]


def _cloud_distance(a: Cloud, b: Cloud, start: int) -> float:
    n = len(a)
    matched = [False] * n
    total = 0.0
    i = start
    while True:
        best, index = math.inf, -1
        for j in range(n):
            if not matched[j]:
                d = (a[i][0] - b[j][0]) ** 2 + (a[i][1] - b[j][1]) ** 2
                if d < best:
                    best, index = d, j
        matched[index] = True
        weight = 1 - ((i - start + n) % n) / n
        total += weight * math.sqrt(best)
        i = (i + 1) % n
        if i == start:
            return total


def cloud_distance(a: Cloud, b: Cloud) -> float:
    n = len(a)
    step = max(1, int(n**0.5))
    best = math.inf
    for i in range(0, n, step):
        best = min(best, _cloud_distance(a, b, i), _cloud_distance(b, a, i))
    return best


def confidence(distance: float, n: int = CLOUD_POINTS) -> float:
    """Distance du nuage -> confiance 0..1 (1 = identique)."""
    return max(0.0, 1.0 - (distance / n) / CONFIDENCE_SCALE)


@dataclass
class Match:
    label: str
    confidence: float
    custom: bool = False


@dataclass
class Library:
    """Modeles integres + traces appris par l'utilisateur."""

    custom: dict[str, list[Cloud]] = field(default_factory=dict)
    _builtin: dict[str, list[Cloud]] = field(default_factory=dict, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    def __post_init__(self) -> None:
        for label, variants in TEMPLATES.items():
            self._builtin[label] = [normalize(v) for v in variants]

    def add_custom(self, label: str, strokes: Sequence[Stroke]) -> None:
        with self._lock:
            self.custom.setdefault(label, []).append(normalize(strokes))

    def remove_custom(self, label: str) -> bool:
        with self._lock:
            return self.custom.pop(label, None) is not None

    def labels(self) -> list[str]:
        return list(dict.fromkeys([*TEMPLATES, *self.custom]))

    def dump(self) -> dict[str, list[list[list[float]]]]:
        with self._lock:
            return {k: [[[x, y] for x, y in cloud] for cloud in v] for k, v in self.custom.items()}

    def load(self, data: Any) -> int:
        """Charge des traces personnalisees (ignore ce qui est invalide) ; renvoie le nombre de modeles."""
        count = 0
        if not isinstance(data, dict):
            return 0
        with self._lock:
            for label, clouds in data.items():
                if not isinstance(label, str) or not isinstance(clouds, list):
                    continue
                for cloud in clouds[:20]:
                    try:
                        points = [(float(x), float(y)) for x, y in cloud]
                    except (TypeError, ValueError):
                        continue
                    if len(points) >= 2:
                        self.custom.setdefault(label[:40], []).append(points)
                        count += 1
        return count

    def recognize(self, strokes: Sequence[Stroke], labels: Sequence[str] | None = None, top: int = 3) -> list[Match]:
        strokes = [s for s in strokes if len(s) >= 2]
        if not strokes:
            return []
        cloud = normalize(strokes)
        allowed = set(labels) if labels else None
        results: dict[str, Match] = {}
        with self._lock:
            pools = [(self._builtin, False), (self.custom, True)]
            for pool, is_custom in pools:
                for label, clouds in pool.items():
                    if allowed is not None and label not in allowed:
                        continue
                    for template in clouds:
                        conf = confidence(cloud_distance(cloud, template))
                        if label not in results or conf > results[label].confidence:
                            results[label] = Match(label, round(conf, 3), is_custom)
        return sorted(results.values(), key=lambda m: m.confidence, reverse=True)[:top]


_library = Library()


def library() -> Library:
    return _library


def label_value(label: str) -> int | str:
    """``"7"`` -> 7 (utilisable dans un calcul) ; une forme reste un texte."""
    return int(label) if label.isdigit() else label


# --------------------------------------------------------------------------
# Suivi du doigt
# --------------------------------------------------------------------------

PEN_MODES = ("index", "pinch", "any")


@dataclass
class Drawing:
    strokes: list[Stroke]
    duration: float


class Tracker:
    """Transforme des positions de doigt en traits.

    ``update(pen, x, y, now)`` : ``pen`` vrai = stylo baisse (le doigt « ecrit »).
    Le dessin est termine quand le stylo reste leve plus de ``idle_ms`` ; ``update`` renvoie
    alors un ``Drawing`` (ou ``None`` s'il est trop court pour etre un dessin).
    """

    def __init__(self, idle_ms: int = 800, min_points: int = 8, min_length: float = 0.12, max_seconds: float = 12.0):
        self.idle = idle_ms / 1000.0
        self.min_points = min_points
        self.min_length = min_length
        self.max_seconds = max_seconds
        self.reset()

    def reset(self) -> None:
        self.strokes: list[Stroke] = []
        self._pen_down = False
        self._last_pen = 0.0
        self._started = 0.0
        self._smooth: tuple[float, float] | None = None

    @property
    def active(self) -> bool:
        return bool(self.strokes)

    def points(self) -> list[tuple[float, float]]:
        """Tous les points (pour l'apercu), les traits mis bout a bout."""
        return [p for s in self.strokes for p in s]

    def update(self, pen: bool, x: float | None, y: float | None, now: float) -> Drawing | None:
        if pen and x is not None and y is not None:
            if self._smooth is None or not self._pen_down:
                self._smooth = (x, y)
            else:
                self._smooth = (self._smooth[0] * 0.5 + x * 0.5, self._smooth[1] * 0.5 + y * 0.5)
            if not self.strokes:
                self._started = now
            if not self._pen_down:
                self.strokes.append([])
            stroke = self.strokes[-1]
            if not stroke or math.dist(stroke[-1], self._smooth) > 0.004:
                stroke.append(self._smooth)
            self._pen_down = True
            self._last_pen = now
            if now - self._started > self.max_seconds:
                return self._finish(now)
            return None

        self._pen_down = False
        if self.strokes and now - self._last_pen > self.idle:
            return self._finish(now)
        return None

    def _finish(self, now: float) -> Drawing | None:
        strokes, duration = [s for s in self.strokes if len(s) >= 2], max(0.0, self._last_pen - self._started)
        total = sum(len(s) for s in strokes)
        long_enough = _path_length(strokes) >= self.min_length
        self.reset()
        if total < self.min_points or not long_enough:
            return None
        return Drawing(strokes, duration)


# --------------------------------------------------------------------------
# Rendu PNG (sans dependance)
# --------------------------------------------------------------------------


def render_png(strokes: Sequence[Stroke], size: int = 256, thickness: int = 9, margin: float = 0.12) -> bytes:
    """Trace noir sur fond blanc, centre et a l'echelle de l'image (pour une IA vision)."""
    pts = [p for s in strokes for p in s]
    pixels = bytearray(b"\xff" * (size * size))
    if pts:
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        span = max(max(xs) - min(xs), max(ys) - min(ys)) or 1.0
        scale = size * (1 - 2 * margin) / span
        ox = (size - (max(xs) - min(xs)) * scale) / 2 - min(xs) * scale
        oy = (size - (max(ys) - min(ys)) * scale) / 2 - min(ys) * scale
        radius = max(1, thickness // 2)

        def stamp(cx: float, cy: float) -> None:
            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    if dx * dx + dy * dy <= radius * radius:
                        px, py = int(cx) + dx, int(cy) + dy
                        if 0 <= px < size and 0 <= py < size:
                            pixels[py * size + px] = 0

        for stroke in strokes:
            mapped = [(x * scale + ox, y * scale + oy) for x, y in stroke]
            for i, p in enumerate(mapped):
                stamp(*p)
                if i:
                    q = mapped[i - 1]
                    steps = max(1, int(math.dist(p, q)))
                    for k in range(1, steps):
                        stamp(q[0] + (p[0] - q[0]) * k / steps, q[1] + (p[1] - q[1]) * k / steps)

    raw = b"".join(b"\x00" + bytes(pixels[y * size : (y + 1) * size]) for y in range(size))

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", size, size, 8, 0, 0, 0, 0)  # 8 bits, niveaux de gris
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")
