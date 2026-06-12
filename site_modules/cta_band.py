"""CTA band — full-width conversion moment. Content: headline,
subheadline, cta_label. Button always routes somewhere real."""
from __future__ import annotations

from typing import Any, Dict, Tuple

from ._base import safe, ov, cta_button

VARIANTS = ("band",)


def render(variant: str, content: Dict[str, Any], ctx: Dict[str, Any]) -> Tuple[str, str]:
    headline = content.get("headline") or "Ready when you are."
    sub = content.get("subheadline") or ""
    sub_html = f'<p class="sxm-ctaband-sub" {ov("cta", "subheadline")}>{safe(sub)}</p>' if sub else ""
    html = f"""
<section class="sxm-section sxm-ctaband sxm-reveal" id="cta">
  <div class="sxm-inner sxm-ctaband-inner">
    <h2 {ov('cta', 'headline')}>{safe(headline)}</h2>
    {sub_html}
    {cta_button(ctx, content.get('cta_label') or 'Book a session', 'cta')}
  </div>
</section>"""
    css = """
.sxm-ctaband { background: linear-gradient(135deg, var(--sx-accent-soft), var(--sx-surface-2)); }
.sxm-ctaband-inner { text-align: center; max-width: 720px; }
.sxm-ctaband h2 { margin-bottom: 16px; }
.sxm-ctaband-sub { margin: 0 auto 30px; font-size: 1.08rem; color: var(--sx-muted); }"""
    return html, css
