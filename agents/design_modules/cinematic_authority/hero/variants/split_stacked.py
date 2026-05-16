"""Variant 5 — SPLIT STACKED.

Compound hero. Two stacked rows:
  Row 1 — full-width centered manifesto: eyebrow + heading (with
          italic emphasis) + subtitle. No CTA in row 1.
  Row 2 — two-column 50/50: hero image (landscape, no bleed) left,
          supporting content block right containing the CTA + value
          props (a short bulleted list of 3 key benefits, derived
          from subtitle — or a placeholder of 3 generic Cathedral-
          flavored value props if subtitle doesn't fragment cleanly).

The two rows are separated by a slim signal-color accent line that
spans roughly 1/3 of the column width — a structural punctuation mark
between the manifesto and the functional info.

Best for: service businesses with immediate functional needs (hours,
location, ranges of service), pastoral / community programs that need
to communicate both their why AND their how on the first scroll.

Visual signature vs other variants:
  vs manifesto_center: V1 = single centered block; V5 has a SECOND
    row below with functional info + image.
  vs asymmetric_left/right: V2/V3 are single-row two-column;
    V5 is two-row, with manifesto + image+content row stacked.
  vs full_bleed_overlay: V5's image is contained in a column; V4's
    image fills the section.

Layout sketch:
  ┌─────────────────────────────────────────┐
  │           EYEBROW                       │
  │     Heading with italic                 │
  │       subtitle line                     │
  │           ━━━━━                         │
  │                                          │
  │  ┌─────────────┐ ┌────────────────────┐ │
  │  │             │ │  • Value prop 1    │ │
  │  │   image     │ │  • Value prop 2    │ │
  │  │   16:10     │ │  • Value prop 3    │ │
  │  └─────────────┘ │  [CTA pill]        │ │
  │                  └────────────────────┘ │
  └─────────────────────────────────────────┘
"""
from __future__ import annotations

from html import escape
from typing import Dict, List

from ..types import RenderContext
from ..primitives import (
    render_eyebrow,
    render_heading,
    render_subtitle,
    render_cta_button,
)


def _format_inline_vars(var_dict: Dict[str, str]) -> str:
    return "; ".join(f"{k}: {v}" for k, v in var_dict.items())


def _derive_value_props(subtitle: str) -> List[str]:
    """Fragment the subtitle into 2-3 value props if it has clear
    delimiters (semicolon, em-dash, '. '). Falls back to 3 Cathedral-
    flavored generic props if subtitle doesn't fragment cleanly."""
    if not subtitle:
        return ["Considered process", "Attentive practice", "Lasting outcomes"]
    # Try semicolon-separated
    parts = [p.strip(" .;—–-") for p in subtitle.replace("—", ";").replace(".", ";").split(";")]
    parts = [p for p in parts if p and len(p) > 3]
    if len(parts) >= 2:
        return parts[:3]
    return [subtitle.strip(" ."), "By appointment", "Considered process"]


def render_split_stacked(
    context: RenderContext,
    brand_vars: Dict[str, str],
    treatment_vars: Dict[str, str],
) -> str:
    """Render variant 5 — manifesto top, image+CTA columns below."""
    content = context.composition.content
    treatments = context.composition.treatments

    merged_vars = {**brand_vars, **treatment_vars}
    section_style = _format_inline_vars(merged_vars)

    eyebrow_html = render_eyebrow(content.eyebrow, treatments)
    heading_html = render_heading(content.heading, content.heading_emphasis, treatments)
    subtitle_html = render_subtitle(content.subtitle, treatments)
    cta_html = render_cta_button(content.cta_primary, content.cta_target, treatments)

    slot_name = content.image_slot_ref or "hero_main"
    image_url = context.slot_resolutions.get(slot_name, "")
    safe_alt = escape(f"{slot_name} — Hero image")

    # Value props derived from subtitle structure.
    value_props = _derive_value_props(content.subtitle)
    value_props_html = "\n".join(
        f"""<li style="
              display: flex;
              align-items: baseline;
              gap: 12px;
              padding: 8px 0;
              font-family: var(--ca-sans, system-ui, -apple-system, sans-serif);
              font-size: 15px;
              line-height: 1.5;
              color: var(--brand-text-primary, #0F172A);
              opacity: 0.85;
            ">
              <span style="
                display: inline-block;
                width: 8px;
                height: 8px;
                background: var(--brand-signal, #C6952F);
                transform: rotate(45deg);
                flex-shrink: 0;
                margin-top: 6px;
              " data-override-target="hero.value_prop_{i}_marker" data-override-type="color"></span>
              <span data-override-target="hero.value_prop_{i}" data-override-type="text">{escape(p)}</span>
            </li>"""
        for i, p in enumerate(value_props, start=1)
    )

    return f"""<section
  data-section="hero"
  class="ca-hero ca-hero-split-stacked"
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
  <div style="max-width: var(--hero-content-max-width, 1180px); margin: 0 auto;">
    <!-- Row 1: centered manifesto -->
    <div style="text-align: center; display: flex; flex-direction: column; align-items: center;">
      {eyebrow_html}
      {heading_html}
      {subtitle_html}
    </div>
    <!-- Punctuation rule between rows -->
    <div
      data-override-target="hero.accent_seam"
      data-override-type="color"
      style="
        width: 96px;
        height: 3px;
        background: var(--brand-signal, #C6952F);
        margin: 32px auto 56px;
      "
    ></div>
    <!-- Row 2: image + functional content -->
    <div style="
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: var(--hero-column-gap, 64px);
      align-items: center;
    ">
      <div style="
        position: relative;
        aspect-ratio: 16 / 10;
        overflow: hidden;
        background: var(--brand-deep-secondary, #122040);
        box-shadow: 0 24px 48px rgba(0, 0, 0, 0.18);
      ">
        <img
          data-slot="{escape(slot_name)}"
          data-override-target="{escape(slot_name)}"
          data-override-type="image"
          src="{escape(image_url)}"
          alt="{safe_alt}"
          style="width: 100%; height: 100%; object-fit: cover; display: block;"
        />
      </div>
      <div style="display: flex; flex-direction: column; gap: 16px;">
        <ul style="list-style: none; padding: 0; margin: 0 0 16px 0;">
          {value_props_html}
        </ul>
        {cta_html}
      </div>
    </div>
  </div>
</section>"""
