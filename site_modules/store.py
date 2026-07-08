"""Store module — features up to 3 REAL sellable offerings (from ctx,
never invented) with a CTA to the hosted store page. Renders nothing
when the business has no sellable products. Content: eyebrow, headline,
intro, cta_label.

Site Arc 9 (data dignity): the whole section is SUPPRESSED until at
least _MIN_REAL_PRODUCTS products carry a real image AND a real price
(>= $_MIN_REAL_PRICE) — a one-test-product store destroys trust."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

from ._base import safe, safe_url, ov, eyebrow, heading_accent, accent_headline

logger = logging.getLogger(__name__)

VARIANTS = ("featured",)

_MIN_REAL_PRODUCTS = 2
_MIN_REAL_PRICE = 5.0


def _min_real_products(ctx: Dict[str, Any]) -> int:
    """Site Arc 11 (connections): the owner's explicit connections.store
    = True relaxes the arc-9 two-product trust threshold to a 1-real-
    product floor — explicit intent outranks the heuristic. Absent/False
    keeps the default (False suppresses entirely; see render)."""
    conn = (ctx.get("connections")
            if isinstance(ctx.get("connections"), dict) else {})
    return 1 if conn.get("store") is True else _MIN_REAL_PRODUCTS


def _store_forced_off(ctx: Dict[str, Any]) -> bool:
    """connections.store=False → the section never renders, products or
    not (gather_context also disables ctx.store; this is self-defense
    for directly-constructed contexts)."""
    conn = (ctx.get("connections")
            if isinstance(ctx.get("connections"), dict) else {})
    return conn.get("store") is False


def _real_items(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Products with a real image AND a real (>= $5) price — the trust
    threshold the section suppression counts."""
    out: List[Dict[str, Any]] = []
    for o in (store.get("items") or []):
        if not isinstance(o, dict):
            continue
        has_img = str(o.get("image_url") or "").startswith("http")
        try:
            price = float(o.get("current_price") or 0)
        except (TypeError, ValueError):
            price = 0.0
        if has_img and price >= _MIN_REAL_PRICE:
            out.append(o)
    return out


def store_would_render(ctx: Dict[str, Any]) -> bool:
    """Would the store section actually render for this ctx? Public so
    offerings can decide whether store-catalog items should be excluded
    from its own list (only when BOTH would show the same item)."""
    store = ctx.get("store") or {}
    if _store_forced_off(ctx):
        return False
    return bool(store.get("enabled") and store.get("url")
                and len(_real_items(store)) >= _min_real_products(ctx))


def render(variant: str, content: Dict[str, Any], ctx: Dict[str, Any]) -> Tuple[str, str]:
    dna = ctx["dna"]
    store = ctx.get("store") or {}
    items: List[Dict[str, Any]] = (store.get("items") or [])[:3]
    url = store.get("url") or ""
    if _store_forced_off(ctx):
        logger.info("[store] section suppressed: owner connections.store=False")
        return "", ""
    if not store.get("enabled") or not items or not url:
        return "", ""
    real = _real_items(store)
    min_real = _min_real_products(ctx)
    if len(real) < min_real:
        logger.info(
            f"[store] section suppressed: {len(real)} product(s) with a real "
            f"image + real price (>= ${_MIN_REAL_PRICE:.0f}); need "
            f"{min_real}")
        return "", ""

    eb = eyebrow("store", content.get("eyebrow") or "The shop")
    headline = content.get("headline") or "From the store"
    intro = content.get("intro") or ""
    intro_html = (f'<p class="sxm-store-intro sxm-muted" {ov("store", "intro")}>{safe(intro)}</p>'
                  if intro else "")

    cards = []
    for o in items:
        img = (f'<img class="sxm-store-img" src="{safe_url(o.get("image_url"))}" '
               f'alt="{safe(o.get("name") or "Product photo")}">'
               if str(o.get("image_url") or "").startswith("http")
               else '<div class="sxm-store-img sxm-store-img-ph" role="presentation"></div>')
        try:
            price = f"${float(o.get('current_price') or 0):,.2f}"
        except (TypeError, ValueError):
            price = ""
        cards.append(f"""
      <a class="sxm-store-card sxm-card" href="{safe_url(url)}">
        {img}
        <div class="sxm-store-meta"><span>{safe(o.get('name'))}</span>
        <span class="sxm-store-price">{safe(price)}</span></div>
      </a>""")

    html = f"""
<section class="sxm-section sxm-store sxm-reveal" id="store">
  <div class="sxm-inner">
    {heading_accent(dna)}
    {eb}
    <h2 {ov('store', 'headline')}>{accent_headline(headline)}</h2>
    {intro_html}
    <div class="sxm-store-grid">{''.join(cards)}
    </div>
    <div class="sxm-store-cta">
      <a class="sxm-cta" href="{safe_url(url)}"><span {ov('store', 'cta_label')}>{safe(content.get('cta_label') or 'Visit the store')}</span></a>
    </div>
  </div>
</section>"""
    css = """
.sxm-store h2 { margin-bottom: 16px; }
.sxm-store-intro { font-size: 1.02rem; margin-bottom: 10px; }
.sxm-store-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 20px; margin-top: 30px; }
.sxm-store-card { display: block; background: var(--sx-surface); border: 1px solid var(--sx-border);
  border-radius: var(--sx-radius-card); overflow: hidden; color: var(--sx-text); }
.sxm-store-img { width: 100%; aspect-ratio: 4/3; object-fit: cover; display: block; }
.sxm-store-img-ph { background: linear-gradient(135deg, var(--sx-surface-2), var(--sx-surface)); }
.sxm-store-meta { display: flex; justify-content: space-between; gap: 10px; padding: 14px 16px; font-weight: 600; }
.sxm-store-price { color: var(--sx-accent); font-weight: 700; white-space: nowrap; }
.sxm-store-cta { margin-top: 30px; }"""
    return html, css
