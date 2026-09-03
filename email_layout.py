"""
email_layout.py — the shape every business email leaves in.

THE GAP THIS CLOSES
  Every email a business sent through the platform went out as bare
  plain text: a draft body with the closing line and the signature
  appended as more lines. Gmail renders that as one grey block — no
  paragraph spacing, no brand, the signature indistinguishable from the
  message. Placeholders the drafting side never filled ({business_name},
  {closing_line}) leaked into real mail.

  This module turns a plain-text body into a laid-out, branded HTML
  email — and the matching plain-text alternative — using what the
  business already configured: the brand kit (primary colour, logo,
  tagline) and the Email Templates signature. Nothing here decides
  WHETHER to send; email_sender calls it for business-originated sends.

WHAT IT DOES NOT DO
  - It does not touch bodies that are already HTML (a caller that built
    its own markup keeps it).
  - It does not invent brand. No logo → a wordmark in the brand colour;
    no brand colour → the platform accent. Never a placeholder image.
  - It is pure. No I/O, no settings lookups; the caller hands in the
    business row.
"""
from __future__ import annotations

import html as _html
import re
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_ACCENT = "#2e7dff"
_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_URL_RE = re.compile(r"(https?://[^\s<>\"']+)")
_PLACEHOLDER_RE = re.compile(r"\{([a-z_]+)\}")


# ─── What the business configured ───────────────────────────────────


def brand_of(settings: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Primary colour, logo, tagline — tolerant of both brand_kit shapes
    (nested `colors.primary` and legacy flat `primary_color`)."""
    settings = settings if isinstance(settings, dict) else {}
    kit = settings.get("brand_kit") if isinstance(settings.get("brand_kit"), dict) else {}
    colors = kit.get("colors") if isinstance(kit.get("colors"), dict) else {}
    primary = (colors.get("primary") or kit.get("primary_color") or "").strip()
    if not _HEX_RE.match(primary):
        primary = DEFAULT_ACCENT
    logo = (kit.get("logo_url") or "").strip()
    if not logo.lower().startswith("https://"):
        logo = ""  # http:// logos are blocked by most clients; data: URIs bloat
    tagline = (kit.get("tagline") or "").strip()
    heading = (kit.get("font_heading") or (kit.get("font_pair") or {}).get("heading") or "").strip() \
        if isinstance(kit.get("font_pair"), (dict, type(None))) else ""
    return {"primary": primary, "logo_url": logo, "tagline": tagline, "font_heading": heading}


def signature_of(settings: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    settings = settings if isinstance(settings, dict) else {}
    et = settings.get("email_templates") if isinstance(settings.get("email_templates"), dict) else {}
    sig = et.get("signature")
    return sig if isinstance(sig, dict) else {}


def rules_of(settings: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    settings = settings if isinstance(settings, dict) else {}
    et = settings.get("email_templates") if isinstance(settings.get("email_templates"), dict) else {}
    rules = et.get("global_rules")
    return rules if isinstance(rules, dict) else {}


# ─── Placeholders ───────────────────────────────────────────────────


def placeholder_values(biz: Dict[str, Any], *, contact_name: Optional[str] = None,
                       extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Everything a template may reference, resolved for one send. The
    contact's FIRST name is what {contact_name} means in a greeting."""
    settings = biz.get("settings") if isinstance(biz.get("settings"), dict) else {}
    sig = signature_of(settings)
    rules = rules_of(settings)
    first = (contact_name or "").strip().split(" ")[0] if contact_name else ""
    values = {
        "contact_name": first or "there",
        "name": first or "there",
        "business_name": (biz.get("name") or sig.get("business") or "").strip(),
        "practitioner_name": (sig.get("name") or settings.get("practitioner_name") or "").strip(),
        "closing_line": (rules.get("closing_line") or "").strip(),
        "booking_url": (sig.get("link_page_url") or settings.get("link_page_url") or "").strip(),
    }
    for k, v in (extra or {}).items():
        if isinstance(v, str):
            values[k] = v
    return values


def fill_placeholders(text: str, values: Dict[str, str]) -> str:
    """Replace known {tokens}. Unknown tokens are left alone (a literal
    brace in a message is not ours to eat); an EMPTY known value removes
    the token and any trailing space so "Hi {contact_name}," can't
    become "Hi ,"."""
    def _sub(m: "re.Match[str]") -> str:
        key = m.group(1)
        if key not in values:
            return m.group(0)
        return values[key]
    out = _PLACEHOLDER_RE.sub(_sub, text or "")
    return re.sub(r"[ \t]+([,.!?])", r"\1", out)


# ─── Signature ──────────────────────────────────────────────────────


def signature_plaintext(sig: Dict[str, Any]) -> str:
    """Byte-identical to the frontend's buildSignaturePlain and Chief's
    _build_signature_plaintext, so the block can be recognised again."""
    if not isinstance(sig, dict):
        return ""
    lines: List[str] = []
    if sig.get("name"):
        lines.append(str(sig["name"]))
    title_line = " · ".join(s for s in [sig.get("title"), sig.get("business")] if s)
    if title_line:
        lines.append(title_line)
    if sig.get("tagline"):
        lines.append(str(sig["tagline"]))
    contact = " · ".join(s for s in [sig.get("phone"), sig.get("email")] if s)
    if contact:
        lines.append(contact)
    if sig.get("link_page_url"):
        lines.append(str(sig["link_page_url"]))
    return "\n".join(lines)


def split_trailers(body: str, sig: Dict[str, Any], disclaimer: str = "") -> Tuple[str, bool, str]:
    """Peel the plain-text signature and disclaimer Chief appended off the
    end of a body, so the layout can render them as designed blocks.
    Returns (message, had_signature, disclaimer_text)."""
    text = (body or "").replace("\r\n", "\n").rstrip()
    disc = (disclaimer or "").strip()
    found_disc = ""
    if disc:
        tail = "\n\n--\n" + disc
        if text.endswith(tail):
            text = text[: -len(tail)].rstrip()
            found_disc = disc
    had_sig = False
    sig_text = signature_plaintext(sig)
    if sig_text and text.endswith(sig_text):
        text = text[: -len(sig_text)].rstrip()
        had_sig = True
    return text, had_sig, found_disc


def signature_html(sig: Dict[str, Any], primary: str) -> str:
    """Mirrors EmailTemplates.tsx buildSignatureHtml — the practitioner
    saw this exact block on the Signature page."""
    e = _html.escape
    name = e(str(sig.get("name") or ""))
    title_line = e(" · ".join(s for s in [sig.get("title"), sig.get("business")] if s))
    tagline = e(str(sig.get("tagline") or ""))
    phone = e(str(sig.get("phone") or ""))
    email = e(str(sig.get("email") or ""))
    link = e(str(sig.get("link_page_url") or ""))
    logo = e(str(sig.get("logo_url") or ""))
    if not any([name, title_line, tagline, phone, email, link]):
        return ""
    p = e(primary)
    left = (f'<td style="padding-right:16px;border-right:2px solid {p};vertical-align:top;">'
            f'<img src="{logo}" width="60" alt="" style="display:block;border:0;" /></td>'
            if logo.startswith("https://") else "")
    rows = []
    if name:
        rows.append(f'<div style="font-weight:bold;font-size:16px;color:#1f2937;">{name}</div>')
    if title_line:
        rows.append(f'<div style="color:#6b7280;font-size:13px;">{title_line}</div>')
    if tagline:
        rows.append(f'<div style="margin-top:4px;font-size:12px;color:{p};">{tagline}</div>')
    if phone or email:
        sep = " · " if phone and email else ""
        rows.append(f'<div style="margin-top:6px;font-size:12px;color:#374151;">{phone}{sep}{email}</div>')
    if link:
        href = link if link.startswith("http") else "https://" + link
        rows.append(f'<div style="margin-top:4px;"><a href="{href}" style="color:{p};font-size:12px;">{link}</a></div>')
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" style="font-family:Arial,Helvetica,sans-serif;'
        'font-size:14px;color:#333;border-collapse:collapse;margin-top:24px;"><tr>'
        f'{left}<td style="{"padding-left:16px;" if left else ""}vertical-align:top;">{"".join(rows)}</td>'
        '</tr></table>'
    )


def _drop_trailing_name(text: str, sig: Dict[str, Any]) -> str:
    """The seeded templates end with "{closing_line}\\n{practitioner_name}".
    With a signature that starts with the same name, the send read
    "Best,\\nKevin McCloud\\nKevin McCloud\\n...". One name is enough."""
    name = str(sig.get("name") or "").strip()
    if not name:
        return text
    stripped = text.rstrip()
    if stripped.endswith("\n" + name) or stripped == name:
        return stripped[: -len(name)].rstrip()
    return text


def compose_trailers(body: str, settings: Optional[Dict[str, Any]]) -> str:
    """Closing line + signature + disclaimer, appended per global_rules.
    Mirrors chief_of_staff._compose_body_with_signature so a preview and
    a real send agree; both stay plain text until the layout runs."""
    out = (body or "").rstrip()
    rules = rules_of(settings)
    sig = signature_of(settings)
    closing = (rules.get("closing_line") or "").strip()
    if closing and closing not in out:
        out += f"\n\n{closing}"
    if rules.get("always_include_signature", True):
        sig_text = signature_plaintext(sig)
        if sig_text and sig_text not in out:
            out = _drop_trailing_name(out, sig)
            out += f"\n{sig_text}" if closing else f"\n\n{sig_text}"
    disclaimer = (rules.get("disclaimer") or "").strip()
    if disclaimer and disclaimer not in out:
        out += f"\n\n--\n{disclaimer}"
    return out

# ─── Body ───────────────────────────────────────────────────────────


def _linkify(escaped: str) -> str:
    return _URL_RE.sub(lambda m: f'<a href="{m.group(1)}" style="color:inherit;">{m.group(1)}</a>', escaped)


def paragraphs_html(text: str) -> str:
    """Blank line → new paragraph; single newline → line break. URLs
    become links. Everything is escaped first — the body is the
    practitioner's words, not markup."""
    text = (text or "").replace("\r\n", "\n").strip()
    if not text:
        return ""
    out = []
    for block in re.split(r"\n\s*\n", text):
        lines = [_linkify(_html.escape(l.rstrip())) for l in block.split("\n")]
        out.append(
            '<p style="margin:0 0 16px;font-size:16px;line-height:1.6;color:#1f2937;">'
            + "<br />".join(lines) + "</p>")
    return "".join(out)


def render_html(message: str, *, business_name: str, brand: Dict[str, Any],
                sig: Optional[Dict[str, Any]] = None, disclaimer: str = "",
                unsubscribe_url: Optional[str] = None, preheader: str = "") -> str:
    """The email. One 600px column, the brand colour as a rule at the
    top and on links, the logo or a wordmark, the message in real
    paragraphs, the signature as the block the practitioner designed,
    and a footer that says who sent it and how to stop."""
    e = _html.escape
    primary = brand.get("primary") or DEFAULT_ACCENT
    name = e(business_name or "")
    logo = brand.get("logo_url") or ""
    tagline = e(brand.get("tagline") or "")
    header_inner = (
        f'<img src="{e(logo)}" alt="{name}" height="44" style="display:block;height:44px;max-width:220px;border:0;" />'
        if logo else
        f'<div style="font-family:Georgia,\'Times New Roman\',serif;font-size:22px;font-weight:600;letter-spacing:-0.01em;color:{e(primary)};">{name}</div>'
    )
    sig_block = signature_html(sig or {}, primary)
    disc_block = (
        f'<p style="margin:24px 0 0;font-size:12px;line-height:1.5;color:#6b7280;">{e(disclaimer)}</p>'
        if disclaimer else "")
    unsub = (
        f' · <a href="{e(unsubscribe_url)}" style="color:#6b7280;">Unsubscribe</a>'
        if unsubscribe_url else "")
    pre = e(preheader or "")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light">
<title>{name}</title>
</head>
<body style="margin:0;padding:0;background:#f3f4f6;-webkit-font-smoothing:antialiased;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;">{pre}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f3f4f6;">
<tr><td align="center" style="padding:32px 16px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="width:100%;max-width:600px;background:#ffffff;border-radius:12px;overflow:hidden;">
<tr><td style="height:5px;background:{e(primary)};font-size:0;line-height:0;">&nbsp;</td></tr>
<tr><td style="padding:28px 36px 8px;font-family:Arial,Helvetica,sans-serif;">{header_inner}</td></tr>
<tr><td style="padding:16px 36px 8px;font-family:Arial,Helvetica,sans-serif;">
{paragraphs_html(message)}
{sig_block}
{disc_block}
</td></tr>
<tr><td style="padding:20px 36px 28px;font-family:Arial,Helvetica,sans-serif;font-size:12px;line-height:1.5;color:#6b7280;border-top:1px solid #e5e7eb;">
{name}{(" · " + tagline) if tagline else ""}<br />
You're receiving this because you're in touch with {name}{unsub}.
</td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""


def render_for_send(body: str, biz: Dict[str, Any], *,
                    unsubscribe_url: Optional[str] = None) -> Tuple[str, str]:
    """(html, text) for one business-originated send. The text half is
    the body exactly as composed — signature lines and all — so a client
    that prefers text loses nothing."""
    settings = biz.get("settings") if isinstance(biz.get("settings"), dict) else {}
    sig = signature_of(settings)
    rules = rules_of(settings)
    brand = brand_of(settings)
    message, had_sig, disclaimer = split_trailers(body, sig, rules.get("disclaimer") or "")
    html_out = render_html(
        message,
        business_name=biz.get("name") or sig.get("business") or "",
        brand=brand,
        sig=sig if had_sig else None,
        disclaimer=disclaimer,
        unsubscribe_url=unsubscribe_url,
        preheader=(message.strip().split("\n")[0][:120] if message.strip() else ""),
    )
    text_out = (body or "").replace("\r\n", "\n").strip() + "\n"
    return html_out, text_out
