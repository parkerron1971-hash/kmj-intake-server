"""Strand-aware gradient generators.

10 strands → 10 distinct gradient characters that match each strand's
spatial DNA. The dominant strand is parsed from `brief.blendRatio`
(format: "60% Editorial / 40% Luxury") and lowercased to match the IDs
in studio_strands.STYLE_STRANDS.
"""
from __future__ import annotations
import re
from typing import Optional


HERO_SELECTORS = (
    "[data-strand-bg], "
    ".split-hero, "
    ".editorial-hero, "
    ".immersive-section.scene-1, "
    ".showcase-hero, "
    ".statement-hero, "
    ".minimal-hero"
)

CTA_SELECTORS = ".cta-button, [data-cta], button.primary, .btn-primary"


def _gradient_for_strand(strand_id: str, palette: dict) -> str:
    """Return CSS for the given strand. Uses doubled-braces for CSS rules
    so the f-string emits literal { and }.
    """
    bg = palette.get("background", "#0a0a0a")
    bg2 = palette.get("secondary", "#13131a")
    accent = palette.get("accent", "#c9a84c")
    primary = palette.get("primary", accent)

    if strand_id == "luxury":
        # Ceremonial gold radial — light pooling effect, gold in upper-third.
        return f"""
{HERO_SELECTORS} {{
  background-image: radial-gradient(ellipse 70% 60% at 70% 25%, color-mix(in srgb, {accent} 12%, transparent) 0%, transparent 60%),
                    linear-gradient(180deg, {bg} 0%, color-mix(in srgb, {bg2} 80%, {bg}) 100%);
  background-attachment: fixed;
}}
{CTA_SELECTORS} {{
  background-image: linear-gradient(135deg, {accent} 0%, color-mix(in srgb, {accent} 80%, #fff) 100%);
}}
"""

    if strand_id == "dark":
        # Cinematic glow — deep darkness with single light source overhead.
        return f"""
{HERO_SELECTORS} {{
  background-image: radial-gradient(ellipse 60% 80% at 50% 0%, color-mix(in srgb, {accent} 16%, transparent) 0%, transparent 50%),
                    linear-gradient(180deg, {bg} 0%, #000 100%);
}}
{CTA_SELECTORS} {{
  background-image: linear-gradient(135deg, {accent} 0%, color-mix(in srgb, {accent} 60%, #000) 100%);
  box-shadow: 0 0 40px -10px {accent};
}}
"""

    if strand_id == "editorial":
        # Asymmetric type-driven — gradient placed off-center, suggests grid tension.
        return f"""
{HERO_SELECTORS} {{
  background-image: linear-gradient(115deg, {bg} 0%, {bg} 60%, color-mix(in srgb, {accent} 8%, {bg}) 100%);
}}
{CTA_SELECTORS} {{
  background-image: linear-gradient(90deg, {accent} 0%, {accent} 100%);
}}
"""

    if strand_id == "minimal":
        # Almost nothing — single tonal shift, maximum restraint.
        return f"""
{HERO_SELECTORS} {{
  background: linear-gradient(180deg, {bg} 0%, color-mix(in srgb, {bg2} 50%, {bg}) 100%);
}}
{CTA_SELECTORS} {{
  background-image: linear-gradient(90deg, {accent} 0%, {accent} 100%);
}}
"""

    if strand_id == "bold":
        # High-energy color blocking — split palette, fixed background.
        return f"""
{HERO_SELECTORS} {{
  background-image: linear-gradient(135deg, {bg} 0%, {bg} 50%, {accent} 50%, {accent} 100%);
  background-attachment: fixed;
  background-size: 200% 200%;
  background-position: 0% 0%;
}}
{CTA_SELECTORS} {{
  background-image: linear-gradient(45deg, {accent} 0%, color-mix(in srgb, {primary} 70%, {accent}) 100%);
}}
"""

    if strand_id == "organic":
        # Warm earth flow — soft transitions, tactile feel.
        return f"""
{HERO_SELECTORS} {{
  background-image: radial-gradient(ellipse 100% 80% at 30% 80%, color-mix(in srgb, {accent} 14%, transparent) 0%, transparent 70%),
                    radial-gradient(ellipse 80% 60% at 80% 20%, color-mix(in srgb, {primary} 10%, transparent) 0%, transparent 60%),
                    linear-gradient(180deg, {bg} 0%, color-mix(in srgb, {bg2} 60%, {bg}) 100%);
}}
{CTA_SELECTORS} {{
  background-image: linear-gradient(135deg, {accent} 0%, color-mix(in srgb, {accent} 70%, {primary}) 100%);
  border-radius: 8px;
}}
"""

    if strand_id == "retrotech":
        # Terminal scanlines — sharp, technical.
        return f"""
{HERO_SELECTORS} {{
  background-image: linear-gradient(180deg, transparent 0%, transparent 50%, color-mix(in srgb, {accent} 4%, transparent) 50%, color-mix(in srgb, {accent} 4%, transparent) 100%),
                    linear-gradient(180deg, {bg} 0%, {bg} 100%);
  background-size: 100% 4px, 100% 100%;
}}
{CTA_SELECTORS} {{
  background-image: none;
  background: {accent};
  border: 2px solid {accent};
  text-shadow: 0 0 8px {accent};
}}
"""

    if strand_id == "corporate":
        # Authority navy with structured gold accent edge — institutional feel.
        return f"""
{HERO_SELECTORS} {{
  background-image: linear-gradient(180deg, {bg} 0%, color-mix(in srgb, {bg2} 70%, {bg}) 100%),
                    linear-gradient(90deg, transparent 0%, transparent 95%, color-mix(in srgb, {accent} 30%, transparent) 100%);
}}
{CTA_SELECTORS} {{
  background-image: linear-gradient(180deg, {accent} 0%, color-mix(in srgb, {accent} 85%, #000) 100%);
  border: 1px solid color-mix(in srgb, {accent} 60%, #000);
}}
"""

    if strand_id == "playful":
        # Vibrant joy — multiple soft color washes, rounded CTA.
        return f"""
{HERO_SELECTORS} {{
  background-image: radial-gradient(circle at 20% 30%, color-mix(in srgb, {accent} 20%, transparent) 0%, transparent 50%),
                    radial-gradient(circle at 80% 70%, color-mix(in srgb, {primary} 18%, transparent) 0%, transparent 50%),
                    linear-gradient(135deg, {bg} 0%, {bg2} 100%);
}}
{CTA_SELECTORS} {{
  background-image: linear-gradient(135deg, {accent}, {primary});
  border-radius: 24px;
}}
"""

    if strand_id == "brutalist":
        # No gradient — hard contrast only. Brutalism rejects soft transitions.
        return f"""
{HERO_SELECTORS} {{
  background: {bg};
  border-bottom: 4px solid {accent};
}}
{CTA_SELECTORS} {{
  background: {accent};
  border: 3px solid {bg};
  text-transform: uppercase;
  letter-spacing: 0.1em;
}}
"""

    # Default — soft single-color gradient.
    return f"""
{HERO_SELECTORS} {{
  background: linear-gradient(180deg, {bg} 0%, {bg2} 100%);
}}
"""


def render_styles_for_strand(dominant_strand: str, palette: dict) -> str:
    """Wrap the strand-specific gradient CSS in a tagged <style> block."""
    safe_strand = (dominant_strand or "minimal").lower()
    css = _gradient_for_strand(safe_strand, palette or {})
    return (
        f'<style data-pass="3-8e-strand-gradients" '
        f'data-strand="{safe_strand}">{css}</style>'
    )


def parse_dominant_strand(brief: Optional[dict]) -> Optional[str]:
    """Extract the dominant strand id from brief.blendRatio.

    Format: '60% Editorial / 40% Luxury' → 'editorial'.
    Returns None if the brief is missing or unparseable.
    """
    if not brief:
        return None
    ratio = brief.get("blendRatio") or ""
    if not ratio:
        return None
    m = re.match(r"\s*(\d+)%\s+([A-Za-z\-]+)", ratio)
    if m:
        return m.group(2).lower()
    return None


def parse_palette_from_brief(brief: Optional[dict]) -> dict:
    """Extract palette {role: hex} from brief.palette[]."""
    if not brief:
        return {}
    out: dict = {}
    for c in (brief.get("palette") or []):
        if not isinstance(c, dict):
            continue
        role = c.get("role", "")
        hex_val = c.get("hex", "")
        if role and hex_val:
            out[role] = hex_val
    return out
