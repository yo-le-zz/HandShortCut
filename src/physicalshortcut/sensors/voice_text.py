"""Traitement du texte reconnu par la voix : normalisation, correspondance floue, nombres en francais.

Fonctions pures (aucune dependance audio) : testables sans micro ni modele.
"""

from __future__ import annotations

import difflib
import re
import unicodedata

UNITS = {
    "zero": 0, "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "sept": 7, "huit": 8,
    "neuf": 9, "dix": 10, "onze": 11, "douze": 12, "treize": 13, "quatorze": 14, "quinze": 15, "seize": 16,
}
TENS = {"vingt": 20, "vingts": 20, "trente": 30, "quarante": 40, "cinquante": 50, "soixante": 60}
NUMBER_WORDS = set(UNITS) | set(TENS) | {"cent", "cents", "et"}


def normalize(text: str) -> str:
    """Minuscules, sans accents ni ponctuation, espaces simples."""
    text = unicodedata.normalize("NFD", str(text).lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[^a-z0-9\s]", " ", text.replace("-", " ").replace("'", " "))
    return re.sub(r"\s+", " ", text).strip()


def _words(text: str) -> list[str]:
    return normalize(text).split()


def match_phrase(text: str, phrases: list[str], mode: str = "contains", threshold: float = 0.82) -> str | None:
    """Renvoie la phrase attendue reconnue dans ``text`` (modes ``contains``, ``exact``, ``fuzzy``)."""
    spoken = _words(text)
    if not spoken:
        return None
    joined = " ".join(spoken)
    best: tuple[float, str] | None = None
    for phrase in phrases:
        target = _words(phrase)
        if not target:
            continue
        target_text = " ".join(target)
        if mode == "exact":
            if joined == target_text:
                return phrase
            continue
        if re.search(rf"(?<![a-z0-9]){re.escape(target_text)}(?![a-z0-9])", joined):
            return phrase
        if mode == "fuzzy":
            size = len(target)
            for start in range(max(1, len(spoken) - size + 1)):
                window = " ".join(spoken[start : start + size])
                ratio = difflib.SequenceMatcher(None, window, target_text).ratio()
                if ratio >= threshold and (best is None or ratio > best[0]):
                    best = (ratio, phrase)
    return best[1] if best else None


def extract_number(text: str) -> int | None:
    """Premier nombre trouve dans le texte : chiffres (``30``) ou mots (``quatre vingt dix sept``)."""
    tokens = _words(text)
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.isdigit():
            return int(token)
        if token in UNITS or token in TENS or token in ("cent", "cents"):
            total, current, last_was_four = 0, 0, False
            while i < len(tokens) and tokens[i] in NUMBER_WORDS | {"mille"}:
                word = tokens[i]
                if word == "et":
                    i += 1
                    continue
                if word in UNITS:
                    current += UNITS[word]
                    last_was_four = word == "quatre"
                elif word in ("vingt", "vingts") and last_was_four and current == 4:
                    current = 80
                    last_was_four = False
                elif word in TENS:
                    current += TENS[word]
                    last_was_four = False
                elif word in ("cent", "cents"):
                    current = (current or 1) * 100
                    total += current
                    current = 0
                    last_was_four = False
                elif word == "mille":
                    break
                i += 1
            return total + current
        i += 1
    return None
