"""Pass 4.0i Phase B — intensity → CSS variable values.

Maps the three intensity levels (restrained / confident / bold) to:
  - multiplier (1.0 / 1.15 / 1.3) applied to variant-declared base sizes
  - font-weight selection (800 / 800 / 900)
  - letter-spacing (-1.6px / -2.4px / -3.0px)
  - amplitude + spacing multipliers (same as size multiplier; treatments
    that consume amplitude will scale opacity/scale/offset by this factor)

Two-sided clamp at multiplier application makes rubric violations from
intensity math impossible:

    effective = max(min(base × multiplier, sanity_ceiling), rubric_floor)

Rubric floors come from cinematic_authority_rubric.json (the only rubric
on disk today). Studio Brut variants are checked against these floors
until a Studio-Brut-specific rubric ships — the floors are conservative
for Studio Brut's poster aesthetic, so this is acceptable.

Sanity ceilings are NOT rubric-enforced — they're layout-readability
limits chosen to prevent bold intensity from pushing display type past
single-line readability at extreme viewports. Adjustable.
"""
from __future__ import annotations

from typing import Dict

# ─── Rubric floors (Pass 4.0d.3 cinematic_authority rubric) ────────

HERO_H1_FLOOR_REM: float = 3.0
SECTION_H2_FLOOR_REM: float = 2.0

# ─── Sanity ceilings (layout-readability, Pass 4.0i) ──────────────

HERO_H1_SANITY_CEILING_REM: float = 10.0
SECTION_H2_SANITY_CEILING_REM: float = 6.0

# ─── Intensity level config ────────────────────────────────────────

INTENSITY_CONFIG: Dict[str, Dict] = {
    "restrained": {
        "multiplier": 1.0,
        "weight": 800,
    },
    "confident": {
        "multiplier": 1.15,
        "weight": 800,
    },
    "bold": {
        "multiplier": 1.3,
        "weight": 900,
    },
}

INTENSITY_DEFAULT: str = "restrained"


def clamp_size(base_rem: float, multiplier: float,
               floor_rem: float, ceiling_rem: float) -> float:
    """Two-sided clamp: effective = max(min(base*mult, ceiling), floor).
    Makes rubric violations from intensity math impossible. Variant
    authors who pick a base below the rubric floor will silently render
    at the floor; the Phase B smoke test catches the author error."""
    return max(min(base_rem * multiplier, ceiling_rem), floor_rem)


def intensity_css_vars(intensity: str,
                       h1_base_rem: float,
                       h2_base_rem: float) -> Dict[str, str]:
    """CSS variable assignments the variant merges into its section style.

    Variant declares its own h1_base_rem and h2_base_rem (its natural
    display scale). massive_letterform might use h1_base_rem=8.0;
    color_block_split might use 3.2. Translator clamps to safe range.

    Returns string values so the variant can interpolate directly into
    inline style declarations. CSS variables produced (all values carry
    their CSS units inline so primitives can consume via var() directly):

      --hero-h1-font-size           effective h1 size in rem (e.g. "4.000rem")
      --hero-h2-font-size           effective h2 size in rem
      --hero-display-weight         font-weight value ("800" or "900") — may
                                    be overridden in the primitive's chain by
                                    --hero-font-fixed-weight when the font
                                    declares weight_locked=True
      --hero-treatment-amplitude    multiplier for treatments that scale
                                    (background opacity, gradient stops, etc.)
      --hero-element-spacing-mult   multiplier for inter-element gaps

    Phase B finalize ownership rule: intensity owns size + weight TIER.
    Font owns tracking (--hero-letter-spacing is emitted by font_resolver,
    NOT here) and case (--hero-text-transform from font_resolver). Pre-
    finalize this translator also emitted --hero-letter-spacing with a
    -1.6/-2.4/-3.0px progression — that's been removed so the font's
    per-font base tracking applies regardless of intensity, matching
    the ownership rule.
    """
    cfg = INTENSITY_CONFIG.get(intensity)
    if cfg is None:
        cfg = INTENSITY_CONFIG[INTENSITY_DEFAULT]

    mult = cfg["multiplier"]
    h1_effective = clamp_size(
        h1_base_rem, mult, HERO_H1_FLOOR_REM, HERO_H1_SANITY_CEILING_REM,
    )
    h2_effective = clamp_size(
        h2_base_rem, mult, SECTION_H2_FLOOR_REM, SECTION_H2_SANITY_CEILING_REM,
    )

    return {
        "--hero-h1-font-size": f"{h1_effective:.3f}rem",
        "--hero-h2-font-size": f"{h2_effective:.3f}rem",
        "--hero-display-weight": str(cfg["weight"]),
        "--hero-treatment-amplitude": f"{mult:.3f}",
        "--hero-element-spacing-mult": f"{mult:.3f}",
    }
