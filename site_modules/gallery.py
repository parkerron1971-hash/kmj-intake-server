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
/* Arc B (2026-07-21) — THE MAT: practitioners upload mixed material
   (white-ground product shots next to full-bleed art), and raw tiles
   read as uploads floating on the page — the live noir build glared.
   A surface mat + hairline + inset pad makes any mix hang together
   like one curated wall. Overlay figures keep their full-bleed crop. */
.sxm-gal-fig:not(.sxm-gal-fig-over) { background: var(--sx-surface);
  border: 1px solid var(--sx-border); border-radius: var(--sx-radius-image);
  padding: 10px; }
.sxm-gal-fig:not(.sxm-gal-fig-over) .sxm-gal-img {
  border-radius: calc(var(--sx-radius-image) - 4px); }
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


# Gallery-by-intent (2026-07-18, Kevin's ruling): the gallery's DESIGN
# should exist when the practitioner asked for one (site_prefs.
# wants_gallery) or the business type clearly implies visual work —
# even before any photos exist. Empty state = designed accent frames
# (never stock imagery, never fake work — D10 holds); the practitioner
# fills them by uploading to the Media Library, and the next compose /
# cache-invalidate swaps real photos in automatically.
_VISUAL_TYPE_HINTS = (
    "salon", "barber", "beauty", "nail", "lash", "photo", "design",
    "artist", "art", "tattoo", "contractor", "construction", "landscap",
    "baker", "cake", "florist", "flower", "event", "cater", "decor",
    "boutique", "fashion", "jewel", "furniture", "wood", "detail",
    "clean", "real estate", "realtor", "makeup", "stylist", "craft",
)


def _gallery_wanted(ctx: Dict[str, Any]) -> bool:
    prefs = ctx.get("site_prefs") if isinstance(ctx.get("site_prefs"), dict) else {}
    wants = prefs.get("wants_gallery")
    if wants is True:
        return True
    if wants is False:
        return False
    # Unset → interpret from the business type.
    btype = str((ctx.get("business") or {}).get("type") or "").lower()
    return any(h in btype for h in _VISUAL_TYPE_HINTS)


def _render_awaiting(content: Dict[str, Any], ctx: Dict[str, Any]) -> Tuple[str, str]:
    """The designed EMPTY gallery: six accent-washed frames that read as
    intentional texture, each a future home for the practitioner's own
    photo. No stock, no fake work, no 'coming soon' copy."""
    dna = ctx.get("dna") or {}
    eb = eyebrow("gallery", content.get("eyebrow") or "")
    headline = content.get("headline") or "The work"
    frames = "".join(
        f'<figure class="sxm-gal-frame" aria-hidden="true">'
        f'<span class="sxm-gal-frame-mark"></span></figure>'
        for _ in range(6))
    html = f"""
<section class="sxm-section sxm-gallery sxm-gal-await sxm-reveal" id="gallery">
  <div class="sxm-inner">
    {heading_accent(dna)}
    {eb}
    <h2 {ov('gallery', 'headline')}>{accent_headline(headline)}</h2>
    <div class="sxm-gal-grid sxm-gal-awaitgrid">{frames}</div>
  </div>
</section>"""
    css = _BASE_CSS + """
.sxm-gal-awaitgrid { display: grid; gap: clamp(10px, 1.6vw, 18px);
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); }
.sxm-gal-frame { margin: 0; aspect-ratio: 4 / 3; position: relative;
  border-radius: var(--sx-radius-image);
  border: 1px solid color-mix(in srgb, var(--sx-accent) 26%, var(--sx-border));
  background:
    linear-gradient(135deg,
      color-mix(in srgb, var(--sx-accent) 7%, transparent) 0%,
      transparent 55%),
    color-mix(in srgb, var(--sx-text) 3%, transparent);
  display: flex; align-items: center; justify-content: center; }
.sxm-gal-frame:nth-child(even) { background:
    linear-gradient(315deg,
      color-mix(in srgb, var(--sx-accent) 5%, transparent) 0%,
      transparent 60%),
    color-mix(in srgb, var(--sx-text) 2%, transparent); }
.sxm-gal-frame-mark { width: 14px; height: 14px; transform: rotate(45deg);
  background: color-mix(in srgb, var(--sx-accent) 30%, transparent); }
"""
    return html, css


def render(variant: str, content: Dict[str, Any], ctx: Dict[str, Any]) -> Tuple[str, str]:
    imgs = _images(ctx)
    if not imgs:
        if _gallery_wanted(ctx):
            return _render_awaiting(content, ctx)
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
