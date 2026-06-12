"""Contact + footer module — always last, always functional: booking
link when enabled, mailto when an email exists, brand footer line from
the Brand Engine bundle. Content: headline, note."""
from __future__ import annotations

from typing import Any, Dict, Tuple

from ._base import safe, safe_url, ov, heading_accent

VARIANTS = ("standard",)


def render(variant: str, content: Dict[str, Any], ctx: Dict[str, Any]) -> Tuple[str, str]:
    dna = ctx["dna"]
    biz = ctx.get("business") or {}
    booking = ctx.get("booking") or {}
    contact = ctx.get("contact") or {}

    headline = content.get("headline") or "Get in touch"
    note = content.get("note") or ""
    note_html = f'<p class="sxm-muted" {ov("contact", "note")}>{safe(note)}</p>' if note else ""

    actions = []
    if booking.get("enabled") and booking.get("url"):
        actions.append(f'<a class="sxm-cta" href="{safe_url(booking["url"])}">'
                       f'<span {ov("contact", "cta_label")}>{safe(content.get("cta_label") or "Book now")}</span></a>')
    email = (contact.get("email") or "").strip()
    if email and "@" in email:
        actions.append(f'<a class="sxm-contact-mail" href="mailto:{safe_url(email)}">{safe(email)}</a>')
    if not actions:
        actions.append(f'<span class="sxm-muted">Reach out — {safe(biz.get("name") or "we")} would love to hear from you.</span>')

    footer_line = safe((ctx.get("footer") or {}).get("copyright_line")
                       or f"© {biz.get('name') or ''}")

    html = f"""
<section class="sxm-section sxm-contact sxm-reveal" id="contact">
  <div class="sxm-inner sxm-contact-inner">
    {heading_accent(dna)}
    <h2 {ov('contact', 'headline')}>{safe(headline)}</h2>
    {note_html}
    <div class="sxm-contact-actions">{''.join(actions)}</div>
  </div>
</section>
<footer class="sxm-footer">
  <div class="sxm-inner sxm-footer-inner">
    <span>{footer_line}</span>
    <a href="https://mysolutionist.app/" target="_blank" rel="noopener" class="sxm-footer-power">Powered by Solutionist</a>
  </div>
</footer>"""
    css = """
.sxm-contact-inner { text-align: center; max-width: 680px; }
.sxm-contact .sxm-mark { margin-left: auto; margin-right: auto; }
.sxm-contact h2 { margin-bottom: 14px; }
.sxm-contact-actions { display: flex; gap: 22px; justify-content: center; align-items: center;
  flex-wrap: wrap; margin-top: 28px; }
.sxm-contact-mail { font-size: 1.02rem; font-weight: 600; border-bottom: 1.5px solid var(--sx-accent); padding-bottom: 2px; }
.sxm-footer { border-top: 1px solid var(--sx-border); padding: 26px var(--sx-gutter); }
.sxm-footer-inner { display: flex; justify-content: space-between; align-items: center; gap: 14px;
  flex-wrap: wrap; font-size: .82rem; color: var(--sx-muted); }
.sxm-footer-power { color: var(--sx-muted); }
.sxm-footer-power:hover { color: var(--sx-accent); }"""
    return html, css
