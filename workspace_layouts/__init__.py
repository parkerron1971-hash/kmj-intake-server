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

_cache: Dict[str, Dict[str, Any]] = {}


def _load(archetype: str) -> Dict[str, Any]:
    path = os.path.join(_DIR, f"{archetype}.json")
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def get_preset(archetype: str, *, validate: bool = True) -> Dict[str, Any]:
    """One preset, deep-copied.

    `validate=False` exists for the tests that deliberately malform a preset
    — nothing in production should pass it.
    """
    key = (archetype or "").strip().lower()
    if key not in ARCHETYPES:
        raise KeyError(
            f"unknown archetype {archetype!r}; known: {', '.join(ARCHETYPES)}"
        )
    if key not in _cache:
        layout = _load(key)
        if validate:
            # Imported here, not at module scope: the validator imports the
            # registry and the catalog, and a cycle through this package
            # would make the import order load-bearing.
            import workspace_layout_validator as validator
            validator.assert_valid(layout, business_id=None)
        _cache[key] = layout
    return copy.deepcopy(_cache[key])


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
