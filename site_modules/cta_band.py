"""CTA band — full-width conversion moment. Content: headline,
subheadline, cta_label. Button always routes somewhere real.

Quality-floor arc 7: the band is now the original bar's full-bleed SOLID
accent 'gold band' punctuation (was a soft accent-soft→surface gradient):
solid var(--sx-accent) ground, var(--sx-on-accent) ink (contrast-enforced
in brand_dna), 64-80px vertical padding, inverted CTA pill, floating
diamonds (skipped for brut / stilled per motion rules in _base)."""
from __future__ import annotations

from typing import Any, Dict, Tuple

from ._base import safe, ov, cta_button, accent_headline, diamond_field

VARIANTS = ("band",)


def render(variant: str, content: Dict[str, Any], ctx: Dict[str, Any]) -> Tuple[str, str]:
    dna = ctx.get("dna") or {}
    headline = content.get("headline") or "Ready when you are."
    sub = content.get("subheadline") or ""
    sub_html = f'<p class="sxm-ctaband-sub" {ov("cta", "subheadline")}>{safe(sub)}</p>' if sub else ""
    html = f"""
<section class="sxm-section sxm-ctaband sxm-reveal" id="cta">{diamond_field(dna, 2)}
  <div class="sxm-inner sxm-ctaband-inner">
    <h2 {ov('cta', 'headline')}>{accent_headline(headline)}</h2>
    {sub_html}
    {cta_button(ctx, content.get('cta_label') or 'Book a session', 'cta')}
  </div>
</section>"""
    css = """
.sxm-ctaband { position: relative; overflow: hidden;
  background: var(--sx-accent); color: var(--sx-on-accent);
  padding-top: clamp(64px, 8vw, 80px); padding-bottom: clamp(64px, 8vw, 80px); }
.sxm-ctaband-inner { position: relative; text-align: center; max-width: 720px; }
.sxm-ctaband h2 { margin-bottom: 16px; color: var(--sx-on-accent); }
.sxm-ctaband .sxm-accent-word { color: var(--sx-on-accent); font-weight: 500; }
.sxm-ctaband-sub { margin: 0 auto 30px; font-size: 1.08rem;
  color: color-mix(in srgb, var(--sx-on-accent) 85%, var(--sx-accent)); }
/* Inverted CTA — an accent button would vanish on its own ground. */
.sxm-ctaband .sxm-cta { background: var(--sx-on-accent); color: var(--sx-accent);
  box-shadow: 0 16px 40px color-mix(in srgb, var(--sx-on-accent) 22%, transparent); }
.sxm-ctaband .sxm-cta:hover { background: var(--sx-on-accent); filter: brightness(1.08);
  box-shadow: 0 20px 50px color-mix(in srgb, var(--sx-on-accent) 30%, transparent); }
.sxm-ctaband .sxm-diamond { color: var(--sx-on-accent); }"""
    return html, css
