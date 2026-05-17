"""Backward-compatibility shim. Pass 4.0g Phase E moved the composer
logic into agents/composer/hero_composer.py and parameterized it with
module_id. Spike scripts that import `compose_cathedral_hero` or the
`_strip_code_fence` helper from this module continue to work via this
shim.

The actual composer logic + system prompt now live in hero_composer.py
under MODULES['cathedral'].

If you're writing NEW code, import directly from hero_composer:

    from agents.composer.hero_composer import compose_hero
    composition = compose_hero(business_id, module_id='cathedral')

The old surface remains available below for spike script compatibility:

    from agents.composer.cathedral_hero_composer import compose_cathedral_hero
    composition = compose_cathedral_hero(business_id)
"""
from __future__ import annotations

from typing import Any, Dict

# Re-export helpers and entry points so existing callers keep working.
from agents.composer.hero_composer import (
    compose_hero,
    fetch_business_context,
    build_user_prompt,
    _strip_code_fence,
    _enforce_image_slot_consistency,
    _enforce_depth_treatments,
    _missing_depth_fields,
    _safe_fallback,
    MODULES,
    CATHEDRAL_SYSTEM_PROMPT as COMPOSER_SYSTEM_PROMPT,
    COMPOSER_MODEL,
    COMPOSER_MAX_TOKENS,
    COMPOSER_TEMPERATURE,
)
# Re-export the composition type at the legacy import path.
from agents.design_modules.cinematic_authority.hero.types import (
    CathedralHeroComposition,
    HeroContent,
    IMAGE_USING_VARIANTS,
    Treatments,
    VariantId,
)


def compose_cathedral_hero(business_id: str) -> Dict[str, Any]:
    """Pass 4.0f Phase 3 entry preserved as a thin shim. Delegates to
    the generalized composer with module_id='cathedral'."""
    return compose_hero(business_id, module_id="cathedral")


def compose_for_spike(business_id: str) -> Dict[str, Any]:
    """Phase 3 testing helper preserved for spike script compatibility."""
    composition = compose_cathedral_hero(business_id)
    composition["_business_id"] = business_id
    return composition
