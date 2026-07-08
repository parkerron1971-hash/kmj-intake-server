"""Contact + footer module — always last, always FUNCTIONAL. Wires to the
real things the business runs: a working contact form (POSTs to the live
/sites/{id}/contact-submit endpoint, which creates a contact + emails the
owner), the booking page when enabled, plus real logistics (hours, address,
phone) and social links. Falls back to a mailto when no form endpoint is
available. Content: headline, note, cta_label.

Site Arc 11b — THE FINALE: the closing section is a composition, not a
column. Desktop = two columns: LEFT the invitation (accent headline,
note, direct channels as hairline rows with whisper labels), RIGHT the
form as a crafted card (surface elevation, roomy inputs, accent focus
ring, full-width premium send). Mobile stacks invitation → card; no
form → the invitation holds the center alone. Deterministic and
never-bespoke, exactly as before.

CONSENT ELEGANCE (Site Arc 11b): the SMS consent block (checkbox +
full A2P disclosure) reveals only once the phone field has input —
the booking widget's progressive pattern. The node stays in the DOM
hidden by a class; without JS it is simply visible (graceful
fallback). While the phone is empty the form shows one whisper line
instead of the legal wall. The disclosure WORDING and the recorded
payload are byte-identical to Arc 11 whenever shown."""
from __future__ import annotations

from typing import Any, Dict, Tuple

from ._base import (safe, safe_url, ov, heading_accent, social_profile_url,
                    accent_headline, diamond_mark)

VARIANTS = ("standard",)

# Display names for social platforms — links carry REAL text labels
# (accessibility: never emoji-only anchors).
_SOCIAL_NAMES = {
    "instagram": "Instagram",
    "facebook": "Facebook",
    "youtube": "YouTube",
    "twitter": "Twitter",
    "linkedin": "LinkedIn",
    "tiktok": "TikTok",
}


def _social_links(social: Dict[str, Any]) -> str:
    """The socials as one channel row: whisper 'Follow' label + real
    text links. Empty handles → '' (the row never renders bare)."""
    out = []
    for plat, handle in (social or {}).items():
        if not handle:
            continue
        url = social_profile_url(plat, handle)
        if not url:
            continue
        label = _SOCIAL_NAMES.get((plat or "").lower(), str(plat).strip().title() or "Profile")
        # Site Arc 10: social labels speak in the whisper voice — the
        # third type voice on the contact chapter's small labels.
        out.append(f'<a class="sxm-social sxm-whisper" href="{safe_url(url)}" target="_blank" '
                   f'rel="noopener" aria-label="{safe(label)}">{safe(label)}</a>')
    if not out:
        return ""
    return ('<div class="sxm-contact-social sxm-channel">'
            '<span class="sxm-whisper sxm-channel-label">Follow</span>'
            f'<span class="sxm-channel-body">{"".join(out)}</span></div>')


def _logistics(contact: Dict[str, Any]) -> str:
    """Phone / hours / address as elegant channel rows (whisper labels).
    The wrapper keeps class sxm-contact-logistics — the Arc 11
    editability exemption + smoke contract ride on it; display:contents
    lets the rows sit in the channels column."""
    bits = []
    if contact.get("phone"):
        bits.append('<div class="sxm-channel">'
                    '<span class="sxm-whisper sxm-channel-label">Phone</span>'
                    f'<a href="tel:{safe_url(contact["phone"])}">{safe(contact["phone"])}</a></div>')
    if contact.get("hours"):
        bits.append('<div class="sxm-channel">'
                    '<span class="sxm-whisper sxm-channel-label">Hours</span>'
                    f'<span class="sxm-channel-text">{safe(contact["hours"])}</span></div>')
    if contact.get("address"):
        bits.append('<div class="sxm-channel">'
                    '<span class="sxm-whisper sxm-channel-label">Visit</span>'
                    f'<span class="sxm-channel-text">{safe(contact["address"])}</span></div>')
    return f'<div class="sxm-contact-logistics">{"".join(bits)}</div>' if bits else ""


def _sms_consent_block(ctx: Dict[str, Any]) -> str:
    """SMS opt-in for the contact form (A2P compliance, Arc 1). Rendered
    ONLY when the platform can actually text (contact.sms_capable) and
    only inside a real form. UNCHECKED by default; wording mirrors the
    booking-widget / /sms opt-in disclosure. Includes an optional phone
    field — consent without a number is unrecordable.

    Site Arc 11 (connections): an explicit owner connections.sms_updates
    = False hides the affordance even on an SMS-capable platform; True
    (or absent) keeps the capability-gated default. The disclosure
    wording is COMPLIANCE COPY — deliberately un-targeted (see _base).

    Site Arc 11b (consent elegance): the disclosure reveals only once
    the phone field has input — JS arms the form (sxm-consent-armed)
    and toggles sxm-consent-open as the number is typed; while empty, a
    single whisper hint line shows instead. No JS → no armed class →
    the disclosure is simply visible (compliance never depends on JS).
    The disclosure text below is BYTE-IDENTICAL to Arc 11."""
    conn = (ctx.get("connections")
            if isinstance(ctx.get("connections"), dict) else {})
    if conn.get("sms_updates") is False:
        return ""
    if not (ctx.get("contact") or {}).get("sms_capable"):
        return ""
    biz_name = safe((ctx.get("business") or {}).get("name") or "this business")
    return f"""
      <input name="phone" type="tel" autocomplete="tel" placeholder="Mobile number">
      <p class="sxm-consent-hint sxm-whisper" {ov("contact", "sms_hint")}>Add your mobile for text updates (optional)</p>
      <label class="sxm-sms-consent">
        <input type="checkbox" name="sms_consent" value="1">
        <span>By checking this box, I agree to receive SMS messages from {biz_name}
        via The Solutionist System (replies, confirmations, and reminders). Consent is
        not a condition of any purchase. Message frequency varies. Message and data
        rates may apply. Reply <strong>STOP</strong> to opt out at any time, or
        <strong>HELP</strong> for help.</span>
      </label>"""


def render(variant: str, content: Dict[str, Any], ctx: Dict[str, Any]) -> Tuple[str, str]:
    dna = ctx["dna"]
    biz = ctx.get("business") or {}
    booking = ctx.get("booking") or {}
    contact = ctx.get("contact") or {}
    # Site Arc 11 — explicit owner connections (absent dict → every
    # behavior below is byte-identical to the pre-Arc-11 auto defaults).
    conn = (ctx.get("connections")
            if isinstance(ctx.get("connections"), dict) else {})

    headline = content.get("headline") or "Get in touch"
    note = content.get("note") or ""
    note_html = f'<p class="sxm-muted" {ov("contact", "note")}>{safe(note)}</p>' if note else ""

    # Primary action: booking page when enabled.
    cta_html = ""
    if booking.get("enabled") and booking.get("url"):
        cta_html = (f'<a class="sxm-cta" href="{safe_url(booking["url"])}">'
                    f'<span {ov("contact", "cta_label")}>{safe(content.get("cta_label") or "Book now")}</span></a>')

    # Real contact form → the live submit endpoint. mailto is the fallback.
    # Site Arc 11: connections.contact_form=False renders the channels
    # (mailto / logistics / socials) WITHOUT the form — explicit owner
    # intent; absent/True keeps the endpoint-gated default.
    email = (contact.get("email") or "").strip()
    submit_url = contact.get("submit_url") or ""
    form_html = ""
    script_html = ""
    if submit_url and conn.get("contact_form") is not False:
        form_html = f"""
    <form id="sxm-contact-form" class="sxm-contact-form" data-endpoint="{safe_url(submit_url)}">
      <input name="name" type="text" placeholder="Your name" required>
      <input name="email" type="email" placeholder="Your email" required>
      <textarea name="message" rows="5" placeholder="How can we help?" required></textarea>{_sms_consent_block(ctx)}
      <button type="submit" class="sxm-cta" {ov('contact', 'send_label')}>Send message</button>
    </form>"""
        script_html = """
<script>
(function(){
  var f=document.getElementById('sxm-contact-form'); if(!f) return;
  var p=f.querySelector('input[name="phone"]');
  if(p){
    f.classList.add('sxm-consent-armed');
    var sync=function(){
      if(p.value.replace(/\\s/g,'')){ f.classList.add('sxm-consent-open'); }
      else { f.classList.remove('sxm-consent-open'); }
    };
    p.addEventListener('input',sync); sync();
  }
  f.addEventListener('submit', function(ev){
    ev.preventDefault();
    var fd=new FormData(f), b=f.querySelector('button'), orig=b.textContent;
    b.disabled=true; b.textContent='Sending…';
    var payload={name:fd.get('name'),email:fd.get('email'),message:fd.get('message')};
    var ph=fd.get('phone'); if(ph){ payload.phone=ph; }
    var c=f.querySelector('input[name="sms_consent"]');
    if(c){ payload.sms_consent=!!c.checked; }
    fetch(f.getAttribute('data-endpoint'),{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify(payload)})
      .then(function(r){return r.json();})
      .then(function(){ f.innerHTML='<p class="sxm-sent">Thanks — your message is on its way.</p>'; })
      .catch(function(){ b.disabled=false; b.textContent=orig; });
  });
})();
</script>"""
    mail_html = ('<div class="sxm-contact-mail sxm-channel">'
                 '<span class="sxm-whisper sxm-channel-label">Email</span>'
                 f'<a href="mailto:{safe_url(email)}">{safe(email)}</a></div>'
                 if email and "@" in email else "")

    # Site Arc 11: connections.socials=False suppresses the social links
    # even when handles exist; True/absent keeps the data-gated default
    # (links only ever render from REAL handles — never invented).
    social_html = ("" if conn.get("socials") is False
                   else _social_links(contact.get("social") or {}))

    channels = mail_html + _logistics(contact) + social_html
    channels_html = (f'<div class="sxm-contact-channels">{channels}</div>'
                     if channels else "")

    # Footer line is presentation text → targeted (total editability).
    # "Powered by Solutionist" is platform chrome → un-targeted by design.
    footer_line = safe((ctx.get("footer") or {}).get("copyright_line")
                       or f"© {biz.get('name') or ''}")

    # Site Arc 11: the SMS invitation line — only with the owner's
    # explicit sms_updates connection AND a real routing keyword on file
    # (gather_context fetches it). Whisper voice, targeted.
    sms_keyword = str(contact.get("sms_keyword") or "").strip()
    sms_line_html = ""
    if conn.get("sms_updates") and sms_keyword and contact.get("sms_capable"):
        sms_line_html = (f'\n    <span class="sxm-footer-sms" '
                         f'{ov("contact", "sms_line")}>Text {safe(sms_keyword)} '
                         f'to connect</span>')

    # THE FINALE COMPOSITION (Site Arc 11b): invitation column + form
    # card. No form → the invitation holds the center alone (solo).
    invite_html = f"""
    <div class="sxm-contact-invite">
      {heading_accent(dna)}
      <h2 {ov('contact', 'headline')}>{accent_headline(headline)}</h2>
      {note_html}
      {f'<div class="sxm-contact-actions">{cta_html}</div>' if cta_html else ''}
      {channels_html}
    </div>"""
    card_html = (f'\n    <div class="sxm-contact-formcard">{form_html}\n    </div>'
                 if form_html else "")
    solo = "" if form_html else " sxm-contact-solo"

    html = f"""
<section class="sxm-section sxm-contact sxm-reveal" id="contact">
  <div class="sxm-inner sxm-contact-inner{solo}">{invite_html}{card_html}
  </div>
</section>
<footer class="sxm-footer">
  <div class="sxm-inner sxm-footer-inner sxm-whisper">
    <span class="sxm-footer-brand">{diamond_mark(dna)}<span {ov('contact', 'footer_line')}>{footer_line}</span></span>{sms_line_html}
    <a href="https://mysolutionist.app/" target="_blank" rel="noopener" class="sxm-footer-power">Powered by Solutionist</a>
  </div>
</footer>{script_html}"""
    css = """
/* THE FINALE (Site Arc 11b): desktop two columns — invitation | form
   card; mobile stacks invitation then card. */
.sxm-contact-inner { display: grid; grid-template-columns: 1fr 1fr;
  gap: clamp(44px, 7vw, 96px); align-items: start; }
.sxm-contact-invite { text-align: left; max-width: 520px; }
.sxm-contact h2 { margin-bottom: 14px; }
.sxm-contact-actions { display: flex; gap: 22px; align-items: center; flex-wrap: wrap; margin: 26px 0 6px; }
/* Solo finale (no form): the invitation holds the center alone. */
.sxm-contact-solo { grid-template-columns: 1fr; justify-items: center; }
.sxm-contact-solo .sxm-contact-invite { text-align: center; }
.sxm-contact-solo .sxm-mark { margin-left: auto; margin-right: auto; }
.sxm-contact-solo .sxm-contact-actions { justify-content: center; }
.sxm-contact-solo .sxm-channel { justify-content: center; }
/* Direct channels — hairline rows, whisper labels. */
.sxm-contact-channels { margin-top: 36px; display: flex; flex-direction: column;
  border-top: 1px solid var(--sx-border); }
.sxm-contact-logistics { display: contents; }
.sxm-channel { display: flex; align-items: baseline; gap: 18px; padding: 14px 2px;
  border-bottom: 1px solid var(--sx-border); font-size: .95rem; }
.sxm-channel-label { flex: 0 0 72px; }
.sxm-channel a { font-weight: 600; }
.sxm-channel-text { color: var(--sx-text); }
.sxm-channel-body { display: flex; gap: 10px 18px; flex-wrap: wrap; }
.sxm-contact-social .sxm-social { text-decoration: none;
  border-bottom: 1.5px solid var(--sx-accent-soft); padding-bottom: 1px; }
.sxm-contact-social .sxm-social:hover { border-bottom-color: var(--sx-accent); }
/* The form as a crafted card — soft surface elevation. */
.sxm-contact-formcard { background: var(--sx-surface); border: 1px solid var(--sx-border);
  border-radius: var(--sx-radius-card); padding: clamp(26px, 3.6vw, 46px);
  box-shadow: 0 26px 70px rgba(0, 0, 0, .16); }
/* FORM ALIGNMENT CONTRACT (Site Arc 11): the card holds the form, and
   INSIDE the form every control shares ONE left edge — inputs,
   textarea, consent row and submit all start at the form's left edge,
   full form width, left-aligned text. Nothing inside the form may
   inherit a centered ancestor. */
.sxm-contact-form { display: flex; flex-direction: column; align-items: stretch; gap: 14px;
  width: 100%; text-align: left; }
.sxm-contact-form input, .sxm-contact-form textarea { padding: 15px 17px; font: inherit; color: var(--sx-text);
  background: var(--sx-bg); border: 1px solid var(--sx-border); border-radius: var(--sx-radius-card); width: 100%; box-sizing: border-box;
  text-align: left; transition: border-color .25s var(--sx-ease), box-shadow .25s var(--sx-ease); }
.sxm-contact-form input::placeholder, .sxm-contact-form textarea::placeholder { color: var(--sx-muted); }
.sxm-contact-form input:focus, .sxm-contact-form textarea:focus { outline: none;
  border-color: var(--sx-accent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--sx-accent) 22%, transparent); }
.sxm-contact-form button { margin-top: 6px; width: 100%; cursor: pointer; }  /* full-width premium send — same left edge */
/* SMS consent row — a proper left-aligned flex row: checkbox top-aligned
   with the first text line, disclosure text explicitly LEFT-aligned (a
   centered ancestor can never recenter it), readable measure, muted. */
.sxm-sms-consent { display: flex; flex-direction: row; gap: 10px; align-items: flex-start;
  justify-content: flex-start; text-align: left; max-width: 52ch; width: 100%;
  margin: 0; font-size: .8rem; line-height: 1.6; color: var(--sx-muted); cursor: pointer; }
.sxm-sms-consent input { margin: 4px 0 0; flex-shrink: 0; width: auto; accent-color: var(--sx-accent); }
.sxm-sms-consent span { flex: 1 1 auto; min-width: 0; text-align: left; display: block; }
/* CONSENT ELEGANCE (Site Arc 11b): JS arms the form; armed + empty
   phone → one whisper hint instead of the legal wall; typing a number
   opens the full disclosure. No JS → never armed → the disclosure
   stays visible (compliance without JavaScript). */
.sxm-consent-hint { display: none; margin: 0; font-size: .68rem; letter-spacing: .18em; }
.sxm-contact-form.sxm-consent-armed .sxm-consent-hint { display: block; }
.sxm-contact-form.sxm-consent-armed.sxm-consent-open .sxm-consent-hint { display: none; }
.sxm-contact-form.sxm-consent-armed .sxm-sms-consent { display: none; }
.sxm-contact-form.sxm-consent-armed.sxm-consent-open .sxm-sms-consent { display: flex; }
.sxm-sent { font-size: 1.05rem; font-weight: 600; color: var(--sx-accent); text-align: center; }
@media (max-width: 900px) {
  .sxm-contact-inner { grid-template-columns: 1fr; gap: 44px; }
  .sxm-contact-invite { max-width: none; }
}
.sxm-footer { border-top: 1px solid var(--sx-border); padding: 26px var(--sx-gutter); }
.sxm-footer-brand { display: inline-flex; align-items: center; }
.sxm-footer-inner { display: flex; justify-content: space-between; align-items: center; gap: 14px; flex-wrap: wrap; font-size: .82rem; color: var(--sx-muted); }
.sxm-footer-power { color: var(--sx-muted); }
.sxm-footer-power:hover { color: var(--sx-accent); }
.sxm-footer-sms { color: var(--sx-accent); white-space: nowrap; }"""
    return html, css
