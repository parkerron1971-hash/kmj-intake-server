"""Pass 4.0b.5 — Canonical slot taxonomy.

11 starter slots covering the three roles a Cinematic Authority site
needs imagery for:

  profile     — practitioner / founder portraits. Default to placeholder
                because we never want to substitute a stock face for a
                real one. Practitioner uploads via the Slot Management
                UI (PART 5).
  atmosphere  — environmental / contextual photography that sets mood
                without standing in for a person. Defaults to Unsplash
                with DALL-E fallback when no relevant Unsplash result
                clears the relevance threshold.
  decorative  — abstract textures / accent imagery. Defaults to DALL-E
                because Unsplash rarely has on-brand abstracts.

Each slot record carries:
  role               — one of {profile, atmosphere, decorative}
  description        — human-readable label for the Slot Management UI
  default_strategy   — placeholder | unsplash | dalle | unsplash_with_dalle_fallback
  aspect_ratio       — target aspect (used in placeholder render +
                       Unsplash orientation hint + DALL-E size hint)
  min_dimensions     — minimum width/height for a retrieved image to be
                       considered acceptable (Unsplash filter, DALL-E
                       sizing target)
"""
from __future__ import annotations

from typing import Dict, Optional


SLOT_DEFINITIONS: Dict[str, Dict] = {
    "hero_main": {
        "role": "atmosphere",
        "description": "Primary hero image — sets the brand mood",
        "default_strategy": "unsplash_with_dalle_fallback",
        "aspect_ratio": "16:9",
        "min_dimensions": {"width": 1600, "height": 900},
    },
    "about_subject": {
        "role": "profile",
        "description": "Practitioner headshot or portrait",
        "default_strategy": "placeholder",
        "aspect_ratio": "4:5",
        "min_dimensions": {"width": 800, "height": 1000},
    },
    "founder_photo": {
        "role": "profile",
        "description": "Founder portrait for about/team sections",
        "default_strategy": "placeholder",
        "aspect_ratio": "1:1",
        "min_dimensions": {"width": 600, "height": 600},
    },
    "gallery_1": {
        "role": "atmosphere",
        "description": "Gallery image 1",
        "default_strategy": "unsplash_with_dalle_fallback",
        "aspect_ratio": "4:3",
        "min_dimensions": {"width": 1200, "height": 900},
    },
    "gallery_2": {
        "role": "atmosphere",
        "description": "Gallery image 2",
        "default_strategy": "unsplash_with_dalle_fallback",
        "aspect_ratio": "4:3",
        "min_dimensions": {"width": 1200, "height": 900},
    },
    "gallery_3": {
        "role": "atmosphere",
        "description": "Gallery image 3",
        "default_strategy": "unsplash_with_dalle_fallback",
        "aspect_ratio": "4:3",
        "min_dimensions": {"width": 1200, "height": 900},
    },
    "gallery_4": {
        "role": "atmosphere",
        "description": "Gallery image 4",
        "default_strategy": "unsplash_with_dalle_fallback",
        "aspect_ratio": "4:3",
        "min_dimensions": {"width": 1200, "height": 900},
    },
    "chamber_main": {
        "role": "atmosphere",
        "description": "Atmospheric/environmental image",
        "default_strategy": "unsplash_with_dalle_fallback",
        "aspect_ratio": "3:2",
        "min_dimensions": {"width": 1200, "height": 800},
    },
    "decorative_1": {
        "role": "decorative",
        "description": "Texture or abstract accent",
        "default_strategy": "dalle",
        "aspect_ratio": "1:1",
        "min_dimensions": {"width": 600, "height": 600},
    },
    "decorative_2": {
        "role": "decorative",
        "description": "Texture or abstract accent",
        "default_strategy": "dalle",
        "aspect_ratio": "1:1",
        "min_dimensions": {"width": 600, "height": 600},
    },
    "decorative_3": {
        "role": "decorative",
        "description": "Texture or abstract accent",
        "default_strategy": "dalle",
        "aspect_ratio": "1:1",
        "min_dimensions": {"width": 600, "height": 600},
    },
}


VALID_ROLES = ("profile", "atmosphere", "decorative")
VALID_STRATEGIES = (
    "placeholder",
    "unsplash",
    "dalle",
    "unsplash_with_dalle_fallback",
)


def get_slot_definition(slot_name: str) -> Optional[Dict]:
    """Return the definition for a slot, or None when the slot name
    isn't in the canonical taxonomy. Callers should treat None as
    'unknown slot — render placeholder, do not retrieve'."""
    return SLOT_DEFINITIONS.get(slot_name)


def list_slots(role_filter: Optional[str] = None) -> Dict[str, Dict]:
    """Return all slot definitions, optionally filtered by role.
    Used by the Slot Management UI to populate role-tab views."""
    if role_filter:
        return {
            k: v for k, v in SLOT_DEFINITIONS.items()
            if v["role"] == role_filter
        }
    return dict(SLOT_DEFINITIONS)
