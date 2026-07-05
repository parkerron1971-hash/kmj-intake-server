"""Testimonials module — renders REAL testimonials from ctx only
(integrity rule: never invented). Content: eyebrow, headline.
ctx['testimonials'] = [{quote, name|author, role?}] — the canonical store
writes 'name'; 'author' is honored for older rows. Variants: spotlight, grid."""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from ._base import safe, ov, eyebrow, heading_accent, accent_headline

VARIANTS = ("spotlight", "grid", "marquee")

_MAX = 6


def render(variant: str, content: Dict[str, Any], ctx: Dict[str, Any]) -> Tuple[str, str]:
    dna = ctx["dna"]
    # isinstance guard: specs/ctx can carry legacy string entries — one
    # non-dict row must not crash the whole render (self-defense even
    # though gather_context filters too).
    rows: List[Dict[str, Any]] = [t for t in (ctx.get("testimonials") or [])
                                  if isinstance(t, dict) and (t.get("quote") or "").strip()][:_MAX]
    if not rows:
        return "", ""

    eb = eyebrow("testimonials", content.get("eyebrow") or "Kind words")
    headline = content.get("headline") or "What clients say"

    if variant == "spotlight":
        t = rows[0]
        role = f'<span class="sxm-muted"> — {safe(t.get("role"))}</span>' if t.get("role") else ""
        html = f"""
<section class="sxm-section sxm-testi-spot sxm-reveal" id="testimonials">
  <div class="sxm-inner sxm-testi-spot-inner">
    {heading_accent(dna)}
    {eb}
    <blockquote class="sxm-testi-big">{safe(t['quote'])}</blockquote>
    <div class="sxm-testi-attr">{safe(t.get('author') or t.get('name') or 'A client')}{role}</div>
  </div>
</section>"""
        css = """
.sxm-testi-spot { background: var(--sx-surface-2); }
.sxm-testi-spot-inner { max-width: 880px; text-align: center; }
.sxm-testi-spot .sxm-mark, .sxm-testi-spot .sxm-eyebrow { margin-left: auto; margin-right: auto; }
.sxm-testi-big { margin: 18px 0 26px; font-family: var(--sx-font-heading);
  font-size: clamp(1.5rem, 3.2vw, 2.3rem); font-weight: 500; line-height: 1.35; font-style: italic; }
.sxm-testi-attr { font-size: .95rem; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; color: var(--sx-accent); }"""
        return html, css

    if variant == "marquee":
        # Arc 3 — one hero quote oversized under a giant quotation
        # ornament + up to two supporting voices (craft source: cathedral
        # quote_anchor's anchored-quote move, in token discipline). All
        # quotes are REAL ctx rows — never invented.
        t = rows[0]
        role = f'<span class="sxm-muted"> — {safe(t.get("role"))}</span>' if t.get("role") else ""
        support = []
        for s in rows[1:3]:
            s_role = f'<div class="sxm-muted sxm-testi-role">{safe(s.get("role"))}</div>' if s.get("role") else ""
            support.append(f"""
      <figure class="sxm-mq-sup">
        <blockquote>{safe(s['quote'])}</blockquote>
        <figcaption>{safe(s.get('author') or s.get('name') or 'A client')}{s_role}</figcaption>
      </figure>""")
        support_html = (f'<div class="sxm-mq-pair">{"".join(support)}\n    </div>'
                        if support else "")
        html = f"""
<section class="sxm-section sxm-testi-marquee sxm-reveal" id="testimonials">
  <div class="sxm-inner sxm-testi-mq-inner">
    <span class="sxm-mq-mark" aria-hidden="true">“</span>
    {heading_accent(dna)}
    {eb}
    <blockquote class="sxm-mq-big">{safe(t['quote'])}</blockquote>
    <div class="sxm-testi-attr">{safe(t.get('author') or t.get('name') or 'A client')}{role}</div>
    {support_html}
  </div>
</section>"""
        css = """
.sxm-testi-marquee { background: var(--sx-surface-2); overflow: hidden; }
.sxm-testi-mq-inner { position: relative; }
.sxm-mq-mark { position: absolute; top: -48px; left: -14px; font-family: var(--sx-font-heading);
  font-size: clamp(7rem, 16vw, 13rem); line-height: 1; color: var(--sx-accent);
  opacity: .14; pointer-events: none; user-select: none; }
.sxm-mq-big { margin: 20px 0 24px; font-family: var(--sx-font-heading);
  font-size: clamp(1.8rem, 4.2vw, 3.1rem); line-height: 1.25; font-style: italic; max-width: 26ch; }
.sxm-testi-attr { font-size: .95rem; font-weight: 700; letter-spacing: .06em;
  text-transform: uppercase; color: var(--sx-accent); }
.sxm-mq-pair { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 26px; margin-top: 46px; }
.sxm-mq-sup { margin: 0; border-left: 3px solid var(--sx-accent); padding-left: 18px; }
.sxm-mq-sup blockquote { margin: 0 0 12px; font-style: italic; line-height: 1.8; }
.sxm-mq-sup figcaption { font-weight: 700; font-size: .9rem; color: var(--sx-accent); }
.sxm-testi-role { font-weight: 400; font-size: .82rem; margin-top: 2px; }"""
        return html, css

    cards = []
    for t in rows:
        role = f'<div class="sxm-muted sxm-testi-role">{safe(t.get("role"))}</div>' if t.get("role") else ""
        cards.append(f"""
      <figure class="sxm-testi-card sxm-card">
        <blockquote>{safe(t['quote'])}</blockquote>
        <figcaption>{safe(t.get('author') or t.get('name') or 'A client')}{role}</figcaption>
      </figure>""")
    html = f"""
<section class="sxm-section sxm-testi-grid-sec sxm-reveal" id="testimonials">
  <div class="sxm-inner">
    {heading_accent(dna)}
    {eb}
    <h2 {ov('testimonials', 'headline')}>{accent_headline(headline)}</h2>
    <div class="sxm-testi-grid">{''.join(cards)}
    </div>
  </div>
</section>"""
    css = """
.sxm-testi-grid-sec { background: var(--sx-surface-2); }
.sxm-testi-grid-sec h2 { margin-bottom: 34px; }
.sxm-testi-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 22px; }
.sxm-testi-card { margin: 0; background: var(--sx-surface); border: 1px solid var(--sx-border);
  border-radius: var(--sx-radius-card); padding: 28px; }
.sxm-testi-card blockquote { margin: 0 0 18px; font-style: italic; line-height: 1.8; }
.sxm-testi-card figcaption { font-weight: 700; font-size: .9rem; color: var(--sx-accent); }
.sxm-testi-role { font-weight: 400; font-size: .82rem; margin-top: 2px; }"""
    return html, css
