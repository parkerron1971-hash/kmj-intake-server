"""Gallery module — image slots gallery_1..gallery_4 (existing slot
names → existing population pipeline). Content: eyebrow, headline."""
from __future__ import annotations

from typing import Any, Dict, Tuple

from ._base import safe, ov, eyebrow, heading_accent

VARIANTS = ("grid",)


def render(variant: str, content: Dict[str, Any], ctx: Dict[str, Any]) -> Tuple[str, str]:
    dna = ctx["dna"]
    eb = eyebrow("gallery", content.get("eyebrow") or "")
    headline = content.get("headline") or "The work"
    biz_name = (ctx.get("business") or {}).get("name") or "Business"
    imgs = "".join(
        f'\n      <img data-slot="gallery_{i}" src="" '
        f'alt="{safe(biz_name)} gallery image {i}" class="sxm-gal-img sxm-gal-{i}">'
        for i in range(1, 5))
    html = f"""
<section class="sxm-section sxm-gallery sxm-reveal" id="gallery">
  <div class="sxm-inner">
    {heading_accent(dna)}
    {eb}
    <h2 {ov('gallery', 'headline')}>{safe(headline)}</h2>
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
