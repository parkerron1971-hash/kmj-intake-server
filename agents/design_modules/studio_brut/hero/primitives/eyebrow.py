"""Studio Brut eyebrow — uppercase letter-spaced label like Cathedral
in shape, but Studio Brut interprets weight and tracking more
aggressively. Eyebrows in Studio Brut frequently double as codes
("CASE 23", "VOL. II", "EST. 2024") — see type_ornament.render_code_label
for the codified variant.

Treatment sensitivity:
  emphasis_weight=eyebrow_dominant → 16px (larger than Cathedral's 15)
                                     + weight 800 for graphic-poster weight
  typography=bold     → tighter tracking 0.18em (vs default 0.22em)
  typography=refined  → looser tracking 0.30em + lighter weight 500
  typography=playful  → loosest tracking 0.36em + medium weight 600
                        + slight italic permitted on eyebrow only
"""
from __future__ import annotations

from html import escape

from ..types import Treatments


def render_eyebrow(
    text: str,
    treatments: Treatments,
    target_path: str = "hero.eyebrow",
) -> str:
    """Render the eyebrow label."""
    size_px = {
        "eyebrow_dominant": "16px",
        "balanced":         "13px",
        "heading_dominant": "12px",
    }[treatments.emphasis_weight]
    bottom_margin = {
        "generous": "28px",
        "standard": "20px",
        "compact":  "14px",
    }[treatments.spacing_density]

    safe_text = escape(text or "")
    return (
        f'<div class="sb-hero-eyebrow" '
        f'data-override-target="{escape(target_path)}" '
        f'data-override-type="text" '
        f'style="font-size: {size_px}; '
        f'letter-spacing: var(--sb-eyebrow-tracking, 0.22em); '
        f'text-transform: uppercase; '
        f'font-weight: var(--sb-eyebrow-weight, 800); '
        f'font-style: var(--sb-eyebrow-style, normal); '
        f'color: var(--sb-eyebrow-color, var(--brand-signal, #FACC15)); '
        f'font-family: var(--sb-sans-stack, "Inter", "Space Grotesk", '
        f'system-ui, -apple-system, sans-serif); '
        f'margin-bottom: {bottom_margin}; '
        f'line-height: 1.1;">'
        f"{safe_text}"
        f"</div>"
    )
