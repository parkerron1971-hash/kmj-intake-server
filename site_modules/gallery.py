"""Gallery module — the practitioner's REAL photos.

Renders settings.media_library.gallery (via ctx["gallery"]): their own
pictures of products, finished work, and results — a VARIABLE number of
images, with captions, across four layouts that each hold up at any count
(1, 2, 5, 12, 20+). SELF-DROPS when there are no visible photos — data
dignity, the same rule offerings/testimonials follow. No more stock-filler
galleries on composed sites.

Variants:
  grid     — uniform responsive tiles (auto-fit); the safe default.
  masonry  — varied natural heights (CSS columns); best for mixed shots.
  mosaic   — featured-first editorial (the first photo leads); curated feel.
  carousel — a swipeable row; great for a product line-up.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from ._base import safe, safe_url, ov, eyebrow, heading_accent, accent_headline

VARIANTS = ("grid", "masonry", "mosaic", "carousel")

_MAX_IMAGES = 24  # a curated showcase, not a dumping ground


def _images(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    # gather_context already filters visible + sorts; the module self-defends
    # too (hidden / url-less rows never render) in case of another call path.
    raw = ctx.get("gallery")
    if not isinstance(raw, list):
        return []
    return [g for g in raw
            if isinstance(g, dict) and str(g.get("url") or "").strip()
            and g.get("show_on_website", True)][:_MAX_IMAGES]


def _figure(img: Dict[str, Any], biz_name: str, overlay: bool = False) -> str:
    url = safe_url(img.get("url"))
    if not url:
        return ""
    alt = safe(img.get("alt") or img.get("caption") or f"{biz_name} — work sample")
    cap = safe(str(img.get("caption") or "").strip())
    if overlay:
        figcap = (f'<figcaption class="sxm-gal-cap sxm-gal-cap-over">{cap}</figcaption>'
                  if cap else "")
        cls = "sxm-gal-fig sxm-gal-fig-over"
    else:
        figcap = (f'<figcaption class="sxm-gal-cap sxm-small">{cap}</figcaption>'
                  if cap else "")
        cls = "sxm-gal-fig"
    return (f'<figure class="{cls}">'
            f'<img src="{url}" alt="{alt}" loading="lazy" class="sxm-gal-img">'
            f'{figcap}</figure>')


# Shared CSS — the figure/image/caption primitives every layout reuses.
_BASE_CSS = """
.sxm-gallery h2 { margin-bottom: var(--sx-space-6, 32px); }
.sxm-gal-fig { margin: 0; }
.sxm-gal-cap { margin-top: var(--sx-space-2, 8px); color: var(--sx-muted); line-height: 1.4; }
.sxm-gal-fig-over { position: relative; overflow: hidden; border-radius: var(--sx-radius-image); }
.sxm-gal-cap-over { position: absolute; left: 0; right: 0; bottom: 0; margin: 0;
  padding: 26px 16px 12px; font-size: var(--sx-small, .82rem); color: #fff;
  background: linear-gradient(to top, rgba(0,0,0,.62), transparent);
  opacity: 0; transform: translateY(6px); transition: opacity .3s var(--sx-ease), transform .3s var(--sx-ease); }
.sxm-gal-fig-over:hover .sxm-gal-cap-over { opacity: 1; transform: none; }
@media (prefers-reduced-motion: reduce) {
  .sxm-gal-cap-over { transition: none; } }
"""

_LAYOUT_CSS = {
    "grid": """
.sxm-gal-grid { display: grid; gap: var(--sx-space-4, 16px);
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 260px), 1fr)); }
.sxm-gal-grid .sxm-gal-img { width: 100%; aspect-ratio: 4 / 3; object-fit: cover;
  border-radius: var(--sx-radius-image); display: block; }
""",
    "masonry": """
.sxm-gal-masonry { columns: 3; column-gap: var(--sx-space-4, 16px); }
.sxm-gal-masonry .sxm-gal-fig { break-inside: avoid; margin: 0 0 var(--sx-space-4, 16px); }
.sxm-gal-masonry .sxm-gal-img { width: 100%; height: auto; display: block;
  border-radius: var(--sx-radius-image); }
@media (max-width: 900px) { .sxm-gal-masonry { columns: 2; } }
@media (max-width: 560px) { .sxm-gal-masonry { columns: 1; } }
""",
    "mosaic": """
.sxm-gal-mosaic { display: grid; gap: var(--sx-space-3, 12px); grid-auto-flow: dense;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 210px), 1fr)); grid-auto-rows: 210px; }
.sxm-gal-mosaic .sxm-gal-fig { height: 100%; }
.sxm-gal-mosaic .sxm-gal-fig:first-child { grid-column: span 2; grid-row: span 2; }
.sxm-gal-mosaic .sxm-gal-img { width: 100%; height: 100%; object-fit: cover;
  border-radius: var(--sx-radius-image); display: block; }
@media (max-width: 560px) {
  .sxm-gal-mosaic { grid-auto-rows: 180px; }
  .sxm-gal-mosaic .sxm-gal-fig:first-child { grid-column: span 2; grid-row: span 2; } }
""",
    "carousel": """
.sxm-gal-carousel { display: flex; gap: var(--sx-space-4, 16px); overflow-x: auto;
  scroll-snap-type: x mandatory; padding-bottom: var(--sx-space-3, 12px);
  -webkit-overflow-scrolling: touch; scrollbar-width: thin;
  -webkit-mask-image: linear-gradient(90deg, #000 calc(100% - 40px), transparent);
  mask-image: linear-gradient(90deg, #000 calc(100% - 40px), transparent); }
.sxm-gal-carousel .sxm-gal-fig { flex: 0 0 clamp(240px, 42vw, 380px); scroll-snap-align: start; }
.sxm-gal-carousel .sxm-gal-img { width: 100%; aspect-ratio: 4 / 3; object-fit: cover;
  border-radius: var(--sx-radius-image); display: block; }
@media (max-width: 560px) { .sxm-gal-carousel .sxm-gal-fig { flex-basis: 78vw; } }
""",
}


def render(variant: str, content: Dict[str, Any], ctx: Dict[str, Any]) -> Tuple[str, str]:
    imgs = _images(ctx)
    if not imgs:
        return "", ""   # self-drop — never a stock-filler gallery

    if variant not in VARIANTS:
        variant = "grid"
    dna = ctx.get("dna") or {}
    biz_name = (ctx.get("business") or {}).get("name") or "Business"
    overlay = variant in ("mosaic", "carousel")   # cropped tiles → caption overlay
    figs = [f for f in (_figure(g, biz_name, overlay=overlay) for g in imgs) if f]
    if not figs:
        return "", ""

    eb = eyebrow("gallery", content.get("eyebrow") or "")
    headline = content.get("headline") or "The work"
    container_class = f"sxm-gal-{variant}"
    html = f"""
<section class="sxm-section sxm-gallery sxm-reveal" id="gallery">
  <div class="sxm-inner">
    {heading_accent(dna)}
    {eb}
    <h2 {ov('gallery', 'headline')}>{accent_headline(headline)}</h2>
    <div class="{container_class}">{''.join(figs)}</div>
  </div>
</section>"""
    css = _BASE_CSS + _LAYOUT_CSS[variant]
    return html, css
