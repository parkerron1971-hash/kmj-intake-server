"""Contact + footer module — always last, always FUNCTIONAL. Wires to the
real things the business runs: a working contact form (POSTs to the live
/sites/{id}/contact-submit endpoint, which creates a contact + emails the
owner), the booking page when enabled, plus real logistics (hours, address,
phone) and social links. Falls back to a mailto when no form endpoint is
available. Content: headline, note, cta_label."""
from __future__ import annotations

from typing import Any, Dict, Tuple

from ._base import safe, safe_url, ov, heading_accent

VARIANTS = ("standard",)

_SOCIAL = {
    "instagram": ("\U0001F4F8", "https://instagram.com/"),
    "facebook": ("\U0001F4D8", "https://facebook.com/"),
    "youtube": ("\U0001F4FA", "https://youtube.com/"),
    "twitter": ("\U0001F426", "https://twitter.com/"),
    "linkedin": ("\U0001F4BC", "https://linkedin.com/in/"),
    "tiktok": ("\U0001F3B5", "https://tiktok.com/@"),
}


def _social_links(social: Dict[str, Any]) -> str:
    out = []
    for plat, handle in (social or {}).items():
        if not handle:
            continue
        icon, base = _SOCIAL.get(plat, ("\U0001F517", ""))
        h = str(handle).strip()
        url = h if h.startswith("http") else (base + h.lstrip("@") if base else "#")
        out.append(f'<a class="sxm-social" href="{safe_url(url)}" target="_blank" '
                   f'rel="noopener" title="{safe(plat)}">{icon}</a>')
    return f'<div class="sxm-contact-social">{"".join(out)}</div>' if out else ""


def _logistics(contact: Dict[str, Any]) -> str:
    bits = []
    if contact.get("hours"):
        bits.append(f'<span class="sxm-muted">\U0001F557 {safe(contact["hours"])}</span>')
    if contact.get("address"):
        bits.append(f'<span class="sxm-muted">\U0001F4CD {safe(contact["address"])}</span>')
    if contact.get("phone"):
        bits.append(f'<a class="sxm-muted" href="tel:{safe_url(contact["phone"])}">\U0001F4DE {safe(contact["phone"])}</a>')
    return f'<div class="sxm-contact-logistics">{"".join(bits)}</div>' if bits else ""


def render(variant: str, content: Dict[str, Any], ctx: Dict[str, Any]) -> Tuple[str, str]:
    dna = ctx["dna"]
    biz = ctx.get("business") or {}
    booking = ctx.get("booking") or {}
    contact = ctx.get("contact") or {}

    headline = content.get("headline") or "Get in touch"
    note = content.get("note") or ""
    note_html = f'<p class="sxm-muted" {ov("contact", "note")}>{safe(note)}</p>' if note else ""

    # Primary action: booking page when enabled.
    cta_html = ""
    if booking.get("enabled") and booking.get("url"):
        cta_html = (f'<a class="sxm-cta" href="{safe_url(booking["url"])}">'
                    f'<span {ov("contact", "cta_label")}>{safe(content.get("cta_label") or "Book now")}</span></a>')

    # Real contact form → the live submit endpoint. mailto is the fallback.
    email = (contact.get("email") or "").strip()
    submit_url = contact.get("submit_url") or ""
    form_html = ""
    script_html = ""
    if submit_url:
        form_html = f"""
    <form id="sxm-contact-form" class="sxm-contact-form" data-endpoint="{safe_url(submit_url)}">
      <input name="name" type="text" placeholder="Your name" required>
      <input name="email" type="email" placeholder="Your email" required>
      <textarea name="message" rows="4" placeholder="How can we help?" required></textarea>
      <button type="submit" class="sxm-cta">Send message</button>
    </form>"""
        script_html = """
<script>
(function(){
  var f=document.getElementById('sxm-contact-form'); if(!f) return;
  f.addEventListener('submit', function(ev){
    ev.preventDefault();
    var fd=new FormData(f), b=f.querySelector('button');
    b.disabled=true; b.textContent='Sending…';
    fetch(f.getAttribute('data-endpoint'),{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({name:fd.get('name'),email:fd.get('email'),message:fd.get('message')})})
      .then(function(r){return r.json();})
      .then(function(){ f.innerHTML='<p class="sxm-sent">Thanks — your message is on its way.</p>'; })
      .catch(function(){ b.disabled=false; b.textContent='Send message'; });
  });
})();
</script>"""
    mail_html = (f'<a class="sxm-contact-mail" href="mailto:{safe_url(email)}">{safe(email)}</a>'
                 if email and "@" in email else "")

    footer_line = safe((ctx.get("footer") or {}).get("copyright_line")
                       or f"© {biz.get('name') or ''}")

    html = f"""
<section class="sxm-section sxm-contact sxm-reveal" id="contact">
  <div class="sxm-inner sxm-contact-inner">
    {heading_accent(dna)}
    <h2 {ov('contact', 'headline')}>{safe(headline)}</h2>
    {note_html}
    {f'<div class="sxm-contact-actions">{cta_html}</div>' if cta_html else ''}
    {form_html}
    {_logistics(contact)}
    {mail_html}
    {_social_links(contact.get("social") or {})}
  </div>
</section>
<footer class="sxm-footer">
  <div class="sxm-inner sxm-footer-inner">
    <span>{footer_line}</span>
    <a href="https://mysolutionist.app/" target="_blank" rel="noopener" class="sxm-footer-power">Powered by Solutionist</a>
  </div>
</footer>{script_html}"""
    css = """
.sxm-contact-inner { text-align: center; max-width: 640px; }
.sxm-contact .sxm-mark { margin-left: auto; margin-right: auto; }
.sxm-contact h2 { margin-bottom: 14px; }
.sxm-contact-actions { display: flex; gap: 22px; justify-content: center; align-items: center; flex-wrap: wrap; margin: 24px 0; }
.sxm-contact-form { display: flex; flex-direction: column; gap: 12px; max-width: 460px; margin: 26px auto 8px; text-align: left; }
.sxm-contact-form input, .sxm-contact-form textarea { padding: 13px 15px; font: inherit; color: var(--sx-text);
  background: var(--sx-surface); border: 1px solid var(--sx-border); border-radius: var(--sx-radius-card); width: 100%; box-sizing: border-box; }
.sxm-contact-form button { margin-top: 4px; cursor: pointer; }
.sxm-sent { font-size: 1.05rem; font-weight: 600; color: var(--sx-accent); text-align: center; }
.sxm-contact-logistics { display: flex; gap: 22px; justify-content: center; flex-wrap: wrap; margin-top: 22px; font-size: .92rem; }
.sxm-contact-mail { display: inline-block; margin-top: 16px; font-size: 1rem; font-weight: 600; border-bottom: 1.5px solid var(--sx-accent); padding-bottom: 2px; }
.sxm-contact-social { display: flex; gap: 16px; justify-content: center; margin-top: 20px; font-size: 1.5rem; }
.sxm-contact-social a { text-decoration: none; }
.sxm-footer { border-top: 1px solid var(--sx-border); padding: 26px var(--sx-gutter); }
.sxm-footer-inner { display: flex; justify-content: space-between; align-items: center; gap: 14px; flex-wrap: wrap; font-size: .82rem; color: var(--sx-muted); }
.sxm-footer-power { color: var(--sx-muted); }
.sxm-footer-power:hover { color: var(--sx-accent); }"""
    return html, css
