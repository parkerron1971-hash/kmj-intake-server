"""Gallery module — image slots gallery_1..gallery_4 (existing slot
names → existing population pipeline). Content: eyebrow, headline.
Variants: grid, mosaic (Arc 3 — varied-size tiles w/ soft mask fades)."""
from __future__ import annotations

from typing import Any, Dict, Tuple

from ._base import safe, ov, eyebrow, heading_accent, accent_headline

VARIANTS = ("grid", "mosaic")


def render(variant: str, content: Dict[str, Any], ctx: Dict[str, Any]) -> Tuple[str, str]:
    dna = ctx["dna"]
    eb = eyebrow("gallery", content.get("eyebrow") or "")
    headline = content.get("headline") or "The work"
    biz_name = (ctx.get("business") or {}).get("name") or "Business"

    if variant == "mosaic":
        # Arc 3 — varied-size mosaic: two large tiles + two small (craft
        # source: studio_brut's asymmetric color-block composition,
        # translated to imagery in token discipline). Soft bottom mask
        # fade on every tile — gradients always fade, never hard-edged.
        tiles = "".join(
            f'\n      <div class="sxm-imgbox sxm-card-lite sxm-mo-t{i}">'
            f'<img data-slot="gallery_{i}" src="" '
            f'alt="{safe(biz_name)} gallery image {i}" class="sxm-mo-img"></div>'
            for i in range(1, 5))
        html = f"""
<section class="sxm-section sxm-gallery sxm-reveal" id="gallery">
  <div class="sxm-inner">
    {heading_accent(dna)}
    {eb}
    <h2 {ov('gallery', 'headline')}>{accent_headline(headline)}</h2>
    <div class="sxm-gal-mosaic">{tiles}
    </div>
  </div>
</section>"""
        css = """
.sxm-gallery h2 { margin-bottom: 34px; }
.sxm-gal-mosaic { display: grid; grid-template-columns: repeat(6, 1fr); grid-auto-rows: 200px; gap: 14px; }
.sxm-gal-mosaic .sxm-imgbox { height: 100%; }
.sxm-mo-t1 { grid-column: span 4; grid-row: span 2; }
.sxm-mo-t2 { grid-column: span 2; }
.sxm-mo-t3 { grid-column: span 2; }
.sxm-mo-t4 { grid-column: span 6; }
.sxm-mo-img { width: 100%; height: 100%; object-fit: cover; border-radius: var(--sx-radius-image);
  -webkit-mask-image: linear-gradient(to bottom, #000 72%, rgba(0, 0, 0, .45) 100%);
  mask-image: linear-gradient(to bottom, #000 72%, rgba(0, 0, 0, .45) 100%); }
@media (max-width: 860px) {
  .sxm-gal-mosaic { grid-template-columns: repeat(2, 1fr); grid-auto-rows: 170px; }
  .sxm-mo-t1 { grid-column: span 2; grid-row: span 2; }
  .sxm-mo-t2, .sxm-mo-t3 { grid-column: span 1; }
  .sxm-mo-t4 { grid-column: span 2; }
}"""
        return html, css

    imgs = "".join(
        f'\n      <img data-slot="gallery_{i}" src="" '
        f'alt="{safe(biz_name)} gallery image {i}" class="sxm-gal-img sxm-card-lite sxm-gal-{i}">'
        for i in range(1, 5))
    html = f"""
<section class="sxm-section sxm-gallery sxm-reveal" id="gallery">
  <div class="sxm-inner">
    {heading_accent(dna)}
    {eb}
    <h2 {ov('gallery', 'headline')}>{accent_headline(headline)}</h2>
    <div class="sxm-gal-grid">{imgs}
    </div>
  </div>
</section>"""
    css = """
.sxm-gallery h2 { margin-bottom: 34px; }
.sxm-gal-grid { display: grid; grid-template-columns: repeat(4, 1fr); grid-auto-rows: 220px; gap: 14px; }
.sxm-gal-img { width: 100%; height: 100%; object-fit: cover; border-radius: var(--sx-radius-image); }
.sxm-gal-1 { grid-column: span 2; grid-row: span 2; }
.sxm-gal-4 { grid-column: span 2; }
@media (max-width: 860px) { .sxm-gal-grid { grid-template-columns: repeat(2, 1fr); grid-auto-rows: 170px; }
  .sxm-gal-1 { grid-column: span 2; grid-row: span 1; } }"""
    return html, css
