"""Header/nav module — Arc 1 "Wear the Brand" (Smart Sites quality).

Structural chrome, NOT an LLM-choosable section: render_page always
renders it first, before the hero. Sticky translucent bar with the
business logo (or a heading-font wordmark when no logo asset exists),
anchor links to the sections that ACTUALLY rendered, and a CTA that
always routes somewhere real (booking page > #contact).

Deterministic by construction: no JS, no external icon libs. Mobile
collapses the links to a horizontal scroll strip with soft-faded
gradient edges (gradients always fade — never hard-edged).
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from ._base import safe, safe_url, diamond_mark, ov

# Rendered-module id → (anchor, label). Order here is only a fallback;
# links are emitted in the order the sections rendered on the page.
_NAV_LABELS = {
    "about": ("#about", "About"),
    "offerings": ("#offerings", "Services"),
    "showcase": ("#showcase", "Programs"),
    "gallery": ("#gallery", "Gallery"),
    "testimonials": ("#testimonials", "Testimonials"),
    "store": ("#store", "Store"),
}
_MAX_LINKS = 4  # non-contact links; Contact is always appended last


def _pick_logo(ctx: Dict[str, Any]) -> str:
    """Logo variant by palette darkness: a light logo sits on a dark
    ground and vice versa. Falls back to the primary mark; empty string
    means 'use the text wordmark'."""
    assets = (ctx.get("bundle") or {}).get("assets") or {}
    mode = ((ctx.get("dna") or {}).get("palette") or {}).get("mode") or "dark"
    variant = assets.get("logo_light") if mode == "dark" else assets.get("logo_dark")
    url = variant or assets.get("primary") or ""
    return url if str(url).startswith("http") else ""


def render_header(rendered_ids: List[str], ctx: Dict[str, Any]) -> Tuple[str, str]:
    """rendered_ids = module ids that actually produced HTML, in page
    order. Returns (header_html, header_css)."""
    biz = ctx.get("business") or {}
    name = biz.get("name") or "Home"
    booking = ctx.get("booking") or {}

    logo_url = _pick_logo(ctx)
    if logo_url:
        brand_inner = (f'<img class="sxm-header-logo" src="{safe_url(logo_url)}" '
                       f'alt="{safe(name)} logo">')
    else:
        # Quality-floor arc 7: the bar's small static diamond beside the
        # wordmark (skipped for brut; a real logo IS the brand mark).
        brand_inner = (f'{diamond_mark(ctx.get("dna") or {})}'
                       f'<span class="sxm-header-wordmark">{safe(name)}</span>')

    links = []
    for mid in rendered_ids:
        if mid in _NAV_LABELS and len(links) < _MAX_LINKS:
            anchor, label = _NAV_LABELS[mid]
            links.append(f'<a href="{anchor}">{label}</a>')
    if "contact" in rendered_ids:
        links.append('<a href="#contact">Contact</a>')
    nav_html = (f'<nav class="sxm-header-nav" aria-label="Site sections">{"".join(links)}</nav>'
                if links else "")

    if booking.get("enabled") and booking.get("url"):
        cta_href, cta_label = safe_url(booking["url"]), "Book now"
    else:
        cta_href, cta_label = "#contact", "Get in touch"

    html = f"""
<header class="sxm-header">
  <div class="sxm-header-inner">
    <a class="sxm-header-brand" href="#top" aria-label="{safe(name)} — home">{brand_inner}</a>
    {nav_html}
    <a class="sxm-cta sxm-header-cta" href="{cta_href}"><span {ov('header', 'cta_label')}>{cta_label}</span></a>
  </div>
</header>"""

    css = """
html { scroll-padding-top: 84px; }
.sxm-header { position: sticky; top: 0; z-index: 60;
  background: color-mix(in srgb, var(--sx-bg) 78%, transparent);
  -webkit-backdrop-filter: blur(14px); backdrop-filter: blur(14px);
  border-bottom: 1px solid color-mix(in srgb, var(--sx-border) 70%, transparent); }
.sxm-header-inner { max-width: var(--sx-content-max); margin: 0 auto;
  display: flex; align-items: center; gap: clamp(14px, 3vw, 34px);
  padding: 12px var(--sx-gutter); min-height: 64px; }
.sxm-header-brand { display: flex; align-items: center; min-width: 0; color: var(--sx-text); }
.sxm-header-logo { height: 38px; width: auto; max-width: 180px; object-fit: contain; display: block; }
.sxm-header-wordmark { font-family: var(--sx-font-heading); font-weight: var(--sx-heading-weight);
  font-size: 1.22rem; letter-spacing: var(--sx-letter-tight); white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis; }
.sxm-header-nav { display: flex; align-items: center; gap: clamp(14px, 2.4vw, 28px);
  margin-left: auto; overflow-x: auto; scrollbar-width: none; -ms-overflow-style: none;
  /* soft-faded edges when links overflow — the gradient FADES, never hard-edged */
  -webkit-mask-image: linear-gradient(to right, transparent 0, #000 18px, #000 calc(100% - 18px), transparent 100%);
  mask-image: linear-gradient(to right, transparent 0, #000 18px, #000 calc(100% - 18px), transparent 100%); }
.sxm-header-nav::-webkit-scrollbar { display: none; }
/* Quality-floor arc 7 — the bar's nav voice: small caps, wide tracking,
   accent underline sweeping 0→100% on hover. */
.sxm-header-nav a { position: relative; color: var(--sx-text); font-size: .72rem;
  font-weight: 700; letter-spacing: .2em; text-transform: uppercase;
  white-space: nowrap; opacity: .82; padding: 6px 0;
  transition: opacity .15s ease, color .15s ease; }
.sxm-header-nav a::after { content: ""; position: absolute; left: 0; bottom: 0;
  height: 2px; width: 100%; background: var(--sx-accent);
  transform: scaleX(0); transform-origin: left;
  transition: transform .3s var(--sx-ease); }
.sxm-header-nav a:hover { opacity: 1; color: var(--sx-accent); }
.sxm-header-nav a:hover::after { transform: scaleX(1); }
@media (prefers-reduced-motion: reduce) {
  .sxm-header-nav a::after { transition: none; }
}
.sxm-header-cta { padding: 10px 20px; font-size: .85rem; flex-shrink: 0; }
@media (max-width: 768px) {
  .sxm-header-inner { min-height: 56px; gap: 12px; }
  .sxm-header-logo { height: 32px; }
  .sxm-header-nav { gap: 16px; padding: 2px 0; }
  html { scroll-padding-top: 68px; }
}"""
    return html, css
