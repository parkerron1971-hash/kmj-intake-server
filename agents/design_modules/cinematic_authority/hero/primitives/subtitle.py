"""Subtitle primitive — supporting line beneath the heading. Cathedral
signature: lighter weight, muted color, generous line height.

Treatment sensitivity:
  emphasis_weight=balanced         → larger size (22-26px), more presence
  emphasis_weight=heading_dominant → smaller (18-20px), subordinate
  emphasis_weight=eyebrow_dominant → small (16-18px), unobtrusive
  spacing_density=generous         → wider max-width, larger bottom margin

Phase 2.6 depth dimension:
  typography=playful → subtitle picks up italic (--ca-subtitle-italic)
  typography=refined → lighter weight (--ca-subtitle-weight: 300)
  typography=bold    → slightly heavier weight (--ca-subtitle-weight: 500)
"""
from __future__ import annotations

from html import escape

from ..types import Treatments


def render_subtitle(
    text: str,
    treatments: Treatments,
    target_path: str = "hero.subtitle",
) -> str:
    """Render the subtitle line beneath the heading."""
    size_clamp = {
        "heading_dominant": "clamp(1.125rem, 1.6vw, 1.25rem)",
        "balanced": "clamp(1.25rem, 2vw, 1.6rem)",
        "eyebrow_dominant": "clamp(1rem, 1.4vw, 1.125rem)",
    }[treatments.emphasis_weight]
    bottom_margin = {
        "generous": "40px",
        "standard": "32px",
        "compact": "24px",
    }[treatments.spacing_density]
    max_width = {
        "generous": "640px",
        "standard": "560px",
        "compact": "480px",
    }[treatments.spacing_density]

    safe_text = escape(text or "")
    return (
        f'<p class="ca-hero-subtitle" '
        f'data-override-target="{escape(target_path)}" '
        f'data-override-type="text" '
        f'style="font-size: {size_clamp}; '
        f'line-height: 1.55; '
        f'font-weight: var(--ca-subtitle-weight, 400); '
        f'font-style: var(--ca-subtitle-italic, normal); '
        f'color: var(--subtitle-color, var(--brand-text-primary, #0F172A)); '
        f'opacity: 0.78; '
        f'font-family: var(--ca-sans, system-ui, -apple-system, sans-serif); '
        f'max-width: {max_width}; '
        f'margin: 0 0 {bottom_margin} 0;">'
        f"{safe_text}"
        f"</p>"
    )
