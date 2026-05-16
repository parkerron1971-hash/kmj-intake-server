"""Studio Brut CTA — sharp-cornered rectangle by default (not pill).
Cathedral CTAs are 999px-radius pills; Studio Brut CTAs commit to
sharp edges (4px radius max) and aggressive weight (800 baseline,
900 on hover via CSS later).

Treatment sensitivity:
  color_emphasis controls bg + text color via --cta-bg / --cta-text vars
  spacing_density adjusts vertical padding
  color_depth=gradient_accents → bold authority-to-signal gradient bg
  color_depth=radial_glows → radial signal glow halo
  typography=playful → slight italic on CTA label permitted
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
    """Render the primary CTA button. `target` is the href value."""
    padding_v = {
        "generous": "18px",
        "standard": "15px",
        "compact":  "12px",
    }[treatments.spacing_density]
    padding_h = {
        "generous": "40px",
        "standard": "32px",
        "compact":  "24px",
    }[treatments.spacing_density]

    safe_text = escape(text or "Get in touch")
    safe_target = escape(target or "#contact")
    return (
        f'<a class="sb-hero-cta-button" '
        f'href="{safe_target}" '
        f'data-override-target="{escape(target_path)}" '
        f'data-override-type="text" '
        f'style="display: inline-flex; '
        f'align-items: center; '
        f'gap: 12px; '
        f'padding: {padding_v} {padding_h}; '
        f'background-color: var(--cta-bg, var(--brand-signal, #FACC15)); '
        f'background-image: var(--sb-cta-bg-image, none); '
        f'color: var(--cta-text, var(--brand-text-on-signal, #09090B)); '
        f'font-size: 15px; '
        f'font-weight: 800; '
        f'font-style: var(--sb-cta-style, normal); '
        f'letter-spacing: 0.06em; '
        f'text-transform: uppercase; '
        f'text-decoration: none; '
        # Studio Brut: sharp corners. 4px radius is the maximum;
        # 0px is welcome when the brand calls for it (set via brand-kit
        # convention or a Studio Brut variant override).
        f'border-radius: var(--sb-cta-radius, 4px); '
        f'font-family: var(--sb-sans-stack, "Inter", "Space Grotesk", '
        f'system-ui, -apple-system, sans-serif); '
        f'box-shadow: var(--sb-cta-glow, '
        f'4px 4px 0 var(--brand-text-primary, #09090B)); '
        f'transition: transform 200ms cubic-bezier(0.16, 1, 0.3, 1), '
        f'box-shadow 200ms cubic-bezier(0.16, 1, 0.3, 1);">'
        f"{safe_text}"
        f"</a>"
    )
