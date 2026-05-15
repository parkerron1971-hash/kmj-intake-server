"""CTA button primitive — pill-shaped, brand-signal background, large
weight type. Cathedral signature: 999px border radius, color from the
active color_emphasis treatment, letter-spaced label.

Treatment sensitivity:
  color_emphasis controls bg + text color via --cta-bg / --cta-text vars
  spacing_density adjusts vertical padding
"""
from __future__ import annotations

from html import escape

from ..types import Treatments


def render_cta_button(
    text: str,
    target: str,
    treatments: Treatments,
    target_path: str = "hero.cta_primary",
) -> str:
    """Render the primary CTA button. `target` is the href value
    (anchor like #book, mailto:, or absolute URL)."""
    padding_v = {
        "generous": "16px",
        "standard": "14px",
        "compact": "11px",
    }[treatments.spacing_density]

    safe_text = escape(text or "Get in touch")
    safe_target = escape(target or "#contact")
    return (
        f'<a class="ca-hero-cta-button" '
        f'href="{safe_target}" '
        f'data-override-target="{escape(target_path)}" '
        f'data-override-type="text" '
        f'style="display: inline-flex; '
        f'align-items: center; '
        f'gap: 8px; '
        f'padding: {padding_v} 32px; '
        f'background: var(--cta-bg, var(--brand-signal, #C6952F)); '
        f'color: var(--cta-text, var(--brand-text-on-signal, #0F172A)); '
        f'font-size: 14px; '
        f'font-weight: 700; '
        f'letter-spacing: 0.08em; '
        f'text-transform: uppercase; '
        f'text-decoration: none; '
        f'border-radius: 999px; '
        f'font-family: var(--ca-sans, system-ui, -apple-system, sans-serif); '
        f'box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12); '
        f'transition: transform 200ms cubic-bezier(0.16, 1, 0.3, 1), '
        f'box-shadow 200ms cubic-bezier(0.16, 1, 0.3, 1);">'
        f"{safe_text}"
        f"</a>"
    )
