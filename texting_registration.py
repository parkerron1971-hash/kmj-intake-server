"""texting_registration.py — texting under each business's own name (ISV), step 1.

docs/plans/ISV_TEXTING_PLAN_2026-10-11.md (Kevin, 2026-10-11: "write up the
isv build plan and start it"). Twilio's rules for a platform like ours: each
business that texts is registered as its OWN brand with its own campaign,
because one campaign for many companies is rejected (error 30926). Step 1
builds everything Twilio's reviewers check, with no Twilio calls and no money:

  THE PAGES. Each business site serves /texting-terms and /texting-privacy in
  the business's own name: who texts, what about, how often, STOP and HELP,
  rates, and the privacy line reviewers look for. They are the campaign's
  terms and privacy URLs (required on every campaign since June 2026).

  THE WORDS. campaign_words(): the campaign as Twilio will read it, generated
  from the business: the use case (Low Volume Mixed: bookings, replies AND
  offers, so the use case never has to change), a description that says who
  sends, who receives and why, the message flow quoting the opt-in boxes,
  sample messages that name the business, and the keyword replies.

  THE ANSWERS. What only the owner knows (legal name, business type, address,
  website, the person Twilio may contact), saved in texting_registrations.
  NEVER the EIN: it is typed at submit (step 3) and goes straight to Twilio;
  here only whether there is one.

  READINESS. What a reviewer will look for, checked: the site is live, booking
  is live, the pages answer, the answers are complete.
"""
from __future__ import annotations

import asyncio
import html
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

import sb_clients
from business_access import business_access

logger = logging.getLogger("texting_registration")

router = APIRouter(prefix="/texting", tags=["texting"])

USE_CASE = "LOW_VOLUME"            # Twilio's "Low Volume Mixed"
BUSINESS_TYPES = {"sole_proprietor": "Sole proprietor", "llc": "LLC", "corporation": "Corporation",
                  "partnership": "Partnership", "nonprofit": "Nonprofit"}
STATES = set("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY "
             "NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY PR".split())
PRIVACY_LINE = ("We do not sell or share your mobile number or your SMS opt-in data and consent with third "
                "parties or affiliates for their marketing purposes.")
TERMS_PATH, PRIVACY_PATH = "/texting-terms", "/texting-privacy"


class Answers(BaseModel):
    """What the owner tells us for Twilio. extra="forbid": an "ein" key is
    refused, so a tax ID can never be saved here by mistake."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    legal_name: str = Field(min_length=2, max_length=120)
    business_type: str
    has_ein: bool
    street: str = Field(min_length=3, max_length=120)
    city: str = Field(min_length=2, max_length=80)
    state: str = Field(min_length=2, max_length=2)
    postal_code: str
    website: Optional[str] = Field(default=None, max_length=200)
    rep_first_name: str = Field(min_length=1, max_length=60)
    rep_last_name: str = Field(min_length=1, max_length=60)
    rep_title: str = Field(min_length=2, max_length=80)
    rep_email: str = Field(min_length=5, max_length=200)
    rep_phone: str

    @model_validator(mode="after")
    def check(self):
        if self.business_type not in BUSINESS_TYPES:
            raise ValueError("Choose sole proprietor, LLC, corporation, partnership or nonprofit.")
        self.state = self.state.upper()
        if self.state not in STATES:
            raise ValueError("Use the two-letter state, like MI.")
        if not re.fullmatch(r"\d{5}(-\d{4})?", self.postal_code):
            raise ValueError("Use a five-digit ZIP code.")
        if self.website and not re.fullmatch(r"https://[^\s/]+\.[^\s]+", self.website):
            raise ValueError("Use the website's full address, starting with https://.")
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", self.rep_email):
            raise ValueError("That email address doesn't look right.")
        digits = re.sub(r"\D", "", self.rep_phone)
        if len(digits) == 10:
            digits = "1" + digits
        if len(digits) != 11 or not digits.startswith("1"):
            raise ValueError("Use a US phone number, like (231) 555-0100.")
        self.rep_phone = "+" + digits
        if self.business_type == "sole_proprietor" and self.has_ein:
            raise ValueError("A sole proprietor with an EIN registers as an LLC or the business type on the EIN.")
        return self


def brand_path(answers: Optional[Dict[str, Any]]) -> Optional[str]:
    """Which Twilio brand the business takes: 'sole_proprietor' without an
    EIN (one number, the owner confirms by a code to their own mobile), else
    'low_volume_standard'. None until the answers say."""
    if not answers:
        return None
    return "low_volume_standard" if answers.get("has_ein") else "sole_proprietor"


# ── the words Twilio reads ────────────────────────────────────────────

def booking_box(name: str) -> str:
    """The booking page's booking-texts checkbox in the business's name (the
    words it shows once the business registers; plan step 3)."""
    return (f"I agree to receive text messages about my bookings (confirmations, reminders, updates) from {name}. "
            "Not required to book. Msg frequency varies. Msg & data rates may apply. Reply STOP to opt out, "
            "HELP for help.")


def offers_box(name: str) -> str:
    """The booking page's separate, optional offers checkbox."""
    return (f"Also text me about offers and openings from {name}. Optional, not required to book. Msg frequency "
            "varies. Msg & data rates may apply. Reply STOP to opt out.")


def campaign_words(name: str, origin: str, *, offer_code: str = "FALL10") -> Dict[str, Any]:
    """The campaign registration as Twilio's reviewers will read it, in the
    business's name. Follows Twilio's published rejection reasons: say who
    sends, who receives and why; samples that name the business; opt-in
    quoted word for word; marketing consent collected apart; no public URL
    shorteners (links are the business's own site)."""
    book = f"{origin}/book"
    return {
        "use_case": USE_CASE,
        "description": (f"{name} texts its own clients who opted in on its booking page or website: booking "
                        "confirmations, appointment reminders, replies to their questions, and, only to clients "
                        "who separately agreed to them, occasional offers and openings. The messages are from "
                        f"{name} about its own services."),
        "message_flow": (f"Clients opt in on {name}'s booking page ({book}) by checking an unchecked box that "
                         f"reads: \"{booking_box(name)}\" A separate, optional, unchecked box collects consent to "
                         f"offers: \"{offers_box(name)}\" Consent is never required to book. Texting terms: "
                         f"{origin}{TERMS_PATH}. Privacy policy: {origin}{PRIVACY_PATH}."),
        "samples": [
            f"{name}: Your appointment is confirmed for Tue, Oct 14 at 3:00 PM. Reply STOP to opt out.",
            f"Reminder from {name}: your appointment is tomorrow at 3:00 PM. Reply STOP to opt out.",
            f"{name}: Thanks for coming in! Book your next visit here: {book} Reply STOP to opt out.",
            f"{name}: This week only, $10 off your next visit with the code {offer_code}: "
            f"{book}?offer={offer_code} Reply STOP to opt out.",
        ],
        "opt_in_keywords": ["START", "YES", "UNSTOP"],
        "opt_in_message": (f"{name}: You're subscribed to texts about your bookings. Msg frequency varies. "
                           "Msg & data rates may apply. Reply HELP for help, STOP to opt out."),
        "opt_out_keywords": ["STOP", "STOPALL", "UNSUBSCRIBE", "CANCEL", "END", "QUIT"],
        "opt_out_message": f"{name}: You're unsubscribed and won't get more texts from us. Reply START to resubscribe.",
        "help_keywords": ["HELP", "INFO"],
        "help_message": (f"{name}: For help, reply to this message or visit {origin}{TERMS_PATH}. "
                         "Msg & data rates may apply. Reply STOP to opt out."),
        "has_embedded_links": True,
        "has_embedded_phone": False,
        "terms_url": f"{origin}{TERMS_PATH}",
        "privacy_url": f"{origin}{PRIVACY_PATH}",
    }


# ── the pages ─────────────────────────────────────────────────────────

_PAGE_CSS = """
:root { color-scheme: light dark; --bg: #ffffff; --text: #16181d; --muted: #5b6070; --line: #dcdfe5; }
@media (prefers-color-scheme: dark) { :root { --bg: #111317; --text: #eceef2; --muted: #a3a8b5; --line: #2a2e36; } }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); font: 16px/1.6 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 720px; margin: 0 auto; padding: 40px 20px 64px; }
h1 { font-size: 28px; line-height: 1.25; margin: 0 0 6px; }
h2 { font-size: 18px; margin: 28px 0 6px; }
p, li { color: var(--text); }
.muted { color: var(--muted); font-size: 14px; }
a { color: inherit; }
footer { margin-top: 40px; padding-top: 16px; border-top: 1px solid var(--line); }
"""


def _page(title: str, name: str, body: str, origin: str) -> str:
    n = html.escape(name)
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(title)} | {n}</title>
<style>{_PAGE_CSS}</style></head>
<body><main>
<p class="muted">{n}</p>
<h1>{html.escape(title)}</h1>
{body}
<footer class="muted"><a href="{html.escape(origin)}{TERMS_PATH}">Texting terms</a> ·
<a href="{html.escape(origin)}{PRIVACY_PATH}">Texting privacy</a> ·
<a href="{html.escape(origin)}/book">Book</a></footer>
</main></body></html>"""


def terms_html(name: str, origin: str, contact_email: Optional[str] = None) -> str:
    """/texting-terms: the business's text messaging terms."""
    n = html.escape(name)
    contact = (f' or email <a href="mailto:{html.escape(contact_email)}">{html.escape(contact_email)}</a>'
               if contact_email else "")
    body = f"""
<p>{n} sends text messages to clients who agree to receive them. These terms explain what you get and how to stop.</p>
<h2>What we text</h2>
<ul>
<li><strong>About your bookings:</strong> confirmations, appointment reminders, updates, and replies to your messages. You agree to these with the box on our booking page or website.</li>
<li><strong>Offers and openings:</strong> occasional offers, only if you separately agree with the optional offers box when you book.</li>
</ul>
<p>Agreeing to texts is never required to book or buy anything.</p>
<h2>How often</h2>
<p>Message frequency varies with your bookings and activity. Message and data rates may apply.</p>
<h2>How to stop or get help</h2>
<p>Reply <strong>STOP</strong> to any text to stop all texts from {n}; you'll get one message confirming it. Reply <strong>START</strong> to sign up again. Reply <strong>HELP</strong> for help{contact}.</p>
<p>Carriers are not liable for delayed or undelivered messages.</p>
<h2>Privacy</h2>
<p>{html.escape(PRIVACY_LINE)} See our <a href="{html.escape(origin)}{PRIVACY_PATH}">texting privacy policy</a>.</p>"""
    return _page("Text messaging terms", name, body, origin)


def privacy_html(name: str, origin: str, contact_email: Optional[str] = None) -> str:
    """/texting-privacy: the business's privacy policy for text messages."""
    n = html.escape(name)
    contact = (f' To ask about your information, email <a href="mailto:{html.escape(contact_email)}">'
               f'{html.escape(contact_email)}</a>.' if contact_email else "")
    body = f"""
<p>This policy covers the mobile number and messages you share with {n} when you agree to receive texts.</p>
<h2>What we collect</h2>
<p>Your mobile number, your consent (when and where you gave it), and the messages we exchange.</p>
<h2>How we use it</h2>
<p>Only to send the texts you agreed to (about your bookings and, if you chose, offers and openings), to answer your messages, and to honor STOP and HELP.</p>
<h2>Sharing</h2>
<p><strong>{html.escape(PRIVACY_LINE)}</strong> We use service providers (our booking software and its text messaging provider) only to deliver our messages to you.</p>
<h2>Your choices</h2>
<p>Reply <strong>STOP</strong> to any text to stop all texts from {n}, or <strong>HELP</strong> for help.{contact}</p>
<p>See our <a href="{html.escape(origin)}{TERMS_PATH}">text messaging terms</a>.</p>"""
    return _page("Text messaging privacy policy", name, body, origin)


# ── the answers and readiness ─────────────────────────────────────────

def _read(path: str) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(path)
    if not isinstance(rows, list):
        raise RuntimeError("read failed")
    return rows


def registration(business_id: str) -> Optional[Dict[str, Any]]:
    """The business's texting_registrations row, or None. Raises on a failed read."""
    rows = _read(f"/texting_registrations?business_id=eq.{business_id}&select=*&limit=1")
    return rows[0] if rows else None


def site_origin(business_id: str) -> Optional[str]:
    """The business's site address (custom domain first), or None. Raises on
    a failed read."""
    import business_marketing_links as links
    site = links.site_for(business_id)
    return links.origin(site) if site else None


def readiness(business: Dict[str, Any], *, answers: Optional[Dict[str, Any]], origin: Optional[str],
              bookable: Optional[bool]) -> List[Dict[str, Any]]:
    """What Twilio's reviewers look for, each {key, ok, label, fix}. A check
    that couldn't be read is ok None (never a guess)."""
    out = [
        {"key": "site", "ok": bool(origin), "label": "Your website is live",
         "fix": "Publish your site in Build, My Site: reviewers open it."},
        {"key": "booking", "ok": bookable, "label": "Your booking page takes bookings",
         "fix": "Publish your booking page with at least one service: it's where clients agree to texts."},
        {"key": "pages", "ok": bool(origin),
         "label": "Your texting terms and privacy pages are up" + (f" ({origin}{TERMS_PATH})" if origin else ""),
         "fix": "They go up with your website."},
        {"key": "answers", "ok": bool(answers), "label": "Your business details for the registration",
         "fix": "Add your legal business name, address and the person Twilio can contact."},
    ]
    return out


async def overview(business: Dict[str, Any]) -> Dict[str, Any]:
    bid = str(business["id"])
    try:
        row = await asyncio.to_thread(registration, bid)
    except RuntimeError:
        raise HTTPException(503, "Your texting registration couldn't be read just now. Try again in a minute.")
    try:
        origin = await asyncio.to_thread(site_origin, bid)
    except Exception as e:
        logger.warning("texting registration: site unread for %s: %s", bid[:8], e)
        origin = None
    bookable: Optional[bool] = None
    try:
        import business_marketing_links as links
        bookable = await asyncio.to_thread(links.bookable, bid, business)
    except Exception as e:
        logger.warning("texting registration: booking unread for %s: %s", bid[:8], e)
    answers = (row or {}).get("answers") or None
    name = str((answers or {}).get("legal_name") or business.get("name") or "Your business")
    shown_name = str(business.get("name") or name)
    return {
        "status": (row or {}).get("status") or "not_started",
        "answers": answers,
        "brand_path": brand_path(answers),
        "readiness": readiness(business, answers=answers, origin=origin, bookable=bookable),
        "words": campaign_words(shown_name, origin) if origin else None,
        "pages": {"terms": f"{origin}{TERMS_PATH}", "privacy": f"{origin}{PRIVACY_PATH}"} if origin else None,
        "business_types": BUSINESS_TYPES,
    }


@router.get("/registration/{business_id}")
async def get_registration(business_id: str, biz: dict = Depends(business_access("owner"))):
    """The owner's texting registration: answers, readiness, and the words
    Twilio will read. Owner only (it holds the representative's details)."""
    return {"ok": True, **await overview(biz)}


@router.put("/registration/{business_id}")
async def save_registration(business_id: str, body: Answers, biz: dict = Depends(business_access("owner"))):
    """Save the answers (never an EIN). Nothing is sent to Twilio."""
    bid = str(UUID(str(biz["id"])))
    row = {"business_id": bid, "answers": body.model_dump(mode="json"),
           "updated_at": datetime.now(timezone.utc).isoformat()}
    try:
        current = await asyncio.to_thread(registration, bid)
    except RuntimeError:
        raise HTTPException(503, "Your details couldn't be saved just now. Nothing changed.") from None
    if current and current.get("status") not in (None, "draft", "failed"):
        raise HTTPException(409, "Your registration is with Twilio already, so these details can't change here. "
                                 "If something is wrong, tell us and we'll update it with Twilio.")
    saved = await asyncio.to_thread(
        sb_clients.sb_post_as_service, "/texting_registrations?on_conflict=business_id",
        {**row, "status": (current or {}).get("status") or "draft"}, "resolution=merge-duplicates,return=representation")
    if not saved:
        raise HTTPException(503, "Your details couldn't be saved just now. Nothing changed.")
    return {"ok": True, **await overview(biz)}


# ── the public pages (public_site serves them on the business's site) ──

async def page_for(business_id: str, kind: str) -> Optional[str]:
    """The HTML for /texting-terms or /texting-privacy, or None when the
    business can't be read."""
    try:
        rows = await asyncio.to_thread(
            _read, f"/businesses?id=eq.{UUID(str(business_id))}&select=id,name,settings&limit=1")
        origin = await asyncio.to_thread(site_origin, str(business_id))
    except Exception as e:
        logger.warning("texting page unread for %s: %s", str(business_id)[:8], e)
        return None
    if not rows or not origin:
        return None
    name = str(rows[0].get("name") or "This business")
    try:
        import public_site
        email = public_site._business_public_email(rows[0].get("settings") or {}) or None
    except Exception:
        email = None
    return terms_html(name, origin, email) if kind == "terms" else privacy_html(name, origin, email)
