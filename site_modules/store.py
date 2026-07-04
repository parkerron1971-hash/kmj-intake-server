"""Store module — features up to 3 REAL sellable offerings (from ctx,
never invented) with a CTA to the hosted store page. Renders nothing
when the business has no sellable products. Content: eyebrow, headline,
intro, cta_label."""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from ._base import safe, safe_url, ov, eyebrow, heading_accent

VARIANTS = ("featured",)


def render(variant: str, content: Dict[str, Any], ctx: Dict[str, Any]) -> Tuple[str, str]:
    dna = ctx["dna"]
    store = ctx.get("store") or {}
    items: List[Dict[str, Any]] = (store.get("items") or [])[:3]
    url = store.get("url") or ""
    if not store.get("enabled") or not items or not url:
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
      <a class="sxm-store-card" href="{safe_url(url)}">
        {img}
        <div class="sxm-store-meta"><span>{safe(o.get('name'))}</span>
        <span class="sxm-store-price">{safe(price)}</span></div>
      </a>""")

    html = f"""
<section class="sxm-section sxm-store sxm-reveal" id="store">
  <div class="sxm-inner">
    {heading_accent(dna)}
    {eb}
    <h2 {ov('store', 'headline')}>{safe(headline)}</h2>
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
  border-radius: var(--sx-radius-card); overflow: hidden; color: var(--sx-text); transition: transform .18s ease; }
.sxm-store-card:hover { transform: translateY(-3px); }
.sxm-store-img { width: 100%; aspect-ratio: 4/3; object-fit: cover; display: block; }
.sxm-store-img-ph { background: linear-gradient(135deg, var(--sx-accent-soft), var(--sx-surface-2)); }
.sxm-store-meta { display: flex; justify-content: space-between; gap: 10px; padding: 14px 16px; font-weight: 600; }
.sxm-store-price { color: var(--sx-accent); font-weight: 700; white-space: nowrap; }
.sxm-store-cta { margin-top: 30px; }"""
    return html, css
