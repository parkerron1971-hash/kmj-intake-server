"""Offerings module — renders REAL offerings rows from ctx (never
invented by the LLM). Content: eyebrow, headline, intro. Variants:
cards, list. Prices honor show_price_to_customer; the per-offering Book
CTA appears only when booking is actually enabled — function first."""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from ._base import safe, safe_url, ov, eyebrow, heading_accent

VARIANTS = ("cards", "list")

_MAX_ITEMS = 9


def _price(o: Dict[str, Any]) -> str:
    if o.get("show_price_to_customer") is False:
        return ""
    p = o.get("current_price")
    if p in (None, ""):
        return ""
    try:
        val = float(p)
    except (TypeError, ValueError):
        return ""
    cur = (o.get("currency") or "usd").upper()
    sym = "$" if cur == "USD" else f"{cur} "
    txt = f"{sym}{val:,.0f}" if val == int(val) else f"{sym}{val:,.2f}"
    return f'<div class="sxm-off-price">{safe(txt)}</div>'


def _duration(o: Dict[str, Any]) -> str:
    d = o.get("duration_min")
    if not d:
        return ""
    return f'<span class="sxm-off-dur sxm-muted">{int(d)} min</span>'


def render(variant: str, content: Dict[str, Any], ctx: Dict[str, Any]) -> Tuple[str, str]:
    dna = ctx["dna"]
    rows: List[Dict[str, Any]] = [o for o in (ctx.get("offerings") or []) if o.get("name")][:_MAX_ITEMS]
    if not rows:
        return "", ""  # no real offerings → no section; nothing is invented

    booking = ctx.get("booking") or {}
    book_href = safe_url(booking.get("url")) if booking.get("enabled") and booking.get("url") else ""

    eb = eyebrow("offerings", content.get("eyebrow") or "Offerings")
    headline = content.get("headline") or "Ways to work together"
    intro = content.get("intro") or ""
    intro_html = (f'<p class="sxm-off-intro sxm-muted" {ov("offerings", "intro")}>{safe(intro)}</p>'
                  if intro else "")

    items = []
    for o in rows:
        cta = (f'<a class="sxm-off-book" href="{book_href}">Book</a>' if book_href else "")
        desc = safe(o.get("description") or "")
        desc_html = f'<p class="sxm-off-desc sxm-muted">{desc}</p>' if desc else ""
        items.append(f"""
      <div class="sxm-off-item">
        <div class="sxm-off-head">
          <h3>{safe(o['name'])}</h3>
          {_duration(o)}
        </div>
        {desc_html}
        <div class="sxm-off-foot">{_price(o)}{cta}</div>
      </div>""")

    layout_class = "sxm-off-cards" if variant != "list" else "sxm-off-list"
    html = f"""
<section class="sxm-section sxm-offerings sxm-reveal" id="offerings">
  <div class="sxm-inner">
    {heading_accent(dna)}
    {eb}
    <h2 {ov('offerings', 'headline')}>{safe(headline)}</h2>
    {intro_html}
    <div class="{layout_class}">{''.join(items)}
    </div>
  </div>
</section>"""

    shared = """
.sxm-offerings h2 { margin-bottom: 16px; }
.sxm-off-intro { font-size: 1.05rem; margin-bottom: 12px; }
.sxm-off-head { display: flex; justify-content: space-between; align-items: baseline; gap: 14px; }
.sxm-off-head h3 { font-size: 1.25rem; }
.sxm-off-dur { font-size: .85rem; white-space: nowrap; }
.sxm-off-desc { font-size: .98rem; margin: 10px 0 0; }
.sxm-off-foot { display: flex; justify-content: space-between; align-items: center; margin-top: 18px; }
.sxm-off-price { font-family: var(--sx-font-heading); font-size: 1.15rem; font-weight: 700; color: var(--sx-accent); }
.sxm-off-book { font-weight: 700; font-size: .9rem; letter-spacing: .03em; padding: 9px 18px;
  border: 1.5px solid var(--sx-accent); border-radius: var(--sx-radius-button); transition: background .15s, color .15s; }
.sxm-off-book:hover { background: var(--sx-accent); color: var(--sx-on-accent); }"""

    if variant == "list":
        css = shared + """
.sxm-off-list { display: flex; flex-direction: column; margin-top: 34px; }
.sxm-off-list .sxm-off-item { padding: 26px 0; border-top: 1px solid var(--sx-border); }
.sxm-off-list .sxm-off-item:last-child { border-bottom: 1px solid var(--sx-border); }"""
    else:
        css = shared + """
.sxm-off-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(290px, 1fr)); gap: 22px; margin-top: 34px; }
.sxm-off-cards .sxm-off-item { background: var(--sx-surface); border: 1px solid var(--sx-border);
  border-radius: var(--sx-radius-card); padding: 28px; display: flex; flex-direction: column; }
.sxm-off-cards .sxm-off-foot { margin-top: auto; padding-top: 18px; }"""
    return html, css
