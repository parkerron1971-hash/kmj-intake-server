"""The public page for one client form — /public/widget/form/{form_id}.

Chief has handed out this address since client forms shipped (the
receipt's `embed_url`, the composed site's linked forms, the list verb)
and nothing ever served it: the only public door was POST /intake/submit,
which takes JSON. A practitioner who texted a registration link to a
client sent them to a 404 (2026-09-18, Embrace the Shift Workshop).

This is that page: the form's own fields, in the business's brand, posting
to the intake endpoint the way the booking page posts to its widget. Pure
render function (unit-testable); the routes live in intake_endpoint (API
host) and public_site (the site's own domain, custom domains too).
"""
from __future__ import annotations

import html as _html
import json
from typing import Any, Dict, List

from public_form_theme import resolve_theme, css_vars as theme_css, font_links, safe_url
from urllib.parse import urlsplit

# The honeypot the submit door drops on. Rendered hidden and unlabeled so a
# person never fills it; the endpoint discards any submission that does.
HONEYPOT_NAME = "sol-hp"
_TEXT_TYPES = ("text", "email", "phone", "number", "date", "url")


def _esc(s: Any) -> str:
    return _html.escape(str(s if s is not None else ""), quote=True)


def _field_html(f: Dict[str, Any]) -> str:
    name = str(f.get("name") or "").strip()
    if not name or name in (HONEYPOT_NAME, "_hp"):
        return ""
    label = str(f.get("label") or name).strip()
    ftype = str(f.get("type") or "text").strip().lower()
    required = bool(f.get("required"))
    req_attr = " required" if required else ""
    star = ' <span class="req" aria-hidden="true">*</span>' if required else ""
    fid = "f-" + "".join(c if c.isalnum() else "-" for c in name)
    lab = f'<label for="{fid}">{_esc(label)}{star}</label>'
    if ftype == "textarea":
        ctl = f'<textarea id="{fid}" name="{_esc(name)}" rows="4"{req_attr}></textarea>'
    elif ftype == "select":
        opts = "".join(f'<option value="{_esc(o)}">{_esc(o)}</option>'
                       for o in (f.get("options") or []) if str(o).strip())
        ctl = (f'<select id="{fid}" name="{_esc(name)}"{req_attr}>'
               f'<option value="">Choose…</option>{opts}</select>')
    elif ftype == "checkbox":
        return (f'<div class="field check"><input type="checkbox" id="{fid}" '
                f'name="{_esc(name)}" value="yes"{req_attr}> {lab}</div>')
    else:
        itype = {"phone": "tel", "email": "email", "number": "number",
                 "date": "date", "url": "url"}.get(ftype, "text")
        extra = ' inputmode="numeric"' if ftype == "number" else ""
        ctl = f'<input type="{itype}" id="{fid}" name="{_esc(name)}"{req_attr}{extra}>'
    return f'<div class="field">{lab}{ctl}</div>'


def render_form_page(business: Dict[str, Any], form: Dict[str, Any], *,
                     submit_url: str, canonical_url: str, site=None, embedded=False) -> str:
    """The complete HTML document for one active client form."""
    name = (business.get("name") or "").strip() or "Contact"
    form_name = (form.get("name") or "").strip() or "Get in touch"
    settings = form.get("settings") if isinstance(form.get("settings"), dict) else {}
    description = str(settings.get("description") or "").strip()
    thanks = str(settings.get("confirmation_message") or "Thanks — we'll be in touch soon.").strip()
    fields: List[Dict[str, Any]] = [f for f in (form.get("fields") or []) if isinstance(f, dict)]
    fields_html = "".join(_field_html(f) for f in fields)
    theme = resolve_theme(business, site, settings)
    css_vars = theme_css(theme)
    registration = form.get('form_type') == 'event'
    submit_label = 'Register' if registration else 'Send'
    heading = form_name[:-13] if registration and form_name.endswith(' Registration') else form_name
    introduction = description or ('Complete the details below to register.' if registration else 'Complete the form below.')
    required_note = '<p class="required-note">* Required fields</p>' if any(f.get('required') for f in fields) else ''
    canonical = urlsplit(safe_url(canonical_url))
    home_url = f'{canonical.scheme}://{canonical.netloc}/' if theme['source']=='website' and canonical.netloc else ''
    logo = f'<img class="brand-logo" src="{_esc(theme["logo_url"])}" alt="{_esc(name)}">' if theme['logo_url'] else ''
    back = f'<a class="back" href="{_esc(home_url)}" target="_top">Back to website <span aria-hidden="true">↗</span></a>' if home_url else ''
    payload = {"form_id": str(form.get("id") or ""),
               "business_id": str(form.get("business_id") or business.get("id") or "")}
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(form_name)} — {_esc(name)}</title>
<meta name="description" content="{_esc(description or form_name + ' for ' + name)}">
<link rel="canonical" href="{_esc(canonical_url)}">
<meta name="robots" content="noindex">
{font_links(theme)}
<style>
{css_vars}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--surface);color:var(--text-primary);font-family:var(--font-body);line-height:1.5}}
/* Layout follows the converted two-column registration reference; live
   website tokens replace its raster backdrop, invented logo and fixed copy.
   Intrinsic rows retain every real field at every viewport width. */
main{{max-width:1280px;margin:0 auto;padding:32px clamp(20px,5vw,64px) 48px}}
.site-header{{display:flex;justify-content:space-between;align-items:center;gap:24px;min-height:56px}}
.brand{{display:flex;align-items:center;gap:14px;min-width:0}}
.brand-logo{{display:block;width:auto;max-width:160px;max-height:64px;object-fit:contain}}
.brand:has(.brand-logo) .biz{{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%)}}
.back{{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--text-primary);text-decoration:none;white-space:nowrap;min-height:44px;display:inline-flex;align-items:center;gap:10px}}
.back:hover{{text-decoration:underline;text-underline-offset:5px}}
.back:focus-visible,button:focus-visible{{outline:2px solid var(--focus);outline-offset:4px}}
.form-layout{{display:grid;grid-template-columns:minmax(0,1.08fr) minmax(0,1fr);gap:clamp(40px,7vw,100px);align-items:start;margin-top:80px}}
.intro,.form-panel{{min-width:0}}
.kicker{{font-size:12px;font-weight:600;letter-spacing:.16em;text-transform:uppercase;color:var(--text-secondary);margin:0 0 20px}}
.required-note{{font-size:12px;color:var(--text-secondary);margin:0 0 24px}}
@media(max-width:767px){{main{{padding:24px 20px 32px}}.form-layout{{grid-template-columns:minmax(0,1fr);gap:32px;margin-top:44px}}.site-header{{gap:12px}}.brand-logo{{max-width:124px;max-height:52px}}.back{{font-size:10px;letter-spacing:.03em}}}}
body[data-embedded=true] main{{max-width:640px;padding:24px 20px}}
body[data-embedded=true] .site-header{{display:none}}
body[data-embedded=true] .form-layout{{display:block;margin-top:0}}
body[data-embedded=true] .intro{{margin-bottom:28px}}
body[data-embedded=true] h1{{font-size:clamp(1.6rem,5vw,2.3rem)}}
.biz{{font-size:.85rem;letter-spacing:.06em;text-transform:uppercase;color:var(--text-muted);margin:0 0 8px}}
h1{{font-family:var(--font-heading);font-size:clamp(2.2rem,4.8vw,4.5rem);font-weight:800;letter-spacing:-.035em;line-height:1.03;margin:0 0 24px;overflow-wrap:anywhere}}
.lead{{color:var(--text-secondary);font-size:18px;line-height:1.6;max-width:42ch;margin:0}}
.field{{margin:0 0 26px}}
.field label{{display:block;font-size:12px;letter-spacing:.06em;font-weight:600;margin:0 0 10px}}
.field.check{{display:flex;gap:10px;align-items:center}}
.field.check label{{margin:0;font-weight:500}}
.req{{color:var(--accent)}}
input,select,textarea{{width:100%;font:inherit;font-size:16px;min-height:52px;color:inherit;background:var(--input-surface);border:1px solid var(--border);border-radius:var(--radius);padding:12px 14px}}
input[type=checkbox]{{width:20px;height:20px;min-height:20px;flex:none;accent-color:var(--focus)}}
textarea{{resize:vertical;min-height:120px}}
input:focus,select:focus,textarea:focus{{outline:2px solid var(--focus);outline-offset:3px;border-color:var(--accent)}}
.hp{{position:absolute;left:-10000px;top:auto;width:1px;height:1px;overflow:hidden}}
button{{display:inline-block;width:100%;font:inherit;font-weight:700;color:var(--accent-text);background:var(--accent);border:0;border-radius:var(--radius);padding:16px 18px;min-height:56px;letter-spacing:.08em;cursor:pointer;margin-top:8px}}
button:hover{{background:var(--accent-hover)}}
button[disabled]{{opacity:.6;cursor:wait}}
.done{{display:none;padding:22px;border:1px solid var(--border);border-radius:var(--radius);background:var(--input-surface)}}
.done h2{{font-family:var(--font-heading);margin:0 0 8px;font-size:1.25rem}}
.err{{display:none;color:var(--error);margin:12px 0 0}}
footer{{margin-top:36px;font-size:.8rem;color:var(--text-muted)}}
</style>
</head>
<body data-style-source="{theme['source']}" data-embedded="{str(bool(embedded)).lower()}">
<main>
<header class="site-header"><div class="brand">{logo}<p class="biz">{_esc(name)}</p></div>{back}</header>
<div class="form-layout">
<section class="intro" aria-labelledby="form-heading">
<p class="kicker">{'Registration' if registration else 'Get in touch'}</p>
<h1 id="form-heading">{_esc(heading)}</h1>
<p class="lead">{_esc(introduction)}</p>
</section>
<div class="form-panel">
<form id="client-form" method="post" action="{_esc(submit_url)}" novalidate>
{required_note}
{fields_html}
<div class="hp" aria-hidden="true"><label>Leave this empty<input type="text" name="{HONEYPOT_NAME}" tabindex="-1" autocomplete="off"></label></div>
<button type="submit" id="send">{submit_label}</button>
<p class="err" id="err" role="alert"></p>
</form>
<section class="done" id="done" aria-live="polite"><h2 tabindex="-1">Received</h2><p>{_esc(thanks)}</p></section>
<footer>Powered by The Solutionist System</footer>
</div>
</div>
</main>
<script>
(function(){{
  var form=document.getElementById('client-form'),btn=document.getElementById('send'),
      err=document.getElementById('err'),done=document.getElementById('done');
  var meta={json.dumps(payload)};
  form.addEventListener('submit',function(e){{
    e.preventDefault();err.style.display='none';
    var data={{}};
    Array.prototype.forEach.call(form.elements,function(el){{
      if(!el.name)return;
      if(el.type==='checkbox'){{data[el.name]=el.checked?'yes':'';return;}}
      data[el.name]=el.value;
    }});
    var missing=[];
    Array.prototype.forEach.call(form.querySelectorAll('[required]'),function(el){{
      var v=el.type==='checkbox'?el.checked:String(el.value||'').trim();
      if(!v){{missing.push(el.id);}}
    }});
    if(missing.length){{err.textContent='Please fill in the required fields.';err.style.display='block';document.getElementById(missing[0]).focus();return;}}
    if(!form.reportValidity())return;
    btn.disabled=true;btn.textContent='Sending…';
    fetch({json.dumps(submit_url)},{{method:'POST',headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{form_id:meta.form_id,business_id:meta.business_id,data:data}})}})
    .then(function(r){{return r.json().then(function(j){{return {{ok:r.ok,j:j}};}});}})
    .then(function(x){{
      if(!x.ok){{throw new Error((x.j&&x.j.detail)||'Something went wrong.');}}
      form.style.display='none';done.style.display='block';done.querySelector('h2').focus();done.scrollIntoView({{behavior:'smooth',block:'start'}});
    }})
    .catch(function(ex){{err.textContent=ex.message||'Something went wrong. Please try again.';err.style.display='block';btn.disabled=false;btn.textContent={json.dumps(submit_label)};}});
  }});
}})();
</script>
</body>
</html>"""
