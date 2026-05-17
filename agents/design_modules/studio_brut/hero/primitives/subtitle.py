"""Studio Brut subtitle — punchier than Cathedral's. Tighter line
length (Studio Brut subtitles are 6-12 words typical, not 12-20).
Slightly heavier baseline weight (500 not 400).

Treatment sensitivity:
  emphasis_weight=balanced         → larger size for two-thought
                                     hero patterns
  spacing_density=generous         → moderate max-width (still
                                     denser than Cathedral's generous)
  typography=playful               → italic permitted on subtitle
  typography=refined               → weight 400 (lighter than baseline)
"""
from __future__ import annotations

from html import escape

from ..types import Treatments


def render_subtitle(
    text: str,
    treatments: Treatments,
    target_path: str = "hero.subtitle",
) -> str:
    """Render the subtitle line."""
    size_clamp = {
        "heading_dominant": "clamp(1rem, 1.4vw, 1.125rem)",
        "balanced":         "clamp(1.125rem, 1.7vw, 1.375rem)",
        "eyebrow_dominant": "clamp(0.95rem, 1.3vw, 1.05rem)",
    }[treatments.emphasis_weight]
    bottom_margin = {
        "generous": "32px",
        "standard": "24px",
        "compact":  "16px",
    }[treatments.spacing_density]
    # Studio Brut max-widths run tighter than Cathedral's — denser
    # typographic columns.
    max_width = {
        "generous": "520px",
        "standard": "460px",
        "compact":  "400px",
    }[treatments.spacing_density]

    safe_text = escape(text or "")
    return (
        f'<p class="sb-hero-subtitle" '
        f'data-override-target="{escape(target_path)}" '
        f'data-override-type="text" '
        f'style="font-size: {size_clamp}; '
        f'line-height: 1.45; '
        f'font-weight: var(--sb-subtitle-weight, 500); '
        f'font-style: var(--sb-subtitle-italic, normal); '
        f'color: var(--sb-subtitle-color, var(--brand-text-primary, #09090B)); '
        f'opacity: 0.88; '
        f'font-family: var(--sb-sans-stack, "Inter", "Space Grotesk", '
        f'system-ui, -apple-system, sans-serif); '
        f'max-width: {max_width}; '
        f'margin: 0 0 {bottom_margin} 0;">'
        f"{safe_text}"
        f"</p>"
    )
