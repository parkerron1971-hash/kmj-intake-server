"""Constraint option IDs used across Designer Agent and Brief Expander.

Single source of truth for the enum-style choice spaces:
  - 6 layout archetypes
  - 6 accent styles
  - 3 site types

Keep in sync with frontend if/when those constants get duplicated client-side.
"""
from __future__ import annotations


LAYOUT_ARCHETYPE_IDS: list[str] = [
    "split",              # standard hero split + services grid (default)
    "editorial-scroll",   # single column reading experience
    "showcase",           # portfolio-first, large images
    "statement",          # massive text hero, no image
    "immersive",          # atmospheric backgrounds everywhere
    "minimal-single",     # extremely condensed, 3-4 sections
]

LAYOUT_ARCHETYPE_DESCRIPTIONS: dict[str, str] = {
    "split":             "Standard hero split + services grid. Reliable for most service businesses.",
    "editorial-scroll":  "Single-column reading experience. Best for editorial brands, scholar-educators, narrative-driven offerings.",
    "showcase":          "Portfolio-first, large images. Best for visual brands — designers, photographers, artists.",
    "statement":         "Massive text hero, no image. Best for brand statements, manifestos, single-message landing pages.",
    "immersive":         "Atmospheric backgrounds everywhere, cinematic pacing. Best for premium experiential brands.",
    "minimal-single":    "Extremely condensed, 3-4 sections. Best for radical minimalist brands.",
}

ACCENT_STYLE_IDS: list[str] = [
    "ceremonial",       # diamond marks, gold rules, four-point stars
    "cinematic",        # film-inspired noir treatments
    "editorial",        # registration marks, asterisks, double rules
    "cultural-african", # Adinkra symbols, kente patterns, geometric grid marks
    "botanical",        # leaf motifs, vine dividers, organic curves
    "structural",       # grid lines, hard rules, technical marks
]

SITE_TYPE_IDS: list[str] = [
    "full-site",
    "landing-page",
    "one-page",
]


def is_valid_archetype(aid: str) -> bool:
    return aid in LAYOUT_ARCHETYPE_IDS


def is_valid_accent_style(sid: str) -> bool:
    return sid in ACCENT_STYLE_IDS


def is_valid_site_type(sid: str) -> bool:
    return sid in SITE_TYPE_IDS
