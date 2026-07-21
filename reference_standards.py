"""
reference_standards.py — Arc D (2026-07-21): the judge gets a bar.

Until now the vision grader scored builds in a vacuum — "is this good?"
with no definition of good. Top-tier needs a standard to be held
against. This module carries AUTHORED north-star descriptions of what
excellent looks like per design direction; the vision judge receives
the matching standard and is told a page that would look amateur next
to it cannot pass.

The standards are deliberately about CRAFT (type, space, materials,
imagery discipline), never about content — they anchor taste, not
branding, so they can never leak a competitor's identity into a build.

Curation hook: REFERENCE_STANDARDS_JSON (env, a JSON object keyed like
STANDARDS) merges over the defaults — Kevin can raise or retarget any
bar without a deploy.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger("reference_standards")

STANDARDS: Dict[str, str] = {
    "refined_luxury": (
        "- Display type is a refined serif or high-contrast face set with "
        "generous negative space; never a condensed impact face.\n"
        "- Accents are desaturated and precious — champagne gold, deep "
        "forest, oxblood — spent on hairlines, numerals and one CTA; "
        "never neon, never glowing.\n"
        "- Materials feel physical: paper-grain darks, engraved rules, "
        "letterpress spacing. Imagery is treated (toned, matted, "
        "consistent) — nothing raw.\n"
        "- The page moves like a hotel lobby: slow reveals, no bounce, "
        "one quiet section that holds only type.\n"
        "- Reference bar: an Aman resort site, a Mont Blanc product page, "
        "a Kinfolk feature spread.")
    ,
    "editorial": (
        "- The scroll reads like a magazine feature: a spine (numerals or "
        "rules), small-caps eyebrows, display headlines with real "
        "hierarchy, body copy at a comfortable measure.\n"
        "- Every section earns its place with SUBSTANCE — descriptions, "
        "prices, stories — never a bare label floating in space.\n"
        "- One serif voice for display, one workhorse for body, one "
        "italic accent used at most twice.\n"
        "- Reference bar: a New York Times feature, a Stripe Press book "
        "page, a Pentagram case study.")
    ,
    "warm_community": (
        "- Rounded but disciplined: soft radii, warm neutrals, real "
        "photography of real people treated consistently.\n"
        "- Type is humanist and legible; warmth comes from color and "
        "imagery, not from clutter.\n"
        "- Sections connect like a welcome tour — every card has a next "
        "step; nothing dead-ends.\n"
        "- Reference bar: a Headspace landing page, a well-made church "
        "campus site, Mailchimp's friendlier pages.")
    ,
    "bold_statement": (
        "- Impact faces are ALLOWED here — huge condensed headlines, hard "
        "grids, high contrast — but composed: aligned edges, deliberate "
        "overlaps, no accidental dead zones.\n"
        "- Neon accents are legal but singular: one electric color doing "
        "one job, on near-black or near-white, never fighting a second "
        "loud hue.\n"
        "- Reference bar: a Nike campaign page, a music festival site "
        "that still ships clean, Brutalist portfolios that align.")
    ,
    "minimal_technical": (
        "- Radical restraint: few elements, perfect spacing, monospace or "
        "geometric type, thin rules.\n"
        "- Whitespace is the design; anything that doesn't inform leaves.\n"
        "- Reference bar: Linear's marketing site, Vercel docs, a Swiss "
        "grid poster.")
    ,
    "default": (
        "- Clear hierarchy (one oversized moment per viewport), a "
        "systematic spacing rhythm, accents in materials not just text, "
        "imagery treated consistently, zero empty or broken-looking "
        "sections.\n"
        "- Reference bar: a current Squarespace flagship template "
        "executed WELL — the floor for 'professional', not the ceiling.")
    ,
}

_CLASS_KEYWORDS = (
    ("refined_luxury", ("luxur", "sovereign", "premium", "elegant", "refined",
                        "quiet", "understated", "noir", "prestig")),
    ("editorial", ("editorial", "magazine", "essay", "literar", "story",
                   "journal", "serif")),
    ("warm_community", ("warm", "community", "welcom", "ministry", "church",
                        "nurtur", "friendly", "human")),
    ("bold_statement", ("bold", "brutal", "impact", "loud", "poster",
                        "statement", "electric", "neon")),
    ("minimal_technical", ("minimal", "technical", "precise", "system",
                           "mono", "engineer", "clean")),
)


def _overrides() -> Dict[str, str]:
    raw = (os.environ.get("REFERENCE_STANDARDS_JSON") or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning(f"[standards] REFERENCE_STANDARDS_JSON unparseable: {e}")
        return {}


def classify(evidence_text: str) -> str:
    """Direction evidence (design decisions + prefs, any casing) → the
    standard key. First keyword class to score ≥1 wins by ORDER — refined
    outranks bold on mixed evidence, same tie-break philosophy as the
    Arc B pairing resolution."""
    s = (evidence_text or "").lower()
    for key, words in _CLASS_KEYWORDS:
        if any(w in s for w in words):
            return key
    return "default"


def standard_for(ctx: Optional[Dict[str, Any]]) -> str:
    """The authored bar for this build's direction. Never raises; always
    returns a non-empty standard (default floor at minimum)."""
    try:
        c = ctx or {}
        design = c.get("design") or {}
        prefs = c.get("site_prefs") if isinstance(c.get("site_prefs"), dict) else {}
        evidence = " ".join((
            json.dumps(design, ensure_ascii=False, default=str),
            str((prefs or {}).get("feel_words") or ""),
            str((prefs or {}).get("boldness") or ""),
            str(((c.get("bundle") or {}).get("design") or {}).get("vibe_family") or ""),
        ))
        key = classify(evidence)
    except Exception as e:
        logger.warning(f"[standards] classify failed, using default: {e}")
        key = "default"
    merged = {**STANDARDS, **_overrides()}
    return merged.get(key) or merged["default"]
