"""Variant 7 — QUOTE ANCHOR.

Testimony as opening statement. The heading slot carries a pull quote
(e.g., 'They reframed everything in the first hour.'). The subtitle
slot becomes the attribution ('— Anna Stewart, Founder of Hearth').
The eyebrow gives context ('WHAT CLIENTS SAY'). CTA below.

Visual signature: NO diamond motif anywhere. Replaced by oversized
serif quotation marks (Playfair Display "and") rendered as
typographic ornament — one before the quote (top-left of heading
column, opening "), one after (bottom-right of heading column,
closing "). The quotes themselves are the focal motif. Italic serif,
brand signal color, opacity ~0.45 so they read as ornament not text.

Best for: businesses where social proof is the opening move — high-
end consultants, established practitioners, anyone whose testimonials
carry more weight than a self-description.

Visual signature vs other variants:
  vs manifesto_center / layered_diamond: V7 has NO diamond motif at
    all — the only Cathedral Hero variant without diamonds. Quotation
    marks fill the ornament role.
  vs every other variant: the heading reads as a quote (italic + quote
    marks framing it), not a declaration. Attribution beneath gives
    away the quote's source.
"""
from __future__ import annotations

from html import escape
from typing import Dict

from ..types import RenderContext, Treatments
from ..primitives import (
    render_eyebrow,
    render_heading,
    render_cta_button,
)


def _format_inline_vars(var_dict: Dict[str, str]) -> str:
    return "; ".join(f"{k}: {v}" for k, v in var_dict.items())


def _render_attribution(text: str, target_path: str = "hero.subtitle") -> str:
    """Subtitle rendered as attribution line. Smaller than standard
    subtitle, with leading em-dash. Distinct from standard subtitle
    primitive since this variant repurposes the subtitle slot."""
    safe_text = escape(text or "")
    # Strip a leading em-dash if Composer already added one (we add it
    # ourselves for visual consistency).
    safe_text = safe_text.lstrip("—-– ").strip()
    return (
        f'<p class="ca-hero-attribution" '
        f'data-override-target="{escape(target_path)}" '
        f'data-override-type="text" '
        f'style="font-size: 15px; '
        f'line-height: 1.5; '
        f'font-weight: 600; '
        f'letter-spacing: 0.08em; '
        f'text-transform: uppercase; '
        f'color: var(--brand-text-primary, #0F172A); '
        f'opacity: 0.72; '
        f'font-family: var(--ca-sans, system-ui, -apple-system, sans-serif); '
        f'margin: 0 0 32px 0;">'
        f"— {safe_text}"
        f"</p>"
    )


def render_quote_anchor(
    context: RenderContext,
    brand_vars: Dict[str, str],
    treatment_vars: Dict[str, str],
) -> str:
    """Render variant 7 — quote-led hero with oversized quotation marks."""
    content = context.composition.content
    treatments = context.composition.treatments

    merged_vars = {**brand_vars, **treatment_vars}
    section_style = _format_inline_vars(merged_vars)

    # V7-specific: cap heading size regardless of treatment choice.
    # Quote text is typically longer than declarative headings and
    # would overflow at heading_dominant's clamp(3rem, 8vw, 6rem).
    # Force the heading primitive into 'balanced' scale (smaller clamp)
    # so quotes stay readable. Other treatment dimensions still apply
    # (color, spacing, etc.).
    quote_heading_treatments = Treatments(
        color_emphasis=treatments.color_emphasis,
        spacing_density=treatments.spacing_density,
        emphasis_weight="balanced",
    )

    eyebrow_html = render_eyebrow(content.eyebrow, treatments)
    heading_html = render_heading(content.heading, content.heading_emphasis, quote_heading_treatments)
    attribution_html = _render_attribution(content.subtitle)
    cta_html = render_cta_button(content.cta_primary, content.cta_target, treatments)

    # Oversized typographic quotation marks. Position-absolute, signal
    # color, italic serif. The opening mark sits top-left of the heading
    # block; the closing mark sits bottom-right. Together they bracket
    # the quote like an editorial pull-quote treatment.
    open_quote = (
        f'<div aria-hidden="true" '
        f'data-override-target="hero.quote_mark_open" '
        f'data-override-type="color" '
        f'style="position: absolute; '
        f'top: -32px; left: -16px; '
        f'font-family: var(--ca-serif, Georgia, \'Times New Roman\', serif); '
        f'font-style: italic; '
        f'font-weight: 700; '
        f'font-size: clamp(120px, 16vw, 220px); '
        f'line-height: 1; '
        f'color: var(--brand-signal, #C6952F); '
        f'opacity: 0.42; '
        f'pointer-events: none; '
        f'user-select: none; '
        f'z-index: 0;">'
        f'“'  # opening curly double-quote
        f'</div>'
    )
    close_quote = (
        f'<div aria-hidden="true" '
        f'data-override-target="hero.quote_mark_close" '
        f'data-override-type="color" '
        f'style="position: absolute; '
        f'bottom: -80px; right: -16px; '
        f'font-family: var(--ca-serif, Georgia, \'Times New Roman\', serif); '
        f'font-style: italic; '
        f'font-weight: 700; '
        f'font-size: clamp(120px, 16vw, 220px); '
        f'line-height: 1; '
        f'color: var(--brand-signal, #C6952F); '
        f'opacity: 0.42; '
        f'pointer-events: none; '
        f'user-select: none; '
        f'z-index: 0;">'
        f'”'  # closing curly double-quote
        f'</div>'
    )

    return f"""<section
  data-section="hero"
  class="ca-hero ca-hero-quote-anchor"
  style="{section_style};
    position: relative;
    background: var(--brand-warm-neutral, #F8F6F1);
    padding-top: var(--hero-section-padding-y, 100px);
    padding-bottom: var(--hero-section-padding-y, 100px);
    padding-left: var(--hero-section-padding-x, 64px);
    padding-right: var(--hero-section-padding-x, 64px);
    overflow: hidden;
  "
>
  <div style="
    max-width: 900px;
    margin: 0 auto;
    text-align: left;
    position: relative;
  ">
    {open_quote}
    <div style="position: relative; z-index: 1;">
      {eyebrow_html}
      <div style="font-style: italic;">
        {heading_html}
      </div>
      {attribution_html}
      {cta_html}
    </div>
    {close_quote}
  </div>
</section>"""
