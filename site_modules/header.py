"""Header/nav module — Arc 1 "Wear the Brand" (Smart Sites quality).

Structural chrome, NOT an LLM-choosable section: render_page always
renders it first, before the hero. Sticky translucent bar with the
business logo (or a heading-font wordmark when no logo asset exists),
anchor links to the sections that ACTUALLY rendered, and a CTA that
always routes somewhere real (booking page > #contact).

Deterministic by construction: no JS, no external icon libs. Mobile
collapses the links into a CSS-only hamburger drawer (the same
checkbox-toggle pattern the multi-page nav uses) — a horizontal
scroll strip with mask-faded edges read as a rendering bug in
ship-gate review (chars of the first/last link visibly clipped at
every viewport), so that treatment was removed.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from ._base import safe, safe_url, diamond_mark, ov, is_brut

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


def _header_variant(ctx: Dict[str, Any]) -> str:
    """Menu architecture by design DNA (2026-07-18, Kevin: "the menu
    for every site looks the same"). Same philosophy as
    heading_accent: the personality signals that already vary the
    page now vary the BAR itself. Deterministic — same business,
    same menu.
      brut            -> "split"   nav-left architecture, hard edge, no blur
      block accent    -> "banner"  centered two-row masthead
      soft accent     -> "ghost"   transparent over the hero, solidifies on scroll
      everything else -> "classic" the original bar
    """
    dna = ctx.get("dna") or {}
    if is_brut(dna):
        return "split"
    style = str(dna.get("accent_style") or "")
    if style in ("block_mark", "block"):
        return "banner"
    if style in ("soft_rule", "soft"):
        return "ghost"
    return "classic"


def render_header(rendered_ids: List[str], ctx: Dict[str, Any]) -> Tuple[str, str]:
    """rendered_ids = module ids that actually produced HTML, in page
    order. Returns (header_html, header_css)."""
    # Creative-capture arc (2026-07-18): a model-AUTHORED nav spec (see
    # nav_spec.py) drives the bar when present — architecture + logo
    # treatment + CTA style + link style + accent detail + CTA wording,
    # ~576 legal combinations rendered by the hand-written CSS below.
    # No/invalid spec (or SITE_NAV_SPEC=off) → the DNA-variant bars.
    spec = ctx.get("nav_spec") if isinstance(ctx.get("nav_spec"), dict) else None
    variant = (spec or {}).get("architecture") or _header_variant(ctx)
    if variant not in ("classic", "split", "banner", "ghost"):
        variant = _header_variant(ctx)
    spec_classes = ""
    if spec:
        spec_classes = (
            f" sxm-nav--cta-{spec.get('cta_style') or 'pill'}"
            f" sxm-nav--links-{spec.get('link_style') or 'caps'}"
            f" sxm-nav--accent-{spec.get('accent_detail') or 'underline'}"
        )
    biz = ctx.get("business") or {}
    name = biz.get("name") or "Home"
    booking = ctx.get("booking") or {}

    logo_url = _pick_logo(ctx)
    if spec and spec.get("logo_treatment") in ("wordmark", "monogram"):
        # The author chose typography over the uploaded image.
        logo_url = ""
    if logo_url:
        brand_inner = (f'<img class="sxm-header-logo" src="{safe_url(logo_url)}" '
                       f'alt="{safe(name)} logo">')
    else:
        # Quality-floor arc 7: the bar's small static diamond beside the
        # wordmark (skipped for brut; a real logo IS the brand mark).
        brand_inner = (f'{diamond_mark(ctx.get("dna") or {})}'
                       f'<span class="sxm-header-wordmark">{safe(name)}</span>')

    # Multi-page nav (site_multipage): real cross-page links with an
    # is-active marker + a CSS-only mobile hamburger drawer. Falls back to
    # the anchor nav (single-page) when no page context is present.
    page_nav = ctx.get("page_nav") if isinstance(ctx.get("page_nav"), dict) else None
    pages = (page_nav or {}).get("pages") or []
    if pages:
        def _page_link(p: Dict[str, Any]) -> str:
            cls = ' class="is-active" aria-current="page"' if p.get("active") else ""
            return (f'<a href="{safe_url(p.get("href") or "#")}"{cls}>'
                    f'{safe(p.get("name") or "")}</a>')
        link_items = "".join(_page_link(p) for p in pages)
        nav_html = (f'<nav class="sxm-header-nav sxm-header-pagenav" '
                    f'aria-label="Pages">{link_items}</nav>')
        brand_href = next((p.get("href") for p in pages if p.get("id") == "home"), "#top")
        drawer_html = (
            '\n<input type="checkbox" id="sxm-nav-toggle" class="sxm-nav-toggle" aria-hidden="true">'
            '\n<label for="sxm-nav-toggle" class="sxm-hamburger" aria-label="Open menu">'
            '<span></span><span></span><span></span></label>'
            f'\n<nav class="sxm-header-drawer" aria-label="Pages (mobile)">{link_items}</nav>')
    else:
        links = []
        # Menu voice (Kevin's ruling 2026-07-22, "the menu is stale"):
        # each destination carries a small accent index numeral — the
        # nav reads as a table of contents for a designed document, not
        # four flat words. Numbering follows the page's real order.
        for mid in rendered_ids:
            if mid in _NAV_LABELS and len(links) < _MAX_LINKS:
                anchor, label = _NAV_LABELS[mid]
                links.append(
                    f'<a href="{anchor}"><span class="sxm-nav-num" '
                    f'aria-hidden="true">{len(links) + 1:02d}</span>{label}</a>')
        if "contact" in rendered_ids:
            links.append(
                f'<a href="#contact"><span class="sxm-nav-num" '
                f'aria-hidden="true">{len(links) + 1:02d}</span>Contact</a>')
        if links:
            link_items = "".join(links)
            nav_html = (f'<nav class="sxm-header-nav" aria-label="Site sections">'
                        f'{link_items}</nav>')
            # F3 (2026-07-18): the anchor nav gets the same CSS-only
            # hamburger drawer as the page nav — a clipped "Contact"
            # link off-canvas at 390px was the ship-gate's broken=y.
            drawer_html = (
                '\n<input type="checkbox" id="sxm-nav-toggle" class="sxm-nav-toggle" aria-hidden="true">'
                '\n<label for="sxm-nav-toggle" class="sxm-hamburger" aria-label="Open menu">'
                '<span></span><span></span><span></span></label>'
                f'\n<nav class="sxm-header-drawer" aria-label="Site sections (mobile)">{link_items}</nav>')
        else:
            nav_html = ""
            drawer_html = ""
        brand_href = "#top"

    if booking.get("enabled") and booking.get("url"):
        cta_href, cta_label = safe_url(booking["url"]), "Book now"
    else:
        cta_href, cta_label = "#contact", "Get in touch"
    if spec and spec.get("cta_label"):
        cta_label = safe(str(spec["cta_label"]))

    html = f"""
<header class="sxm-header sxm-header--{variant}{spec_classes}">
  <div class="sxm-header-inner">
    <a class="sxm-header-brand" href="{brand_href}" aria-label="{safe(name)} — home">{brand_inner}</a>
    {nav_html}
    <a class="sxm-cta sxm-header-cta" href="{cta_href}"><span {ov('header', 'cta_label')}>{cta_label}</span></a>{drawer_html}
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
  font-size: clamp(0.98rem, 0.7rem + 1.1vw, 1.22rem);
  letter-spacing: var(--sx-letter-tight); white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis; }
/* Ship-gate finding (3/3 acceptance builds): a long business name
   ellipsized to "…" at 390px — "an ellipsis in a logo reads as broken,
   not responsive". Small viewports let the wordmark wrap to two tight
   lines instead of truncating; the fluid clamp above already shrinks it
   before the wrap is needed. */
@media (max-width: 480px) {
  .sxm-header-wordmark { white-space: normal; overflow: visible;
    text-overflow: clip; line-height: 1.08; font-size: 0.95rem;
    max-width: 46vw; }
}
.sxm-header-nav { display: flex; align-items: center; gap: clamp(14px, 2.4vw, 28px);
  margin-left: auto; overflow-x: auto; scrollbar-width: none; -ms-overflow-style: none; }
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
/* The index numerals — a designed table of contents, not flat words. */
.sxm-nav-num { font-size: .58rem; letter-spacing: .08em; margin-right: 7px;
  color: var(--sx-accent); font-variant-numeric: tabular-nums;
  vertical-align: 0.18em; opacity: .85;
  transition: opacity .15s ease; }
.sxm-header-nav a:hover .sxm-nav-num { opacity: 1; }
.sxm-header-drawer .sxm-nav-num { font-size: .7rem; margin-right: 10px;
  color: var(--sx-accent); font-variant-numeric: tabular-nums; }
@media (prefers-reduced-motion: reduce) {
  .sxm-header-nav a::after { transition: none; }
}
.sxm-header-cta { padding: 10px 20px; font-size: .85rem; flex-shrink: 0; }
@media (max-width: 768px) {
  .sxm-header-inner { min-height: 56px; gap: 12px; }
  .sxm-header-logo { height: 32px; }
  .sxm-header-nav { gap: 16px; padding: 2px 0; }
  html { scroll-padding-top: 68px; }
}
/* ── Multi-page nav (site_multipage) ── */
.sxm-header-pagenav a.is-active { opacity: 1; color: var(--sx-accent); }
.sxm-header-pagenav a.is-active::after { transform: scaleX(1); }
.sxm-nav-toggle, .sxm-hamburger, .sxm-header-drawer { display: none; }
@media (max-width: 768px) {
  .sxm-header-nav { display: none; }
  .sxm-header-cta { display: none; }
  .sxm-hamburger { display: inline-flex; flex-direction: column; gap: 5px; margin-left: auto;
    width: 42px; height: 42px; align-items: center; justify-content: center; cursor: pointer; }
  .sxm-hamburger span { display: block; width: 22px; height: 2px; border-radius: 2px;
    background: var(--sx-text); transition: transform .25s ease, opacity .2s ease; }
  .sxm-header-drawer { display: flex; position: absolute; top: 100%; left: 0; right: 0;
    flex-direction: column; padding: 6px var(--sx-gutter) 16px;
    background: color-mix(in srgb, var(--sx-bg) 96%, transparent);
    -webkit-backdrop-filter: blur(16px); backdrop-filter: blur(16px);
    border-bottom: 1px solid color-mix(in srgb, var(--sx-border) 70%, transparent);
    max-height: 0; overflow: hidden; opacity: 0; pointer-events: none;
    transition: max-height .3s var(--sx-ease), opacity .2s ease; }
  .sxm-nav-toggle:checked ~ .sxm-header-drawer { max-height: 72vh; opacity: 1; pointer-events: auto; }
  .sxm-header-drawer a { padding: 13px 2px; font-size: .98rem; font-weight: 600;
    letter-spacing: .02em; text-transform: none; color: var(--sx-text); opacity: .9;
    border-bottom: 1px solid color-mix(in srgb, var(--sx-border) 40%, transparent); }
  .sxm-header-drawer a.is-active { color: var(--sx-accent); opacity: 1; }
  .sxm-header-drawer a::after { display: none; }
  .sxm-nav-toggle:checked ~ .sxm-hamburger span:nth-child(1) { transform: translateY(7px) rotate(45deg); }
  .sxm-nav-toggle:checked ~ .sxm-hamburger span:nth-child(2) { opacity: 0; }
  .sxm-nav-toggle:checked ~ .sxm-hamburger span:nth-child(3) { transform: translateY(-7px) rotate(-45deg); }
}
@media (prefers-reduced-motion: reduce) {
  .sxm-header-drawer, .sxm-hamburger span { transition: none; }
}

/* ── Menu architectures (2026-07-18) — the bar follows the DNA ── */
/* split: nav leads, brand centered, hard editorial edge, no blur. */
@media (min-width: 769px) {
  .sxm-header--split { background: var(--sx-bg);
    -webkit-backdrop-filter: none; backdrop-filter: none;
    border-bottom: 2px solid var(--sx-text); }
  .sxm-header--split .sxm-header-nav { order: -1; margin-left: 0; }
  .sxm-header--split .sxm-header-brand { margin-left: auto; margin-right: auto; }
  .sxm-header--split .sxm-header-wordmark { font-size: 1.34rem; }
}
/* banner: centered two-row masthead — brand above, nav + CTA below. */
@media (min-width: 769px) {
  .sxm-header--banner .sxm-header-inner { flex-wrap: wrap; justify-content: center;
    row-gap: 2px; padding-top: 14px; padding-bottom: 10px; }
  .sxm-header--banner .sxm-header-brand { flex-basis: 100%; justify-content: center; }
  .sxm-header--banner .sxm-header-wordmark { font-size: 1.5rem; }
  .sxm-header--banner .sxm-header-logo { height: 44px; }
  .sxm-header--banner .sxm-header-nav { margin-left: 0; }
  .sxm-header--banner .sxm-header-cta { padding: 7px 16px; font-size: .78rem; }
  .sxm-header--banner + main, html:has(.sxm-header--banner) { scroll-padding-top: 112px; }
}
/* ghost: transparent over the hero, solidifies as you scroll.
   Scroll-driven animation where supported; graceful solid fallback. */
@supports (animation-timeline: scroll()) {
  .sxm-header--ghost { background: transparent; border-bottom-color: transparent;
    -webkit-backdrop-filter: none; backdrop-filter: none;
    animation: sxm-header-solidify linear both;
    animation-timeline: scroll(); animation-range: 0 180px; }
  @keyframes sxm-header-solidify {
    to { background: color-mix(in srgb, var(--sx-bg) 88%, transparent);
         border-bottom-color: color-mix(in srgb, var(--sx-border) 70%, transparent);
         -webkit-backdrop-filter: blur(14px); backdrop-filter: blur(14px); }
  }
  @media (prefers-reduced-motion: reduce) {
    .sxm-header--ghost { animation: none;
      background: color-mix(in srgb, var(--sx-bg) 78%, transparent);
      border-bottom-color: color-mix(in srgb, var(--sx-border) 70%, transparent); }
  }
}

/* ── Authored-spec axes (nav_spec.py, 2026-07-18) — each class is one
      independent decision the model composes; absent classes = today's
      defaults, so the DNA-variant fallback renders unchanged. ── */
.sxm-nav--cta-sharp .sxm-header-cta { border-radius: 0; }
.sxm-nav--cta-ghost .sxm-header-cta { background: transparent;
  color: var(--sx-text); box-shadow: inset 0 0 0 1.5px var(--sx-accent); }
.sxm-nav--cta-text .sxm-header-cta { background: transparent;
  color: var(--sx-accent); padding-left: 6px; padding-right: 6px;
  box-shadow: none; }
.sxm-nav--links-title .sxm-header-nav a { text-transform: none;
  letter-spacing: .035em; font-size: .84rem; font-weight: 600; }
.sxm-nav--links-lower .sxm-header-nav a { text-transform: lowercase;
  letter-spacing: .09em; }
.sxm-nav--accent-dot .sxm-header-brand::after { content: "";
  width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0;
  background: var(--sx-accent); margin-left: 7px; align-self: flex-end;
  margin-bottom: 6px; }
.sxm-nav--accent-frame .sxm-header-cta { outline: 1px solid var(--sx-accent);
  outline-offset: 3px; }
.sxm-nav--accent-none .sxm-header-nav a::after { display: none; }"""
    return html, css
