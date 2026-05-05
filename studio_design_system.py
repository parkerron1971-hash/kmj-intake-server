"""Studio Design System Builder: composite direction → CSS tokens + component CSS.

Pure functions. Adapted from src/lib/designSystemBuilder.ts.

The TS source consumes a `DesignBrief` (Studio's brief schema). Smart Sites
has the canonical brand bundle and the CompositeDirection from
studio_composite. This module bridges: takes a CompositeDirection +
business name and produces the same DesignSystem shape (palette, fonts,
strand-aware nav/card/cta CSS).

Strand-specific card and CTA rules are ported verbatim from the TS source's
cardRules / ctaRules tables.
"""
from __future__ import annotations

from typing import Dict, Optional, TypedDict

from studio_composite import CompositeDirection, hex_to_hsl
from studio_data import STYLE_STRANDS, FontPairing


# ─── CONTRAST HELPERS (Session 2 patch) ───────────────────────────────


def _yiq_luminance(hex_color: str) -> float:
    """Perceived brightness via YIQ luminance (0-255).

    HSL lightness underrepresents perceived brightness for warm colors —
    pure yellow has HSL L=50% but YIQ ~226 (very bright). YIQ is the
    standard cheap approximation for "would dark text or light text be
    more readable on this background." Threshold at ~128.
    """
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return 128.0  # neutral fallback
    try:
        r = int(h[0:2], 16)
        g = int(h[2:4], 16)
        b = int(h[4:6], 16)
    except ValueError:
        return 128.0
    return (r * 299 + g * 587 + b * 114) / 1000


def _pick_contrast_text(
    bg_hex: str,
    dark_color: str = "#1A1A1A",
    light_color: str = "#F8F8F8",
) -> str:
    """Return dark or light text color based on perceived background brightness."""
    return dark_color if _yiq_luminance(bg_hex) >= 128 else light_color


def _pick_accent_contrast(accent_hex: str) -> str:
    """When the accent color becomes a button/element background, pick
    text color that contrasts. Yellows/golds (perceptually bright) get
    dark text; deep accents get light text."""
    return "#1A1A1A" if _yiq_luminance(accent_hex) >= 128 else "#FFFFFF"


class DesignSystem(TypedDict):
    business_name: str
    concept_name: Optional[str]
    tagline: Optional[str]
    copy_voice: str
    tension_statement: Optional[str]
    palette_bg: str
    palette_accent: str
    palette_text: str
    palette_surface: str
    palette_muted: str
    palette_cta: str
    font_display: str
    font_body: str
    font_accent: str
    google_fonts_url: str
    dominant_strand: str
    recessive_strand: str
    spatial_dna: str
    animation_character: str
    nav_css: str
    card_css: str
    cta_css: str
    typography_css: str
    reveal_css: str


# ─── VOCAB → STRAND MAPPING ───────────────────────────────────────────
# Maps each of the 23 vocabularies to one of the 10 STYLE_STRANDS so the
# strand-specific card/CTA rules can be selected. Built by hand from the
# vocabulary's color_philosophy + typography_direction signals.

VOCAB_TO_STRAND: Dict[str, str] = {
    # cultural-identity
    "expressive-vibrancy": "bold",
    "sovereign-authority": "luxury",
    "warm-community": "organic",
    "cultural-fusion": "editorial",
    "diaspora-modern": "luxury",
    "asian-excellence": "minimal",
    "indigenous-earth": "organic",
    "universal-premium": "luxury",
    # community-movement
    "faith-ministry": "luxury",
    "wellness-healing": "organic",
    "creative-artist": "editorial",
    "activist-advocate": "bold",
    "scholar-educator": "corporate",
    "street-culture": "dark",
    # life-stage
    "rising-entrepreneur": "playful",
    "established-authority": "corporate",
    "reinvention": "bold",
    "legacy-builder": "luxury",
    # aesthetic-movement
    "maximalist": "bold",
    "minimalist": "minimal",
    "editorial": "editorial",
    "organic-natural": "organic",
    "futurist-tech": "retrotech",
}


# ─── STRAND CARD CSS — port from designSystemBuilder.ts:cardRules ─────


def _strand_card_css(strand: str, accent: str, text_color: str, surface: str, muted: str) -> str:
    """Port of designSystemBuilder.ts cardRules table.

    Pass 3.5 Session 2 patch: rules whose card background is the surface
    color (organic/corporate/playful) now explicitly set a contrast-aware
    text color. Without this, dark text on dark surfaces (or light text
    on light surfaces) was unreadable when the page background and the
    surface color disagreed on lightness.
    """
    surface_text = _pick_contrast_text(surface, dark_color=text_color)
    rules = {
        "luxury": f".card {{ border: none; border-bottom: 0.5px solid {muted}; padding: 2rem 0; }}",
        "brutalist": f".card {{ border: 2px solid {text_color}; border-radius: 0; padding: 1.5rem; }}",
        "editorial": f".card {{ padding: 1.5rem 0; border-bottom: 1px solid {muted}20; }}",
        "minimal": f".card {{ border-bottom: 1px solid {muted}10; padding: 2rem 0; }}",
        "dark": f".card {{ background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; padding: 1.5rem; color: {_pick_contrast_text(surface, dark_color=text_color)}; }}",
        "organic": f".card {{ border-radius: 20px; padding: 1.5rem; background: {surface}; color: {surface_text}; }}",
        "bold": f".card {{ border-left: 6px solid {accent}; padding: 1.5rem; }}",
        "retrotech": f".card {{ border: 1px solid {accent}40; border-radius: 0; padding: 1rem; }}",
        "corporate": f".card {{ background: {surface}; border: 1px solid rgba(255,255,255,0.1); padding: 1.5rem; border-radius: 4px; color: {surface_text}; }}",
        "playful": f".card {{ border-radius: 20px; padding: 1.5rem; background: {surface}; color: {surface_text}; transition: all 0.3s; }} .card:hover {{ transform: translateY(-4px); }}",
    }
    return rules.get(strand, rules["dark"])


# ─── STRAND CTA CSS — port from designSystemBuilder.ts:ctaRules ───────


def _strand_cta_css(strand: str, cta_color: str, bg: str, text_color: str, muted: str) -> str:
    """Port of designSystemBuilder.ts ctaRules table.

    Pass 3.5 Session 2 patch: every rule whose CTA background is the
    accent/cta color (luxury/dark/organic/bold/corporate/playful) now
    picks text color via _pick_accent_contrast(cta_color) instead of
    using the page bg. The TS source assumed dark page backgrounds; on
    light vocabularies (e.g., scholar-educator + ETS), the old rules
    produced near-white text on yellow accents — unreadable.
    """
    on_accent = _pick_accent_contrast(cta_color)
    rules = {
        "luxury": f".cta-btn {{ border-radius: 0; font-size: 11px; letter-spacing: 0.18em; text-transform: uppercase; padding: 16px 40px; background: {cta_color}; color: {on_accent}; text-decoration: none; display: inline-block; }}",
        "brutalist": f".cta-btn {{ border: 3px solid {text_color}; background: transparent; color: {text_color}; padding: 12px 32px; border-radius: 0; font-weight: 700; text-decoration: none; display: inline-block; }}",
        "editorial": f".cta-btn {{ background: none; color: {text_color}; border: none; border-bottom: 1px solid {text_color}; padding: 8px 0; text-decoration: none; display: inline-block; }}",
        "minimal": f".cta-btn {{ background: none; color: {text_color}; border-bottom: 1px solid {muted}; padding: 8px 2px; text-decoration: none; display: inline-block; }}",
        "dark": f".cta-btn {{ background: {cta_color}; color: {on_accent}; border-radius: 4px; padding: 12px 32px; text-decoration: none; display: inline-block; }}",
        "organic": f".cta-btn {{ border-radius: 100px; background: {cta_color}; color: {on_accent}; padding: 14px 36px; text-decoration: none; display: inline-block; }}",
        "bold": f".cta-btn {{ font-weight: 900; text-transform: uppercase; background: {cta_color}; color: {on_accent}; padding: 16px 48px; border-radius: 4px; text-decoration: none; display: inline-block; }}",
        "retrotech": f".cta-btn {{ background: transparent; border: 1px solid {cta_color}; color: {cta_color}; padding: 10px 24px; border-radius: 0; text-decoration: none; display: inline-block; }}",
        "corporate": f".cta-btn {{ background: {cta_color}; color: {on_accent}; padding: 12px 32px; border-radius: 0; text-decoration: none; display: inline-block; }}",
        "playful": f".cta-btn {{ border-radius: 100px; font-weight: 800; background: {cta_color}; color: {on_accent}; padding: 14px 36px; text-decoration: none; display: inline-block; }}",
    }
    return rules.get(strand, rules["dark"])


# ─── NAV / TYPOGRAPHY / REVEAL CSS — port from designSystemBuilder.ts ─


def _hex_to_rgb_triple(hex_color: str) -> str:
    """Port of designSystemBuilder.ts:hexToRgb. Returns 'r,g,b' string."""
    h = hex_color.lstrip("#")
    try:
        r = int(h[0:2], 16)
        g = int(h[2:4], 16)
        b = int(h[4:6], 16)
    except (ValueError, IndexError):
        r = g = b = 0
    return f"{r},{g},{b}"


def _generate_nav_css(bg: str, accent: str, text_color: str, cta_color: str,
                       f_display: str, f_accent: str) -> str:
    rgb = _hex_to_rgb_triple(bg)
    return (
        f"nav {{ position: fixed; top: 0; left: 0; right: 0; z-index: 100; "
        f"display: flex; align-items: center; justify-content: space-between; "
        f"padding: 1.1rem 2.5rem; background: rgba({rgb}, 0.92); "
        f"backdrop-filter: blur(12px); border-bottom: 1px solid rgba(255,255,255,0.07); }}\n"
        f".nav-logo {{ font-family: '{f_display}', serif; font-size: 1.2rem; "
        f"font-weight: 700; color: {accent}; text-decoration: none; }}\n"
        f".nav-link {{ font-family: '{f_accent}', monospace; font-size: 0.65rem; "
        f"letter-spacing: 0.15em; text-transform: uppercase; color: {text_color}; "
        f"text-decoration: none; opacity: 0.6; transition: opacity 0.2s, color 0.2s; }}\n"
        f".nav-link:hover {{ opacity: 1; color: {accent}; }}\n"
        f".nav-cta {{ font-family: '{f_accent}', monospace; font-size: 0.65rem; "
        f"font-weight: 700; letter-spacing: 0.15em; text-transform: uppercase; "
        f"background: {cta_color}; color: {bg}; padding: 0.55rem 1.25rem; "
        f"text-decoration: none; display: inline-block; }}"
    )


def _generate_typography_css(bg: str, accent: str, text_color: str,
                              f_display: str, f_body: str, f_accent: str) -> str:
    return (
        f"h1, h2, h3 {{ font-family: '{f_display}', serif; color: {text_color}; }}\n"
        f"body {{ font-family: '{f_body}', sans-serif; color: {text_color}; background: {bg}; }}\n"
        f".label {{ font-family: '{f_accent}', monospace; font-size: 0.62rem; "
        f"letter-spacing: 0.22em; text-transform: uppercase; color: {accent}; }}\n"
        f"p {{ line-height: 1.8; }}"
    )


_REVEAL_CSS = (
    ".reveal { opacity: 0; transform: translateY(24px); "
    "transition: opacity 0.7s ease, transform 0.7s ease; }\n"
    ".reveal.visible { opacity: 1; transform: none; }"
)


# ─── BUILD DESIGN SYSTEM ──────────────────────────────────────────────


def build_design_system(
    composite: CompositeDirection,
    business_name: str,
    tagline: Optional[str] = None,
    concept_name: Optional[str] = None,
) -> DesignSystem:
    """Compose a DesignSystem from a CompositeDirection + business metadata.

    Adapted from designSystemBuilder.ts:buildDesignSystem. The TS version
    consumes a DesignBrief; we consume the upstream CompositeDirection
    directly. Strand-specific card and CTA rules come from the same tables
    as the TS source.
    """
    palette = composite["blended_color_system"]
    bg = palette["background"]
    accent = palette["accent"]
    text_color = palette["text"]
    surface = palette["secondary"]
    muted = text_color + "60"
    cta_color = accent

    pairing = composite.get("selected_font_pairing")
    if pairing:
        f_display = pairing["heading_font"]
        f_body = pairing["body_font"]
        google_fonts_url = pairing["google_fonts_url"]
    else:
        f_display = "Georgia"
        f_body = "Inter"
        google_fonts_url = "https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap"
    f_accent = "monospace"

    primary = composite["primary_vocabulary"]
    primary_id = primary["id"]
    dominant = VOCAB_TO_STRAND.get(primary_id, "dark")

    aesthetic = composite.get("aesthetic_vocabulary")
    secondary_vocab = composite.get("secondary_vocabulary")
    if aesthetic:
        recessive = VOCAB_TO_STRAND.get(aesthetic["id"], dominant)
    elif secondary_vocab:
        recessive = VOCAB_TO_STRAND.get(secondary_vocab["id"], dominant)
    else:
        recessive = dominant

    strand_data = STYLE_STRANDS.get(dominant)
    spatial_dna = strand_data["spatial_dna"] if strand_data else ""

    # Animation character from vocab energy
    animation_character = primary["energy"]

    nav_css = _generate_nav_css(bg, accent, text_color, cta_color, f_display, f_accent)
    card_css = _strand_card_css(dominant, accent, text_color, surface, muted)
    cta_css = _strand_cta_css(dominant, cta_color, bg, text_color, muted)
    typography_css = _generate_typography_css(bg, accent, text_color, f_display, f_body, f_accent)

    return DesignSystem(
        business_name=business_name,
        concept_name=concept_name,
        tagline=tagline,
        copy_voice=composite["blended_energy"],
        tension_statement=None,
        palette_bg=bg,
        palette_accent=accent,
        palette_text=text_color,
        palette_surface=surface,
        palette_muted=muted,
        palette_cta=cta_color,
        font_display=f_display,
        font_body=f_body,
        font_accent=f_accent,
        google_fonts_url=google_fonts_url,
        dominant_strand=dominant,
        recessive_strand=recessive,
        spatial_dna=spatial_dna,
        animation_character=animation_character,
        nav_css=nav_css,
        card_css=card_css,
        cta_css=cta_css,
        typography_css=typography_css,
        reveal_css=_REVEAL_CSS,
    )


def get_reveal_script() -> str:
    """Port of designSystemBuilder.ts:getRevealScript."""
    return (
        "<script>\n"
        "var obs = new IntersectionObserver(function(entries) {\n"
        "  entries.forEach(function(e) {\n"
        "    if (e.isIntersecting) { e.target.classList.add('visible'); obs.unobserve(e.target); }\n"
        "  });\n"
        "}, { threshold: 0.1 });\n"
        "document.querySelectorAll('.reveal').forEach(function(el) { obs.observe(el); });\n"
        "</script>"
    )
