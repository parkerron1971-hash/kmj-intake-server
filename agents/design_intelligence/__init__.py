"""Pass 4.0a — Design Intelligence Module loader.

Each module is one .md file with the full design brain. Modules are
loaded into LLM context when the Director Agent (Pass 4.0b) critiques
or refines a site.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

MODULE_DIR = Path(__file__).parent

# Module registry: maps module_id → metadata + matching strand combinations.
# The Designer Agent's strand pick determines which module loads. Each
# `matches_strands` tuple is (strand_a, strand_b, min_ratio_a, max_ratio_a).
MODULE_REGISTRY: dict = {
    "cinematic_authority": {
        "filename": "cinematic_authority_intelligence.md",
        "name": "Cinematic Authority",
        "tagline": "MasterClass meets Apple — editorial typography meets cinematic depth",
        "matches_strands": [
            ("editorial", "bold", 50, 70),
            # Symmetric pair: bold-dominant blends are the same family
            # viewed from the other direction.
            ("bold", "editorial", 30, 50),
            # Close-enough adjacents that share the same compositional
            # vocabulary (large display serif + dark cinematic depth).
            ("editorial", "luxury", 50, 70),
            ("editorial", "dark", 50, 70),
        ],
        "canonical_example": "embracetheshift.live",
    },
    # Future modules will be added in later passes:
    #   "cathedral", "pulpit", "atelier", "trader_floor",
    #   "field_manual", "studio_brut"
}


def list_modules() -> List[Dict]:
    """Return metadata for all available modules.

    Strips the internal `matches_strands` field — callers that need
    matching should use `find_module_for_strands` instead.
    """
    return [
        {"id": mid, **{k: v for k, v in meta.items() if k != "matches_strands"}}
        for mid, meta in MODULE_REGISTRY.items()
    ]


def load_module(module_id: str) -> Optional[str]:
    """Return the full markdown text of a Design Intelligence Module.

    Returns None if the module is unknown OR its file is missing on disk
    (e.g. a registry entry exists for a planned module whose markdown
    hasn't landed yet). The Director Agent treats None as "no module-
    driven critique available — ship Builder output as-is."
    """
    meta = MODULE_REGISTRY.get(module_id)
    if not meta:
        return None
    path = MODULE_DIR / meta["filename"]
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def find_module_for_strands(
    strand_a: str,
    strand_b: str,
    ratio_a: int,
) -> Optional[str]:
    """Return the module_id whose strand band covers this Designer pick.

    Walks MODULE_REGISTRY in insertion order and returns the FIRST match.
    Returns None when no module covers the pick (Director Agent falls
    back to current Builder behavior for that site).
    """
    for module_id, meta in MODULE_REGISTRY.items():
        for sa, sb, min_r, max_r in meta["matches_strands"]:
            if sa == strand_a and sb == strand_b and min_r <= ratio_a <= max_r:
                return module_id
    return None
