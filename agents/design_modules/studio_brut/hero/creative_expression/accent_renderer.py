"""Pass 4.0i Phase B — Studio Brut accent rendering.

Six accent options including no_accent default. Each accent is a small
graphic element the variant conditionally renders. All use brand kit
CSS variables (--brand-signal primarily, --brand-authority for contrast).

Registry pattern: render_accent dispatches to per-accent renderer
functions. Unknown accent_id returns empty string (graceful failure;
warning logged).

DNA gates per Pass 4.0g:
  * NO `class="diamond"` (Cathedral signature)
  * NO `font-style: italic` on <h1> (Cathedral signature)
  * MUST use var(--brand-*) references, never raw hex for palette roles
  * NO --ca-* (Cathedral CSS var leakage)

The Studio Brut type_initial accent is INTENTIONALLY distinct from
Cathedral's future manuscript_drop_cap: type_initial is brutalist
(sans-serif full-bleed graphic element, often overlapping image or
background), drop cap is editorial (serif illuminated in-line glyph).
"""
from __future__ import annotations

import logging
import re
from html import escape
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# ─── Vocabulary ────────────────────────────────────────────────────

STUDIO_BRUT_ACCENT_IDS: List[str] = [
    "no_accent",
    "oversized_punctuation",
    "geometric_stamp",
    "type_initial",
    "code_label",
    "color_block_accent",
]

STUDIO_BRUT_ACCENT_DEFAULT: str = "no_accent"


# ─── Helpers ───────────────────────────────────────────────────────

def _first_letter(text: str) -> str:
    """Strip leading non-letter chars and return the first letter (uppercased).
    Empty string if no letter found."""
    if not text:
        return ""
    for ch in text:
        if ch.isalpha():
            return ch.upper()
    return ""


def _short_label(content: Optional[Any], fallback: str = "NO.01") -> str:
    """Derive a short ALL-CAPS code-style label.

    Priority:
      1. content.business_label (Composer-suggested in Phase C, e.g. 'VOL.II')
      2. derived from content.eyebrow first 3 chars + sequence number
      3. fallback ("NO.01")

    Always upper-cased. ASCII-safe by stripping non-printable.
    """
    if content is not None:
        biz_label = getattr(content, "business_label", None)
        if biz_label and isinstance(biz_label, str) and biz_label.strip():
            return biz_label.strip().upper()[:16]
        eyebrow = getattr(content, "eyebrow", None) or ""
        if isinstance(eyebrow, str):
            stem = re.sub(r"[^A-Za-z0-9]", "", eyebrow)[:3].upper()
            if stem:
                return f"{stem}.01"
    return fallback


def _code_font_stack(font_id: str) -> str:
    """Code-style monospace stack for code_label accent. brutalist_geometric
    declares its own --hero-font-code (JetBrains Mono); other font_ids fall
    back to platform monospace."""
    # The variant exposes --hero-font-code only for fonts that declared one
    # (currently just brutalist_geometric per fonts.py). Use a layered
    # fallback so the accent works regardless: prefer --hero-font-code,
    # then a hard JetBrains Mono reference, then platform monospace.
    return (
        "var(--hero-font-code, 'JetBrains Mono', "
        "ui-monospace, 'SF Mono', Menlo, monospace)"
    )


# ─── Per-accent renderers ──────────────────────────────────────────

def _render_oversized_punctuation(
    brand_vars: Dict[str, str],
    font_id: str,
    content: Optional[Any],
) -> str:
    """Single oversized punctuation mark as graphic element. Defaults to
    ampersand (universal). Composer may override via content.accent_glyph
    in Phase C (e.g., '"' open-quote for quote brands)."""
    glyph = "&amp;"
    if content is not None:
        custom = getattr(content, "accent_glyph", None)
        if isinstance(custom, str) and 0 < len(custom) <= 3:
            glyph = escape(custom)
    return (
        '<div class="sb-accent sb-accent-oversized-punctuation" '
        'data-override-target="hero.accent_punctuation" '
        'aria-hidden="true" '
        'style="'
        'font-family: var(--hero-font-display, var(--sb-display-stack)); '
        'font-size: clamp(8rem, 22vw, 18rem); '
        'font-weight: 900; '
        'line-height: 0.7; '
        'color: var(--brand-signal, #FACC15); '
        'opacity: 0.85; '
        'pointer-events: none; '
        'user-select: none; '
        'letter-spacing: -0.05em;'
        '">'
        f'{glyph}'
        '</div>'
    )


def _render_geometric_stamp(
    brand_vars: Dict[str, str],
    font_id: str,
    content: Optional[Any],
) -> str:
    """Geometric stamp/badge with short text inside. Signal-colored background,
    on-signal text. Composer suggests text via content.accent_stamp_text;
    falls back to a year-style EST.YYYY placeholder."""
    text = "EST. 2026"
    if content is not None:
        custom = getattr(content, "accent_stamp_text", None)
        if isinstance(custom, str) and custom.strip():
            text = custom.strip().upper()[:14]
    return (
        '<div class="sb-accent sb-accent-geometric-stamp" '
        'data-override-target="hero.accent_stamp" '
        'data-override-type="text" '
        'style="'
        'display: inline-flex; '
        'align-items: center; '
        'justify-content: center; '
        'width: 96px; height: 96px; '
        'background: var(--brand-signal, #FACC15); '
        'color: var(--brand-text-on-signal, #09090B); '
        'font-family: var(--hero-font-display, var(--sb-display-stack)); '
        'font-weight: var(--hero-display-weight, 800); '
        'font-size: 0.75rem; '
        'letter-spacing: 0.08em; '
        'text-transform: uppercase; '
        'text-align: center; '
        'line-height: 1.0; '
        'border-radius: 4px; '
        'transform: rotate(-4deg);'
        '">'
        f'{escape(text)}'
        '</div>'
    )


def _render_type_initial(
    brand_vars: Dict[str, str],
    font_id: str,
    content: Optional[Any],
) -> str:
    """First letter of heading at massive scale as graphic background-tier
    element. Distinct from Cathedral's manuscript_drop_cap: this is
    full-bleed graphic, not illuminated in-line."""
    letter = ""
    if content is not None:
        heading = getattr(content, "heading", None)
        letter = _first_letter(heading or "")
    if not letter:
        letter = "A"  # generic fallback for content-less smoke renders
    return (
        '<div class="sb-accent sb-accent-type-initial" '
        'data-override-target="hero.accent_type_initial" '
        'aria-hidden="true" '
        'style="'
        'font-family: var(--hero-font-display, var(--sb-display-stack)); '
        'font-size: clamp(12rem, 32vw, 24rem); '
        'font-weight: 900; '
        'line-height: 0.78; '
        'color: var(--brand-signal, #FACC15); '
        'opacity: 0.18; '
        'pointer-events: none; '
        'user-select: none; '
        'letter-spacing: -0.04em;'
        '">'
        f'{escape(letter)}'
        '</div>'
    )


def _render_code_label(
    brand_vars: Dict[str, str],
    font_id: str,
    content: Optional[Any],
) -> str:
    """Vertical or horizontal monospace code mark (VOL.II / SVC.04 / EST.YYYY).
    Uses --hero-font-code when available (brutalist_geometric) — falls
    back to platform monospace."""
    label = _short_label(content, fallback="VOL.01")
    code_font = _code_font_stack(font_id)
    return (
        '<div class="sb-accent sb-accent-code-label" '
        'data-override-target="hero.accent_code_label" '
        'data-override-type="text" '
        'style="'
        f'font-family: {code_font}; '
        'font-size: 0.75rem; '
        'font-weight: 500; '
        'letter-spacing: 0.18em; '
        'text-transform: uppercase; '
        'color: var(--brand-signal, #FACC15); '
        'line-height: 1.0;'
        '">'
        f'{escape(label)}'
        '</div>'
    )


def _render_color_block_accent(
    brand_vars: Dict[str, str],
    font_id: str,
    content: Optional[Any],
) -> str:
    """Small colored geometric shape (parallelogram block) for visual
    punctuation. CSS-only, no SVG. Uses --brand-signal as a fill with
    --brand-authority as the rim/shadow for depth."""
    return (
        '<div class="sb-accent sb-accent-color-block" '
        'data-override-target="hero.accent_color_block" '
        'data-override-type="color" '
        'aria-hidden="true" '
        'style="'
        'width: 88px; height: 24px; '
        'background: var(--brand-signal, #FACC15); '
        'box-shadow: 6px 6px 0 var(--brand-authority, #DC2626); '
        'transform: skewX(-12deg); '
        'pointer-events: none;'
        '"></div>'
    )


# ─── Registry + dispatch ───────────────────────────────────────────

_ACCENT_REGISTRY: Dict[str, Callable[..., str]] = {
    "oversized_punctuation": _render_oversized_punctuation,
    "geometric_stamp": _render_geometric_stamp,
    "type_initial": _render_type_initial,
    "code_label": _render_code_label,
    "color_block_accent": _render_color_block_accent,
    # no_accent intentionally NOT in registry — short-circuits to empty.
}


# Per-accent natural positioning. Each accent has a default slot inside
# the hero section. Variants apply this style on a wrapping div around
# the accent HTML — keeps variant code one-liner and consistent across
# all 11 variants. Variants that need a non-default position can opt out
# and position the bare accent themselves (rare; not used in Pass 4.0i).
_ACCENT_POSITIONS: Dict[str, str] = {
    "oversized_punctuation":
        "position: absolute; top: 32px; right: 40px; "
        "z-index: 6; pointer-events: none;",
    "geometric_stamp":
        "position: absolute; top: 24px; left: 24px; "
        "z-index: 6;",
    "type_initial":
        "position: absolute; top: 50%; left: 50%; "
        "transform: translate(-50%, -50%); "
        "z-index: 0; pointer-events: none;",
    "code_label":
        "position: absolute; top: 28px; right: 28px; "
        "z-index: 6;",
    "color_block_accent":
        "position: absolute; top: 36px; left: 32px; "
        "z-index: 6;",
}


def accent_position_style(accent_id: str) -> str:
    """Wrapping-div CSS for the accent's natural position inside a hero
    section. Empty string for no_accent / unknown. Variants apply this
    to a div wrapping the render_accent() output.

    Variants must ensure their <section data-section="hero"> has
    `position: relative` (or equivalent positioned ancestor) so absolute
    positioning resolves correctly. All 11 Studio Brut variants already
    do this per Pass 4.0g Phase B.
    """
    if not accent_id or accent_id == "no_accent":
        return ""
    return _ACCENT_POSITIONS.get(accent_id, "")


def render_accent(
    accent_id: str,
    brand_vars: Dict[str, str],
    font_id: str,
    content: Optional[Any] = None,
) -> str:
    """Return accent HTML sub-component. Empty string for no_accent
    or unknown accent_id (graceful — never raises).

    `brand_vars` reserved for future per-accent palette-aware tuning;
    current accents pull brand kit values via var(--brand-*) directly
    so brand_vars is unused. Kept in signature for forward compat.

    `content` is the HeroContent (or any object exposing .heading,
    .eyebrow, .business_label, etc.). Used by type_initial (first
    letter of heading) and code_label (label text derivation).
    """
    if not accent_id or accent_id == "no_accent":
        return ""
    renderer = _ACCENT_REGISTRY.get(accent_id)
    if renderer is None:
        logger.warning(
            "[creative_expression.accent_renderer] unknown accent_id=%r — "
            "rendering empty accent",
            accent_id,
        )
        return ""
    return renderer(brand_vars, font_id, content)


def render_positioned_accent(
    accent_id: str,
    brand_vars: Dict[str, str],
    font_id: str,
    content: Optional[Any] = None,
) -> str:
    """Convenience: render_accent() wrapped in a positioning div per
    _ACCENT_POSITIONS. Empty string when no accent is rendered. Variants
    call this for a one-line accent insertion; bypass via render_accent()
    if a variant needs to override positioning.
    """
    inner = render_accent(accent_id, brand_vars, font_id, content)
    if not inner:
        return ""
    pos = accent_position_style(accent_id)
    return f'<div class="sb-accent-wrap" style="{pos}">{inner}</div>'
