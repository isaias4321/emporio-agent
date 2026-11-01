"""Tiny Portuguese-friendly text helpers (accent folding, light stemming)."""
from __future__ import annotations

import re
import unicodedata

STOPWORDS = {
    "de", "da", "do", "das", "dos", "para", "pra", "com", "um", "uma", "uns", "umas",
    "o", "a", "os", "as", "e", "em", "no", "na", "nos", "nas", "que", "qual", "quais",
    "quero", "queria", "tem", "voces", "voce", "ter", "por", "ao", "se", "me", "meu",
    "minha", "sobre", "como", "ou", "is", "the", "of", "and", "for", "to",
}


def normalize(text: object) -> str:
    """Lowercase and strip accents: 'Violão' -> 'violao'."""
    s = unicodedata.normalize("NFKD", str(text))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower().strip()


def stem(tok: str) -> str:
    """Very light PT plural stemmer (good enough for catalog/policy matching)."""
    if len(tok) > 3:
        if tok.endswith(("oes", "aes")):
            return tok[:-3] + "ao"
        if tok.endswith("ais"):
            return tok[:-3] + "al"
        if tok.endswith("ores"):
            return tok[:-2]
        if tok.endswith("s"):
            return tok[:-1]
    return tok


def tokenize(text: object, drop_stopwords: bool = True) -> list[str]:
    toks = re.findall(r"[a-z0-9]+", normalize(text))
    if drop_stopwords:
        toks = [t for t in toks if t not in STOPWORDS]
    return [stem(t) for t in toks]
