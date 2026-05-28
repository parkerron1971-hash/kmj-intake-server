"""Pass 4.0i Phase B — Studio Brut font_id → CSS + loading resolver.

Three surfaces:
  resolve_font(font_id)      → full config dict (or default on miss)
  font_css_vars(font_id)     → dict of --hero-font-* CSS variable assignments
  font_loading_html(font_id) → Google Fonts <link> tags + preload for display

All three are pure functions, no side effects. Variants call font_css_vars
to inject CSS variables into their section's inline style; font_loading_html
is emitted exactly once per page (Composer pipeline handles dedup if multiple
Hero compositions ever coexist — Pass 4.0i scope is single-Hero per page).
"""
from __future__ import annotations

import logging
from typing import Dict

from .fonts import STUDIO_BRUT_FONTS, STUDIO_BRUT_FONT_DEFAULT

logger = logging.getLogger(__name__)


def resolve_font(font_id: str) -> Dict:
    """Return the font config dict for font_id, or the default config if
    font_id is missing/invalid. Logs a warning on fallback so misconfiguration
    is visible in Railway logs."""
    cfg = STUDIO_BRUT_FONTS.get(font_id)
    if cfg is None:
        if font_id:
            logger.warning(
                "[creative_expression.font_resolver] unknown font_id=%r, "
                "falling back to %s",
                font_id, STUDIO_BRUT_FONT_DEFAULT,
            )
        cfg = STUDIO_BRUT_FONTS[STUDIO_BRUT_FONT_DEFAULT]
    return cfg


def font_css_vars(font_id: str) -> Dict[str, str]:
    """CSS variable assignments the variant merges into its section style.

      --hero-font-display          full display font-family stack
      --hero-font-body             full body font-family stack
      --hero-text-transform        case treatment per font (uppercase|none)
      --hero-letter-spacing        per-font base tracking (carries CSS units)
      --hero-font-code             monospace stack (only when font declares a 'code' face)
      --hero-font-fixed-weight     locked weight (ONLY when weight_locked=True);
                                   primitive consumes this with precedence
                                   over intensity's --hero-display-weight so a
                                   single-weight serif (DM Serif Display)
                                   doesn't get faux-bold synthesized

    Variants reference these via var(--hero-...) with --sb-* fallbacks so
    older compositions without creative_expression still render unchanged.

    Phase B finalize: font now owns case + tracking (the user's locked
    ownership rule). Intensity stops emitting --hero-letter-spacing; only
    this resolver sets it. text-transform is a new dimension introduced
    here — pre-finalize all 5 fonts inherited the variant's hardcoded
    uppercase from the bold typography treatment.
    """
    cfg = resolve_font(font_id)
    out = {
        "--hero-font-display": cfg["display"],
        "--hero-font-body": cfg["body"],
        "--hero-text-transform": cfg["case"],
        "--hero-letter-spacing": cfg["tracking"],
    }
    if "code" in cfg:
        out["--hero-font-code"] = cfg["code"]
    # Weight-lock for single-weight display faces (currently only
    # brutalist_editorial / DM Serif Display). The primitive's font-weight
    # var chain reads --hero-font-fixed-weight FIRST so a bold-intensity
    # editorial Hero still renders at the font's authentic 400 weight.
    if cfg.get("weight_locked"):
        out["--hero-font-fixed-weight"] = str(cfg["base_weight"])
    return out


def font_loading_html(font_id: str) -> str:
    """Return the <link> tags to load this font_id's Google Fonts via CSS2 API.

    Includes:
      * preconnect to fonts.googleapis.com + fonts.gstatic.com (idempotent —
        browser dedups across multiple preconnects to same origin)
      * stylesheet <link> with display=swap to avoid FOUT blocking
      * preload <link> for the display face so first paint reaches the
        right typography quickly

    Single-quote attribute style matches the existing Studio Brut spot-check
    test doc shell for consistency. Caller is responsible for not duplicating
    if multiple Heros emit this on the same page (Pass 4.0i scope: one Hero).
    """
    cfg = resolve_font(font_id)
    families = cfg["google_families"]
    if not families:
        return ""
    family_query = "&".join(f"family={fam}" for fam in families)
    stylesheet_url = (
        f"https://fonts.googleapis.com/css2?{family_query}&display=swap"
    )
    preload_family = cfg.get("preload_family", "")
    preload_html = ""
    if preload_family:
        # Browsers preload a stylesheet under a different `as` than fonts.
        # Use as=style for the CSS2 endpoint — the actual font files get
        # discovered through the stylesheet and pre-warmed via preconnect.
        preload_url = (
            f"https://fonts.googleapis.com/css2?family={preload_family}&display=swap"
        )
        preload_html = (
            f'<link rel="preload" as="style" '
            f'href="{preload_url}">'
        )
    return (
        '<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
        f'{preload_html}'
        f'<link rel="stylesheet" href="{stylesheet_url}">'
    )
