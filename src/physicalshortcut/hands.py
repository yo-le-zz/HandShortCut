"""Analyse de la main : doigts leves, comptage, poses.

Travaille sur les vecteurs normalises produits par ``gesture_engine`` (21 points x 3
coordonnees par main, centres sur le poignet) : aucune camera ni MediaPipe requis, donc
testable. Un doigt est « leve » quand ses articulations sont alignees (angle ouvert) et
que sa pointe est plus loin du poignet que sa premiere articulation.

Indices MediaPipe : 0 poignet ; pouce 1-4 ; index 5-8 ; majeur 9-12 ; annulaire 13-16 ;
auriculaire 17-20 (base, articulation, articulation, pointe).
"""

from __future__ import annotations

import math
from collections.abc import Sequence

HAND_LEN = 21 * 3
FINGER_NAMES = ("pouce", "index", "majeur", "annulaire", "auriculaire")

# (base, articulation, articulation distale, pointe) de chaque doigt long
_FINGERS = ((5, 6, 7, 8), (9, 10, 11, 12), (13, 14, 15, 16), (17, 18, 19, 20))

EXTENDED_ANGLE = 140.0  # degres : au-dela, le doigt est considere comme tendu
THUMB_ANGLE = 140.0

# Poses nommees (pouce, index, majeur, annulaire, auriculaire) : 1 = leve, 0 = replie
POSES: dict[str, tuple[int, int, int, int, int]] = {
    "poing": (0, 0, 0, 0, 0),
    "main_ouverte": (1, 1, 1, 1, 1),
    "pouce_leve": (1, 0, 0, 0, 0),
    "pointer": (0, 1, 0, 0, 0),
    "victoire": (0, 1, 1, 0, 0),
    "trois": (0, 1, 1, 1, 0),
    "quatre": (0, 1, 1, 1, 1),
    "rock": (0, 1, 0, 0, 1),
    "telephone": (1, 0, 0, 0, 1),
    "ok_trois_doigts": (1, 0, 1, 1, 1),
}


def split_hands(vec: Sequence[float] | None) -> list[list[float]]:
    """Vecteur de frame (126 valeurs) -> liste des mains presentes (63 valeurs, de gauche a droite)."""
    if not vec:
        return []
    hands = []
    for start in range(0, len(vec) - HAND_LEN + 1, HAND_LEN):
        chunk = list(vec[start : start + HAND_LEN])
        if any(abs(v) > 1e-9 for v in chunk):
            hands.append(chunk)
    return hands


def _pt(hand: Sequence[float], index: int) -> tuple[float, float, float]:
    return hand[index * 3], hand[index * 3 + 1], hand[index * 3 + 2]


def _angle(a, b, c) -> float:
    """Angle en degres au point b entre les segments b->a et b->c."""
    v1 = [a[i] - b[i] for i in range(3)]
    v2 = [c[i] - b[i] for i in range(3)]
    n1, n2 = math.hypot(*v1), math.hypot(*v2)
    if n1 < 1e-9 or n2 < 1e-9:
        return 180.0
    cos = max(-1.0, min(1.0, sum(x * y for x, y in zip(v1, v2, strict=True)) / (n1 * n2)))
    return math.degrees(math.acos(cos))


def finger_states(hand: Sequence[float]) -> list[int]:
    """[pouce, index, majeur, annulaire, auriculaire] -> 1 si leve, 0 si replie."""
    wrist = _pt(hand, 0)
    states = []

    # pouce : segment droit et pointe eloignee de la base de l'index
    ip, tip = _pt(hand, 3), _pt(hand, 4)
    index_base = _pt(hand, 5)
    straight = _angle(_pt(hand, 2), ip, tip) >= THUMB_ANGLE
    away = math.dist(tip, index_base) > 1.15 * math.dist(ip, index_base)
    states.append(1 if straight and away else 0)

    for base, pip, dip, tip_i in _FINGERS:
        straight = _angle(_pt(hand, base), _pt(hand, pip), _pt(hand, dip)) >= EXTENDED_ANGLE
        farther = math.dist(wrist, _pt(hand, tip_i)) > math.dist(wrist, _pt(hand, pip))
        states.append(1 if straight and farther else 0)
    return states


def analyze(vec: Sequence[float] | None) -> list[dict]:
    """Une entree par main visible : doigts leves et nombre."""
    out = []
    for hand in split_hands(vec):
        fingers = finger_states(hand)
        out.append({"fingers": fingers, "count": sum(fingers)})
    return out


def total_count(vec: Sequence[float] | None) -> int:
    return sum(h["count"] for h in analyze(vec))


def pose_mismatches(fingers: Sequence[int], pattern: Sequence[int | None]) -> int:
    """Nombre de doigts qui different du motif (``None`` = indifferent)."""
    return sum(1 for state, want in zip(fingers, pattern, strict=False) if want is not None and state != want)


# --------------------------------------------------------------------------
# Main synthetique (tests, modeles de gestes, apercu)
# --------------------------------------------------------------------------

# bases des 4 doigts longs (x, y) dans le repere de la main (poignet = 0,0, majeur = 1 unite au-dessus)
_BASES = ((-0.42, -0.92), (0.0, -1.0), (0.38, -0.93), (0.74, -0.78))
_LENGTHS = ((0.52, 0.32, 0.27), (0.6, 0.38, 0.3), (0.56, 0.36, 0.28), (0.44, 0.28, 0.24))


def synth_hand(fingers: Sequence[int], *, mirror: bool = False) -> list[float]:
    """Main normalisee (63 valeurs) avec les doigts demandes leves (1) ou replies (0)."""
    pts: list[tuple[float, float, float]] = [(0.0, 0.0, 0.0)] * 21
    # pouce : base sur le cote, tendu vers l'exterieur ou replie vers la paume
    cmc = (-0.28, -0.22)
    mcp = (-0.52, -0.42)
    pts[1] = (*cmc, 0.0)
    pts[2] = (*mcp, 0.0)
    if fingers[0]:
        pts[3] = (mcp[0] - 0.28, mcp[1] - 0.2, 0.0)
        pts[4] = (mcp[0] - 0.55, mcp[1] - 0.38, 0.0)
    else:
        pts[3] = (-0.38, -0.62, 0.0)
        pts[4] = (-0.22, -0.78, 0.0)
    for finger, (base, lengths) in enumerate(zip(_BASES, _LENGTHS, strict=True)):
        b = base
        l1, l2, l3 = lengths
        pts[5 + finger * 4] = (*b, 0.0)
        if fingers[finger + 1]:
            p = (b[0], b[1] - l1)
            d = (b[0], p[1] - l2)
            t = (b[0], d[1] - l3)
        else:  # replie : la phalange proximale se raccourcit (perspective), la pointe revient vers la paume
            p = (b[0], b[1] - l1 * 0.55)
            d = (b[0], p[1] + l2 * 0.5)
            t = (b[0], d[1] + l3 * 0.9)
        pts[6 + finger * 4], pts[7 + finger * 4], pts[8 + finger * 4] = (*p, 0.0), (*d, 0.0), (*t, 0.0)
    flat: list[float] = []
    for x, y, z in pts:
        flat.extend((-x if mirror else x, y, z))
    return flat


def synth_frame(*hands: Sequence[int]) -> list[float]:
    """Vecteur de frame (126 valeurs) a partir d'une ou deux mains (gauche -> droite)."""
    vec: list[float] = []
    for i, fingers in enumerate(hands[:2]):
        vec.extend(synth_hand(fingers, mirror=(i == 0 and len(hands) == 2)))
    vec.extend([0.0] * (HAND_LEN * 2 - len(vec)))
    return vec
