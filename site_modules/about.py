"""About module — 3 variants. Content: eyebrow, headline, body,
pull_quote (optional). Image slot: about_subject (portrait/pullquote).
'pullquote' (Arc 3) is the editorial spread: a large pulled line +
narrative column + portrait with an offset frame ornament."""
from __future__ import annotations

import re
from typing import Any, Dict, Tuple

from ._base import safe, ov, eyebrow, heading_accent

VARIANTS = ("portrait", "narrative", "pullquote")


def _pulled_line(content: Dict[str, Any], body: str) -> str:
    """The line the spread pulls large: the composer's pull_quote when
    present, else the first sentence of the about copy (magazines pull
    verbatim from the article — so do we). Word-boundary capped."""
    quote = str(content.get("pull_quote") or "").strip()
    if not quote:
        parts = re.split(r"(?<=[.!?])\s+", body.strip(), maxsplit=1)
        quote = parts[0] if parts else body
    if len(quote) > 160:
        quote = quote[:160].rsplit(" ", 1)[0].rstrip(",;:—- ") + "…"
    return quote


def _backfill_body(ctx: Dict[str, Any]) -> str:
    """Real-data fallback for an empty about body: the practitioner's
    own about_business prose (brand bundle), trimmed ~400 chars on a
    word boundary. Never generated."""
    intel = (ctx.get("bundle") or {}).get("practitioner_intelligence") or {}
    blob = " ".join(str(intel.get("about_business") or "").split())
    if not blob:
        return ""
    if len(blob) <= 400:
        return blob
    cut = blob[:400].rsplit(" ", 1)[0].rstrip(",;:—- ")
    return cut + "…"


def render(variant: str, content: Dict[str, Any], ctx: Dict[str, Any]) -> Tuple[str, str]:
    dna = ctx["dna"]
    eb = eyebrow("about", content.get("eyebrow") or "About")
    headline = content.get("headline") or "The practice"
    body = (content.get("body") or "").strip() or _backfill_body(ctx)
    if not body:
        # Nothing real to say → no section. Never render heading-only.
        return "", ""
    quote = content.get("pull_quote") or ""
    # Meaningful portrait alt: the practitioner (or the business) by name.
    who = ((ctx.get("bundle") or {}).get("practitioner") or {}).get("display_name") or ""
    if not who or who == "The Practitioner":
        who = (ctx.get("business") or {}).get("name") or "Portrait"
    img_alt = safe(who)
    quote_html = (f'<blockquote class="sxm-about-quote" {ov("about", "pull_quote")}>{safe(quote)}</blockquote>'
                  if quote else "")

    if variant == "pullquote":
        # Arc 3 editorial spread (craft source: cathedral quote_anchor +
        # framed-panel image w/ the frame line broken by an offset —
        # ported into token discipline). Frame ornament is pure CSS.
        pulled = _pulled_line(content, body)
        html = f"""
<section class="sxm-section sxm-about-pq sxm-reveal" id="about">
  <div class="sxm-inner">
    {heading_accent(dna)}
    {eb}
    <blockquote class="sxm-pq-line" {ov('about', 'pull_quote')}>{safe(pulled)}</blockquote>
    <div class="sxm-pq-grid">
      <div class="sxm-pq-col">
        <h2 {ov('about', 'headline')}>{safe(headline)}</h2>
        <p class="sxm-about-body" {ov('about', 'body')}>{safe(body)}</p>
      </div>
      <div class="sxm-pq-photo">
        <div class="sxm-imgbox">
          <img data-slot="about_subject" src="" alt="{img_alt}">
        </div>
      </div>
    </div>
  </div>
</section>"""
        css = """
.sxm-about-pq { background: var(--sx-surface); }
.sxm-pq-line { margin: 6px 0 44px; font-family: var(--sx-font-heading);
  font-size: clamp(1.7rem, 3.6vw, 2.7rem); line-height: 1.28; font-style: italic; max-width: 26ch; }
.sxm-pq-line::before { content: "\\201C"; color: var(--sx-accent); margin-right: 8px; }
.sxm-pq-grid { display: grid; grid-template-columns: 1.15fr .85fr; gap: clamp(32px, 6vw, 80px); align-items: start; }
.sxm-pq-col h2 { margin-bottom: 18px; }
.sxm-pq-col .sxm-about-body { font-size: 1.06rem; }
.sxm-pq-photo { position: relative; padding: 0 18px 18px 0; }
.sxm-pq-photo::before { content: ""; position: absolute; top: 18px; left: 18px; right: 0; bottom: 0;
  border: 2px solid color-mix(in srgb, var(--sx-accent) 55%, transparent);
  border-radius: var(--sx-radius-image); }
.sxm-pq-photo .sxm-imgbox { position: relative; z-index: 1; }
.sxm-pq-photo img { width: 100%; aspect-ratio: 4/5; object-fit: cover; display: block; }
@media (max-width: 860px) { .sxm-pq-grid { grid-template-columns: 1fr; } }"""
        return html, css

    if variant == "narrative":
        html = f"""
<section class="sxm-section sxm-about-narrative sxm-reveal" id="about">
  <div class="sxm-inner sxm-about-narrow">
    {heading_accent(dna)}
    {eb}
    <h2 {ov('about', 'headline')}>{safe(headline)}</h2>
    <p class="sxm-about-body" {ov('about', 'body')}>{safe(body)}</p>
    {quote_html}
  </div>
</section>"""
        css = """
.sxm-about-narrative { background: var(--sx-surface); }
.sxm-about-narrow { max-width: 760px; }
.sxm-about-narrative h2 { margin-bottom: 22px; }
.sxm-about-body { font-size: 1.08rem; }
.sxm-about-quote { margin: 30px 0 0; padding-left: 22px; border-left: 3px solid var(--sx-accent);
  font-family: var(--sx-font-heading); font-size: 1.3rem; font-style: italic; line-height: 1.4; }"""
        return html, css

    # default: portrait (split image/text)
    html = f"""
<section class="sxm-section sxm-about-portrait sxm-reveal" id="about">
  <div class="sxm-inner sxm-about-grid">
    <div class="sxm-about-photo sxm-imgbox">
      <img data-slot="about_subject" src="" alt="{img_alt}">
    </div>
    <div>
      {heading_accent(dna)}
      {eb}
      <h2 {ov('about', 'headline')}>{safe(headline)}</h2>
      <p class="sxm-about-body" {ov('about', 'body')}>{safe(body)}</p>
      {quote_html}
    </div>
  </div>
</section>"""
    css = """
.sxm-about-portrait { background: var(--sx-surface); }
.sxm-about-grid { display: grid; grid-template-columns: .8fr 1.2fr; gap: clamp(32px, 6vw, 76px); align-items: center; }
.sxm-about-photo img { width: 100%; aspect-ratio: 4/5; object-fit: cover; border-radius: var(--sx-radius-image); }
.sxm-about-portrait h2 { margin-bottom: 20px; }
.sxm-about-body { font-size: 1.06rem; }
.sxm-about-quote { margin: 28px 0 0; padding-left: 22px; border-left: 3px solid var(--sx-accent);
  font-family: var(--sx-font-heading); font-size: 1.25rem; font-style: italic; line-height: 1.4; }
@media (max-width: 860px) { .sxm-about-grid { grid-template-columns: 1fr; } }"""
    return html, css
