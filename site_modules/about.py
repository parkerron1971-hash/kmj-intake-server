"""About module — 2 variants. Content: eyebrow, headline, body,
pull_quote (optional). Image slot: about_subject (portrait variant)."""
from __future__ import annotations

from typing import Any, Dict, Tuple

from ._base import safe, ov, eyebrow, heading_accent

VARIANTS = ("portrait", "narrative")


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
    <div class="sxm-about-photo">
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
