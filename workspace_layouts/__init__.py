"""
workspace_layouts — the five hand-authored archetype presets.

Static JSON, hand-written, no LLM anywhere near them. Chief's job in phase
one is to pick one of these; it does not get to author a sixth.

The loader validates on read (`workspace_layout_validator`) so a preset that
drifts out of contract fails at import in the test suite rather than at
render in front of a practitioner. Presets are cached after the first read
and returned as deep copies — a caller that mutates its layout must not
mutate everyone else's.
"""
from __future__ import annotations

import copy
import json
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger("workspace_layouts")

_DIR = os.path.dirname(os.path.abspath(__file__))

# Declared order — this is the order Chief offers overrides in, and it runs
# from the most schedule-shaped business to the most deadline-shaped one.
ARCHETYPES = ("salon", "trades", "therapist", "ministry", "consultant",
              "nonprofit", "law_firm")

# ─── layout VARIANTS ─────────────────────────────────────────────────
# An archetype says which room a business is in. A VARIANT says what
# that room leads with today, and it is not a taste question: Chief
# picks it from the business's own numbers and re-picks when they move.
#
# A firm whose collection has collapsed and a firm whose matters have
# stalled need the same seven surfaces in a different order, with a
# different thing at the top and a different verb in the action row.
# Before this, both got the docket, because the archetype was the only
# dial there was.
#
# The FIRST entry is the default — the variant a business gets before
# there is enough measured about it to say anything better, and the one
# whose file keeps the plain `<archetype>.json` name so every existing
# caller, test and row keeps working untouched.
VARIANTS: Dict[str, tuple] = {
    "law_firm": ("docket", "board", "ledger", "diary"),
}


def variants(archetype: str) -> List[str]:
    """The variants this archetype ships, default first.

    An archetype with no entry has exactly one layout, and that is a
    real answer rather than a gap: a variant should exist because a
    situation demands a different lead, not so that every vertical has
    the same number of them.
    """
    return list(VARIANTS.get((archetype or "").strip().lower(), ()))


def default_variant(archetype: str) -> Optional[str]:
    v = variants(archetype)
    return v[0] if v else None


def is_variant(archetype: str, variant: Optional[str]) -> bool:
    return bool(variant) and variant in variants(archetype)

_cache: Dict[str, Dict[str, Any]] = {}


def _load(archetype: str, variant: Optional[str] = None) -> Dict[str, Any]:
    """Read one layout file.

    The DEFAULT variant lives at `<archetype>.json` and every other at
    `<archetype>.<variant>.json`. Keeping the default where it has
    always been is the whole reason this change touches nothing else:
    every existing row, test and caller that knows only an archetype
    still resolves to exactly the file it used to.
    """
    name = archetype if not variant or variant == default_variant(archetype)         else f"{archetype}.{variant}"
    path = os.path.join(_DIR, f"{name}.json")
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _attach_identity(layout: Dict[str, Any]) -> None:
    """Resolve the preset's `identity` reference into the real thing.

    The preset names an identity; it does not carry one. Each used to
    hold a thirteen-key palette of which NINE keys were byte-identical
    across all seven, and the four that moved disagreed with the desk
    for every single vertical — a law firm was gold on one screen and
    blue on the other.

    Resolving here rather than storing means the two can no longer
    drift: there is one definition, in workspace_identity.py, and both
    the desk and the composer read it.
    """
    import workspace_identity

    key = layout.get("identity")
    ident = workspace_identity.IDENTITIES.get(key) if key else None
    if not ident:
        # Not fatal. A layout renders without an identity — it simply
        # wears the practitioner's own design, which is exactly what two
        # of the seven do on purpose.
        return
    layout["identity"] = dict(ident, key=key)
    layout["identity_tokens"] = workspace_identity.tokens(layout["archetype"])


def get_preset(archetype: str, *, variant: Optional[str] = None,
               validate: bool = True) -> Dict[str, Any]:
    """One preset, deep-copied.

    `variant` selects which layout of that archetype. Unknown or absent
    falls back to the default rather than raising: a variant is a
    RECOMMENDATION, and a stale one stored on a row must never be able
    to blank a practitioner's home screen.

    `validate=False` exists for the tests that deliberately malform a preset
    — nothing in production should pass it.
    """
    key = (archetype or "").strip().lower()
    if key not in ARCHETYPES:
        raise KeyError(
            f"unknown archetype {archetype!r}; known: {', '.join(ARCHETYPES)}"
        )
    v = (variant or "").strip().lower() or None
    if v and not is_variant(key, v):
        logger.warning("unknown variant %r for %s; using the default", v, key)
        v = None
    v = v or default_variant(key)
    cache_key = f"{key}:{v}" if v else key

    if cache_key not in _cache:
        layout = _load(key, v)
        _attach_identity(layout)
        if validate:
            # Imported here, not at module scope: the validator imports the
            # registry and the catalog, and a cycle through this package
            # would make the import order load-bearing.
            import workspace_layout_validator as validator
            validator.assert_valid(layout, business_id=None)
        _cache[cache_key] = layout
    return copy.deepcopy(_cache[cache_key])


def all_presets() -> List[Dict[str, Any]]:
    return [get_preset(a) for a in ARCHETYPES]


def archetypes() -> List[str]:
    return list(ARCHETYPES)


def summaries() -> List[Dict[str, Any]]:
    """Enough to render an override picker without shipping five full
    schemas to the client."""
    out = []
    for a in ARCHETYPES:
        p = get_preset(a)
        lead = next((s for s in p["surfaces"] if s["role"] == "lead"), None)
        out.append({
            "archetype": a,
            "label": p["label"],
            "vertical": p["vertical"],
            "rationale": p["rationale"],
            "lead_primitive": lead["primitive"] if lead else None,
            "lead_title": lead["title"] if lead else None,
            "surface_count": len(p["surfaces"]),
            "suppressed": [s["primitive"] for s in p.get("suppressed") or []],
        })
    return out


def for_vertical(vertical: str) -> Optional[str]:
    """The archetype a canonical vertical maps to, or None.

    Deliberately not a fallback-to-generic: a vertical with no archetype is
    a classification question, and `workspace_archetypes` answers it with
    evidence rather than this map shrugging.
    """
    v = (vertical or "").strip().lower()
    for a in ARCHETYPES:
        if get_preset(a)["vertical"] == v:
            return a
    return None
