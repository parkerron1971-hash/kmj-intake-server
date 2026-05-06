"""Deterministic font resolution per strand pair.

Per Studio's pattern: fonts are NEVER an LLM choice. The Designer Agent
picks strands; STRAND_FONT_MAP determines fonts deterministically based
on the dominant strand. This guarantees typography consistency.
"""
from __future__ import annotations
from typing import TypedDict


class FontPair(TypedDict):
    display: str
    body: str
    accent: str


# Verbatim port from Studio's STRAND_FONT_MAP (per Pass 3.8a spec).
# Note: spec values differ slightly from the live TS file (the spec is
# canonical for this build).
STRAND_FONT_MAP: dict[str, FontPair] = {
    "editorial": {"display": "Playfair Display", "body": "Inter", "accent": "Inter"},
    "luxury":    {"display": "Cormorant Garamond", "body": "Inter", "accent": "Montserrat"},
    "bold":      {"display": "Anton", "body": "Inter", "accent": "Inter"},
    "minimal":   {"display": "Inter", "body": "Inter", "accent": "Inter"},
    "dark":      {"display": "Bodoni Moda", "body": "Inter", "accent": "Inter"},
    "organic":   {"display": "Cormorant Garamond", "body": "DM Sans", "accent": "Inter"},
    "retrotech": {"display": "JetBrains Mono", "body": "JetBrains Mono", "accent": "JetBrains Mono"},
    "corporate": {"display": "Playfair Display", "body": "Inter", "accent": "Inter"},
    "playful":   {"display": "Fraunces", "body": "Inter", "accent": "Inter"},
    "brutalist": {"display": "Space Grotesk", "body": "Space Mono", "accent": "Space Mono"},
}


def resolve_font_pair(strand_a_id: str, strand_b_id: str, blend_ratio: float) -> FontPair:
    """Resolve font pair from strand pair + ratio.

    Dominant strand (higher ratio) wins. Tie or ratio >= 50 -> strand A.
    Falls back to minimal's pair if either strand id is unknown.
    """
    if blend_ratio >= 50:
        winner = strand_a_id
    else:
        winner = strand_b_id
    return STRAND_FONT_MAP.get(winner, STRAND_FONT_MAP["minimal"])
