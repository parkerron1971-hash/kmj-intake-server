"""Heading primitive — large display serif with one italic emphasis
word in the brand signal color. Cathedral signature: heavy weight,
tight letter-spacing, one italic accent.

Treatment sensitivity:
  emphasis_weight=heading_dominant → clamp(48-96px) display scale
  emphasis_weight=balanced         → clamp(40-64px)
  emphasis_weight=eyebrow_dominant → clamp(36-56px), heading subordinate
  color_emphasis=authority_dominant → heading in brand authority color
  color_emphasis=signal_dominant   → heading in text primary
  color_emphasis=dual_emphasis     → heading in authority, both anchor
"""
from __future__ import annotations

from html import escape

from ..types import Treatments


def _split_emphasis(heading: str, emphasis: str) -> tuple[str, str, str]:
    """Split heading into (before, emphasis_match, after) on the first
    occurrence of emphasis. If emphasis isn't a substring, fall back
    to wrapping the first whitespace-delimited word so the italic
    treatment still applies somewhere — never silently lose the
    italic accent that's a Cathedral signature."""
    if not emphasis or emphasis not in heading:
        # Fallback: italicize the first word so the signature still appears
        parts = heading.split(maxsplit=1)
        if len(parts) == 2:
            first, rest = parts
            return ("", first, " " + rest)
        return ("", heading, "")
    idx = heading.find(emphasis)
    return (heading[:idx], emphasis, heading[idx + len(emphasis):])


def render_heading(
    heading: str,
    heading_emphasis: str,
    treatments: Treatments,
    heading_target_path: str = "hero.heading",
    emphasis_target_path: str = "hero.heading_emphasis",
) -> str:
    """Render <h1> with italic-signal-color emphasis span inside."""
    size_clamp = {
        "heading_dominant": "clamp(3rem, 8vw, 6rem)",
        "balanced": "clamp(2.5rem, 6vw, 4rem)",
        "eyebrow_dominant": "clamp(2.25rem, 5vw, 3.5rem)",
    }[treatments.emphasis_weight]
    bottom_margin = {
        "generous": "32px",
        "standard": "24px",
        "compact": "16px",
    }[treatments.spacing_density]

    before, emphasis_text, after = _split_emphasis(heading, heading_emphasis)
    safe_before = escape(before)
    safe_emphasis = escape(emphasis_text)
    safe_after = escape(after)

    emphasis_span = (
        f'<em class="ca-hero-heading-emphasis" '
        f'data-override-target="{escape(emphasis_target_path)}" '
        f'data-override-type="text" '
        f'style="font-style: italic; '
        f'color: var(--emphasis-color, var(--brand-signal, #C6952F)); '
        f'font-weight: 700;">'
        f"{safe_emphasis}"
        f"</em>"
    )

    return (
        f'<h1 class="ca-hero-heading" '
        f'data-override-target="{escape(heading_target_path)}" '
        f'data-override-type="text" '
        f'style="font-size: {size_clamp}; '
        f'font-weight: 900; '
        f'line-height: 1.05; '
        f'letter-spacing: -0.025em; '
        f'color: var(--heading-color, var(--brand-text-primary, #0F172A)); '
        f'font-family: var(--ca-serif, Georgia, \'Times New Roman\', serif); '
        f'margin: 0 0 {bottom_margin} 0;">'
        f"{safe_before}{emphasis_span}{safe_after}"
        f"</h1>"
    )
