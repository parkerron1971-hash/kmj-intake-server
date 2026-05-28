"""Pass 4.0i Phase B — Studio Brut Hero creative expression layer.

Three coordinated dimensions a practitioner can pick (or Composer
infers from archetype):

  * font_id     — 5 Studio Brut font pairings (Google Fonts only)
  * accent_id   — 6 optional decorative accents (incl. no_accent default)
  * intensity   — restrained / confident / bold (multiplier × clamp)

Module-agnostic intent: intensity treatment is shared across modules.
font_resolver + accent_renderer are Studio Brut-only in Pass 4.0i —
Cathedral vocabularies deferred to Pass 4.0i.x.

See agents/composer/PASS_4_0I_DESIGN.md for the authoritative design.
"""
from __future__ import annotations

from .fonts import (
    STUDIO_BRUT_FONTS,
    STUDIO_BRUT_FONT_DEFAULT,
    STUDIO_BRUT_FONT_IDS,
)
from .font_resolver import (
    resolve_font,
    font_css_vars,
    font_loading_html,
)
from .intensity_translator import (
    INTENSITY_CONFIG,
    INTENSITY_DEFAULT,
    HERO_H1_FLOOR_REM,
    HERO_H1_SANITY_CEILING_REM,
    SECTION_H2_FLOOR_REM,
    SECTION_H2_SANITY_CEILING_REM,
    intensity_css_vars,
    clamp_size,
)
from .accent_renderer import (
    STUDIO_BRUT_ACCENT_IDS,
    STUDIO_BRUT_ACCENT_DEFAULT,
    render_accent,
    accent_position_style,
    render_positioned_accent,
)

__all__ = [
    "STUDIO_BRUT_FONTS",
    "STUDIO_BRUT_FONT_DEFAULT",
    "STUDIO_BRUT_FONT_IDS",
    "resolve_font",
    "font_css_vars",
    "font_loading_html",
    "INTENSITY_CONFIG",
    "INTENSITY_DEFAULT",
    "HERO_H1_FLOOR_REM",
    "HERO_H1_SANITY_CEILING_REM",
    "SECTION_H2_FLOOR_REM",
    "SECTION_H2_SANITY_CEILING_REM",
    "intensity_css_vars",
    "clamp_size",
    "STUDIO_BRUT_ACCENT_IDS",
    "STUDIO_BRUT_ACCENT_DEFAULT",
    "render_accent",
    "accent_position_style",
    "render_positioned_accent",
]
