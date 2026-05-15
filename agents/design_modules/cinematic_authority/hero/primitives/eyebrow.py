"""Eyebrow label primitive — uppercase letter-spaced label above the
heading. Cathedral signature: small caps, signal color, wayfinding.

Treatment sensitivity:
  emphasis_weight=eyebrow_dominant → larger size + bolder weight
  color_emphasis=authority_dominant → eyebrow shifts to text_primary
  spacing_density=compact → tighter bottom margin
"""
from __future__ import annotations

from html import escape

from ..types import Treatments


def render_eyebrow(
    text: str,
    treatments: Treatments,
    target_path: str = "hero.eyebrow",
) -> str:
    """Render the eyebrow label.

    Size scale by emphasis_weight:
      eyebrow_dominant → 15px (visually prominent)
      balanced         → 13px
      heading_dominant → 12px (subordinate to heading)
    """
    size_px = {
        "eyebrow_dominant": "15px",
        "balanced": "13px",
        "heading_dominant": "12px",
    }[treatments.emphasis_weight]
    bottom_margin = {
        "generous": "32px",
        "standard": "24px",
        "compact": "16px",
    }[treatments.spacing_density]
    weight = "800" if treatments.emphasis_weight == "eyebrow_dominant" else "700"

    safe_text = escape(text or "")
    return (
        f'<div class="ca-hero-eyebrow" '
        f'data-override-target="{escape(target_path)}" '
        f'data-override-type="text" '
        f'style="font-size: {size_px}; '
        f'letter-spacing: 0.22em; '
        f'text-transform: uppercase; '
        f'font-weight: {weight}; '
        f'color: var(--eyebrow-color, var(--brand-signal, #C6952F)); '
        f'font-family: var(--ca-sans, system-ui, -apple-system, sans-serif); '
        f'margin-bottom: {bottom_margin}; '
        f'line-height: 1.2;">'
        f"{safe_text}"
        f"</div>"
    )
