"""Offerings module — renders REAL offerings rows from ctx (never
invented by the LLM). Content: eyebrow, headline, intro. Variants:
cards, list. Prices honor show_price_to_customer; the per-offering Book
CTA appears only when booking is actually enabled — function first.

Site Arc 9 (data dignity), tightened Site Arc 11b: $0 renders 'Free'
(a deliberate free offering is generosity, not noise); items priced
>0 and <$5 are placeholder-grade data and are EXCLUDED from the list
entirely — unless they are ALL there is, in which case they keep their
rows price-suppressed so the section isn't empty. Rows deduped by
normalized title; items the store section already shows are excluded;
the featured card's foot is never empty."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from ._base import safe, safe_url, ov, eyebrow, heading_accent, accent_headline

VARIANTS = ("cards", "list", "featured", "menu")

_MAX_ITEMS = 9
_MIN_DIGNIFIED_PRICE = 5.0    # under this, the price line is test-data noise


def _norm_title(name: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(name or "").lower()).strip()


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
    if val == 0:
        # A deliberate free offering reads as generosity, not $0.
        # Site Arc 10: prices speak in the WHISPER voice (the third
        # type voice) — tiny, wide-tracked, muted; the scale gap
        # against the display face is the luxury signal.
        return '<div class="sxm-off-price sxm-whisper">Free</div>'
    if 0 < val < _MIN_DIGNIFIED_PRICE:
        # Placeholder-grade price — no price line. Normally these rows
        # are excluded entirely (Site Arc 11b, render()); this branch
        # still guards the keep-when-only-offering fallback.
        return ""
    cur = (o.get("currency") or "usd").upper()
    sym = "$" if cur == "USD" else f"{cur} "
    txt = f"{sym}{val:,.0f}" if val == int(val) else f"{sym}{val:,.2f}"
    return f'<div class="sxm-off-price sxm-whisper">{safe(txt)}</div>'


def _placeholder_priced(o: Dict[str, Any]) -> bool:
    """True when the offering carries a >$0-but-sub-$5 price — the
    signature of test / placeholder-grade rows (Site Arc 11b: these are
    dropped from the list, not just price-suppressed). $0 is NOT
    placeholder (Free is a legitimate offer); unpriced rows pass."""
    p = o.get("current_price")
    if p in (None, ""):
        return False
    try:
        val = float(p)
    except (TypeError, ValueError):
        return False
    return 0 < val < _MIN_DIGNIFIED_PRICE


def _duration(o: Dict[str, Any]) -> str:
    d = o.get("duration_min")
    if not d:
        return ""
    return f'<span class="sxm-off-dur sxm-muted">{int(d)} min</span>'


def render(variant: str, content: Dict[str, Any], ctx: Dict[str, Any]) -> Tuple[str, str]:
    dna = ctx["dna"]
    # Site Arc 9: dedupe by normalized title (the live page listed the
    # featured item again as row 02) and exclude items the STORE section
    # will already show — but only when the store actually renders, so an
    # item never vanishes from both sections.
    store_names: set = set()
    try:
        from .store import store_would_render
        if store_would_render(ctx):
            store_names = {_norm_title(i.get("name"))
                           for i in ((ctx.get("store") or {}).get("items") or [])
                           if isinstance(i, dict) and i.get("name")}
    except Exception:
        pass
    rows: List[Dict[str, Any]] = []
    seen_titles: set = set()
    for o in (ctx.get("offerings") or []):
        if not o.get("name"):
            continue
        key = _norm_title(o["name"])
        if not key or key in seen_titles or key in store_names:
            continue
        seen_titles.add(key)
        rows.append(o)
    # Site Arc 11b (data dignity, tightened): placeholder-priced rows
    # (>0 and <$5 — e.g. a $2 'Hot Combs' test row) leave the list
    # entirely; hiding just the price still gave test data a whole row
    # on a cinematic page. EXCEPTION: when they are all there is, keep
    # them (price-suppressed by _price) so the section isn't empty.
    dignified = [o for o in rows if not _placeholder_priced(o)]
    if dignified:
        rows = dignified
    rows = rows[:_MAX_ITEMS]
    if not rows:
        return "", ""  # no real offerings → no section; nothing is invented

    booking = ctx.get("booking") or {}
    book_href = safe_url(booking.get("url")) if booking.get("enabled") and booking.get("url") else ""

    eb = eyebrow("offerings", content.get("eyebrow") or "Offerings")
    headline = content.get("headline") or "Ways to work together"
    intro = content.get("intro") or ""
    intro_html = (f'<p class="sxm-off-intro sxm-muted" {ov("offerings", "intro")}>{safe(intro)}</p>'
                  if intro else "")

    if variant == "featured":
        # Arc 3 — flagship feature card + numbered compact rows (craft
        # source: studio_brut stat_strip's numerals-as-visual-interest +
        # cathedral's framed feature panel, in token discipline). The
        # first REAL offering leads with an image slot (chamber_main —
        # existing atmosphere slot, populated by the existing pipeline);
        # the rest read as a dense index. Numbers are positional, never
        # invented data.
        feature, rest = rows[0], rows[1:]
        # Site Arc 11 (total editability): the per-row Book label is
        # PRESENTATION text — one shared target (offerings/book_label)
        # edits every row's label at once.
        f_cta = (f'<a class="sxm-off-book" href="{book_href}" {ov("offerings", "book_label")}>Book</a>'
                 if book_href else "")
        # Site Arc 9: the flagship card's foot is never empty — when no
        # booking CTA exists and the price line was suppressed, fall back
        # to the contact anchor (a premium layout with a blank action
        # area reads as broken).
        if not f_cta and not _price(feature):
            f_cta = (f'<a class="sxm-off-book" href="#contact" '
                     f'{ov("offerings", "book_label")}>Get in touch</a>')
        f_desc = safe(feature.get("description") or "")
        f_desc_html = f'<p class="sxm-off-desc sxm-muted">{f_desc}</p>' if f_desc else ""
        rows_html = []
        for i, o in enumerate(rest, start=2):
            r_cta = (f'<a class="sxm-off-book" href="{book_href}" {ov("offerings", "book_label")}>Book</a>'
                     if book_href else "")
            r_desc = safe(o.get("description") or "")
            r_desc_html = f'<p class="sxm-off-desc sxm-muted">{r_desc}</p>' if r_desc else ""
            rows_html.append(f"""
      <div class="sxm-offf-row">
        <span class="sxm-offf-idx" aria-hidden="true">{i:02d}</span>
        <div class="sxm-offf-rowmain">
          <div class="sxm-off-head"><h3>{safe(o['name'])}</h3>{_duration(o)}</div>
          {r_desc_html}
        </div>
        <div class="sxm-offf-rowend">{_price(o)}{r_cta}</div>
      </div>""")
        rows_block = (f'<div class="sxm-offf-rows">{"".join(rows_html)}\n    </div>'
                      if rows_html else "")
        html = f"""
<section class="sxm-section sxm-offerings sxm-off-featured sxm-reveal" id="offerings">
  <div class="sxm-inner">
    {heading_accent(dna)}
    {eb}
    <h2 {ov('offerings', 'headline')}>{accent_headline(headline)}</h2>
    {intro_html}
    <div class="sxm-offf-feature sxm-card">
      <div class="sxm-imgbox sxm-offf-img">
        <img data-slot="chamber_main" src="" alt="{safe(feature['name'])}">
      </div>
      <div class="sxm-offf-body">
        <span class="sxm-offf-idx" aria-hidden="true">01</span>
        <div class="sxm-off-head"><h3>{safe(feature['name'])}</h3>{_duration(feature)}</div>
        {f_desc_html}
        <div class="sxm-off-foot">{_price(feature)}{f_cta}</div>
      </div>
    </div>
    {rows_block}
  </div>
</section>"""
        css = """
.sxm-offerings h2 { margin-bottom: 16px; }
.sxm-off-intro { font-size: 1.05rem; margin-bottom: 12px; }
.sxm-off-head { display: flex; justify-content: space-between; align-items: baseline; gap: 14px; }
.sxm-off-head h3 { font-size: 1.35rem; }
.sxm-off-dur { font-size: .85rem; white-space: nowrap; }
.sxm-off-desc { font-size: .98rem; margin: 10px 0 0; }
.sxm-off-foot { display: flex; justify-content: space-between; align-items: center; margin-top: 20px; }
.sxm-off-price { font-family: var(--sx-font-heading); font-size: 1.15rem; font-weight: 700; color: var(--sx-accent); }
.sxm-off-book { font-weight: 700; font-size: .9rem; letter-spacing: .03em; padding: 9px 18px;
  border: 1.5px solid var(--sx-accent); border-radius: var(--sx-radius-button); transition: background .15s, color .15s; }
.sxm-off-book:hover { background: var(--sx-accent); color: var(--sx-on-accent); }
.sxm-offf-idx { display: block; font-family: var(--sx-font-heading); font-size: .95rem; font-weight: 700;
  letter-spacing: .14em; color: var(--sx-accent); margin-bottom: 10px; }
.sxm-offf-feature { display: grid; grid-template-columns: 1fr 1fr; gap: clamp(26px, 4.5vw, 60px);
  align-items: center; margin-top: 36px; background: var(--sx-surface); border: 1px solid var(--sx-border);
  border-radius: var(--sx-radius-card); overflow: hidden; }
.sxm-offf-img { border-radius: 0; height: 100%; }
.sxm-offf-img img { width: 100%; height: 100%; min-height: 320px; aspect-ratio: 3/2; object-fit: cover; }
.sxm-offf-body { padding: clamp(24px, 3.5vw, 48px); }
.sxm-offf-rows { margin-top: 14px; }
.sxm-offf-row { display: grid; grid-template-columns: auto 1fr auto; gap: clamp(16px, 3vw, 34px);
  align-items: center; padding: 24px 4px; border-bottom: 1px solid var(--sx-border); }
.sxm-offf-row .sxm-offf-idx { margin-bottom: 0; }
.sxm-offf-rowend { display: flex; align-items: center; gap: 18px; }
@media (max-width: 860px) {
  .sxm-offf-feature { grid-template-columns: 1fr; }
  .sxm-offf-img img { min-height: 0; }
  .sxm-offf-row { grid-template-columns: auto 1fr; }
  .sxm-offf-rowend { grid-column: 2; justify-content: flex-start; }
}"""
        return html, css

    if variant == "menu":
        # Site Arc 10 — the ENGRAVED MENU (exemplar e5 "K Luxury"): the
        # offerings as a menu OBJECT — hairline-ruled rows (row rules
        # are the menu's own linework, not page chrome), italic serif
        # names, whisper-caps prices right-aligned. Hovering a row
        # indents it 1rem and draws a hairline accent line across its
        # top (scaleX 0→1, origin left — the page's micro-signature:
        # hovers DRAW, they don't glow). Data dignity (Arc 9) rides
        # _price unchanged: Free / sub-$5 suppression.
        rows_html = []
        for o in rows:
            r_cta = (f'<a class="sxm-off-book sxm-offmenu-book" href="{book_href}" '
                     f'{ov("offerings", "book_label")}>Book</a>'
                     if book_href else "")
            desc = safe(o.get("description") or "")
            desc_html = (f'<p class="sxm-off-desc sxm-muted">{desc}</p>'
                         if desc else "")
            rows_html.append(f"""
      <div class="sxm-offmenu-row">
        <div class="sxm-offmenu-main">
          <div class="sxm-offmenu-head"><h3 class="sxm-offmenu-name">{safe(o['name'])}</h3>{_duration(o)}</div>
          {desc_html}
        </div>
        <div class="sxm-offmenu-end">{_price(o)}{r_cta}</div>
      </div>""")
        html = f"""
<section class="sxm-section sxm-offerings sxm-off-menu sxm-reveal" id="offerings">
  <div class="sxm-inner">
    {heading_accent(dna)}
    {eb}
    <h2 {ov('offerings', 'headline')}>{accent_headline(headline)}</h2>
    {intro_html}
    <div class="sxm-offmenu">{''.join(rows_html)}
    </div>
  </div>
</section>"""
        css = """
.sxm-offerings h2 { margin-bottom: 16px; }
.sxm-off-intro { font-size: 1.05rem; margin-bottom: 12px; }
.sxm-off-desc { font-size: .96rem; margin: 8px 0 0; max-width: 52ch; }
.sxm-off-dur { font-size: .8rem; white-space: nowrap; color: var(--sx-muted); }
.sxm-offmenu { margin-top: 38px; border-top: 1px solid var(--sx-border); }
.sxm-offmenu-row { position: relative; display: flex; justify-content: space-between;
  align-items: baseline; gap: clamp(18px, 4vw, 44px); padding: 26px 4px;
  border-bottom: 1px solid var(--sx-border);
  transition: padding-left .45s var(--sx-ease); }
.sxm-offmenu-row::before { content: ""; position: absolute; top: -1px; left: 0;
  height: 1px; width: 100%; background: var(--sx-accent);
  transform: scaleX(0); transform-origin: left;
  transition: transform .6s var(--sx-ease); }
.sxm-offmenu-row:hover { padding-left: 1rem; }
.sxm-offmenu-row:hover::before { transform: scaleX(1); }
.sxm-offmenu-head { display: flex; align-items: baseline; gap: 16px; }
.sxm-offmenu-name { font-family: var(--sx-font-heading); font-style: italic;
  font-weight: var(--sx-h2-weight, var(--sx-heading-weight));
  font-size: 1.45rem; letter-spacing: var(--sx-letter-tight); }
.sxm-offmenu-end { display: flex; align-items: baseline; gap: 20px; flex-shrink: 0;
  text-align: right; }
.sxm-offmenu-end .sxm-off-price { white-space: nowrap; }
.sxm-offmenu-book { font-weight: 700; font-size: .78rem; letter-spacing: .08em;
  padding: 7px 15px; border: 1px solid var(--sx-accent);
  border-radius: var(--sx-radius-button); transition: background .15s, color .15s; }
.sxm-offmenu-book:hover { background: var(--sx-accent); color: var(--sx-on-accent); }
@media (max-width: 700px) {
  .sxm-offmenu-row { flex-direction: column; align-items: flex-start; gap: 12px; }
  .sxm-offmenu-end { text-align: left; }
}
@media (prefers-reduced-motion: reduce) {
  .sxm-offmenu-row, .sxm-offmenu-row::before { transition: none; }
  .sxm-offmenu-row:hover { padding-left: 4px; }
}"""
        return html, css

    # Cards get the shared quality-floor depth/hover; list rows stay flat.
    item_class = "sxm-off-item" if variant == "list" else "sxm-off-item sxm-card"
    items = []
    for o in rows:
        cta = (f'<a class="sxm-off-book" href="{book_href}" {ov("offerings", "book_label")}>Book</a>'
               if book_href else "")
        desc = safe(o.get("description") or "")
        desc_html = f'<p class="sxm-off-desc sxm-muted">{desc}</p>' if desc else ""
        items.append(f"""
      <div class="{item_class}">
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
    <h2 {ov('offerings', 'headline')}>{accent_headline(headline)}</h2>
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
