"""Variant 8 — STAT_STRIP.

Tall hero with heading + subtitle content top-aligned and a dense
stat strip across the bottom — 3 stat blocks each composed of a
massive monospace numeral + small-caps label + thin signal-colored
underline. Top section bg differs from bottom strip bg via a hard
divider.

Studio Brut design-doc anchors:
  - "Numbers and codes as visual interest" — Section 3 + Section 4
    both name this as Studio Brut vocabulary
  - "Density" — top is generous, bottom strip packs 3 stats tightly
  - "Sharp commits" — the divider between content + stat strip is
    a hard 6px bar, not a gradient

SPIKE CAVEAT (carried from Cathedral's tabular_authority): stat
tuples are hardcoded. Production fix is to extend HeroContent with a
stats list so Composer fills per-business. Phase B accepts the
caveat — variant validates the LAYOUT works.

Best for: agencies, consultancies, creative shops with provable
work counts (clients, projects, years, awards, sold-out runs).
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from ..types import RenderContext
from ..primitives import (
    render_eyebrow,
    render_heading,
    render_subtitle,
    render_cta_button,
    render_bar,
    render_code_label,
)
from ._depth_helpers import SECTION_DEPTH_BG, render_satellite_ornaments


def _format_inline_vars(d: Dict[str, str]) -> str:
    return "; ".join(f"{k}: {v}" for k, v in d.items())


_DEFAULT_STATS: List[Tuple[str, str]] = [
    ("47",   "PROJECTS SHIPPED"),
    ("12",   "YEARS IN PRACTICE"),
    ("∞",    "REVISIONS REFUSED"),
]


def render_stat_strip(
    context: RenderContext,
    brand_vars: Dict[str, str],
    treatment_vars: Dict[str, str],
) -> str:
    """Render variant 8 — heading top, dense stat strip bottom."""
    content = context.composition.content
    treatments = context.composition.treatments
    merged_vars = {**brand_vars, **treatment_vars}
    section_style = _format_inline_vars(merged_vars)

    eyebrow_html = render_eyebrow(content.eyebrow, treatments)
    heading_html = render_heading(content.heading, content.heading_emphasis, treatments)
    subtitle_html = render_subtitle(content.subtitle, treatments)
    cta_html = render_cta_button(content.cta_primary, content.cta_target, treatments)

    code_html = render_code_label(
        "CASE / 08",
        "hero.code_label",
        size_px=11,
        position_style="margin-bottom: 24px;",
    )

    # Build the 3-stat block — each stat: monospace numeral + label.
    stat_html_parts = []
    for i, (numeral, label) in enumerate(_DEFAULT_STATS):
        stat_html_parts.append(
            f'<div class="sb-hero-stat" '
            f'data-override-target="hero.stat_{i}" '
            f'data-override-type="text" '
            f'style="flex: 1 1 0; min-width: 0;">'
            f'<div style="font-family: var(--sb-mono-stack, '
            f'\'JetBrains Mono\', \'Space Mono\', monospace); '
            f'font-size: clamp(3rem, 7vw, 5.5rem); '
            f'font-weight: 900; '
            f'line-height: 0.95; '
            f'letter-spacing: -0.02em; '
            f'color: var(--brand-text-on-authority, #FFFFFF); '
            f'margin-bottom: 8px;">{numeral}</div>'
            f'<div style="font-size: 11px; '
            f'letter-spacing: 0.18em; '
            f'text-transform: uppercase; '
            f'font-weight: 700; '
            f'color: var(--brand-signal, #FACC15);">{label}</div>'
            f'</div>'
        )
    stats_inner = "\n".join(stat_html_parts)

    divider_bar = render_bar(
        "hero.divider_bar",
        orientation="horizontal",
        length="100%",
        thickness_px=6,
        color_var="var(--brand-signal, #FACC15)",
        position_style="position: absolute; bottom: 220px; left: 0;",
    )

    sats = render_satellite_ornaments(treatments.ornament, "stat_strip")

    return f"""<section
  data-section="hero"
  class="sb-hero sb-hero-stat-strip"
  style="{section_style};
    {SECTION_DEPTH_BG}
    position: relative;
    overflow: hidden;
    min-height: 700px;
    display: flex;
    flex-direction: column;
  "
>
  <!-- Top region: content -->
  <div style="
    flex: 1 1 auto;
    padding: var(--sb-section-padding-y, 80px) var(--sb-section-padding-x, 40px) 80px;
    max-width: var(--sb-content-max-width, 1120px);
    margin: 0 auto;
    width: 100%;
    box-sizing: border-box;
  ">
    {code_html}
    {eyebrow_html}
    {heading_html}
    <div style="display: flex; align-items: flex-end; gap: 48px; flex-wrap: wrap;">
      <div style="flex: 1 1 320px;">{subtitle_html}</div>
      <div>{cta_html}</div>
    </div>
  </div>
  {divider_bar}
  <!-- Bottom strip: stat blocks, authority paint -->
  <div
    data-override-target="hero.stat_strip"
    data-override-type="color"
    style="
      background: var(--brand-authority, #DC2626);
      padding: 40px var(--sb-section-padding-x, 40px);
      display: flex;
      gap: 32px;
      align-items: flex-end;
    "
  >
    {stats_inner}
  </div>
  {sats}
</section>"""
