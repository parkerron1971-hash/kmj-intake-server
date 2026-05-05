"""Vocabulary-driven decoration system (Pass 3.7).

Consumes studio_data.ACCENT_LIBRARY (dividers, textures, corners) and
renders vocabulary-specific ornaments. The library's `template` strings
already use `{color}` and `{opacity}` placeholders — we use str.format()
to substitute design_system colors at render time.

Where ACCENT_LIBRARY data is sparse (e.g. only one corner style exists),
we extend with vibe-family fallbacks (`soft-glow` for warm vibes,
`thin-line` for formal, `geometric` for bold).

All public functions are wrapped by callers in try/except — decoration
failure must NEVER break a page.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from studio_data import ACCENT_LIBRARY, VOCABULARIES


# ─── Vocabulary → accent character map ──────────────────────────────
#
# Each entry uses styles that ACTUALLY EXIST in ACCENT_LIBRARY.
# Divider styles available: 'ceremonial' | 'cultural-african' |
#   'editorial' | 'structural' | 'botanical' | 'thin-line' (fallback)
# Corner treatments (extended): 'structural' (brackets — from library) |
#   'thin-gold' | 'soft-glow' | 'geometric' | 'none'
# Gradient intensity: 'subtle' | 'medium' | 'dramatic'

_VOCAB_ACCENT_MAP: Dict[str, Dict[str, Any]] = {
    # cultural-identity
    "expressive-vibrancy":   {"divider_style": "cultural-african", "corner_treatment": "geometric",  "gradient_intensity": "dramatic", "drop_cap_style": "decorative"},
    "sovereign-authority":   {"divider_style": "ceremonial",       "corner_treatment": "thin-gold",  "gradient_intensity": "subtle",   "drop_cap_style": "serif-classic"},
    "warm-community":        {"divider_style": "botanical",        "corner_treatment": "soft-glow",  "gradient_intensity": "medium",   "drop_cap_style": "serif-classic"},
    "cultural-fusion":       {"divider_style": "cultural-african", "corner_treatment": "geometric",  "gradient_intensity": "medium",   "drop_cap_style": "decorative"},
    "diaspora-modern":       {"divider_style": "ceremonial",       "corner_treatment": "thin-gold",  "gradient_intensity": "medium",   "drop_cap_style": "serif-classic"},
    "asian-excellence":      {"divider_style": "editorial",        "corner_treatment": "thin-gold",  "gradient_intensity": "subtle",   "drop_cap_style": "serif-classic"},
    "indigenous-earth":      {"divider_style": "botanical",        "corner_treatment": "soft-glow",  "gradient_intensity": "medium",   "drop_cap_style": "serif-classic"},
    "universal-premium":     {"divider_style": "editorial",        "corner_treatment": "thin-gold",  "gradient_intensity": "subtle",   "drop_cap_style": "serif-classic"},

    # community-movement
    "faith-ministry":        {"divider_style": "ceremonial",       "corner_treatment": "soft-glow",  "gradient_intensity": "medium",   "drop_cap_style": "serif-classic"},
    "wellness-healing":      {"divider_style": "botanical",        "corner_treatment": "soft-glow",  "gradient_intensity": "medium",   "drop_cap_style": "serif-classic"},
    "creative-artist":       {"divider_style": "editorial",        "corner_treatment": "structural", "gradient_intensity": "medium",   "drop_cap_style": "decorative"},
    "activist-advocate":     {"divider_style": "structural",       "corner_treatment": "structural", "gradient_intensity": "dramatic", "drop_cap_style": "sans-bold"},
    "scholar-educator":      {"divider_style": "editorial",        "corner_treatment": "thin-gold",  "gradient_intensity": "subtle",   "drop_cap_style": "serif-classic"},
    "street-culture":        {"divider_style": "structural",       "corner_treatment": "structural", "gradient_intensity": "dramatic", "drop_cap_style": "sans-bold"},

    # life-stage
    "rising-entrepreneur":   {"divider_style": "editorial",        "corner_treatment": "none",       "gradient_intensity": "medium",   "drop_cap_style": "none"},
    "established-authority": {"divider_style": "ceremonial",       "corner_treatment": "thin-gold",  "gradient_intensity": "subtle",   "drop_cap_style": "serif-classic"},
    "reinvention":           {"divider_style": "structural",       "corner_treatment": "geometric",  "gradient_intensity": "dramatic", "drop_cap_style": "sans-bold"},
    "legacy-builder":        {"divider_style": "ceremonial",       "corner_treatment": "thin-gold",  "gradient_intensity": "subtle",   "drop_cap_style": "serif-classic"},

    # aesthetic-movement
    "maximalist":            {"divider_style": "cultural-african", "corner_treatment": "geometric",  "gradient_intensity": "dramatic", "drop_cap_style": "decorative"},
    "minimalist":            {"divider_style": "editorial",        "corner_treatment": "none",       "gradient_intensity": "subtle",   "drop_cap_style": "none"},
    "editorial":             {"divider_style": "editorial",        "corner_treatment": "none",       "gradient_intensity": "subtle",   "drop_cap_style": "serif-classic"},
    "organic-natural":       {"divider_style": "botanical",        "corner_treatment": "soft-glow",  "gradient_intensity": "medium",   "drop_cap_style": "serif-classic"},
    "futurist-tech":         {"divider_style": "structural",       "corner_treatment": "geometric",  "gradient_intensity": "dramatic", "drop_cap_style": "sans-bold"},
}


_DEFAULT_ACCENT_SET: Dict[str, Any] = {
    "divider_style": "thin-line",
    "corner_treatment": "none",
    "gradient_intensity": "subtle",
    "drop_cap_style": "none",
}


def get_vocab_accent_set(vocab_id: Optional[str]) -> Dict[str, Any]:
    """Return decoration character for a vocabulary. Always returns a
    valid dict — falls back to defaults if vocab_id is unknown."""
    if not vocab_id:
        return dict(_DEFAULT_ACCENT_SET)
    return dict(_VOCAB_ACCENT_MAP.get(vocab_id, _DEFAULT_ACCENT_SET))


# ─── Section dividers ───────────────────────────────────────────────


def _format_template(template: str, color: str, opacity: float) -> str:
    """Substitute {color} and {opacity} placeholders in an ACCENT_LIBRARY
    template. Defensive against missing placeholders."""
    try:
        return template.replace("{color}", color).replace("{opacity}", f"{opacity:.2f}")
    except Exception:
        return ""


def render_section_divider(
    vocab_id: Optional[str],
    design_system: Dict[str, Any],
    width: str = "100%",
) -> str:
    """Render a vocabulary-specific divider. Tries to use the actual
    ACCENT_LIBRARY template for the chosen style; falls back to inline
    HTML when the library doesn't have an entry.
    """
    accent_set = get_vocab_accent_set(vocab_id)
    style = accent_set["divider_style"]
    accent = design_system.get("palette_accent") or "#999"
    text = design_system.get("palette_text") or "#222"

    library = ACCENT_LIBRARY.get("dividers", {})
    entries = library.get(style)

    if entries:
        # Use the first (and currently only) template for this style
        template = entries[0].get("template", "")
        rendered = _format_template(template, accent, 0.65)
        if rendered:
            return f'<div class="reveal heavy-decoration" style="max-width:1100px;margin:0 auto;padding:0 24px;">{rendered}</div>'

    # Fallback: simple thin line — also used for `thin-line` style
    return (
        f'<div class="reveal" style="display:flex;justify-content:center;margin:48px auto;">'
        f'<div style="width:80px;height:1px;background:color-mix(in srgb,{text} 18%,transparent);"></div>'
        f'</div>'
    )


# ─── Decorative corners ─────────────────────────────────────────────


def render_decorative_corners(
    vocab_id: Optional[str],
    design_system: Dict[str, Any],
) -> str:
    """Return HTML to drop inside a position:relative container. Renders
    decorative corner ornaments per the vocabulary's accent set.

    Returns empty string for `corner_treatment: 'none'`.
    """
    accent_set = get_vocab_accent_set(vocab_id)
    treatment = accent_set["corner_treatment"]
    accent = design_system.get("palette_accent") or "#999"

    if treatment == "none":
        return ""

    if treatment == "structural":
        # Use the actual ACCENT_LIBRARY structural bracket template
        library = ACCENT_LIBRARY.get("corners", {}).get("structural") or []
        if library:
            return _format_template(library[0].get("template", ""), accent, 0.65)
        return ""

    if treatment == "thin-gold":
        return (
            f'<div class="heavy-decoration" style="position:absolute;inset:0;pointer-events:none;">'
            f'<div style="position:absolute;top:24px;left:24px;width:32px;height:32px;border-top:2px solid {accent};border-left:2px solid {accent};opacity:0.6;"></div>'
            f'<div style="position:absolute;top:24px;right:24px;width:32px;height:32px;border-top:2px solid {accent};border-right:2px solid {accent};opacity:0.6;"></div>'
            f'<div style="position:absolute;bottom:24px;left:24px;width:32px;height:32px;border-bottom:2px solid {accent};border-left:2px solid {accent};opacity:0.6;"></div>'
            f'<div style="position:absolute;bottom:24px;right:24px;width:32px;height:32px;border-bottom:2px solid {accent};border-right:2px solid {accent};opacity:0.6;"></div>'
            f'</div>'
        )

    if treatment == "soft-glow":
        return (
            f'<div class="heavy-decoration" style="position:absolute;inset:0;pointer-events:none;overflow:hidden;">'
            f'<div style="position:absolute;top:-100px;left:-100px;width:400px;height:400px;background:radial-gradient(circle,color-mix(in srgb,{accent} 22%,transparent) 0%,transparent 65%);"></div>'
            f'<div style="position:absolute;bottom:-100px;right:-100px;width:400px;height:400px;background:radial-gradient(circle,color-mix(in srgb,{accent} 18%,transparent) 0%,transparent 65%);"></div>'
            f'</div>'
        )

    if treatment == "geometric":
        return (
            f'<div class="heavy-decoration" style="position:absolute;inset:0;pointer-events:none;">'
            f'<div style="position:absolute;top:48px;left:48px;width:48px;height:48px;border:3px solid {accent};opacity:0.7;"></div>'
            f'<div style="position:absolute;top:48px;right:48px;width:48px;height:48px;background:{accent};opacity:0.7;"></div>'
            f'<div style="position:absolute;bottom:48px;left:48px;width:48px;height:48px;background:{accent};opacity:0.4;transform:rotate(45deg);"></div>'
            f'</div>'
        )

    return ""


# ─── Gradient generators ────────────────────────────────────────────


def get_gradient_for_section(
    vocab_id: Optional[str],
    design_system: Dict[str, Any],
    position: str = "hero",
) -> str:
    """Return a CSS gradient string for a section position.
    position: 'hero' | 'section' | 'card' | 'cta' | 'footer'.

    Intensity follows the vocabulary's accent set:
      subtle  → 8% accent overlay
      medium  → 18%
      dramatic → 35%
    """
    accent_set = get_vocab_accent_set(vocab_id)
    intensity = accent_set["gradient_intensity"]

    primary = design_system.get("palette_bg") or "#fff"
    accent = design_system.get("palette_accent") or "#999"
    surface = design_system.get("palette_surface") or primary

    intensity_map = {
        "subtle":   {"start": 8,  "end": 0},
        "medium":   {"start": 18, "end": 4},
        "dramatic": {"start": 35, "end": 8},
    }
    o = intensity_map.get(intensity, intensity_map["subtle"])

    if position == "hero":
        return (
            f"linear-gradient(135deg, "
            f"color-mix(in srgb,{accent} {o['start']}%,{primary}) 0%, "
            f"{primary} 60%, "
            f"color-mix(in srgb,{surface} {o['end'] + 6}%,{primary}) 100%)"
        )

    if position == "section":
        return (
            f"linear-gradient(180deg, {primary} 0%, "
            f"color-mix(in srgb,{surface} {max(o['start'] - 4, 4)}%,{primary}) 100%)"
        )

    if position == "card":
        return (
            f"linear-gradient(180deg, {surface} 0%, "
            f"color-mix(in srgb,{accent} {o['end'] + 3}%,{surface}) 100%)"
        )

    if position == "cta":
        return (
            f"linear-gradient(135deg, {accent} 0%, "
            f"color-mix(in srgb,{primary} 22%,{accent}) 100%)"
        )

    if position == "footer":
        return f"color-mix(in srgb,{accent} 4%,{primary})"

    return primary


# ─── Slot dispatcher ────────────────────────────────────────────────


def render_decoration_for(
    vocab_id: Optional[str],
    design_system: Dict[str, Any],
    slot: str,
) -> str:
    """Generic dispatcher used by layouts.
    slot: 'hero_decoration' | 'section_break' | 'footer_ornament'.
    Always returns a string (empty when nothing applies).
    """
    try:
        if slot == "hero_decoration":
            return render_decorative_corners(vocab_id, design_system)
        if slot == "section_break":
            return render_section_divider(vocab_id, design_system)
        if slot == "footer_ornament":
            return render_section_divider(vocab_id, design_system, width="40%")
    except Exception:
        return ""
    return ""
