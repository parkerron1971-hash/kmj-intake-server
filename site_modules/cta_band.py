"""CTA band — full-width conversion moment. Content: headline,
subheadline, cta_label. Button always routes somewhere real.

Variants: "band" (the full-bleed gold punctuation, below) and — B4
(2026-07-18) — "editorial", the quiet close: hairline seam, oversized
display line, text-link CTA whose underline draws on hover. Same fields,
same destination ladder (cta_button style="link").

Quality-floor arc 7: the band is now the original bar's full-bleed SOLID
accent 'gold band' punctuation (was a soft accent-soft→surface gradient):
solid var(--sx-accent) ground, var(--sx-on-accent) ink (contrast-enforced
in brand_dna), 64-80px vertical padding, inverted CTA pill, floating
diamonds (skipped for brut / stilled per motion rules in _base)."""
from __future__ import annotations

from typing import Any, Dict, Tuple

from ._base import safe, ov, cta_button, accent_headline, diamond_field

VARIANTS = ("band", "editorial")


def render(variant: str, content: Dict[str, Any], ctx: Dict[str, Any]) -> Tuple[str, str]:
    dna = ctx.get("dna") or {}
    headline = content.get("headline") or "Ready when you are."
    sub = content.get("subheadline") or ""

    if variant == "editorial":
        # B4 (2026-07-18) — the QUIET conversion moment. The gold band is
        # the loud punctuation; the editorial close is the other pole: a
        # hairline seam, an oversized display line, and a text link whose
        # underline draws on hover. No fill, no pill — the page ground
        # itself carries the ask. Same copy fields, same working href.
        sub_html = (f'<p class="sxm-ctaed-sub sxm-lead" {ov("cta", "subheadline")}>{safe(sub)}</p>'
                    if sub else "")
        html = f"""
<section class="sxm-section sxm-ctaed sxm-reveal" id="cta">
  <div class="sxm-inner sxm-ctaed-inner">
    <h2 {ov('cta', 'headline')}>{accent_headline(headline)}</h2>
    {sub_html}
    {cta_button(ctx, content.get('cta_label') or 'Book a session', 'cta', style='link')}
  </div>
</section>"""
        css = """
.sxm-ctaed { border-top: 1px solid var(--sx-border); }
.sxm-ctaed-inner { max-width: 780px; }
.sxm-ctaed h2 { font-size: clamp(2.6rem, 6vw, 4.6rem); margin-bottom: 18px; }
.sxm-ctaed-sub { margin-bottom: 34px; color: var(--sx-muted); }
/* The quiet CTA — body-size text link, accent ink, an underline that
   DRAWS itself from the left on hover (the house hover rule: hovers
   draw, they don't glow). */
.sxm-cta-link { display: inline-block; font-weight: 700; font-size: 1.02rem;
  letter-spacing: .02em; color: var(--sx-accent); text-decoration: none;
  padding-bottom: 4px; background: linear-gradient(90deg, var(--sx-accent), var(--sx-accent))
    left 100% / 0% 2px no-repeat;
  border-bottom: 1px solid color-mix(in srgb, var(--sx-accent) 35%, transparent);
  transition: background-size .45s var(--sx-ease); }
.sxm-cta-link:hover { background-size: 100% 2px; }
.sxm-cta-link::after { content: "→"; margin-left: 10px; display: inline-block;
  transition: transform .45s var(--sx-ease); }
.sxm-cta-link:hover::after { transform: translateX(6px); }
@media (prefers-reduced-motion: reduce) {
  .sxm-cta-link, .sxm-cta-link::after { transition: none; } }"""
        return html, css

    sub_html = f'<p class="sxm-ctaband-sub" {ov("cta", "subheadline")}>{safe(sub)}</p>' if sub else ""
    html = f"""
<section class="sxm-section sxm-ctaband sxm-reveal" id="cta">{diamond_field(dna, 2)}
  <div class="sxm-inner sxm-ctaband-inner">
    <h2 {ov('cta', 'headline')}>{accent_headline(headline)}</h2>
    {sub_html}
    {cta_button(ctx, content.get('cta_label') or 'Book a session', 'cta')}
  </div>
</section>"""
    # Site Arc 9 — full-bleed fills use the GOVERNED accent ground
    # (--sx-accent-ground: chroma-capped, lightness pulled toward the
    # ground's comfort zone) — a raw S=1.0 brand accent is a fine CTA
    # pill and a blinding 300px band. Small ink keeps raw --sx-accent.
    css = """
.sxm-ctaband { position: relative; overflow: hidden;
  background: var(--sx-accent-ground, var(--sx-accent));
  color: var(--sx-on-accent-ground, var(--sx-on-accent));
  /* P3: pads ride the page's rhythm scale (D5) — was an ad-hoc clamp. */
  padding-top: var(--sx-rhythm-half, clamp(64px, 8vw, 80px));
  padding-bottom: var(--sx-rhythm-half, clamp(64px, 8vw, 80px)); }
.sxm-ctaband-inner { position: relative; text-align: center; max-width: 720px; }
.sxm-ctaband h2 { margin-bottom: 16px; color: var(--sx-on-accent-ground, var(--sx-on-accent)); }
.sxm-ctaband .sxm-accent-word { color: var(--sx-on-accent-ground, var(--sx-on-accent)); font-weight: 500; }
.sxm-ctaband-sub { margin: 0 auto 30px; font-size: 1.08rem;
  color: color-mix(in srgb, var(--sx-on-accent-ground, var(--sx-on-accent)) 85%, var(--sx-accent-ground, var(--sx-accent))); }
/* Inverted CTA — an accent button would vanish on its own ground. */
.sxm-ctaband .sxm-cta { background: var(--sx-on-accent-ground, var(--sx-on-accent)); color: var(--sx-accent);
  box-shadow: 0 16px 40px color-mix(in srgb, var(--sx-on-accent-ground, var(--sx-on-accent)) 22%, transparent); }
.sxm-ctaband .sxm-cta:hover { background: var(--sx-on-accent-ground, var(--sx-on-accent)); filter: brightness(1.08);
  box-shadow: 0 20px 50px color-mix(in srgb, var(--sx-on-accent-ground, var(--sx-on-accent)) 30%, transparent); }
.sxm-ctaband .sxm-diamond { color: var(--sx-on-accent-ground, var(--sx-on-accent)); }"""
    return html, css
